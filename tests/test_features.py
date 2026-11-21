"""Testy nowych funkcji v4.1: gry, automatyzacja, analiza, sterowniki, logi, wentylator (logika bez sprzętu)."""
import os, sys, tempfile, time, unittest
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
_tmp = tempfile.mkdtemp()
os.environ["PRO_OPT_HOME"] = _tmp

from pro_optimizer import analyzer, automation, config, drivers, fan, games, logview, paths, version
from pro_optimizer.settings import Settings


class TestGames(unittest.TestCase):
    def test_layers_preserve_foreign_flags(self):
        v = games.layers_add("~ HIGHDPIAWARE")
        self.assertIn("HIGHDPIAWARE", v); self.assertTrue(games.layers_has(v))
        self.assertEqual(games.layers_add(v), v)                       # idempotentne
        back = games.layers_remove(v)
        self.assertEqual(back, "~ HIGHDPIAWARE")                       # cudza flaga zostaje
        self.assertEqual(games.layers_remove("~ " + games.FSO_TOKEN), "")   # pusta => usuń wartość

    def test_safe_exe_path(self):
        for bad in ("", "C:\\a\\b.txt", 'C:\\a"b.exe', "C:\\a\nb.exe", "relative.exe"):
            self.assertFalse(games.safe_exe_path(bad), bad)
        self.assertTrue(games.safe_exe_path("C:\\Games\\cs2.exe"))

    def test_catalog_valid_and_roblox_first(self):
        cat = config.load_games()
        self.assertEqual(cat[0]["id"], "roblox_player")
        ids = [g["id"] for g in cat]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertTrue(all(g["exes"] for g in cat))

    def test_find_exe_with_hints_and_depth(self):
        root = Path(tempfile.mkdtemp())
        exe = root / "Counter-Strike Global Offensive" / "game" / "bin" / "win64" / "cs2.exe"
        exe.parent.mkdir(parents=True); exe.write_bytes(b"x")
        (root / "Other" / "cs2.exe").parent.mkdir(); (root / "Other" / "cs2.exe").write_bytes(b"x")
        g = next(x for x in config.load_games() if x["id"] == "cs2")
        self.assertEqual(games.find_exe(g, [root]), exe)
        self.assertIsNone(games.find_exe({"id": "x", "exes": ["nope.exe"], "hints": ["Counter"]}, [root]))

    def test_running_games_skip_generic_java(self):
        cat = config.load_games()
        live = games.running_game_exes(cat, {"javaw.exe", "cs2.exe"})
        self.assertEqual([g["id"] for g in live], ["cs2"])


class TestAutomation(unittest.TestCase):
    def test_nothing_enabled_by_default_except_boost(self):
        self.assertEqual(automation.plan({}, 1000, {}, 99, [], set()), [])
        self.assertEqual(automation.plan({}, 1000, {}, 50, ["cs2"], set()), ["game_boost"])

    def test_ram_threshold_and_cooldown(self):
        cfg = {"ram": {"enabled": True, "threshold_pct": 80, "min_interval_min": 10}}
        self.assertEqual(automation.plan(cfg, 10000, {}, 85, [], set()), ["ram"])
        self.assertEqual(automation.plan(cfg, 10000, {}, 70, [], set()), [])
        self.assertEqual(automation.plan(cfg, 10000, {"ram": 10000 - 60}, 95, [], set()), [])      # za wcześnie
        self.assertEqual(automation.plan(cfg, 10000, {"ram": 10000 - 700}, 95, [], set()), ["ram"])

    def test_interval_tasks(self):
        cfg = {"dns": {"enabled": True, "interval_hours": 6}, "clean": {"enabled": True, "interval_hours": 24}}
        now = 1_000_000
        self.assertEqual(sorted(automation.plan(cfg, now, {}, None, [], set())), ["clean", "dns"])
        self.assertEqual(automation.plan(cfg, now, {"dns": now - 3600, "clean": now - 3600}, None, [], set()), [])
        self.assertEqual(automation.plan(cfg, now, {"dns": now - 7 * 3600, "clean": now - 3600}, None, [], set()), ["dns"])

    def test_boost_only_once_per_game_run(self):
        self.assertEqual(automation.plan({}, 1, {}, None, ["cs2"], {"cs2"}), [])

    def test_bad_config_is_ignored(self):
        m = automation.merged({"ram": "zepsute", "nieznane": {"x": 1}, "dns": {"enabled": True}})
        self.assertFalse(m["ram"]["enabled"]); self.assertTrue(m["dns"]["enabled"]); self.assertNotIn("nieznane", m)


class TestAnalyzer(unittest.TestCase):
    def test_flags_real_problems(self):
        f = {"disk": (952 * 2**30, 12.8 * 2**30), "ram_used_pct": 92, "display": {"hz": 60, "max_hz": 180},
             "tweaks": {"power": False, "gamemode": True, "gamedvr": False},
             "gpu": {"temp": 80, "fan": 30}, "defender": {"available": True, "realtime": False}}
        ids = {x.id: x for x in analyzer.analyze(f)}
        for k in ("disk_low", "ram_high", "refresh", "tweak_power", "tweak_gamedvr", "gpu_fan_low", "av_off"):
            self.assertIn(k, ids)
        self.assertNotIn("tweak_gamemode", ids)
        self.assertEqual(ids["refresh"].fix, {"type": "refresh", "hz": 180})
        self.assertEqual(ids["disk_low"].severity, "crit")
        order = [x.severity for x in analyzer.analyze(f)]
        self.assertEqual(order, sorted(order, key=lambda s: analyzer.SEV_ORDER[s]))      # krytyczne najpierw

    def test_healthy_pc_scores_100(self):
        f = {"disk": (1000 * 2**30, 500 * 2**30), "ram_used_pct": 40, "display": {"hz": 180, "max_hz": 180},
             "tweaks": {"power": True, "gamemode": True, "gamedvr": True}, "gpu": {"temp": 55, "fan": 40},
             "defender": {"available": True, "realtime": True, "sig_age_days": 0.5, "quick_age_days": 2}}
        fs = analyzer.analyze(f)
        self.assertEqual(analyzer.score(fs), 100, [x.title for x in fs])

    def test_missing_facts_are_skipped(self):
        self.assertEqual(analyzer.analyze({}), [])

    def test_unoptimized_game_suggestion(self):
        fs = analyzer.analyze({"games_unoptimized": [{"id": "cs2", "name": "Counter-Strike 2"}], "roblox_installed": True})
        self.assertEqual({x.id for x in fs}, {"game_cs2", "roblox_profile"})
        self.assertTrue(all(x.fix["type"] == "game" for x in fs))


class TestDrivers(unittest.TestCase):
    def test_dates_and_age(self):
        self.assertEqual(drivers.parse_dmtf("20260923000000.000000+000"), datetime(2026, 9, 23))
        self.assertEqual(drivers.parse_dmtf("2026-09-23T00:00:00Z"), datetime(2026, 9, 23))
        self.assertIsNone(drivers.parse_dmtf("śmieci")); self.assertIsNone(drivers.parse_dmtf(None))
        self.assertAlmostEqual(drivers.age_years(datetime(2020, 1, 1), datetime(2022, 1, 1)), 2.0, 1)

    def test_vendor_urls_are_https_and_known(self):
        self.assertTrue(drivers.vendor_support_url("Gigabyte Technology Co., Ltd.", "B650 EAGLE").startswith("https://www.gigabyte.com"))
        self.assertTrue(drivers.vendor_support_url("Nieznany", "X Y").startswith("https://www.google.com/search?q="))
        self.assertTrue(all(u.startswith("https://") for _n, u in drivers.GPU_PAGES.values()))

    def test_install_rejects_non_guid(self):
        ok, msg = drivers.install_driver_updates(["'; Remove-Item C:\\ -Recurse; '"])
        self.assertFalse(ok); self.assertIn("Nie wybrano", msg)

    def test_gpu_vendor(self):
        self.assertEqual(drivers.gpu_vendor("NVIDIA GeForce RTX 5080"), "nvidia")
        self.assertEqual(drivers.gpu_vendor("AMD Radeon(TM) Graphics"), "amd")


class TestLogview(unittest.TestCase):
    def test_levels_and_tracebacks(self):
        d = Path(tempfile.mkdtemp())
        (d / "app.log").write_text(
            "2026-11-21 10:00:00,001 INFO a: start\n2026-11-21 10:00:01,002 WARNING a: uwaga\n"
            "2026-11-21 10:00:02,003 ERROR a: bum\nTraceback (most recent call last):\n  File x\nValueError: y\n"
            "2026-11-21 10:00:03,004 INFO a: dalej\n", encoding="utf-8")
        allv = logview.read_tail(100, 0, d)
        self.assertEqual(len(allv), 7)
        errs = logview.read_tail(100, 40, d)
        self.assertEqual([l for l, _ in errs][0].split()[2], "ERROR"); self.assertEqual(len(errs), 4)   # nagłówek + 3 linie traceback
        self.assertEqual(len(logview.read_tail(2, 0, d)), 2)
        logview.clear(d); self.assertEqual(logview.read_tail(100, 0, d), [])

    def test_missing_dir(self):
        self.assertEqual(logview.read_tail(10, 0, Path(tempfile.mkdtemp()) / "nie ma"), [])


class TestFanPolicy(unittest.TestCase):
    def test_curve_floor_emergency_hysteresis(self):
        p = fan.FanPolicy(fan.CURVES["balanced"]["points"])
        self.assertGreaterEqual(p.target(20), fan.MIN_PERCENT)
        self.assertEqual(p.target(90), 100)
        p2 = fan.FanPolicy(fan.CURVES["balanced"]["points"])
        hot = p2.target(70)
        self.assertEqual(p2.target(69), hot)               # drobne wahania nie zmieniają obrotów (histereza)
        self.assertLess(p2.target(50), hot)                # wyraźne ochłodzenie - obroty spadają
        self.assertGreater(p2.target(78), hot)

    def test_controller_without_nvml_is_safe(self):
        c = fan.FanController()
        self.assertIsNone(c.tick(80)); c.release(); self.assertEqual(c.mode, "auto")


class TestSettingsAndVersion(unittest.TestCase):
    def test_new_defaults(self):
        s = Settings()
        for k in ("games", "custom_games", "auto", "fan", "auto_last"):
            self.assertIn(k, s.data)
        self.assertNotIn("auto_update", s.data)
        self.assertEqual(version.parse_version("4.1.0") > version.parse_version("4.0.0"), True)


if __name__ == "__main__":
    unittest.main()

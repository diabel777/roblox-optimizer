"""Testy rdzenia (bez GUI i bez Windowsa).  Uruchom:  python -m unittest discover -s tests -v"""
import hashlib, http.server, io, json, os, shutil, socketserver, sys, tempfile, threading, unittest, zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from pro_optimizer import ed25519, security, cleaner, roblox, backups, config, paths, updater, settings as settings_mod
from pro_optimizer.security import SecurityError, FetchPolicy
from pro_optimizer.version import parse_version, APP_EXE


class Env(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self._env = dict(os.environ)
        os.environ["LOCALAPPDATA"] = str(self.tmp / "Local")
        os.environ["APPDATA"] = str(self.tmp / "Roaming")
        os.environ["PROGRAMDATA"] = str(self.tmp / "PD")
        os.environ["TEMP"] = os.environ["TMP"] = str(self.tmp / "Local" / "Temp")
        os.environ["WINDIR"] = str(self.tmp / "Windows")
        os.environ["PRO_OPT_HOME"] = str(self.tmp / "Local" / "ProUltimateOptimizer")
        os.environ.pop("PROGRAMFILES", None); os.environ.pop("PROGRAMFILES(X86)", None)
        for k in ("Local", "Roaming", "PD", "Windows"):
            (self.tmp / k).mkdir()
        (self.tmp / "Local" / "Temp").mkdir()
        paths.ensure_dirs()

    def tearDown(self):
        os.environ.clear(); os.environ.update(self._env)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def mk(self, rel, size=100):
        p = self.tmp / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"x" * size)
        return p


class TestVersion(unittest.TestCase):
    def test_order(self):
        self.assertTrue(parse_version("4.0.0") > parse_version("3.3"))
        self.assertEqual(parse_version("3.3"), parse_version("3.3.0"))
        self.assertTrue(parse_version("v4.10") > parse_version("4.9.9"))


class TestSecurity(unittest.TestCase):
    def test_url_policy(self):
        security.check_url("https://raw.githubusercontent.com/a/b/main/version.json")
        for bad in ("http://raw.githubusercontent.com/x", "https://evil.example.com/x",
                    "https://raw.githubusercontent.com.evil.com/x", "ftp://github.com/x",
                    "https://user:pw@github.com/x", "file:///etc/passwd"):
            with self.assertRaises(SecurityError, msg=bad):
                security.check_url(bad)

    def test_manifest_signature(self):
        sk = os.urandom(32); pk = ed25519.public_key(sk).hex()
        m = security.sign_manifest({"version": "4.1.0", "package": {"sha256": "0" * 64}}, sk)
        raw = json.dumps(m).encode()
        self.assertEqual(security.verify_manifest(raw, pk)["version"], "4.1.0")
        tampered = json.loads(raw); tampered["version"] = "9.9.9"
        with self.assertRaises(SecurityError):
            security.verify_manifest(json.dumps(tampered).encode(), pk)
        other = ed25519.public_key(os.urandom(32)).hex()
        with self.assertRaises(SecurityError):
            security.verify_manifest(raw, other)
        with self.assertRaises(SecurityError):
            security.verify_manifest(raw, "")          # brak klucza = odmowa
        with self.assertRaises(SecurityError):
            security.verify_manifest(b"not json", pk)

    def test_zip_slip_and_symlink(self):
        d = Path(tempfile.mkdtemp())
        try:
            for name in ("../evil.txt", "/abs.txt", "a/../../evil.txt", "C:/x.txt"):
                z = d / "bad.zip"
                with zipfile.ZipFile(z, "w") as zf:
                    zf.writestr(name, "x")
                with self.assertRaises(SecurityError, msg=name):
                    security.safe_extract(z, d / "out")
            z = d / "sym.zip"
            with zipfile.ZipFile(z, "w") as zf:
                i = zipfile.ZipInfo("link"); i.external_attr = (0o120777 << 16)
                zf.writestr(i, "/etc/passwd")
            with self.assertRaises(SecurityError):
                security.safe_extract(z, d / "out2")
            z = d / "ok.zip"
            with zipfile.ZipFile(z, "w") as zf:
                zf.writestr("a/b.txt", "hello"); zf.writestr("c.txt", "x")
            self.assertEqual(security.safe_extract(z, d / "out3"), 2)
            self.assertEqual((d / "out3" / "a" / "b.txt").read_text(), "hello")
            with self.assertRaises(SecurityError):
                security.safe_extract(z, d / "out4", max_total=3)
        finally:
            shutil.rmtree(d, ignore_errors=True)


class TestCleaner(Env):
    def entry(self, **kw):
        return {"id": "t", "name": "T", "group": "G", "processes": [], **kw}

    def test_safe_target(self):
        L = self.tmp / "Local"
        self.assertTrue(cleaner.is_safe_target(L / "Spotify" / "Data"))
        self.assertTrue(cleaner.is_safe_target(L / "D3DSCache"))
        self.assertTrue(cleaner.is_safe_target(L / "Temp"))
        self.assertFalse(cleaner.is_safe_target(L))
        self.assertFalse(cleaner.is_safe_target(L / "Roblox"))        # jeden człon, nie na liście
        self.assertFalse(cleaner.is_safe_target(self.tmp / "Windows"))
        self.assertFalse(cleaner.is_safe_target("/"))
        self.assertFalse(cleaner.is_safe_target(L / ".." / "Windows" / "System32"))

    def test_scan_and_clean_keeps_folder(self):
        self.mk("Roaming/discord/Cache/a.bin", 1000); self.mk("Roaming/discord/Cache/sub/b.bin", 500)
        self.mk("Roaming/discord/Local Storage/token", 77)           # NIE wolno ruszyć
        e = self.entry(id="discord", paths=["%APPDATA%/discord/Cache", "%APPDATA%/discord/Nope"])
        r = cleaner.scan([e], running=set())[0]
        self.assertEqual((r.size, r.files, r.found), (1500, 2, 1))
        r = cleaner.clean([e], running=set())[0]
        self.assertEqual((r.size, r.files), (1500, 2))
        self.assertTrue((self.tmp / "Roaming/discord/Cache").is_dir())
        self.assertEqual(list((self.tmp / "Roaming/discord/Cache").iterdir()), [])
        self.assertTrue((self.tmp / "Roaming/discord/Local Storage/token").exists())

    def test_running_app_is_skipped(self):
        p = self.mk("Roaming/discord/Cache/a.bin", 10)
        e = self.entry(paths=["%APPDATA%/discord/Cache"], processes=["Discord.exe"])
        r = cleaner.clean([e], running={"discord.exe"})[0]
        self.assertTrue(p.exists()); self.assertIn("Uruchomiona", r.error); self.assertEqual(r.size, 0)

    def test_glob_and_unresolved_var(self):
        self.mk("Local/Google/Chrome/User Data/Profile 1/Cache/x", 5); self.mk("Local/Google/Chrome/User Data/Profile 2/Cache/y", 7)
        e = self.entry(paths=["%LOCALAPPDATA%/Google/Chrome/User Data/Profile */Cache", "%NOPE%/x"])
        r = cleaner.scan([e], running=set())[0]
        self.assertEqual((r.size, r.found), (12, 2))

    def test_symlink_not_followed(self):
        victim = self.mk("Roaming/important/keep.txt", 50)
        (self.tmp / "Roaming/app/Cache").mkdir(parents=True)
        link, target = self.tmp / "Roaming/app/Cache/link", self.tmp / "Roaming/important"
        try:
            os.symlink(target, link)
        except OSError:                              # Windows bez uprawnień do symlinków: użyj junctiona (nie wymaga admina)
            import subprocess
            if os.name != "nt" or subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)],
                                                 capture_output=True).returncode != 0:
                self.skipTest("nie można utworzyć symlinka ani junctiona")
        cleaner.clean([self.entry(paths=["%APPDATA%/app/Cache"])], running=set())
        self.assertTrue(victim.exists())

    def test_unsafe_catalog_path_refused(self):
        v = self.mk("Local/Roblox/Versions/v1/RobloxPlayerBeta.exe", 5)
        cleaner.clean([self.entry(paths=["%LOCALAPPDATA%/Roblox"])], running=set())
        self.assertTrue(v.exists())

    def test_no_double_count_nested(self):
        self.mk("Local/Temp/Roblox/log.txt", 100); self.mk("Local/Temp/other.tmp", 40)
        a = self.entry(id="roblox", paths=["%TEMP%/Roblox"]); b = self.entry(id="temp", paths=["%TEMP%"])
        res = cleaner.scan([a, b], running=set())
        self.assertEqual([r.size for r in res], [100, 40])


class TestRoblox(Env):
    def mkinstall(self, ver, kind="RobloxPlayerBeta.exe", mtime=None):
        p = self.mk(f"Local/Roblox/Versions/{ver}/{kind}", 10)
        if mtime:
            os.utime(p, (mtime, mtime))
        return p

    def test_finds_newest(self):
        self.mkinstall("version-old", mtime=1000); self.mkinstall("version-new", mtime=2000)
        self.mkinstall("version-st", "RobloxStudioBeta.exe", mtime=1500)
        i = roblox.find_installs()
        self.assertEqual(i["player"].version, "version-new"); self.assertEqual(i["studio"].version, "version-st")

    def test_validate(self):
        self.assertEqual(roblox.validate_flags({"FFlagFoo": True, "DFIntBar": 3, "FStringX": "a"}), [])
        self.assertTrue(roblox.validate_flags({"FFlagFoo": "yes"}))
        self.assertTrue(roblox.validate_flags({"DFIntBar": True}))
        self.assertTrue(roblox.validate_flags({"evil": 1}))
        self.assertEqual(roblox.validate_flags({"FFlagDebugPrintInfo": True}), [])   # 'Int' w środku nazwy flagi bool

    def test_apply_backup_and_reapply(self):
        self.mkinstall("version-a", mtime=1000)
        presets = config.load_presets(); self.assertTrue(presets)
        inst = roblox.find_installs()["player"]
        roblox.apply_flags(inst, {"FFlagDebugGraphicsPreferD3D11": True, "FFlagUserFlag": True})
        roblox.apply_flags(inst, roblox.build_flags({"DFIntTextureQualityOverride": 3}, 144, roblox.read_flags(inst)))
        data = roblox.read_flags(inst)
        self.assertEqual(data["DFIntTaskSchedulerTargetFps"], 144); self.assertTrue(data["FFlagUserFlag"])
        self.assertEqual(len(backups.list_backups()), 1)
        # "update Robloxa" = nowy folder wersji bez ustawień
        self.mkinstall("version-b", mtime=5000)
        profile = {"preset": "balanced", "fps": 120, "targets": ["player"], "merge": True}
        self.assertEqual(len(roblox.reapply_if_needed(profile, presets)), 1)
        new = roblox.find_installs()["player"]; self.assertEqual(new.version, "version-b")
        self.assertEqual(roblox.read_flags(new)["DFIntTaskSchedulerTargetFps"], 120)
        self.assertEqual(roblox.reapply_if_needed(profile, presets), [])      # idempotentne
        item = backups.list_backups()[0]
        backups.restore(item, inst.settings_path)

    def test_bad_flags_rejected_nothing_written(self):
        self.mkinstall("version-a"); inst = roblox.find_installs()["player"]
        with self.assertRaises(ValueError):
            roblox.apply_flags(inst, {"nope": 1})
        self.assertFalse(inst.settings_path.exists())

    def test_catalog_valid(self):
        for p in config.load_presets():
            self.assertEqual(roblox.validate_flags(p["flags"]), [], p["id"])
        ids = set()
        for a in config.load_apps():
            self.assertNotIn(a["id"], ids); ids.add(a["id"])
            for pth in a["paths"]:
                self.assertTrue(pth.startswith(("%LOCALAPPDATA%", "%APPDATA%", "%TEMP%", "%WINDIR%", "%PROGRAMDATA%")), pth)


class TestConfigLayering(Env):
    def test_user_override(self):
        (paths.config_dir() / "apps.user.json").write_text(json.dumps([
            {"id": "mine", "name": "Moja", "paths": ["%APPDATA%/mine/Cache"]},
            {"id": "discord", "default": False},
            {"id": "chrome", "disabled": True}]))
        apps = {a["id"]: a for a in config.load_apps()}
        self.assertIn("mine", apps); self.assertFalse(apps["discord"]["default"]); self.assertNotIn("chrome", apps)
        self.assertTrue(apps["discord"]["paths"])           # reszta pól zostaje
        (paths.config_dir() / "theme.json").write_text("{ zepsuty json")
        self.assertIn("colors", config.load_theme())         # zepsuty plik nie wywala aplikacji
        (paths.config_dir() / "theme.json").write_text(json.dumps({"colors": {"accent": "#ff0000"}}))
        t = config.load_theme(); self.assertEqual(t["colors"]["accent"], "#ff0000"); self.assertIn("bg", t["colors"])

    def test_settings_roundtrip_and_corruption(self):
        s = settings_mod.Settings(); s.set("auto_update", False)
        self.assertFalse(settings_mod.Settings().get("auto_update"))
        paths.settings_file().write_text("{{{")
        self.assertTrue(settings_mod.Settings().get("auto_update"))


# ---------------------------------------------------------------- pełny cykl aktualizacji przez lokalny serwer
class _H(http.server.BaseHTTPRequestHandler):
    files = {}
    def do_GET(self):
        path = self.path.split("?")[0]
        if path in self.files:
            body = self.files[path]; self.send_response(200); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)
        elif path == "/redir":
            self.send_response(302); self.send_header("Location", "https://evil.example.com/x"); self.end_headers()
        else:
            self.send_response(404); self.end_headers()
    def log_message(self, *a): pass


class TestUpdater(Env):
    def setUp(self):
        super().setUp()
        self.sk = os.urandom(32); self.pk = ed25519.public_key(self.sk).hex()
        self.srv = socketserver.TCPServer(("127.0.0.1", 0), _H); self.port = self.srv.server_address[1]
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.port}"
        self.policy = FetchPolicy(allowed_hosts=frozenset({"127.0.0.1"}), require_https=False)   # tylko test

    def tearDown(self):
        self.srv.shutdown(); self.srv.server_close(); super().tearDown()

    def publish(self, version, *, corrupt=False, evil_exe=False, bad_sig=False):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr(APP_EXE, "MZ-fake-" + version); z.writestr("_internal/x.dll", "dll")
            if evil_exe:
                z.writestr("../../escape.txt", "pwned")
        pkg = buf.getvalue()
        sha = hashlib.sha256(pkg).hexdigest()
        _H.files["/pkg.zip"] = (pkg + b"X") if corrupt else pkg
        m = security.sign_manifest({"version": version, "download_url": "legacy", "notes": "n",
                                    "package": {"url": self.base + "/pkg.zip", "sha256": sha, "size": len(pkg) + 1}}, self.sk)
        if bad_sig:
            m["version"] = "9.9.9"
        _H.files["/version.json"] = json.dumps(m).encode()

    def upd(self, cur="4.0.0"):
        return updater.Updater(cur, paths.install_root(), self.policy, self.pk, self.base + "/version.json")

    def test_full_cycle(self):
        self.publish("4.1.0")
        u = self.upd(); info = u.check(); self.assertEqual(info.version, "4.1.0")
        seen = []
        d = u.stage(info, lambda a, b: seen.append(a))
        self.assertTrue((d / APP_EXE).exists()); self.assertEqual(d.name, "app-4.1.0")
        self.assertFalse(list(paths.downloads_dir().glob("*.zip")))
        self.assertIsNone(self.upd("4.1.0").check())              # to samo = brak aktualizacji
        self.assertIsNone(self.upd("5.0.0").check())              # nigdy downgrade

    def test_rejects_bad_signature(self):
        self.publish("4.1.0", bad_sig=True)
        with self.assertRaises(SecurityError): self.upd().check()

    def test_rejects_corrupt_package(self):
        self.publish("4.1.0", corrupt=True); u = self.upd(); info = u.check()
        with self.assertRaises(SecurityError): u.stage(info)
        self.assertFalse((paths.install_root() / "app-4.1.0").exists())
        self.assertFalse(list(paths.install_root().glob("*.partial")))

    def test_rejects_zip_slip_package(self):
        self.publish("4.1.0", evil_exe=True); u = self.upd(); info = u.check()
        with self.assertRaises(SecurityError): u.stage(info)
        self.assertFalse((self.tmp / "escape.txt").exists())

    def test_no_key_means_no_updates(self):
        self.publish("4.1.0")
        with self.assertRaises(SecurityError):
            updater.Updater("4.0.0", paths.install_root(), self.policy, "", self.base + "/version.json").check()

    def test_redirect_to_untrusted_host_blocked(self):
        with self.assertRaises(Exception):
            security.fetch_bytes(self.base + "/redir", self.policy)

    def test_bad_version_skipped_and_cleanup(self):
        self.publish("4.1.0"); u = self.upd(); d = u.stage(u.check())
        (d / ".bad").write_text("crash")
        self.assertIsNone(self.upd().check())                     # wersja oznaczona .bad - bez pętli
        for v in ("4.0.0", "3.9.0", "3.8.0"):
            r = paths.install_root() / f"app-{v}"; r.mkdir(); (r / APP_EXE).write_text("x")
        u2 = self.upd("4.1.0"); u2.cleanup_old(keep=2)
        left = sorted(p.name for p in paths.install_root().glob("app-*"))
        self.assertEqual(left, ["app-4.0.0", "app-4.1.0"])


if __name__ == "__main__":
    unittest.main()

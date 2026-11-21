"""Zrzuty nowych stron z podstawionymi danymi (Linux + Xvfb):  xvfb-run python tests/ui_features_smoke.py OUT_DIR"""
import os, subprocess, sys, tempfile, time
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
out = Path(sys.argv[1] if len(sys.argv) > 1 else tempfile.mkdtemp()); out.mkdir(parents=True, exist_ok=True)
tmp = Path(tempfile.mkdtemp())
for k, v in {"LOCALAPPDATA": tmp / "L", "APPDATA": tmp / "R", "PRO_OPT_HOME": tmp / "L" / "P"}.items():
    os.environ[k] = str(v); Path(v).mkdir(parents=True, exist_ok=True)
from pro_optimizer import analyzer, paths, automation
paths.ensure_dirs()
(paths.logs_dir() / "app.log").write_text(
    "2026-11-21 10:00:00,001 INFO pro_optimizer.main: Start PRO Ultimate Optimizer v4.1.0\n"
    "2026-11-21 10:00:05,002 INFO pro_optimizer.automation: Automatyzacja [ram]: zwolniono 1.2 GB (88 procesów)\n"
    "2026-11-21 10:01:00,003 WARNING pro_optimizer.fan: Wentylator: Sterownik odmówił zmiany prędkości (kod 4)\n"
    "2026-11-21 10:02:00,004 ERROR pro_optimizer.updater: Nie udało się sprawdzić aktualizacji\nTraceback (most recent call last):\n  File \"x.py\", line 1\nOSError: brak sieci\n", encoding="utf-8")
from pro_optimizer.ui.app import App
app = App()
def pump(s):
    end = time.time() + s
    while time.time() < end: app.update(); time.sleep(0.03)
def shot(n):
    pump(0.6); subprocess.run(["import", "-window", "root", str(out / f"{n}.png")], check=True)
pump(2.0)
app.show_page("diagnostics"); pump(1.0)
pg = app.page("diagnostics")
facts = {"disk": (952.9 * 2**30, 12.8 * 2**30), "ram_used_pct": 92, "display": {"hz": 60, "max_hz": 180},
         "tweaks": {"power": False, "gamemode": True, "gamedvr": False}, "gpu": {"temp": 80, "fan": 30, "name": "RTX"},
         "defender": {"available": True, "realtime": True, "sig_age_days": 5, "quick_age_days": None},
         "startup_unsigned": ["Updater", "Foo"], "startup_count": 14, "uptime_days": 9, "cache_bytes": 4 * 2**30,
         "games_unoptimized": [{"id": "cs2", "name": "Counter-Strike 2"}], "roblox_installed": True, "top_ram": [("chrome.exe", 4200)]}
pg.findings = analyzer.analyze(facts); pg._render(); shot("diag_filled")
app.show_page("logs"); pump(1.5); shot("logs_filled")
app.show_page("automation")
app.activity.add("ram", True, "zwolniono 1.2 GB (88 procesów)"); app.activity.add("dns", True, "Wyczyszczono pamięć podręczną DNS.")
app.page("automation")._draw_feed(); shot("auto_feed")
app.show_page("drivers"); pump(1.0); shot("drivers2")
app.show_page("antivirus"); pump(1.0); shot("av2")
app.show_page("settings"); pump(0.8); shot("settings2")
print("FEATURES SMOKE DONE"); app.destroy()

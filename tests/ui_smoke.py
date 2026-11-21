"""Smoke-test GUI (Linux + Xvfb):  xvfb-run -s "-screen 0 1280x800x24" python tests/ui_smoke.py OUT_DIR
Buduje udawane środowisko (instalacje Robloxa, cache), przechodzi po stronach i robi zrzuty ekranu."""
import os, subprocess, sys, tempfile, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
out = Path(sys.argv[1] if len(sys.argv) > 1 else tempfile.mkdtemp()); out.mkdir(parents=True, exist_ok=True)

tmp = Path(tempfile.mkdtemp())
for k, v in {"LOCALAPPDATA": tmp / "Local", "APPDATA": tmp / "Roaming", "PROGRAMDATA": tmp / "PD", "WINDIR": tmp / "Win",
             "TEMP": tmp / "Local" / "Temp", "TMP": tmp / "Local" / "Temp", "PRO_OPT_HOME": tmp / "Local" / "ProUltimateOptimizer"}.items():
    os.environ[k] = str(v); Path(v).mkdir(parents=True, exist_ok=True)

def fake(rel, mb):
    p = tmp / rel; p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "wb") as f: f.truncate(int(mb * 1024 * 1024))
fake("Local/Roblox/Versions/version-6f3a9c12d4e8b705/RobloxPlayerBeta.exe", 1)
fake("Local/Roblox/Versions/version-6f3a9c12d4e8b705/RobloxStudioBeta.exe", 1)
fake("Local/Roblox/logs/a.log", 38); fake("Local/Temp/Roblox/x.tmp", 12)
fake("Roaming/discord/Cache/Cache_Data/f1", 412); fake("Roaming/discord/Code Cache/js/a", 64); fake("Roaming/discord/GPUCache/b", 9)
fake("Roaming/Opera Software/Opera GX Stable/Cache/x", 880); fake("Local/Google/Chrome/User Data/Default/Cache/x", 1530)
fake("Local/Spotify/Data/x", 2210); fake("Local/Temp/junk.tmp", 310); fake("Local/NVIDIA/DXCache/s", 150)
fake("Roaming/Code/CachedData/x", 95); fake("Local/Steam/htmlcache/x", 140); fake("Roaming/Telegram Desktop/tdata/user_data/cache/x", 260)

from pro_optimizer import paths
paths.ensure_dirs()
import customtkinter as ctk
from pro_optimizer.ui.app import App

app = App()
def pump(sec):
    end = time.time() + sec
    while time.time() < end:
        app.update(); time.sleep(0.03)
def shot(name):
    pump(0.6)
    subprocess.run(["import", "-window", "root", str(out / f"{name}.png")], check=True)

pump(2.2)
for pid in ("dashboard", "games", "diagnostics", "automation", "cleaner", "system", "fan", "antivirus", "drivers", "backups", "logs", "settings"):
    app.show_page(pid); pump(1.6 if pid in ("cleaner", "dashboard", "games", "diagnostics") else 0.6); shot(pid)

# test dialogu potwierdzenia: kliknij "Tak" po 0.5 s
from pro_optimizer.ui import widgets as w
def click_button(text, tries=40):
    def rec(wd):
        for ch in wd.winfo_children():
            if isinstance(ch, ctk.CTkButton) and ch.cget("text") == text: ch.invoke(); return True
            if rec(ch): return True
        return False
    def tops(wd):                                   # dialog bywa dzieckiem strony, a nie okna głównego
        for ch in wd.winfo_children():
            if isinstance(ch, ctk.CTkToplevel): yield ch
            yield from tops(ch)
    for t in tops(app):
        if rec(t): return
    if tries > 0:                                   # dialog mógł jeszcze nie powstać - spróbuj ponownie
        app.after(150, lambda: click_button(text, tries - 1))
app.after(500, lambda: (shot("dialog"), click_button("Tak")))
res = w.confirm(app, "Test", "Czy dialog działa?")
print("dialog result:", res)
app.toast.show("Zapisano profil „Zbalansowany” (player, studio).", "ok", 60000); shot("toast")

# kliknięcie "Zastosuj profil" - sprawdza zapis ClientAppSettings.json w folderze wersji
app.show_page("games"); pump(0.5)
app.page("games").select("roblox_player"); pump(0.8); shot("games_roblox")
from pro_optimizer.ui.pages.roblox_page import RobloxPage
def find(wd, cls):
    for ch in wd.winfo_children():
        if isinstance(ch, cls): return ch
        r = find(ch, cls)
        if r: return r
rb = find(app.page("games"), RobloxPage); assert rb is not None, "embedded RobloxPage not found"
rb.apply(); pump(1.5)
import json
f = tmp / "Local/Roblox/Versions/version-6f3a9c12d4e8b705/ClientSettings/ClientAppSettings.json"
print("applied:", f.exists(), json.loads(f.read_text()) if f.exists() else None)
print("settings profile:", app.settings.get("roblox_profile"))
# czyszczenie przez GUI
app.show_page("cleaner"); pump(1.5)
page = app.page("cleaner")
app.after(400, lambda: click_button("Wyczyść"))
page.clean(); pump(2.5); shot("cleaner_after")
print("discord cache left:", list((tmp / "Roaming/discord/Cache").rglob("*")))
print("UI SMOKE DONE")
app.destroy()

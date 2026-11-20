"""Launcher - mały, tylko biblioteka standardowa. Skróty wskazują właśnie na niego.

Uruchamia najnowszy folder app-X.Y.Z. Jeśli aplikacja wywali się w ciągu kilku sekund od
startu (zły update), folder dostaje znacznik .bad i launcher automatycznie startuje
poprzednią wersję (rollback). Sam launcher prawie nigdy się nie zmienia.

    ProUltimateOptimizer.exe               uruchom aplikację (skróty)
    ProUltimateOptimizer.exe --uninstall   odinstaluj (wpis w Ustawienia > Aplikacje)
"""
import ctypes
import os
import re
import subprocess
import sys
from pathlib import Path

APP_EXE = "ProUltimateOptimizerApp.exe"
WATCH_SECONDS = 8


def _msg(text):
    try:
        ctypes.windll.user32.MessageBoxW(0, text, "PRO Ultimate Optimizer", 0x10)
    except Exception:
        print(text)


def _ver(name):
    m = re.fullmatch(r"app-(\d+(?:\.\d+)*)", name)
    if not m:
        return None
    p = [int(x) for x in m.group(1).split(".")]
    while len(p) < 4:
        p.append(0)
    return tuple(p)


def candidates(root: Path):
    found = []
    for d in root.iterdir():
        v = _ver(d.name)
        if v and d.is_dir() and (d / APP_EXE).exists() and not (d / ".bad").exists():
            found.append((v, d))
    return [d for _, d in sorted(found, key=lambda t: t[0], reverse=True)]


def uninstall(root: Path, quiet: bool) -> int:
    if not getattr(sys, "frozen", False):                  # uruchamianie z kodu (dev)
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
    from pro_optimizer import install, shell               # leniwie: zwykły start launchera zostaje szybki
    if not quiet:
        if shell.message_box("Czy na pewno odinstalować PRO Ultimate Optimizer?", "Odinstalowanie", 0x24) != 6:
            return 0
        keep = shell.message_box("Zachować Twoje ustawienia, profile i kopie zapasowe?\n\n"
                                 "Tak = zostaną (np. do ponownej instalacji)\nNie = usuń wszystko", "Odinstalowanie", 0x24) == 6
    else:
        keep = True
    try:
        install.uninstall(remove_data=not keep, root=root)
    except Exception as e:                                  # noqa: BLE001
        _msg(f"Odinstalowanie nie powiodło się:\n{e}")
        return 1
    if not quiet:
        shell.message_box("PRO Ultimate Optimizer został odinstalowany.", "Odinstalowanie", 0x40)
    return 0


def main():
    root = Path(sys.executable if getattr(sys, "frozen", False) else __file__).resolve().parent
    args = sys.argv[1:]
    if "--uninstall" in args:
        return uninstall(root, quiet="--quiet" in args)
    cands = candidates(root)
    if not cands:
        _msg("Nie znaleziono zainstalowanej aplikacji.\nUruchom ponownie instalator (Setup).")
        return 1
    for d in cands:
        exe = d / APP_EXE
        try:
            proc = subprocess.Popen([str(exe), *args], cwd=str(d), close_fds=True)
        except OSError:
            (d / ".bad").write_text("start failed")
            continue
        try:
            code = proc.wait(timeout=WATCH_SECONDS)
        except subprocess.TimeoutExpired:
            return 0                      # działa stabilnie - launcher kończy pracę
        if code == 0:
            return 0                      # użytkownik zamknął aplikację normalnie
        try:
            (d / ".bad").write_text(f"exit code {code}")
        except OSError:
            pass
    _msg("Żadna zainstalowana wersja nie uruchamia się poprawnie.\nUruchom instalator, aby naprawić instalację.")
    return 1


if __name__ == "__main__":
    sys.exit(main())

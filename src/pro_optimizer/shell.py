"""Integracja z Windows: skróty, wpis w „Aplikacje i funkcje”, zatrzymanie aplikacji.

Tylko biblioteka standardowa (używa go też maleńki launcher). Poza Windows wszystko to
bezpieczne „nic nie rób” - dzięki temu logikę instalatora da się testować na Linuksie.
Wszystko per-użytkownik (HKCU, Menu Start użytkownika) - żadna operacja nie wymaga admina.
"""
from __future__ import annotations

import logging
import os
import subprocess
from pathlib import Path
from typing import Optional

from .ps import system_exe
from .version import APP_EXE, APP_ID, APP_NAME, VERSION

log = logging.getLogger(__name__)

NT = os.name == "nt"
NO_WINDOW = 0x08000000                       # CREATE_NO_WINDOW
UNINSTALL_KEY = r"Software\Microsoft\Windows\CurrentVersion\Uninstall" + "\\" + APP_ID
PUBLISHER = "Diabeł"

_CSIDL_PROGRAMS = 0x0002                     # Menu Start\Programy (użytkownika)
_CSIDL_DESKTOP = 0x0010                      # Pulpit (z uwzględnieniem OneDrive)

# Skrypt tworzący skrót. Wszystkie dane idą przez zmienne środowiskowe, a NIE przez sklejanie
# tekstu - dzięki temu dziwna nazwa użytkownika (apostrof, $, `) nie może wstrzyknąć kodu.
_PS_LINK = ("$s=(New-Object -ComObject WScript.Shell).CreateShortcut($env:POU_LNK);"
            "$s.TargetPath=$env:POU_TARGET;$s.WorkingDirectory=$env:POU_WD;"
            "$s.IconLocation=$env:POU_ICON;$s.Description=$env:POU_DESC;$s.Save()")


def _special_folder(csidl: int) -> Optional[Path]:
    if not NT:
        return None
    try:
        import ctypes
        buf = ctypes.create_unicode_buffer(260)
        if ctypes.windll.shell32.SHGetFolderPathW(0, csidl, 0, 0, buf) == 0 and buf.value:
            return Path(buf.value)
    except Exception:
        log.debug("SHGetFolderPathW nie zadziałało", exc_info=True)
    return None


def shortcut_paths() -> dict[str, Path]:
    out: dict[str, Path] = {}
    name = f"{APP_NAME}.lnk"
    for key, csidl in (("desktop", _CSIDL_DESKTOP), ("start_menu", _CSIDL_PROGRAMS)):
        base = _special_folder(csidl)
        if base:
            out[key] = base / name
    return out


def create_shortcut(lnk: Path, target: Path, icon: Optional[Path] = None, description: str = APP_NAME) -> bool:
    if not NT:
        return False
    try:
        lnk.parent.mkdir(parents=True, exist_ok=True)
        env = dict(os.environ, POU_LNK=str(lnk), POU_TARGET=str(target), POU_WD=str(target.parent),
                   POU_ICON=f"{icon or target},0", POU_DESC=description)
        subprocess.run([system_exe("powershell"), "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                        "-Command", _PS_LINK], env=env, creationflags=NO_WINDOW, timeout=40,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception as e:
        log.warning("Nie udało się utworzyć skrótu %s: %s", lnk, e)
    return lnk.exists()


def create_shortcuts(target: Path, icon: Optional[Path], desktop: bool, start_menu: bool) -> list[str]:
    """Zwraca listę utworzonych skrótów (do pokazania w podsumowaniu)."""
    made = []
    for key, want in (("desktop", desktop), ("start_menu", start_menu)):
        p = shortcut_paths().get(key)
        if want and p and create_shortcut(p, target, icon):
            made.append(key)
    return made


def remove_shortcuts() -> None:
    for p in shortcut_paths().values():
        try:
            p.unlink(missing_ok=True)
        except OSError as e:
            log.warning("Nie udało się usunąć skrótu %s: %s", p, e)


def _dir_size_kb(root: Path) -> int:
    total = 0
    for dirpath, _dirs, files in os.walk(root):
        for fn in files:
            try:
                total += os.path.getsize(os.path.join(dirpath, fn))
            except OSError:
                pass
    return total // 1024


def register_uninstall(install_root: Path, version: str, launcher: Path, icon: Optional[Path]) -> bool:
    """Wpis w Ustawienia > Aplikacje (HKCU - bez admina)."""
    if not NT:
        return False
    try:
        import winreg
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY, 0, winreg.KEY_SET_VALUE) as k:
            def s(name, val):
                winreg.SetValueEx(k, name, 0, winreg.REG_SZ, str(val))
            s("DisplayName", APP_NAME)
            s("DisplayVersion", version)
            s("Publisher", PUBLISHER)
            s("InstallLocation", install_root)
            s("DisplayIcon", icon or launcher)
            s("UninstallString", f'"{launcher}" --uninstall')
            s("QuietUninstallString", f'"{launcher}" --uninstall --quiet')
            winreg.SetValueEx(k, "NoModify", 0, winreg.REG_DWORD, 1)
            winreg.SetValueEx(k, "NoRepair", 0, winreg.REG_DWORD, 1)
            winreg.SetValueEx(k, "EstimatedSize", 0, winreg.REG_DWORD, _dir_size_kb(install_root))
        return True
    except Exception as e:
        log.warning("Nie udało się zarejestrować aplikacji w Windows: %s", e)
        return False


def unregister_uninstall() -> None:
    if not NT:
        return
    try:
        import winreg
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY)
    except FileNotFoundError:
        pass
    except Exception as e:
        log.warning("Nie udało się usunąć wpisu odinstalowania: %s", e)


def stop_running_app() -> None:
    """Zamyka działającą aplikację (przed aktualizacją launchera / odinstalowaniem)."""
    if not NT:
        return
    try:
        subprocess.run([system_exe("taskkill"), "/IM", APP_EXE, "/F"], creationflags=NO_WINDOW, timeout=15,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass


def message_box(text: str, title: str = APP_NAME, flags: int = 0x40) -> int:
    """MessageBox z ikoną (0x40 info, 0x10 błąd, 0x24 pytanie Tak/Nie). Poza Windows: stdout, 6 (=Tak)."""
    if NT:
        try:
            import ctypes
            return int(ctypes.windll.user32.MessageBoxW(0, text, title, flags))
        except Exception:
            pass
    print(f"[{title}] {text}")
    return 6

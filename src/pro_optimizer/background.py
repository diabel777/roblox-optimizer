"""Praca w tle: ikona przy zegarze (tray), autostart z Windows i przywoływanie ukrytego okna drugim uruchomieniem.

Zamknięcie okna (X) tylko chowa je do zasobnika - automatyka, pilnowanie koloru pada i doping gier działają dalej.
Pełne wyjście: prawy przycisk na ikonie przy zegarze -> Zakończ."""
from __future__ import annotations

import logging
import os
import sys
import threading
from pathlib import Path
from typing import Callable, Optional

log = logging.getLogger(__name__)
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_NAME = "AderisBoost"
EVENT_NAME = "Local\\AderisBoost.ShowWindow"
NT = os.name == "nt"


# --------------------------------------------------------------------------- autostart
def autostart_command(launcher: Path) -> str:
    return f'"{launcher}" --background'


def autostart_enabled() -> bool:
    if not NT:
        return False
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            winreg.QueryValueEx(k, RUN_NAME)
        return True
    except OSError:
        return False


def set_autostart(enabled: bool, launcher: Optional[Path] = None) -> bool:
    if not NT:
        return False
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
            if enabled:
                if launcher is None:
                    from . import paths
                    from .install import launcher_path
                    launcher = launcher_path(paths.install_root())
                winreg.SetValueEx(k, RUN_NAME, 0, winreg.REG_SZ, autostart_command(launcher))
            else:
                try:
                    winreg.DeleteValue(k, RUN_NAME)
                except FileNotFoundError:
                    pass
        return True
    except OSError:
        log.warning("Autostart: zapis do rejestru nie powiódł się", exc_info=True)
        return False


# --------------------------------------------------------------------------- sygnał "pokaż okno"
def signal_existing() -> bool:
    """Drugie uruchomienie: prosi działającą (być może ukrytą) instancję o pokazanie okna."""
    if not NT:
        return False
    import ctypes
    k = ctypes.windll.kernel32
    h = k.OpenEventW(0x0002, False, EVENT_NAME)          # EVENT_MODIFY_STATE
    if not h:
        return False
    k.SetEvent(h)
    k.CloseHandle(h)
    return True


def listen_for_show(callback: Callable[[], None]) -> None:
    """Wątek czekający na sygnał z `signal_existing`; callback wołany w wątku tła (UI musi użyć after)."""
    if not NT:
        return
    import ctypes
    k = ctypes.windll.kernel32
    h = k.CreateEventW(None, False, False, EVENT_NAME)

    def loop():
        while True:
            if k.WaitForSingleObject(h, 0xFFFFFFFF) == 0:
                try:
                    callback()
                except Exception:
                    log.exception("show callback")
    threading.Thread(target=loop, daemon=True).start()


# --------------------------------------------------------------------------- tray
class Tray:
    """Ikona w zasobniku. Gdy biblioteka pystray jest niedostępna, `ok` = False i aplikacja zamyka się normalnie."""

    def __init__(self, title: str, icon_path: Path, on_open: Callable[[], None], on_quit: Callable[[], None]):
        self.ok = False
        self._icon = None
        if not NT:
            return
        try:
            import pystray
            from PIL import Image
            img = Image.open(icon_path)
            try:
                img.size = max(img.info.get("sizes", {(64, 64)}))
            except Exception:
                pass
            img = img.convert("RGBA").resize((64, 64))
            menu = pystray.Menu(
                pystray.MenuItem(f"Otwórz {title}", lambda *_: on_open(), default=True),
                pystray.MenuItem("Zakończ całkowicie", lambda *_: on_quit()),
            )
            self._icon = pystray.Icon("AderisBoost", img, title, menu)
            self.ok = True
        except Exception:
            log.warning("Tray niedostępny", exc_info=True)

    def start(self) -> None:
        if self._icon:
            threading.Thread(target=self._icon.run, daemon=True).start()

    def notify(self, text: str, title: str = "") -> None:
        try:
            if self._icon:
                self._icon.notify(text, title)
        except Exception:
            pass

    def stop(self) -> None:
        try:
            if self._icon:
                self._icon.stop()
        except Exception:
            pass

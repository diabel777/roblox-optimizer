"""Punkt startowy aplikacji."""
from __future__ import annotations

import ctypes
import logging
import logging.handlers
import os
import sys
import time

from . import paths
from .version import APP_NAME, VERSION

_mutex = None


def setup_logging() -> None:
    paths.logs_dir().mkdir(parents=True, exist_ok=True)
    h = logging.handlers.RotatingFileHandler(paths.logs_dir() / "app.log", maxBytes=512 * 1024, backupCount=3, encoding="utf-8")
    h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(h)
    logging.getLogger(__name__).info("Start %s v%s (%s)", APP_NAME, VERSION, sys.executable)


def acquire_single_instance(wait: float = 0.0) -> bool:
    """Jedna instancja naraz. `wait` pozwala nowej instancji (np. po restarcie/UAC) poczekać na zamknięcie starej."""
    global _mutex
    if os.name != "nt":
        return True
    deadline = time.time() + wait
    while True:
        _mutex = ctypes.windll.kernel32.CreateMutexW(None, False, "Local\\ProUltimateOptimizer.SingleInstance")
        if ctypes.windll.kernel32.GetLastError() != 183:      # ERROR_ALREADY_EXISTS
            return True
        ctypes.windll.kernel32.CloseHandle(_mutex)
        if time.time() >= deadline:
            return False
        time.sleep(0.25)


def main() -> int:
    paths.ensure_dirs()
    setup_logging()
    if not acquire_single_instance(wait=8):
        try:
            ctypes.windll.user32.MessageBoxW(0, f"{APP_NAME} jest już uruchomiony.", APP_NAME, 0x40)
        except Exception:
            pass
        return 0
    from .ui.app import App
    App().mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())

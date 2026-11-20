"""Ustawienia użytkownika (settings.json) - zapis atomowy, odporny na uszkodzenia."""
from __future__ import annotations

import json
import logging
import os
import threading
from typing import Any

from . import paths

log = logging.getLogger(__name__)

DEFAULTS: dict[str, Any] = {
    "auto_update": True,
    "update_check_hours": 6,
    "last_update_check": 0,
    "auto_reapply_roblox": True,
    "roblox_profile": {"preset": "balanced", "fps": 0, "targets": ["player", "studio"], "merge": True},
    "max_backups": 30,
    "confirm_destructive": True,
    "tweaks_backup": {},
}

_lock = threading.Lock()


class Settings:
    def __init__(self):
        self.data: dict[str, Any] = {}
        self.load()

    def load(self) -> None:
        loaded: dict = {}
        try:
            with open(paths.settings_file(), "r", encoding="utf-8") as f:
                loaded = json.load(f)
            if not isinstance(loaded, dict):
                loaded = {}
        except FileNotFoundError:
            pass
        except Exception as e:
            log.warning("Uszkodzony settings.json (%s) - używam domyślnych", e)
        self.data = {**json.loads(json.dumps(DEFAULTS)), **loaded}

    def save(self) -> None:
        with _lock:
            try:
                paths.install_root().mkdir(parents=True, exist_ok=True)
                tmp = paths.settings_file().with_suffix(".tmp")
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(self.data, f, indent=2, ensure_ascii=False)
                os.replace(tmp, paths.settings_file())
            except OSError as e:
                log.error("Nie udało się zapisać ustawień: %s", e)

    def get(self, key: str, default: Any = None) -> Any:
        return self.data.get(key, DEFAULTS.get(key, default))

    def set(self, key: str, value: Any) -> None:
        self.data[key] = value
        self.save()

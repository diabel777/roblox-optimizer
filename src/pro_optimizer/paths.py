"""Ścieżki aplikacji. Wszystko per-użytkownik (LOCALAPPDATA) - nie wymaga admina."""
from __future__ import annotations

import os
import sys
from pathlib import Path

from .version import APP_ID


def local_appdata() -> Path:
    v = os.environ.get("LOCALAPPDATA")
    return Path(v) if v else Path.home() / "AppData" / "Local"


def install_root() -> Path:
    """Katalog instalacji: %LOCALAPPDATA%\\ProUltimateOptimizer (PRO_OPT_HOME tylko do testów)."""
    override = os.environ.get("PRO_OPT_HOME")
    return Path(override) if override else local_appdata() / APP_ID


def backups_dir() -> Path:
    return install_root() / "Backups"       # ta sama nazwa co w v3.x - kopie zostają


def logs_dir() -> Path:
    return install_root() / "logs"


def config_dir() -> Path:
    """Tu leżą Twoje pliki do customizacji (theme.json, apps.user.json, presets.user.json)."""
    return install_root() / "config"


def downloads_dir() -> Path:
    return install_root() / "downloads"


def reports_dir() -> Path:
    return install_root() / "reports"


def settings_file() -> Path:
    return install_root() / "settings.json"


def resource_dir() -> Path:
    """Katalog z domyślnymi plikami (config/, assets/) - w exe: _MEIPASS, w dev: korzeń repo."""
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parents[2]


def ensure_dirs() -> None:
    for d in (install_root(), backups_dir(), logs_dir(), config_dir(), downloads_dir()):
        d.mkdir(parents=True, exist_ok=True)

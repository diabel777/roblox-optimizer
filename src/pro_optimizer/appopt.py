"""Optymalizacja aplikacji w tle: gdy działa gra, programy typu przeglądarka/Discord/Spotify dostają niższy priorytet procesora,
więc gra ma więcej mocy. Po zamknięciu gry wszystko wraca do normy. Nic nie zamykamy i nie usuwamy."""
from __future__ import annotations

import logging
import os

log = logging.getLogger(__name__)

BACKGROUND_APPS = {
    "Discord": ["discord.exe"], "Opera": ["opera.exe"], "Chrome": ["chrome.exe"], "Edge": ["msedge.exe"],
    "Firefox": ["firefox.exe"], "Spotify": ["spotify.exe"], "Steam (okna)": ["steamwebhelper.exe"],
    "Teams": ["ms-teams.exe", "teams.exe"], "Slack": ["slack.exe"], "Telegram": ["telegram.exe"],
    "OneDrive": ["onedrive.exe"], "Epic Games Launcher": ["epicgameslauncher.exe", "epicwebhelper.exe"],
    "Battle.net": ["battle.net.exe"], "WhatsApp": ["whatsapp.exe"],
}
_ALL = {e for v in BACKGROUND_APPS.values() for e in v}


def _set(priority_name: str, only_running=None) -> int:
    try:
        import psutil
    except ImportError:
        return 0
    prio = getattr(psutil, priority_name, None)
    if prio is None:
        return 0
    n, me = 0, os.getpid()
    for p in psutil.process_iter(["name", "pid"]):
        try:
            name = (p.info["name"] or "").lower()
            if name in _ALL and p.info["pid"] != me:
                p.nice(prio)
                n += 1
        except (psutil.Error, PermissionError, OSError):
            continue
    return n


def lower_background() -> int:
    """Zwraca liczbę procesów, którym obniżono priorytet (Windows: BELOW_NORMAL; bez admina)."""
    return _set("BELOW_NORMAL_PRIORITY_CLASS") if os.name == "nt" else 0


def restore_background() -> int:
    return _set("NORMAL_PRIORITY_CLASS") if os.name == "nt" else 0

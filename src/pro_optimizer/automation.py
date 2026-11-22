"""Automatyzacja w tle: samo zwalnianie RAM, czyszczenie DNS, czyszczenie cache, pilnowanie optymalizacji,
aktualizacja definicji Defendera i doping gier. Planowanie jest czystą funkcją (testowalną), wykonanie osobno."""
from __future__ import annotations

import logging
import time
from collections import deque
from typing import Callable, Optional

log = logging.getLogger(__name__)

DEFAULTS: dict = {
    "ram": {"enabled": False, "threshold_pct": 85, "min_interval_min": 10},
    "dns": {"enabled": False, "interval_hours": 6},
    "clean": {"enabled": False, "interval_hours": 24},
    "tweaks": {"enabled": False, "interval_hours": 6},
    "defender": {"enabled": False, "interval_hours": 12},
    "game_boost": {"enabled": True},
    "app_opt": {"enabled": True},
}

TASK_LABELS = {
    "ram": "Zwolnienie pamięci RAM", "dns": "Wyczyszczenie DNS", "clean": "Czyszczenie cache aplikacji",
    "tweaks": "Pilnowanie optymalizacji Windows", "defender": "Aktualizacja definicji antywirusa",
    "game_boost": "Doping uruchomionej gry", "app_opt": "Optymalizacja aplikacji w tle",
}


def merged(cfg: Optional[dict]) -> dict:
    out = {k: dict(v) for k, v in DEFAULTS.items()}
    for k, v in (cfg or {}).items():
        if k in out and isinstance(v, dict):
            out[k].update(v)
    return out


def plan(cfg: dict, now: float, last: dict, ram_used_pct: Optional[float], games_running: list[str],
         boosted: set[str]) -> list[str]:
    """Zwraca listę zadań do wykonania teraz. Nic nie wykonuje."""
    cfg = merged(cfg)
    due: list[str] = []

    def elapsed(name: str) -> float:
        return now - float(last.get(name, 0))

    r = cfg["ram"]
    if r["enabled"] and ram_used_pct is not None and ram_used_pct >= r["threshold_pct"] \
            and elapsed("ram") >= r["min_interval_min"] * 60:
        due.append("ram")
    for name, key in (("dns", "interval_hours"), ("clean", "interval_hours"),
                      ("tweaks", "interval_hours"), ("defender", "interval_hours")):
        c = cfg[name]
        if c["enabled"] and elapsed(name) >= max(0.25, float(c[key])) * 3600:
            due.append(name)
    if cfg["game_boost"]["enabled"] and any(g not in boosted for g in games_running):
        due.append("game_boost")
    return due


class Activity:
    """Ostatnie zdarzenia automatyzacji (do wyświetlenia na stronie)."""

    def __init__(self, n: int = 40):
        self.items: deque = deque(maxlen=n)

    def add(self, task: str, ok: bool, text: str) -> None:
        self.items.appendleft((time.time(), task, ok, text))
        (log.info if ok else log.warning)("Automatyzacja [%s]: %s", task, text)


# --------------------------------------------------------------------------- wykonanie
SAFE_TWEAKS = ("power", "gamemode", "gamedvr")        # zmiany bez admina; reszta tylko gdy aplikacja ma uprawnienia


def run_task(name: str, settings, catalog: list[dict], games: list[dict], running: set[str]) -> tuple[bool, str]:
    """Wykonuje jedno zadanie. Wołać z wątku w tle. Zwraca (ok, opis)."""
    from . import cleaner, defender, games as gm, winsys
    if name == "ram":
        res = winsys.trim_ram()
        if not res.get("ok"):
            return False, res.get("msg", "nie udało się")
        return True, f"zwolniono {cleaner.fmt_bytes(res.get('freed', 0))} ({res.get('processes', 0)} procesów)"
    if name == "dns":
        return winsys.flush_dns()
    if name == "clean":
        entries = [e for e in catalog if e.get("default")]
        res = cleaner.clean(entries, running)
        return True, f"zwolniono {cleaner.fmt_bytes(sum(r.size for r in res))} z dysku"
    if name == "tweaks":
        fixed = []
        for t in winsys.TWEAKS:
            if t.id not in SAFE_TWEAKS and not (t.admin and winsys.is_admin()):
                continue
            if t.id not in (settings.get("auto_tweaks") or list(SAFE_TWEAKS)):
                continue
            if winsys.tweak_state(t) is False:
                ok, _ = winsys.apply_tweak(t, settings)
                if ok:
                    fixed.append(t.name)
        return True, ("przywrócono: " + ", ".join(fixed)) if fixed else "wszystko już ustawione"
    if name == "defender":
        return defender.update_signatures()
    if name == "app_opt":
        from . import appopt
        if not gm.running_game_exes(games, running):
            return True, "brak uruchomionej gry - nic do zrobienia (działa automatycznie, gdy włączysz grę)"
        n = appopt.lower_background()
        return True, f"obniżono priorytet {n} procesów w tle (wrócą do normy po zakończeniu gry)"
    if name == "game_boost":
        live = gm.running_game_exes(games, running)
        saved = settings.get("games") or {}
        n = 0
        for g in live:
            if (saved.get(g["id"]) or {}).get("auto_boost", True):
                n += gm.boost_running(g.get("exes", []))
        extra = ""
        if n and merged(settings.get("auto"))["app_opt"]["enabled"]:
            from . import appopt
            extra = f", {appopt.lower_background()} programów w tle spowolniono"
        if n:
            winsys.trim_ram()
        return True, f"gra: {', '.join(g['name'] for g in live)} - priorytet podniesiony ({n} proc.), pamięć zwolniona{extra}"
    return False, "nieznane zadanie"

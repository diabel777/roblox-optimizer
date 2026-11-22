"""Wczytywanie plików konfiguracyjnych: domyślne (w aplikacji) + Twoje nadpisania.

Pliki do customizacji - kładziesz je w  %LOCALAPPDATA%\\ProUltimateOptimizer\\config\\ :
    theme.json          - kolory, czcionki, zaokrąglenia (łączone z domyślnym)
    apps.user.json      - własne aplikacje do czyszczenia (dodają się do katalogu / nadpisują po "id")
    presets.user.json   - własne profile Roblox
Nie musisz przebudowywać aplikacji ani czekać na aktualizację.
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

from . import paths

log = logging.getLogger(__name__)


MAX_CONFIG_BYTES = 1024 * 1024        # większy plik konfiguracji = podejrzany / może zawiesić start
_ID = re.compile(r"^[A-Za-z0-9_.\-]{1,64}$")
_HEX = re.compile(r"^#[0-9A-Fa-f]{6}$")
_USER_OVERRIDABLE = {"default", "disabled", "name", "id", "desc", "group"}   # co wolno zmienić we wpisie wbudowanym


def _read(path: Path) -> Any:
    try:
        if path.stat().st_size > MAX_CONFIG_BYTES:
            log.warning("Pominięto %s: plik za duży", path)
            return None
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return None
    except Exception as e:  # zepsuty JSON użytkownika nie może wywalić aplikacji
        log.warning("Nie można wczytać %s: %s", path, e)
        return None


def deep_merge(base: dict, over: dict) -> dict:
    out = dict(base)
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def _clean_theme(user: dict, base: dict) -> dict:
    """Przepuszcza tylko poprawne wartości (kolory #RRGGBB, liczby w rozsądnym zakresie, tekst czcionki)."""
    out: dict = {}
    for k, v in user.items():
        b = base.get(k)
        if k == "colors" and isinstance(v, dict):
            out[k] = {ck: cv for ck, cv in v.items() if ck in (b or {}) and isinstance(cv, str) and _HEX.match(cv)}
        elif k == "fonts" and isinstance(v, dict):
            f = {}
            for fk, fv in v.items():
                if fk == "family" and isinstance(fv, str) and 1 <= len(fv) <= 60:
                    f[fk] = fv
                elif fk in (b or {}) and fk != "family" and isinstance(fv, int) and not isinstance(fv, bool) and 8 <= fv <= 48:
                    f[fk] = fv
            out[k] = f
        elif k in ("radius", "window") and isinstance(v, dict):
            out[k] = {nk: nv for nk, nv in v.items() if nk in (b or {}) and isinstance(nv, int)
                      and not isinstance(nv, bool) and 0 <= nv <= 4000}
        elif k == "animations" and isinstance(v, bool):
            out[k] = v
    return out


def load_theme() -> dict:
    base = _read(paths.resource_dir() / "config" / "theme.json") or {}
    user = _read(paths.config_dir() / "theme.json")
    return deep_merge(base, _clean_theme(user, base)) if isinstance(user, dict) else base


def _str_list(v: Any, maxn: int = 64) -> list:
    return [x for x in v if isinstance(x, str) and 0 < len(x) <= 400][:maxn] if isinstance(v, list) else []


def _merge_by_id(base: list, user: Any, kind: str = "") -> list:
    """Łączy katalog wbudowany z plikiem użytkownika. Zasady bezpieczeństwa:
    * wpis wbudowany można tylko wyłączyć / zmienić nazwę / opis / domyślne zaznaczenie - nie jego ścieżki ani procesy,
    * nowy wpis użytkownika dostaje flagę user=True i NIGDY nie jest zaznaczony domyślnie (nie czyści się sam)."""
    items = {e["id"]: e for e in base if isinstance(e, dict) and isinstance(e.get("id"), str)}
    for e in (user if isinstance(user, list) else [])[:200]:
        if not isinstance(e, dict) or not isinstance(e.get("id"), str) or not _ID.match(e["id"]):
            continue
        eid = e["id"]
        if e.get("disabled") is True:
            items.pop(eid, None)
        elif eid in items:
            items[eid] = {**items[eid], **{k: v for k, v in e.items() if k in _USER_OVERRIDABLE and k != "id"}}
        else:
            ne = {k: v for k, v in e.items() if isinstance(k, str)}
            if kind == "apps":
                ne = {"id": eid, "name": str(e.get("name", eid))[:80], "group": str(e.get("group", "Własne"))[:40],
                      "paths": _str_list(e.get("paths")), "processes": _str_list(e.get("processes"), 16),
                      "user": True, "default": False}
                if not ne["paths"]:
                    continue
            items[eid] = ne
    return list(items.values())


def load_apps() -> list[dict]:
    base = _read(paths.resource_dir() / "config" / "apps.json") or []
    return _merge_by_id(base, _read(paths.config_dir() / "apps.user.json"), "apps")


def load_presets() -> list[dict]:
    base = _read(paths.resource_dir() / "config" / "presets.json") or []
    return _merge_by_id(base, _read(paths.config_dir() / "presets.user.json"))


def load_games() -> list[dict]:
    base = _read(paths.resource_dir() / "config" / "games.json") or []
    return _merge_by_id(base, _read(paths.config_dir() / "games.user.json"))

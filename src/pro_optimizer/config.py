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
from pathlib import Path
from typing import Any

from . import paths

log = logging.getLogger(__name__)


def _read(path: Path) -> Any:
    try:
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


def load_theme() -> dict:
    base = _read(paths.resource_dir() / "config" / "theme.json") or {}
    user = _read(paths.config_dir() / "theme.json")
    return deep_merge(base, user) if isinstance(user, dict) else base


def _merge_by_id(base: list, user: Any) -> list:
    items = {e["id"]: e for e in base if isinstance(e, dict) and "id" in e}
    for e in (user if isinstance(user, list) else []):
        if not isinstance(e, dict) or "id" not in e:
            continue
        if e.get("disabled"):
            items.pop(e["id"], None)
        elif e["id"] in items:
            items[e["id"]] = {**items[e["id"]], **e}
        else:
            items[e["id"]] = e
    return list(items.values())


def load_apps() -> list[dict]:
    base = _read(paths.resource_dir() / "config" / "apps.json") or []
    return _merge_by_id(base, _read(paths.config_dir() / "apps.user.json"))


def load_presets() -> list[dict]:
    base = _read(paths.resource_dir() / "config" / "presets.json") or []
    return _merge_by_id(base, _read(paths.config_dir() / "presets.user.json"))

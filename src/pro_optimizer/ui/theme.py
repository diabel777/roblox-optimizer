"""Motyw interfejsu - wczytywany z config/theme.json (+ Twoje nadpisania z folderu config)."""
from __future__ import annotations

from types import SimpleNamespace

import customtkinter as ctk

from .. import config

_FALLBACK = {
    "colors": {"bg": "#0A0D14", "sidebar": "#0E121B", "card": "#131926", "card_hover": "#182032", "border": "#1E2738",
               "text": "#E6EAF2", "muted": "#8B96AB", "accent": "#7C5CFF", "accent_hover": "#9277FF",
               "accent2": "#22D3EE", "success": "#34D399", "warning": "#FBBF24", "danger": "#F43F5E",
               "danger_hover": "#FB7185"},
    "fonts": {"family": "Segoe UI", "title": 24, "heading": 15, "body": 13, "small": 11},
    "radius": {"card": 14, "button": 10},
    "window": {"width": 1140, "height": 780, "min_width": 980, "min_height": 680},
    "animations": True,
}

c = SimpleNamespace()      # kolory      -> theme.c.accent
f = SimpleNamespace()      # fonty (rozmiary)
r = SimpleNamespace()      # zaokrąglenia
win = SimpleNamespace()    # okno
flags = SimpleNamespace(animations=True)
_font_cache: dict = {}


def load() -> None:
    data = config.deep_merge(_FALLBACK, config.load_theme())
    c.__dict__.update(data["colors"])
    f.__dict__.update(data["fonts"])
    r.__dict__.update(data["radius"])
    win.__dict__.update(data["window"])
    flags.animations = bool(data.get("animations", True))
    _font_cache.clear()
    ctk.set_appearance_mode("dark")


def font(kind: str = "body", weight: str = "normal") -> ctk.CTkFont:
    key = (kind, weight)
    if key not in _font_cache:
        _font_cache[key] = ctk.CTkFont(family=f.family, size=getattr(f, kind), weight=weight)
    return _font_cache[key]


def blend(a: str, b: str, t: float) -> str:
    """Miesza dwa kolory hex: t=0 -> a, t=1 -> b."""
    pa = [int(a[i:i + 2], 16) for i in (1, 3, 5)]
    pb = [int(b[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(x + (y - x) * t):02X}" for x, y in zip(pa, pb))

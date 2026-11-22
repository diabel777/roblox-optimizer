"""Animacje oparte na after(): przejścia stron, płynne paski, liczniki, pierścień wyniku.
Wszystko liczone od czasu zegara (nie od liczby klatek), więc na wolnym komputerze animacja po prostu jest mniej płynna,
a nie wolniejsza. Animacje można wyłączyć w config/theme.json:  "animations": false  (ułatwienia dostępu / słabe PC)."""
from __future__ import annotations

import time
import tkinter as tk
from typing import Callable, Optional

import customtkinter as ctk

from . import theme
from .theme import c

FRAME_MS = 16
_enabled = True


def set_enabled(v: bool) -> None:
    global _enabled
    _enabled = bool(v)


def enabled() -> bool:
    return _enabled


def ease_out(t: float) -> float:
    return 1 - (1 - t) ** 3


def ease_in_out(t: float) -> float:
    return 3 * t * t - 2 * t * t * t


def tween(widget, ms: int, step: Callable[[float], None], done: Optional[Callable[[], None]] = None,
          ease: Callable[[float], float] = ease_out) -> Callable[[], None]:
    """Wywołuje step(0..1) przez `ms` milisekund. Zwraca funkcję anulującą. Przy wyłączonych animacjach skacze do końca."""
    state = {"stop": False}

    def cancel():
        state["stop"] = True

    if not _enabled or ms <= 0:
        step(1.0)
        if done:
            done()
        return cancel
    t0 = time.perf_counter()

    def tick():
        if state["stop"]:
            return
        try:
            if not widget.winfo_exists():
                return
            t = min(1.0, (time.perf_counter() - t0) * 1000 / ms)
            step(ease(t))
            if t >= 1.0:
                if done:
                    done()
                return
            widget.after(FRAME_MS, tick)
        except tk.TclError:
            return

    tick()
    return cancel


class Animator:
    """Trzyma jedną animację na klucz - nowa anuluje poprzednią (np. szybkie najeżdżanie myszką)."""

    def __init__(self):
        self._c: dict = {}

    def run(self, key, widget, ms, step, done=None, ease=ease_out):
        old = self._c.pop(key, None)
        if old:
            old()
        self._c[key] = tween(widget, ms, step, done, ease)


def fade_color(widget, anim: Animator, key: str, prop: str, a: str, b: str, ms: int = 140) -> None:
    anim.run(key, widget, ms, lambda t: widget.configure(**{prop: theme.blend(a, b, t)}))


def hover_fade(btn: ctk.CTkButton, base: str, hover: str, ms: int = 130) -> None:
    """Płynna zmiana koloru przycisku przy najechaniu (zamiast natychmiastowej)."""
    an = Animator()
    cur = {"c": base}

    def go(target):
        start = cur["c"]

        def step(t):
            cur["c"] = theme.blend(start, target, t)
            btn.configure(fg_color=cur["c"])
        an.run("h", btn, ms, step)

    btn.bind("<Enter>", lambda e: go(hover), add="+")
    btn.bind("<Leave>", lambda e: go(base), add="+")


def slide_in(page, dy: int = 18, ms: int = 220) -> None:
    """Strona wsuwa się z dołu (place + y)."""
    page.place_configure(y=dy)

    def step(t):
        page.place_configure(y=round(dy * (1 - t)))
    tween(page, ms, step, lambda: page.place_configure(y=0))


def smooth_bar(bar: ctk.CTkProgressBar, target: float, ms: int = 450) -> None:
    start = float(getattr(bar, "_anim_val", 0.0))
    target = max(0.0, min(1.0, target))
    if abs(target - start) < 0.004:
        bar.set(target)
        bar._anim_val = target
        return
    old = getattr(bar, "_anim_cancel", None)
    if old:
        old()

    def step(t):
        v = start + (target - start) * t
        bar._anim_val = v
        bar.set(v)
    bar._anim_cancel = tween(bar, ms, step)


def count_to(label: ctk.CTkLabel, start: float, end: float, fmt: Callable[[float], str], ms: int = 700) -> None:
    old = getattr(label, "_count_cancel", None)
    if old:
        old()
    label._count_cancel = tween(label, ms, lambda t: label.configure(text=fmt(start + (end - start) * t)))


class ScoreRing(tk.Canvas):
    """Animowany pierścień wyniku 0-100 z liczbą w środku."""

    def __init__(self, master, size: int = 150, thickness: int = 12):
        super().__init__(master, width=size, height=size, bg=c.card, highlightthickness=0, bd=0)
        self.size, self.th = size, thickness
        self.value = 0.0
        self._cancel = None
        self._draw(0.0, c.muted)

    def _color_for(self, v: float) -> str:
        return c.success if v >= 80 else (c.warning if v >= 55 else c.danger)

    def _draw(self, v: float, color: str) -> None:
        self.delete("all")
        pad = self.th / 2 + 2
        box = (pad, pad, self.size - pad, self.size - pad)
        self.create_arc(*box, start=0, extent=359.9, style="arc", width=self.th, outline=theme.blend(c.card, "#FFFFFF", 0.09))
        if v > 0:
            self.create_arc(*box, start=90, extent=-3.599 * v, style="arc", width=self.th, outline=color)
        self.create_text(self.size / 2, self.size / 2 - 4, text=f"{round(v)}", fill=c.text,
                         font=("Segoe UI", int(self.size / 3.4), "bold"))
        self.create_text(self.size / 2, self.size / 2 + self.size / 5, text="/ 100", fill=c.muted, font=("Segoe UI", 10))

    def set(self, target: float, ms: int = 900) -> None:
        if self._cancel:
            self._cancel()
        start = self.value
        color = self._color_for(target)

        def step(t):
            self.value = start + (target - start) * t
            self._draw(self.value, color)
        self._cancel = tween(self, ms, step)

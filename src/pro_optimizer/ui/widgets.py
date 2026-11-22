"""Wspólne widgety: karty, przyciski, kafelki statystyk, okna dialogowe, toasty, wątki w tle."""
from __future__ import annotations

import logging
import queue
import threading
from typing import Any, Callable, Optional

import customtkinter as ctk

from . import anim, theme
from .theme import c, font, r

log = logging.getLogger(__name__)


# --------------------------------------------------------------------------- praca w tle
class Bg:
    """Uruchamia funkcje w wątkach i odsyła wynik do wątku UI (bezpiecznie dla Tk)."""

    def __init__(self, root):
        self.root = root
        self.q: queue.Queue = queue.Queue()
        root.after(60, self._pump)

    def _pump(self):
        try:
            while True:
                cb, args = self.q.get_nowait()
                try:
                    cb(*args)
                except Exception:
                    log.exception("Błąd w callbacku UI")
        except queue.Empty:
            pass
        try:
            self.root.after(60, self._pump)
        except Exception:
            pass

    def call(self, cb: Callable, *args) -> None:
        """Do wywołania z wątku: wykona cb(*args) w wątku UI."""
        self.q.put((cb, args))

    def run(self, fn: Callable[[], Any], done: Optional[Callable[[Any], None]] = None,
            fail: Optional[Callable[[Exception], None]] = None) -> None:
        def worker():
            try:
                res = fn()
            except Exception as e:  # noqa: BLE001
                log.warning("Zadanie w tle nie powiodło się: %s", e, exc_info=True)
                if fail:
                    self.q.put((fail, (e,)))
                return
            if done:
                self.q.put((done, (res,)))
        threading.Thread(target=worker, daemon=True).start()


# --------------------------------------------------------------------------- podstawowe elementy
def card(master, **kw) -> ctk.CTkFrame:
    kw.setdefault("fg_color", c.card)
    kw.setdefault("border_color", c.border)
    return ctk.CTkFrame(master, corner_radius=r.card, border_width=1, **kw)


def label(master, text: str = "", kind: str = "body", color: Optional[str] = None, weight: str = "normal", **kw):
    kw.setdefault("anchor", "w")
    kw.setdefault("justify", "left")
    return ctk.CTkLabel(master, text=text, font=font(kind, weight), text_color=color or c.text, **kw)


_STYLES = {
    "primary": lambda: dict(fg_color=c.accent, hover_color=c.accent_hover, text_color="#FFFFFF"),
    "success": lambda: dict(fg_color=theme.blend(c.success, "#000000", 0.35), hover_color=theme.blend(c.success, "#000000", 0.15), text_color="#FFFFFF"),
    "danger": lambda: dict(fg_color=theme.blend(c.danger, "#000000", 0.25), hover_color=c.danger, text_color="#FFFFFF"),
    "ghost": lambda: dict(fg_color=theme.blend(c.card, "#FFFFFF", 0.06), hover_color=theme.blend(c.card, "#FFFFFF", 0.13),
                          text_color=c.text, border_width=1, border_color=c.border),
}


def button(master, text: str, command: Optional[Callable] = None, style: str = "primary", height: int = 38, **kw):
    opts = _STYLES[style]()
    opts.update(kw)
    return ctk.CTkButton(master, text=text, command=command, height=height, corner_radius=r.button,
                         font=font("body", "bold"), **opts)


def switch(master, text: str, command: Optional[Callable] = None, **kw):
    return ctk.CTkSwitch(master, text=text, command=command, font=font("body"), text_color=c.text,
                         progress_color=c.accent, button_color="#FFFFFF", button_hover_color="#E5E7EB",
                         fg_color=theme.blend(c.card, "#FFFFFF", 0.14), **kw)


def checkbox(master, text: str, variable=None, command: Optional[Callable] = None, **kw):
    return ctk.CTkCheckBox(master, text=text, variable=variable, command=command, font=font("body"),
                           text_color=c.text, fg_color=c.accent, hover_color=c.accent_hover,
                           border_color=theme.blend(c.border, "#FFFFFF", 0.25), checkmark_color="#FFFFFF",
                           corner_radius=6, border_width=2, **kw)


def progress(master, **kw):
    return ctk.CTkProgressBar(master, height=8, corner_radius=4, progress_color=c.accent,
                              fg_color=theme.blend(c.card, "#FFFFFF", 0.1), **kw)


def entry(master, **kw):
    return ctk.CTkEntry(master, height=36, corner_radius=r.button, fg_color=theme.blend(c.card, "#000000", 0.3),
                        border_color=c.border, text_color=c.text, font=font("body"), **kw)


def scroll_frame(master, **kw):
    return ctk.CTkScrollableFrame(master, fg_color="transparent", corner_radius=0,
                                  scrollbar_button_color=theme.blend(c.card, "#FFFFFF", 0.15),
                                  scrollbar_button_hover_color=theme.blend(c.card, "#FFFFFF", 0.3), **kw)


def badge(master, text: str, color: Optional[str] = None):
    col = color or c.accent
    return ctk.CTkLabel(master, text=f"  {text}  ", font=font("small", "bold"), text_color=col,
                        fg_color=theme.blend(c.card, col, 0.16), corner_radius=8, height=20)


def divider(master):
    return ctk.CTkFrame(master, height=1, fg_color=c.border)


class StatTile(ctk.CTkFrame):
    """Kafelek: tytuł, duża wartość, podpis i opcjonalny pasek."""

    def __init__(self, master, title: str, with_bar: bool = True, bar_color: Optional[str] = None):
        super().__init__(master, corner_radius=r.card, border_width=1, border_color=c.border, fg_color=c.card)
        self.t = label(self, title.upper(), "small", c.muted, "bold")
        self.t.pack(fill="x", padx=18, pady=(16, 0))
        self.v = label(self, "—", "title", c.text, "bold")
        self.v.pack(fill="x", padx=18, pady=(2, 0))
        self.s = label(self, " ", "small", c.muted)
        self.s.pack(fill="x", padx=18, pady=(0, 8))
        self.bar = None
        if with_bar:
            self.bar = progress(self)
            if bar_color:
                self.bar.configure(progress_color=bar_color)
            self.bar.set(0)
            self.bar.pack(fill="x", padx=18, pady=(0, 16))
        else:
            ctk.CTkFrame(self, height=8, fg_color="transparent").pack()

    def set(self, value: str, sub: str = " ", frac: Optional[float] = None, color: Optional[str] = None):
        self.v.configure(text=value)
        self.s.configure(text=sub)
        if self.bar is not None and frac is not None:
            anim.smooth_bar(self.bar, frac)
            if color:
                self.bar.configure(progress_color=color)


# --------------------------------------------------------------------------- dialogi
def _center(win, parent, w: int, h: int):
    parent.update_idletasks()
    x = parent.winfo_rootx() + (parent.winfo_width() - w) // 2
    y = parent.winfo_rooty() + (parent.winfo_height() - h) // 3
    win.geometry(f"{w}x{h}+{max(0, x)}+{max(0, y)}")


def _dialog(parent, title: str, text: str, buttons: list[tuple[str, str, Any]], width: int = 460) -> Any:
    top = ctk.CTkToplevel(parent)
    top.title(title)
    top.configure(fg_color=c.bg)
    top.resizable(False, False)
    top.transient(parent.winfo_toplevel())
    result = {"v": None}

    box = card(top, fg_color=c.card)
    box.pack(fill="both", expand=True, padx=14, pady=14)
    label(box, title, "heading", c.text, "bold").pack(fill="x", padx=20, pady=(18, 6))
    msg = label(box, text, "body", c.muted, wraplength=width - 80)
    msg.pack(fill="x", padx=20, pady=(0, 16))
    row = ctk.CTkFrame(box, fg_color="transparent")
    row.pack(fill="x", padx=20, pady=(0, 18))

    def pick(v):
        result["v"] = v
        top.destroy()

    for i, (txt, style, val) in enumerate(buttons):
        b = button(row, txt, lambda v=val: pick(v), style, width=120)
        b.pack(side="right", padx=(8, 0))
    top.protocol("WM_DELETE_WINDOW", lambda: pick(None))

    top.update_idletasks()
    h = box.winfo_reqheight() + 32
    _center(top, parent.winfo_toplevel(), width, h)
    try:
        top.wait_visibility()
        top.grab_set()
    except Exception:
        pass
    top.focus_force()
    parent.wait_window(top)
    return result["v"]


def confirm(parent, title: str, text: str, ok: str = "Tak", danger: bool = False) -> bool:
    return bool(_dialog(parent, title, text, [(ok, "danger" if danger else "primary", True), ("Anuluj", "ghost", False)]))


def info(parent, title: str, text: str) -> None:
    _dialog(parent, title, text, [("OK", "primary", True)])


class Toast(ctk.CTkFrame):
    """Krótki komunikat w prawym dolnym rogu okna."""

    COLORS = {"ok": "success", "warn": "warning", "err": "danger", "info": "accent2"}

    def __init__(self, root):
        super().__init__(root, corner_radius=12, border_width=1, fg_color=c.card)
        self.lbl = label(self, "", "body", c.text, wraplength=420)
        self.lbl.pack(padx=16, pady=12)
        self._job = None
        self.root = root

    def show(self, text: str, kind: str = "ok", ms: int = 4200):
        col = getattr(c, self.COLORS.get(kind, "accent2"))
        self.configure(border_color=col)
        self.lbl.configure(text=text)
        self.place(relx=1.0, rely=1.0, x=-24 + 70, y=-24, anchor="se")
        self.lift()
        anim.tween(self, 260, lambda t: self.place_configure(x=-24 + round(70 * (1 - t))))
        if self._job:
            self.root.after_cancel(self._job)
        self._job = self.root.after(ms, self.place_forget)


# --------------------------------------------------------------------------- dodatkowe widgety
def option_menu(master, values: list[str], command: Optional[Callable] = None, width: int = 140, **kw):
    return ctk.CTkOptionMenu(master, values=values, width=width, font=font("body"), command=command,
                             fg_color=theme.blend(c.card, "#FFFFFF", 0.1), button_color=theme.blend(c.card, "#FFFFFF", 0.16),
                             button_hover_color=theme.blend(c.card, "#FFFFFF", 0.26), text_color=c.text,
                             dropdown_fg_color=c.card, dropdown_text_color=c.text, dropdown_hover_color=c.card_hover, **kw)


def setting_row(master, title: str, desc: str = "", wrap: int = 560):
    """Wiersz 'tytuł + opis' z miejscem po prawej na kontrolkę. Zwraca (ramka, prawa_strona)."""
    row = ctk.CTkFrame(master, fg_color="transparent")
    row.pack(fill="x", padx=22, pady=7)
    left = ctk.CTkFrame(row, fg_color="transparent")
    left.pack(side="left", fill="x", expand=True)
    label(left, title, "body", c.text, "bold").pack(fill="x")
    if desc:
        label(left, desc, "small", c.muted, wraplength=wrap).pack(fill="x")
    right = ctk.CTkFrame(row, fg_color="transparent")
    right.pack(side="right", padx=(12, 0))
    return row, right


def open_path(path) -> None:
    import os
    import subprocess
    try:
        if os.name == "nt":
            os.startfile(str(path))      # noqa: S606
        else:
            subprocess.Popen(["xdg-open", str(path)])
    except Exception:
        log.debug("open_path", exc_info=True)

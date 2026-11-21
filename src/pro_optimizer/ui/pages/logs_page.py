"""Osobna strona z logami aplikacji: podgląd na żywo, filtr poziomu, kopiowanie, otwieranie folderu."""
from __future__ import annotations

import customtkinter as ctk

from ... import logview, paths
from .. import theme, widgets as w
from ..app import Page
from ..theme import c


class LogsPage(Page):
    title = "Logi"
    subtitle = "Co robi aplikacja - przydatne, gdy coś nie działa. Możesz skopiować logi i wysłać je do pomocy."

    def __init__(self, master, app):
        super().__init__(master, app)
        bar = w.card(self)
        bar.pack(fill="x")
        row = ctk.CTkFrame(bar, fg_color="transparent", height=1)
        row.pack(fill="x", padx=16, pady=12)
        self.level = w.option_menu(row, list(logview.LEVELS), command=lambda v: self.refresh(), width=190)
        self.level.set("Info i wyżej")
        self.level.pack(side="left")
        w.button(row, "Odśwież", self.refresh, "ghost", height=34, width=90).pack(side="left", padx=8)
        self.live = ctk.BooleanVar(value=True)
        w.switch(row, "Na żywo", variable=self.live, width=46).pack(side="left", padx=10)
        w.button(row, "Otwórz folder", lambda: w.open_path(paths.logs_dir()), "ghost", height=34, width=120).pack(side="right")
        w.button(row, "Wyczyść", self.clear, "danger", height=34, width=90).pack(side="right", padx=8)
        w.button(row, "Kopiuj", self.copy, "ghost", height=34, width=90).pack(side="right")

        self.box = ctk.CTkTextbox(self, corner_radius=12, fg_color=theme.blend(c.card, "#000000", 0.35), text_color=c.text,
                                  font=ctk.CTkFont(family="Consolas", size=12), wrap="none", border_width=1, border_color=c.border)
        self.box.pack(fill="both", expand=True, pady=(10, 0))
        tb = self.box._textbox
        tb.tag_config("warn", foreground=c.warning)
        tb.tag_config("err", foreground=c.danger)
        tb.tag_config("dim", foreground=c.muted)
        self.count = w.label(self, "", "small", c.muted)
        self.count.pack(fill="x", pady=(6, 0))
        self._sig = None
        self.after(2000, self._tick)

    def on_show(self) -> None:
        self.refresh()

    def _tick(self) -> None:
        if self.live.get() and self.app.current_page_id() == "logs":
            self.refresh()
        self.after(2000, self._tick)

    def refresh(self) -> None:
        lv = logview.LEVELS[self.level.get()]
        lines = logview.read_tail(600, lv)
        sig = (lv, len(lines), lines[-1][0] if lines else "")
        if sig == self._sig:
            return
        self._sig = sig
        tb = self.box._textbox
        at_end = self.box.yview()[1] >= 0.98
        self.box.configure(state="normal")
        self.box.delete("1.0", "end")
        for ln, level in lines:
            tag = "err" if level >= 40 else ("warn" if level >= 30 else ("dim" if level < 20 else ""))
            tb.insert("end", ln + "\n", tag) if tag else tb.insert("end", ln + "\n")
        self.box.configure(state="disabled")
        if at_end:
            self.box.see("end")
        self.count.configure(text=f"Linii: {len(lines)}  •  {paths.logs_dir()}")

    def copy(self) -> None:
        text = "\n".join(ln for ln, _ in logview.read_tail(600, logview.LEVELS[self.level.get()]))
        self.clipboard_clear()
        self.clipboard_append(text)
        self.app.toast.show("Skopiowano logi do schowka.", "ok")

    def clear(self) -> None:
        if w.confirm(self, "Wyczyść logi", "Usunąć zawartość plików logów?", "Wyczyść", danger=True):
            logview.clear()
            self._sig = None
            self.refresh()

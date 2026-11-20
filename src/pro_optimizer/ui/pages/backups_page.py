"""Kopie zapasowe: lista, przywracanie, usuwanie."""
from __future__ import annotations

import os
import subprocess
import time
import tkinter as tk

import customtkinter as ctk

from ... import backups, paths, roblox
from ...cleaner import fmt_bytes
from .. import theme, widgets as w
from ..app import Page
from ..theme import c, font


class BackupsPage(Page):
    title = "Kopie zapasowe"
    subtitle = "Przed każdą zmianą ustawień Robloxa powstaje kopia. Tu możesz ją przywrócić."

    def __init__(self, master, app):
        super().__init__(master, app)
        self.sel = tk.StringVar(value="")
        self.items: dict[str, backups.BackupItem] = {}

        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.pack(fill="x", pady=(0, 10))
        w.button(bar, "Przywróć zaznaczoną", self.restore, "primary", width=170).pack(side="left")
        w.button(bar, "Usuń", self.delete, "danger", width=90).pack(side="left", padx=8)
        w.button(bar, "Otwórz folder", self.open_folder, "ghost", width=130).pack(side="right")
        w.button(bar, "Odśwież", self.reload, "ghost", width=100).pack(side="right", padx=8)

        self.list = w.scroll_frame(self)
        self.list.pack(fill="both", expand=True)
        self.list.grid_columnconfigure(0, weight=1)
        self.empty = w.label(self.list, "Brak kopii zapasowych. Powstaną automatycznie przy zapisie profilu Robloxa.",
                             "body", c.muted)

    def on_show(self) -> None:
        self.reload()

    def reload(self) -> None:
        for ch in self.list.winfo_children():
            if ch is not self.empty:
                ch.destroy()
        self.items = {b.name: b for b in backups.list_backups()}
        if not self.items:
            self.empty.grid(row=0, column=0, sticky="w", padx=8, pady=12)
            return
        self.empty.grid_forget()
        kinds = {"player": "Roblox Player", "studio": "Roblox Studio", "registry": "Rejestr"}
        for i, b in enumerate(self.items.values()):
            row = ctk.CTkFrame(self.list, corner_radius=12, fg_color=c.card, border_width=1, border_color=c.border)
            row.grid(row=i, column=0, sticky="ew", pady=3)
            row.grid_columnconfigure(1, weight=1)
            ctk.CTkRadioButton(row, text="", variable=self.sel, value=b.name, width=24, fg_color=c.accent,
                               hover_color=c.accent_hover, border_color=c.muted).grid(row=0, column=0, rowspan=2, padx=(14, 0), pady=12)
            w.label(row, b.name, "body", c.text, "bold").grid(row=0, column=1, sticky="w", pady=(10, 0))
            w.label(row, time.strftime("%d.%m.%Y  %H:%M:%S", time.localtime(b.mtime)) + f"  •  {fmt_bytes(b.size)}",
                    "small", c.muted).grid(row=1, column=1, sticky="w", pady=(0, 10))
            w.badge(row, kinds.get(b.kind, b.kind), c.accent2).grid(row=0, column=2, rowspan=2, padx=16)

    def _current(self):
        return self.items.get(self.sel.get())

    def restore(self) -> None:
        b = self._current()
        if not b:
            self.app.toast.show("Zaznacz kopię z listy.", "warn")
            return
        target = None
        if b.kind in ("player", "studio"):
            inst = roblox.find_installs().get(b.kind)
            target = inst.settings_path if inst else None
        if not w.confirm(self, "Przywróć kopię", f"Przywrócić „{b.name}”?\nObecne ustawienia zostaną zastąpione.", "Przywróć"):
            return
        try:
            msg = backups.restore(b, target)
            if b.kind in ("player", "studio"):   # żeby auto-przywracanie nie nadpisało właśnie przywróconej kopii
                prof = dict(self.app.settings.get("roblox_profile"))
                prof["targets"] = [t for t in prof.get("targets", []) if t != b.kind]
                self.app.settings.set("roblox_profile", prof)
            self.app.toast.show(msg, "ok", 5500)
        except Exception as e:
            self.app.toast.show(f"Nie udało się przywrócić: {e}", "err", 6500)

    def delete(self) -> None:
        b = self._current()
        if not b:
            self.app.toast.show("Zaznacz kopię z listy.", "warn")
            return
        if w.confirm(self, "Usuń kopię", f"Trwale usunąć „{b.name}”?", "Usuń", danger=True):
            backups.delete_backup(b)
            self.sel.set("")
            self.reload()

    def open_folder(self) -> None:
        d = paths.backups_dir()
        d.mkdir(parents=True, exist_ok=True)
        try:
            if os.name == "nt":
                os.startfile(str(d))      # noqa: S606
            else:
                subprocess.Popen(["xdg-open", str(d)])
        except Exception:
            self.app.toast.show(str(d), "info")

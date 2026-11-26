"""Kopie zapasowe: lista, przywracanie, usuwanie."""
from __future__ import annotations

import os
import subprocess
import time
import tkinter as tk

import customtkinter as ctk

from ... import backups, paths, roblox, snapshot
from ...cleaner import fmt_bytes
from .. import theme, widgets as w
from ..app import Page
from ..theme import c, font


class BackupsPage(Page):
    title = "Kopie zapasowe"
    subtitle = "Zabezpiecz ustawienia komputera i gier jednym kliknięciem - i cofnij je, gdy coś nie spodoba Ci się."

    def __init__(self, master, app):
        super().__init__(master, app)
        self.sel = tk.StringVar(value="")
        self.items: dict[str, backups.BackupItem] = {}
        self.part_vars = {k: tk.BooleanVar(value=True) for k in snapshot.PARTS}

        # --- tworzenie nowej kopii
        mk = w.card(self)
        mk.pack(fill="x", pady=(0, 12))
        w.label(mk, "Utwórz kopię zapasową", "heading", c.text, "bold").pack(fill="x", padx=22, pady=(18, 2))
        w.label(mk, "Zaznacz, co zabezpieczyć. „Wszystko” zapisuje wszystkie ustawienia, które program może zmienić.",
                "small", c.muted).pack(fill="x", padx=22)
        grid = ctk.CTkFrame(mk, fg_color="transparent")
        grid.pack(fill="x", padx=22, pady=(10, 4))
        grid.grid_columnconfigure((0, 1), weight=1, uniform="p")
        for i, (key, (title, desc)) in enumerate(snapshot.PARTS.items()):
            cell = ctk.CTkFrame(grid, fg_color="transparent")
            cell.grid(row=i // 2, column=i % 2, sticky="ew", pady=3, padx=(0, 12))
            w.checkbox(cell, title, self.part_vars[key]).pack(anchor="w")
            w.label(cell, desc, "small", c.muted, wraplength=330).pack(anchor="w", padx=(30, 0))
        row = ctk.CTkFrame(mk, fg_color="transparent")
        row.pack(fill="x", padx=22, pady=(8, 18))
        self.mk_btn = w.button(row, "Utwórz kopię zaznaczonych", self.create_snapshot, "primary", width=210)
        self.mk_btn.pack(side="left")
        w.button(row, "Zabezpiecz wszystko", self.create_all, "ghost", width=170).pack(side="left", padx=8)

        # --- lista kopii (zakładki)
        self.tabs = ctk.CTkSegmentedButton(self, values=["Kopie programu", "Starsze pliki Roblox"], command=self._tab,
                                           font=theme.font("body", "bold"), selected_color=c.accent,
                                           selected_hover_color=c.accent_hover, unselected_color=c.card,
                                           unselected_hover_color=c.card_hover, text_color=c.text)
        self.tabs.set("Kopie programu")
        self.tabs.pack(anchor="w", pady=(0, 8))

        self.snap_wrap = ctk.CTkFrame(self, fg_color="transparent")
        self.snap_wrap.pack(fill="both", expand=True)
        self.snap_list = w.scroll_frame(self.snap_wrap)
        self.snap_list.pack(fill="both", expand=True)
        self.snap_list.grid_columnconfigure(0, weight=1)

        self.old_wrap = ctk.CTkFrame(self, fg_color="transparent")
        bar = ctk.CTkFrame(self.old_wrap, fg_color="transparent")
        bar.pack(fill="x", pady=(0, 10))
        w.button(bar, "Przywróć zaznaczoną", self.restore, "primary", width=170).pack(side="left")
        w.button(bar, "Usuń", self.delete, "danger", width=90).pack(side="left", padx=8)
        w.button(bar, "Otwórz folder", self.open_folder, "ghost", width=130).pack(side="right")
        w.button(bar, "Odśwież", self.reload, "ghost", width=100).pack(side="right", padx=8)
        self.list = w.scroll_frame(self.old_wrap)
        self.list.pack(fill="both", expand=True)
        self.list.grid_columnconfigure(0, weight=1)
        self.empty = w.label(self.list, "Brak starszych kopii. Powstają przy zapisie profilu Robloxa.", "body", c.muted)

    def _tab(self, which: str) -> None:
        if which == "Kopie programu":
            self.old_wrap.pack_forget()
            self.snap_wrap.pack(fill="both", expand=True)
        else:
            self.snap_wrap.pack_forget()
            self.old_wrap.pack(fill="both", expand=True)
            self.reload()

    # ------------------------------------------------------------------ nowe kopie
    def _collect(self, parts: list[str], label: str):
        inst = roblox.find_installs()
        rb = {k: (v.settings_path if v else None) for k, v in inst.items()}
        return snapshot.create(parts, roblox_settings=rb, games=self.app.games, label=label)

    def create_all(self) -> None:
        for v in self.part_vars.values():
            v.set(True)
        self.create_snapshot()

    def create_snapshot(self) -> None:
        parts = [k for k, v in self.part_vars.items() if v.get()]
        if not parts:
            self.app.toast.show("Zaznacz, co zabezpieczyć.", "warn")
            return
        self.mk_btn.configure(state="disabled", text="Tworzę kopię…")

        def done(s):
            self.mk_btn.configure(state="normal", text="Utwórz kopię zaznaczonych")
            snapshot.prune(20)
            self.app.toast.show(f"Kopia gotowa ({len(s.files)} plików).", "ok")
            self.reload_snapshots()
            from ... import cloud
            self.app.cloud_sync(lambda: cloud.sync_snapshot(s), "Kopia wysłana także do chmury.")

        def fail(e):
            self.mk_btn.configure(state="normal", text="Utwórz kopię zaznaczonych")
            self.app.toast.show(f"Nie udało się utworzyć kopii: {e}", "err", 6500)

        self.app.bg.run(lambda: self._collect(parts, "Ręczna kopia"), done, fail)

    def reload_snapshots(self) -> None:
        for ch in self.snap_list.winfo_children():
            ch.destroy()
        snaps = snapshot.list_snapshots()
        if not snaps:
            w.label(self.snap_list, "Nie masz jeszcze żadnej kopii. Kliknij „Zabezpiecz wszystko”.", "body", c.muted
                    ).grid(row=0, column=0, sticky="w", padx=8, pady=12)
            return
        for i, s in enumerate(snaps):
            row = ctk.CTkFrame(self.snap_list, corner_radius=12, fg_color=c.card, border_width=1, border_color=c.border)
            row.grid(row=i, column=0, sticky="ew", pady=3)
            row.grid_columnconfigure(0, weight=1)
            when = time.strftime("%d.%m.%Y  %H:%M", time.localtime(s.created))
            w.label(row, when + (f"  •  {s.label}" if s.label else ""), "body", c.text, "bold").grid(
                row=0, column=0, sticky="w", padx=16, pady=(12, 0))
            names = ", ".join(snapshot.PARTS[p][0] for p in s.parts)
            w.label(row, f"{names}  •  {fmt_bytes(s.size)}", "small", c.muted, wraplength=520).grid(
                row=1, column=0, sticky="w", padx=16, pady=(0, 12))
            w.button(row, "Przywróć…", lambda sn=s: self.restore_snapshot(sn), "primary", height=32, width=110).grid(
                row=0, column=1, rowspan=2, padx=(8, 4))
            w.button(row, "Usuń", lambda sn=s: self.delete_snapshot(sn), "ghost", height=32, width=70).grid(
                row=0, column=2, rowspan=2, padx=(0, 14))

    def restore_snapshot(self, s) -> None:
        top = ctk.CTkToplevel(self)
        top.title("Przywróć kopię")
        top.configure(fg_color=c.bg)
        top.resizable(False, False)
        top.transient(self.winfo_toplevel())
        box = w.card(top)
        box.pack(fill="both", expand=True, padx=14, pady=14)
        w.label(box, "Co przywrócić?", "heading", c.text, "bold").pack(fill="x", padx=20, pady=(18, 4))
        w.label(box, "Obecne ustawienia z zaznaczonych części zostaną zastąpione tymi z kopii.", "small", c.muted,
                wraplength=380).pack(fill="x", padx=20, pady=(0, 8))
        vars_ = {}
        for p in s.parts:
            vars_[p] = tk.BooleanVar(value=True)
            w.checkbox(box, snapshot.PARTS[p][0], vars_[p]).pack(anchor="w", padx=22, pady=3)
        btns = ctk.CTkFrame(box, fg_color="transparent")
        btns.pack(fill="x", padx=20, pady=(14, 18))

        def go():
            chosen = [p for p, v in vars_.items() if v.get()]
            top.destroy()
            self._do_restore(s, chosen)

        w.button(btns, "Przywróć", go, "primary", width=110).pack(side="right", padx=(8, 0))
        w.button(btns, "Anuluj", top.destroy, "ghost", width=100).pack(side="right")
        top.update_idletasks()
        top.geometry(f"440x{box.winfo_reqheight() + 32}+{self.winfo_rootx() + 200}+{self.winfo_rooty() + 160}")
        try:
            top.wait_visibility()
            top.grab_set()
        except Exception:
            pass

    def _do_restore(self, s, parts) -> None:
        if not parts:
            return
        inst = roblox.find_installs()
        targets = {k: (v.settings_path if v else None) for k, v in inst.items()}

        def done(msgs):
            if "roblox" in parts:
                prof = dict(self.app.settings.get("roblox_profile"))
                prof["targets"] = []          # żeby auto-przywracanie nie nadpisało właśnie przywróconych ustawień
                self.app.settings.set("roblox_profile", prof)
            self.app.toast.show(" ".join(msgs), "ok", 7000)

        self.app.bg.run(lambda: snapshot.restore(s, parts, roblox_targets=targets), done,
                        lambda e: self.app.toast.show(str(e), "err", 8000))

    def delete_snapshot(self, s) -> None:
        if w.confirm(self, "Usuń kopię", "Trwale usunąć tę kopię zapasową?", "Usuń", danger=True):
            snapshot.delete(s)
            self.reload_snapshots()

    def on_show(self) -> None:
        self.reload_snapshots()
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

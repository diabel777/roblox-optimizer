"""Optymalizacja gier: każda gra ma własne, niezależne ustawienia (GPU, pełny ekran, priorytet, doping przy starcie)."""
from __future__ import annotations

import os
import tkinter as tk

import customtkinter as ctk

from ... import cleaner, games as gm, roblox, winsys
from .. import theme, widgets as w
from ..app import Page
from ..theme import c


class GamesPage(Page):
    title = "Gry"
    subtitle = "Każdą grę ustawiasz osobno - ustawienia jednej nie wpływają na inne."

    def __init__(self, master, app):
        super().__init__(master, app)
        self.sel: str | None = None
        self.exe_cache: dict[str, str] = {}
        self.running: set[str] = set()
        self.items: dict[str, dict] = {}

        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        left = w.card(self, width=270)
        left.grid(row=0, column=0, sticky="nsw", padx=(0, 12))
        left.grid_propagate(False)
        bar = ctk.CTkFrame(left, fg_color="transparent", height=1)
        bar.pack(fill="x", padx=12, pady=(12, 6))
        self.btn_detect = w.button(bar, "Wykryj gry", self.detect, "primary", height=34, width=110)
        self.btn_detect.pack(side="left")
        self.lst = w.scroll_frame(left)
        self.lst.pack(fill="both", expand=True, padx=4, pady=(0, 8))

        self.detail = ctk.CTkFrame(self, fg_color="transparent", height=1)
        self.detail.grid(row=0, column=1, sticky="nsew")
        self.detail.grid_columnconfigure(0, weight=1)
        self.detail.grid_rowconfigure(0, weight=1)
        self._build_list()
        self.select(self.app.games[0]["id"])
        self._first = True

    # ------------------------------------------------------------------ lista
    def _build_list(self) -> None:
        for ch in self.lst.winfo_children():
            ch.destroy()
        self.items = {}
        for g in self.app.games:
            row = ctk.CTkFrame(self.lst, corner_radius=10, fg_color="transparent", cursor="hand2")
            row.pack(fill="x", pady=2, padx=4)
            dot = ctk.CTkLabel(row, text="●", width=16, text_color=c.muted)
            dot.pack(side="left", padx=(10, 4), pady=10)
            name = w.label(row, g["name"], "body", c.text, "bold")
            name.pack(side="left", fill="x", expand=True)
            tag = w.label(row, "", "small", c.accent2, anchor="e")
            tag.pack(side="right", padx=10)
            for wd in (row, dot, name, tag):
                wd.bind("<Button-1>", lambda e, gid=g["id"]: self.select(gid))
            self.items[g["id"]] = {"row": row, "dot": dot, "tag": tag}
        self._paint_list()

    def _paint_list(self) -> None:
        saved = self.app.settings.get("games") or {}
        for gid, it in self.items.items():
            g = self._game(gid)
            ent = saved.get(gid) or {}
            n = sum(1 for v in (ent.get("opts") or {}).values() if v)
            live = any(e.lower() in self.running for e in g.get("exes", []))
            found = bool(self.exe_cache.get(gid) or ent.get("exe"))
            it["dot"].configure(text_color=c.success if live else (c.accent if found else c.muted))
            it["tag"].configure(text=f"{n} ust." if n else "")
            it["row"].configure(fg_color=theme.blend(c.card, c.accent, 0.2) if gid == self.sel else "transparent")

    def _game(self, gid: str) -> dict:
        return next(g for g in self.app.games if g["id"] == gid)

    # ------------------------------------------------------------------ wykrywanie
    def on_show(self) -> None:
        if self._first:
            self._first = False
            self.detect(silent=True)
        else:
            self._refresh_running()

    def _refresh_running(self) -> None:
        def done(r):
            self.running = r
            self._paint_list()
        self.app.bg.run(cleaner.running_processes, done)

    def exe_for(self, g: dict) -> str:
        if g.get("kind") == "roblox_player":
            i = roblox.find_installs().get("player")
            return str(i.exe) if i else ""
        if g.get("kind") == "roblox_studio":
            i = roblox.find_installs().get("studio")
            return str(i.exe) if i else ""
        ent = (self.app.settings.get("games") or {}).get(g["id"]) or {}
        if g.get("exe"):
            return g["exe"]
        return ent.get("exe", "")

    def detect(self, silent: bool = False) -> None:
        self.btn_detect.configure(state="disabled", text="Szukam…")
        catalog = list(self.app.games)

        def work():
            found = {}
            for g in catalog:
                exe = self.exe_for(g)
                if not exe and not g.get("kind", "").startswith("roblox"):
                    p = gm.find_exe(g)
                    exe = str(p) if p else ""
                if exe:
                    found[g["id"]] = exe
            return found, cleaner.running_processes()

        def done(res):
            found, running = res
            self.running = running
            saved = dict(self.app.settings.get("games") or {})
            for gid, exe in found.items():
                ent = dict(saved.get(gid) or {})
                if ent.get("exe") != exe:
                    ent["exe"] = exe
                    saved[gid] = ent
            self.app.settings.set("games", saved)
            self.exe_cache = found
            self.btn_detect.configure(state="normal", text="Wykryj gry")
            self._paint_list()
            self.select(self.sel or catalog[0]["id"])
            if not silent:
                self.app.toast.show(f"Wykryto gier: {len(found)} z {len(catalog)}.", "ok")

        def fail(e):
            self.btn_detect.configure(state="normal", text="Wykryj gry")
            self.app.toast.show(f"Błąd wykrywania: {e}", "err")

        self.app.bg.run(work, done, fail)

    # ------------------------------------------------------------------ szczegóły
    def select(self, gid: str) -> None:
        self.sel = gid
        g = self._game(gid)
        for ch in self.detail.winfo_children():
            ch.destroy()
        self._paint_list()
        is_rb = g.get("kind", "").startswith("roblox")
        body = w.scroll_frame(self.detail)
        body.pack(fill="both", expand=True)
        exe = self.exe_for(g)
        saved = (self.app.settings.get("games") or {}).get(gid) or {}

        head = w.card(body)
        head.pack(fill="x", pady=(0, 10))
        top = ctk.CTkFrame(head, fg_color="transparent", height=1)
        top.pack(fill="x", padx=20, pady=(16, 2))
        w.label(top, g["name"], "title", c.text, "bold").pack(side="left")
        if g.get("desc"):
            w.label(head, g["desc"], "small", c.muted, wraplength=520).pack(fill="x", padx=20)
        if exe:
            w.label(head, exe, "small", c.accent2, wraplength=520).pack(fill="x", padx=20, pady=(6, 0))
        else:
            w.label(head, "Nie znaleziono tej gry na tym komputerze. Kliknij „Wykryj gry”, jeśli właśnie ją zainstalowałeś.",
                    "small", c.warning, wraplength=520).pack(fill="x", padx=20, pady=(6, 0))
        ctk.CTkFrame(head, height=14, fg_color="transparent").pack()

        opts = w.card(body)
        opts.pack(fill="x", pady=(0, 10))
        w.label(opts, "Ustawienia tej gry", "heading", c.text, "bold").pack(fill="x", padx=20, pady=(16, 4))
        self.sw: dict[str, ctk.CTkSwitch] = {}
        for oid, title, desc, admin in gm.OPTIONS:
            if is_rb and oid != "prio_high":
                continue                      # ścieżka exe Robloxa zmienia się przy każdej aktualizacji - tylko opcje po nazwie
            if g.get("no_priority_ifeo") and oid == "prio_high":
                continue
            row, right = w.setting_row(opts, title, desc, 400)
            sw = w.switch(right, "", command=lambda o=oid: self._toggle(gid, o), width=46)
            sw.pack(side="right")
            if admin:
                w.badge(right, "Admin", c.warning).pack(side="right", padx=6)
            if not exe or not winsys.IS_WINDOWS:
                sw.configure(state="disabled")
            self.sw[oid] = sw
        row, right = w.setting_row(opts, "Doping po uruchomieniu gry", "Gdy gra wystartuje: podnosi jej priorytet i zwalnia pamięć RAM (potrzebna włączona automatyzacja gier).", 400)
        self.v_boost = tk.BooleanVar(value=saved.get("auto_boost", True))
        w.switch(right, "", variable=self.v_boost, command=lambda: self._set_saved(gid, "auto_boost", self.v_boost.get()), width=46).pack()
        brow = ctk.CTkFrame(opts, fg_color="transparent", height=1)
        brow.pack(fill="x", padx=20, pady=(8, 16))
        w.button(brow, "Zastosuj zalecane", lambda: self._apply_all(gid, True), "primary", height=36, width=170).pack(side="left")
        w.button(brow, "Cofnij wszystko", lambda: self._apply_all(gid, False), "ghost", height=36, width=140).pack(side="left", padx=8)
        self._load_states(gid, exe)

        if is_rb:
            from .roblox_page import RobloxPage
            wrap = w.card(body)
            wrap.pack(fill="x", pady=(0, 10))
            w.label(wrap, "Profil graficzny i limit FPS", "heading", c.text, "bold").pack(fill="x", padx=20, pady=(16, 0))
            w.label(wrap, "Dotyczy Roblox Player i Roblox Studio.", "small", c.muted).pack(fill="x", padx=20)
            rv = RobloxPage(wrap, self.app, embedded=True)
            rv.pack(fill="x", padx=8, pady=(4, 8))
            rv.on_show()

    def _set_saved(self, gid: str, key: str, val) -> None:
        saved = dict(self.app.settings.get("games") or {})
        ent = dict(saved.get(gid) or {})
        ent[key] = val
        saved[gid] = ent
        self.app.settings.set("games", saved)
        self._paint_list()

    def _load_states(self, gid: str, exe: str) -> None:
        if not exe or not winsys.IS_WINDOWS:
            return
        ids = list(self.sw)

        def done(states):
            if self.sel != gid:
                return
            for oid, st in states.items():
                sw = self.sw.get(oid)
                if sw is not None and sw.winfo_exists():
                    (sw.select if st else sw.deselect)()
            self._record_opts(gid, states)

        self.app.bg.run(lambda: {o: gm.option_state(o, exe) for o in ids}, done)

    def _record_opts(self, gid: str, states: dict) -> None:
        saved = dict(self.app.settings.get("games") or {})
        ent = dict(saved.get(gid) or {})
        ent["opts"] = {k: bool(v) for k, v in states.items()}
        saved[gid] = ent
        self.app.settings.set("games", saved)
        self._paint_list()

    def _toggle(self, gid: str, oid: str) -> None:
        exe = self.exe_for(self._game(gid))
        want = bool(self.sw[oid].get())
        sw = self.sw[oid]
        sw.configure(state="disabled")

        def done(res):
            ok, msg = res
            if sw.winfo_exists():
                sw.configure(state="normal")
                if not ok:
                    (sw.deselect if want else sw.select)()
            if ok:
                ent = (self.app.settings.get("games") or {}).get(gid) or {}
                self._record_opts(gid, {**(ent.get("opts") or {}), oid: want})
            self.app.toast.show(msg, "ok" if ok else "warn")

        self.app.bg.run(lambda: gm.set_option(oid, exe, want), done,
                        lambda e: (sw.configure(state="normal"), self.app.toast.show(f"Błąd: {e}", "err")))

    def _apply_all(self, gid: str, on: bool) -> None:
        g = self._game(gid)
        exe = self.exe_for(g)
        if not exe:
            self.app.toast.show("Najpierw wskaż plik gry.", "warn")
            return
        ids = [o for o in self.sw]
        if on and not winsys.is_admin():
            ids = [o for o, _t, _d, adm in gm.OPTIONS if o in self.sw and not adm]

        def work():
            res = {}
            for o in ids:
                ok, msg = gm.set_option(o, exe, on)
                res[o] = (ok, msg)
            return res

        def done(res):
            okc = [o for o, (ok, _m) in res.items() if ok]
            fails = [m for _o, (ok, m) in res.items() if not ok]
            self.select(gid)
            self.app.toast.show(("Zastosowano zalecane ustawienia." if on else "Cofnięto ustawienia.")
                                + (f"\nPominięto: {fails[0]}" if fails else ""), "ok" if okc else "warn", 5500)

        self.app.bg.run(work, done)

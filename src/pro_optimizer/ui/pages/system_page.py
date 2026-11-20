"""Windows i sieć: odwracalne tweaki wydajności, RAM, DNS, reset sieci."""
from __future__ import annotations

import sys
import tkinter as tk

import customtkinter as ctk

from ... import winsys
from ...cleaner import fmt_bytes
from .. import theme, widgets as w
from ..app import Page
from ..theme import c


class SystemPage(Page):
    title = "Windows i sieć"
    subtitle = "Każdą zmianę możesz cofnąć jednym przełącznikiem - oryginalne ustawienia są zapamiętywane."

    def __init__(self, master, app):
        super().__init__(master, app)
        body = w.scroll_frame(self)
        body.pack(fill="both", expand=True)
        body.grid_columnconfigure(0, weight=1)
        r = 0

        if not winsys.IS_WINDOWS:
            ban = w.card(body, border_color=c.warning)
            ban.grid(row=r, column=0, sticky="ew", pady=(0, 12))
            w.label(ban, "Te funkcje działają tylko w systemie Windows.", "body", c.warning, "bold").pack(fill="x", padx=20, pady=14)
            r += 1
        elif not winsys.is_admin():
            ban = w.card(body, border_color=theme.blend(c.card, c.warning, 0.6))
            ban.grid(row=r, column=0, sticky="ew", pady=(0, 12))
            inner = ctk.CTkFrame(ban, fg_color="transparent")
            inner.pack(fill="x", padx=20, pady=14)
            txt = ctk.CTkFrame(inner, fg_color="transparent")
            txt.pack(side="left", fill="x", expand=True)
            w.label(txt, "Część ustawień wymaga administratora", "body", c.text, "bold").pack(fill="x")
            w.label(txt, "Oznaczone plakietką „Admin”. Aplikacja działa na co dzień bez uprawnień administratora - "
                         "podniesiesz je tylko wtedy, gdy będzie to potrzebne.", "small", c.muted, wraplength=560).pack(fill="x")
            w.button(inner, "Uruchom jako administrator", self.elevate, "primary", width=210).pack(side="right")
            r += 1

        tc = w.card(body)
        tc.grid(row=r, column=0, sticky="ew")
        r += 1
        w.label(tc, "Optymalizacje wydajności", "heading", c.text, "bold").pack(fill="x", padx=22, pady=(18, 6))
        self.vars: dict[str, tk.BooleanVar] = {}
        self.switches: dict[str, ctk.CTkSwitch] = {}
        for t in winsys.TWEAKS:
            row = ctk.CTkFrame(tc, fg_color="transparent")
            row.pack(fill="x", padx=22, pady=7)
            v = tk.BooleanVar(value=False)
            sw = w.switch(row, t.name, command=lambda t=t: self.toggle(t), variable=v)
            sw.pack(side="left")
            if t.admin:
                w.badge(row, "Admin", c.warning).pack(side="left", padx=(10, 0))
            if t.reboot:
                w.badge(row, "Restart", c.accent2).pack(side="left", padx=(6, 0))
            w.label(tc, t.desc, "small", c.muted, wraplength=760).pack(fill="x", padx=70, pady=(0, 4))
            if not winsys.IS_WINDOWS:
                sw.configure(state="disabled")
            self.vars[t.id] = v
            self.switches[t.id] = sw
        ctk.CTkFrame(tc, height=10, fg_color="transparent").pack()

        ac = w.card(body)
        ac.grid(row=r, column=0, sticky="ew", pady=(14, 20))
        w.label(ac, "Pamięć i sieć", "heading", c.text, "bold").pack(fill="x", padx=22, pady=(18, 8))
        row = ctk.CTkFrame(ac, fg_color="transparent")
        row.pack(fill="x", padx=22, pady=(0, 6))
        w.button(row, "Zwolnij pamięć RAM", self.ram, "primary", width=190).pack(side="left", padx=(0, 8))
        w.button(row, "Wyczyść DNS", self.dns, "ghost", width=150).pack(side="left", padx=8)
        w.button(row, "Zresetuj sieć (Winsock + IP)", self.net, "danger", width=230).pack(side="left", padx=8)
        self.out = w.label(ac, "Zwalnianie RAM zmniejsza zestaw roboczy procesów (poza Robloxem) - efekt jest realny, "
                               "ale chwilowy, bo Windows oddaje pamięć na żądanie.", "small", c.muted, wraplength=760)
        self.out.pack(fill="x", padx=22, pady=(8, 18))

    def on_show(self) -> None:
        if not winsys.IS_WINDOWS:
            return

        def work():
            return {t.id: winsys.tweak_state(t) for t in winsys.TWEAKS}

        def done(states):
            for tid, st in states.items():
                sw = self.switches[tid]
                (sw.select if st else sw.deselect)()

        self.app.bg.run(work, done)

    # ------------------------------------------------------------------
    def elevate(self) -> None:
        if winsys.relaunch_as_admin():
            self.app.destroy()
            sys.exit(0)
        self.app.toast.show("Nie uzyskano uprawnień administratora.", "warn")

    def toggle(self, t: winsys.Tweak) -> None:
        want = self.vars[t.id].get()
        sw = self.switches[t.id]
        sw.configure(state="disabled")

        def work():
            return (winsys.apply_tweak if want else winsys.revert_tweak)(t, self.app.settings)

        def done(res):
            ok, msg = res
            sw.configure(state="normal")
            if not ok:
                (sw.deselect if want else sw.select)()     # cofnij przełącznik - zmiana się nie udała
            self.app.toast.show(f"{t.name}: {msg}", "ok" if ok else "warn", 5500)

        def fail(e):
            sw.configure(state="normal")
            (sw.deselect if want else sw.select)()
            self.app.toast.show(f"Błąd: {e}", "err")

        self.app.bg.run(work, done, fail)

    def ram(self) -> None:
        self.out.configure(text="Zwalnianie pamięci…", text_color=c.muted)

        def done(res):
            if res.get("ok"):
                self.out.configure(text=f"Gotowe: zwolniono {fmt_bytes(res.get('freed', 0))} "
                                        f"(przetworzono {res.get('processes', 0)} procesów).", text_color=c.success)
            else:
                self.out.configure(text=res.get("msg", "Nie udało się zwolnić pamięci."), text_color=c.warning)

        self.app.bg.run(winsys.trim_ram, done, lambda e: self.out.configure(text=f"Błąd: {e}", text_color=c.danger))

    def dns(self) -> None:
        def done(res):
            self.app.toast.show(res[1], "ok" if res[0] else "warn")
        self.app.bg.run(winsys.flush_dns, done)

    def net(self) -> None:
        if not w.confirm(self, "Reset sieci",
                         "Zresetuje Winsock i stos TCP/IP. Połączenie może na chwilę zniknąć, "
                         "a zmiany zadziałają dopiero po restarcie komputera. Kontynuować?", "Resetuj", danger=True):
            return
        self.app.bg.run(winsys.reset_network, lambda res: self.app.toast.show(res[1], "ok" if res[0] else "warn", 6500))

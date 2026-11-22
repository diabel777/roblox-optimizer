"""Windows i sieć: odwracalne tweaki wydajności, RAM, DNS, reset sieci."""
from __future__ import annotations

import sys
import threading
import tkinter as tk

import customtkinter as ctk

from ... import autotune, nettools, winsys
from ...cleaner import fmt_bytes
from .. import theme, widgets as w
from ..app import Page
from ..theme import c


class SystemPage(Page):
    title = "Szybszy Windows i internet"
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

        qc = w.card(body, border_color=theme.blend(c.card, c.accent, 0.5))
        qc.grid(row=r, column=0, sticky="ew", pady=(0, 14))
        r += 1
        w.label(qc, "Jeden przycisk", "heading", c.text, "bold").pack(fill="x", padx=22, pady=(18, 2))
        w.label(qc, "Aplikacja sprawdzi Twój komputer i włączy tylko to, co bezpieczne i pomaga. Wszystko możesz cofnąć.",
                "small", c.muted, wraplength=720).pack(fill="x", padx=22)
        w.button(qc, "Dopasuj do mojego komputera", self.autotune, "primary", height=44, width=300).pack(anchor="w", padx=22, pady=(10, 4))
        self.auto_out = w.label(qc, "", "small", c.muted, wraplength=720)
        self.auto_out.pack(fill="x", padx=22, pady=(0, 16))

        nc = w.card(body)
        nc.grid(row=r, column=0, sticky="ew", pady=(0, 14))
        r += 1
        w.label(nc, "Internet i ping", "heading", c.text, "bold").pack(fill="x", padx=22, pady=(18, 2))
        w.label(nc, "Zmierz opóźnienie do internetu, ustaw szybki DNS i dostrój TCP pod gry.", "small", c.muted).pack(fill="x", padx=22)
        nr = ctk.CTkFrame(nc, fg_color="transparent", height=1)
        nr.pack(fill="x", padx=22, pady=(10, 4))
        w.button(nr, "Sprawdź ping", self.ping, "primary", height=38, width=150).pack(side="left")
        self.dns_names = {v[0]: k for k, v in nettools.DNS_PROVIDERS.items()}
        self.dns_menu = w.option_menu(nr, list(self.dns_names), width=300)
        self.dns_menu.set(nettools.DNS_PROVIDERS["cloudflare"][0])
        self.dns_menu.pack(side="left", padx=10)
        w.button(nr, "Ustaw DNS", self.set_dns, "ghost", height=38, width=110).pack(side="left")
        nr2 = ctk.CTkFrame(nc, fg_color="transparent", height=1)
        nr2.pack(fill="x", padx=22, pady=(4, 4))
        w.button(nr2, "Dostrój TCP pod gry", self.tune_tcp, "ghost", height=36, width=190).pack(side="left")
        w.button(nr2, "Przywróć DNS od dostawcy", self.reset_dns, "ghost", height=36, width=220).pack(side="left", padx=8)
        self.net_out = w.label(nc, "", "body", c.text, wraplength=720)
        self.net_out.pack(fill="x", padx=22, pady=(6, 16))

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
    def autotune(self) -> None:
        if not winsys.IS_WINDOWS:
            self.app.toast.show("Dostępne tylko w Windows.", "warn")
            return
        ram = winsys.memory_status()
        p = autotune.plan((ram[0] / 2 ** 30) if ram else None, winsys.is_laptop(), winsys.is_admin())
        byid = {t.id: t for t in winsys.TWEAKS}
        names = "\n".join(f"• {byid[i].name} - {p['reasons'].get(i, '')}" for i in p["tweaks"])
        extra = ("\n\nPominięte:\n" + "\n".join("• " + x for x in p["skipped"])) if p["skipped"] else ""
        if not w.confirm(self, "Dopasuj do komputera", f"Włączę:\n{names}{extra}\n\nKażdą zmianę możesz cofnąć.", "Włącz"):
            return
        self.auto_out.configure(text="Pracuję…", text_color=c.muted)

        def work():
            done = 0
            for i in p["tweaks"]:
                ok, _ = winsys.apply_tweak(byid[i], self.app.settings)
                done += bool(ok)
            winsys.flush_dns()
            return done

        def fin(n):
            self.auto_out.configure(text=f"Gotowe: włączono {n} z {len(p['tweaks'])} optymalizacji. Czyszczenie DNS wykonane.", text_color=c.success)
            self.on_show()
        self.app.bg.run(work, fin)

    def ping(self) -> None:
        self.net_out.configure(text="Mierzę…", text_color=c.muted)

        def work():
            return nettools.ping_all()

        def fin(res):
            lines = []
            for name, ms in res.items():
                lbl, _ = nettools.verdict(ms)
                lines.append(f"{name}: {'-' if ms is None else f'{ms:.0f} ms'}  ({lbl})")
            self.net_out.configure(text="\n".join(lines) + "\n" + nettools.best_hint(res), text_color=c.text)
        self.app.bg.run(work, fin)

    def _net_result(self, fn, *a) -> None:
        self.net_out.configure(text="Pracuję…", text_color=c.muted)
        self.app.bg.run(lambda: fn(*a), lambda r: self.net_out.configure(text=r[1], text_color=c.success if r[0] else c.warning))

    def set_dns(self) -> None:
        self._net_result(nettools.set_dns, self.dns_names.get(self.dns_menu.get(), "cloudflare"))

    def reset_dns(self) -> None:
        self._net_result(nettools.reset_dns)

    def tune_tcp(self) -> None:
        self._net_result(nettools.tune_tcp)

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

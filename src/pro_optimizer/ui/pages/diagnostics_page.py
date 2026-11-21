"""Analiza i naprawa: skanuje komputer i gry, tłumaczy problemy i naprawia je jednym kliknięciem."""
from __future__ import annotations

import customtkinter as ctk

from ... import analyzer
from .. import theme, widgets as w
from ..app import Page
from ..theme import c

SEV = {"crit": ("Krytyczne", "danger"), "warn": ("Do poprawy", "warning"), "info": ("Wskazówka", "accent2"), "ok": ("OK", "success")}


class DiagnosticsPage(Page):
    title = "Analiza i naprawa"
    subtitle = "Sprawdzam komputer i gry, mówię co jest nie tak i dlaczego - i naprawiam jednym kliknięciem."

    def __init__(self, master, app):
        super().__init__(master, app)
        head = w.card(self)
        head.pack(fill="x")
        row = ctk.CTkFrame(head, fg_color="transparent", height=1)
        row.pack(fill="x", padx=22, pady=18)
        self.score = ctk.CTkLabel(row, text="—", font=ctk.CTkFont(size=44, weight="bold"), text_color=c.muted, width=100)
        self.score.pack(side="left")
        tx = ctk.CTkFrame(row, fg_color="transparent", height=1)
        tx.pack(side="left", padx=10, fill="x", expand=True)
        self.verdict = w.label(tx, "Kondycja komputera", "heading", c.text, "bold")
        self.verdict.pack(fill="x")
        self.sub = w.label(tx, "Kliknij „Analizuj”, aby sprawdzić komputer.", "small", c.muted, wraplength=360)
        self.sub.pack(fill="x")
        self.btn = w.button(row, "Analizuj", self.run, "primary", height=40, width=130)
        self.btn.pack(side="right")
        self.btn_all = w.button(row, "Napraw wszystko", self.fix_all, "success", height=40, width=150)
        self.bar = w.progress(head)
        self.bar.configure(mode="indeterminate")
        self.list = w.scroll_frame(self)
        self.list.pack(fill="both", expand=True, pady=(12, 0))
        self.list.grid_columnconfigure(0, weight=1)
        self.findings: list[analyzer.Finding] = []
        self._ran = False

    def on_show(self) -> None:
        if not self._ran:
            self.run()

    def run(self) -> None:
        self._ran = True
        self.btn.configure(state="disabled", text="Analizuję…")
        self.bar.pack(fill="x", padx=22, pady=(0, 12))
        self.bar.start()

        def work():
            return analyzer.collect_facts(self.app)

        def done(facts):
            self.bar.stop()
            self.bar.pack_forget()
            self.btn.configure(state="normal", text="Analizuj ponownie")
            self.findings = analyzer.analyze(facts)
            self._render()

        def fail(e):
            self.bar.stop()
            self.bar.pack_forget()
            self.btn.configure(state="normal", text="Analizuj")
            self.app.toast.show(f"Analiza nie powiodła się: {e}", "err")

        self.app.bg.run(work, done, fail)

    def _render(self) -> None:
        for ch in self.list.winfo_children():
            ch.destroy()
        sc = analyzer.score(self.findings)
        col = c.success if sc >= 85 else (c.warning if sc >= 60 else c.danger)
        self.score.configure(text=str(sc), text_color=col)
        bad = [f for f in self.findings if f.severity in ("crit", "warn")]
        self.verdict.configure(text="Wszystko wygląda dobrze" if not bad else f"Do poprawy: {len(bad)}")
        self.sub.configure(text="Ocena to heurystyka - punkty odejmują problemy wg wagi. Każda pozycja poniżej ma wyjaśnienie.")
        fixable = [f for f in self.findings if f.fix and f.fix["type"] in ("tweak", "ram", "refresh", "defender_update")]
        if fixable:
            self.btn_all.pack(side="right", padx=(0, 8))
        else:
            self.btn_all.pack_forget()
        if not self.findings:
            w.label(self.list, "Nie znaleziono żadnych problemów.", "body", c.success).grid(row=0, column=0, sticky="w", padx=8, pady=16)
        for i, f in enumerate(self.findings):
            name, key = SEV[f.severity]
            colr = getattr(c, key)
            cd = w.card(self.list)
            cd.grid(row=i, column=0, sticky="ew", pady=4)
            cd.grid_columnconfigure(0, weight=1)
            tx = ctk.CTkFrame(cd, fg_color="transparent", height=1)
            tx.grid(row=0, column=0, sticky="ew", padx=18, pady=12)
            t = ctk.CTkFrame(tx, fg_color="transparent", height=1)
            t.pack(fill="x")
            w.badge(t, name, colr).pack(side="left")
            w.label(t, f.title, "body", c.text, "bold").pack(side="left", padx=10)
            w.label(tx, f.detail, "small", c.muted, wraplength=640).pack(fill="x", pady=(4, 0))
            if f.fix:
                w.button(cd, f.fix_label or "Napraw", lambda fx=f: self.fix(fx), "primary" if f.severity in ("crit", "warn") else "ghost",
                         height=34, width=150).grid(row=0, column=1, padx=16)

    def fix(self, f: analyzer.Finding, reanalyze: bool = True) -> None:
        self.app.run_fix(f.fix, (lambda: self.run()) if (reanalyze and f.fix["type"] not in ("page", "game")) else None)

    def fix_all(self) -> None:
        todo = [f for f in self.findings if f.fix and f.fix["type"] in ("tweak", "ram", "refresh", "defender_update")]
        if not w.confirm(self, "Napraw wszystko", "Zastosuję automatyczne poprawki (" + str(len(todo)) + "): "
                         + "; ".join(f.title for f in todo[:5]) + ("…" if len(todo) > 5 else "") + "\nKażdą da się cofnąć. Kontynuować?", "Napraw"):
            return
        for f in todo:
            self.app.run_fix(f.fix, None)
        self.after(2500, self.run)

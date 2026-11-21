"""Antywirus: obsługa Microsoft Defendera (wbudowany w Windows) + audyt autostartu."""
from __future__ import annotations

from tkinter import filedialog

import customtkinter as ctk

from ... import defender, winsys
from .. import theme, widgets as w
from ..app import Page
from ..theme import c


def _ago(dt) -> str:
    if not dt:
        return "nigdy"
    from datetime import datetime, timezone
    d = (datetime.now(timezone.utc) - dt).total_seconds()
    if d < 3600:
        return f"{int(d // 60)} min temu"
    if d < 86400:
        return f"{int(d // 3600)} godz. temu"
    return f"{int(d // 86400)} dni temu"


class AntivirusPage(Page):
    title = "Antywirus"
    subtitle = "Ochrona przed wirusami oparta o Microsoft Defender - wygodny panel zamiast ukrytych okien Windows."

    def __init__(self, master, app):
        super().__init__(master, app)
        body = w.scroll_frame(self)
        body.pack(fill="both", expand=True)
        body.grid_columnconfigure(0, weight=1)
        self.busy = False

        sc = w.card(body)
        sc.grid(row=0, column=0, sticky="ew")
        top = ctk.CTkFrame(sc, fg_color="transparent", height=1)
        top.pack(fill="x", padx=22, pady=(18, 4))
        self.shield = ctk.CTkLabel(top, text="🛡", font=ctk.CTkFont(size=34), width=56)
        self.shield.pack(side="left")
        tx = ctk.CTkFrame(top, fg_color="transparent", height=1)
        tx.pack(side="left", padx=10)
        self.state = w.label(tx, "Sprawdzam…", "heading", c.text, "bold")
        self.state.pack(fill="x")
        self.state_sub = w.label(tx, "", "small", c.muted, wraplength=560)
        self.state_sub.pack(fill="x")
        w.button(top, "Odśwież", self.refresh, "ghost", height=32, width=90).pack(side="right")
        self.facts = ctk.CTkFrame(sc, fg_color="transparent", height=1)
        self.facts.pack(fill="x", padx=22, pady=(8, 6))
        self.bar = w.progress(sc)
        self.bar.configure(mode="indeterminate")
        self.msg = w.label(sc, "", "small", c.muted, wraplength=720)
        self.msg.pack(fill="x", padx=22, pady=(4, 6))
        br = ctk.CTkFrame(sc, fg_color="transparent", height=1)
        br.pack(fill="x", padx=22, pady=(4, 18))
        self.btns = [
            w.button(br, "Szybkie skanowanie", lambda: self.scan("quick"), "primary", height=38, width=170),
            w.button(br, "Pełne skanowanie", lambda: self.scan("full"), "ghost", height=38, width=160),
            w.button(br, "Skanuj folder…", self.scan_folder, "ghost", height=38, width=140),
            w.button(br, "Aktualizuj definicje", self.update_sigs, "ghost", height=38, width=170),
        ]
        for b in self.btns:
            b.pack(side="left", padx=(0, 8))

        tc = w.card(body)
        tc.grid(row=1, column=0, sticky="ew", pady=(14, 0))
        top2 = ctk.CTkFrame(tc, fg_color="transparent", height=1)
        top2.pack(fill="x", padx=22, pady=(18, 4))
        w.label(top2, "Wykryte zagrożenia", "heading", c.text, "bold").pack(side="left")
        self.btn_rm = w.button(top2, "Usuń zagrożenia", self.remove, "danger", height=30, width=150)
        self.threat_box = ctk.CTkFrame(tc, fg_color="transparent", height=1)
        self.threat_box.pack(fill="x", padx=22, pady=(0, 16))

        ac = w.card(body)
        ac.grid(row=2, column=0, sticky="ew", pady=(14, 20))
        top3 = ctk.CTkFrame(ac, fg_color="transparent", height=1)
        top3.pack(fill="x", padx=22, pady=(18, 2))
        w.label(top3, "Programy w autostarcie", "heading", c.text, "bold").pack(side="left")
        w.button(top3, "Sprawdź", self.audit, "ghost", height=30, width=90).pack(side="right")
        w.label(ac, "Pokazuje programy uruchamiane z Windowsem i status ich podpisu cyfrowego. „Niepodpisany” nie znaczy „wirus” - "
                    "to sygnał, że warto sprawdzić, skąd pochodzi program.", "small", c.muted, wraplength=720).pack(fill="x", padx=22)
        self.audit_box = ctk.CTkFrame(ac, fg_color="transparent", height=1)
        self.audit_box.pack(fill="x", padx=22, pady=(8, 16))
        self._loaded = False

    def on_show(self) -> None:
        if not self._loaded:
            self._loaded = True
            self.refresh()

    def _busy(self, on: bool, text: str = "") -> None:
        self.busy = on
        for b in self.btns:
            b.configure(state="disabled" if on else "normal")
        if on:
            self.bar.pack(fill="x", padx=22, pady=(4, 0), before=self.msg)
            self.bar.start()
        else:
            self.bar.stop()
            self.bar.pack_forget()
        self.msg.configure(text=text, text_color=c.muted)

    def refresh(self) -> None:
        def done(s):
            for ch in self.facts.winfo_children():
                ch.destroy()
            if not s.available:
                self.state.configure(text="Nie można odczytać stanu antywirusa", text_color=c.warning)
                self.state_sub.configure(text=s.message)
                return
            ok = s.antivirus and s.realtime
            self.state.configure(text="Komputer jest chroniony" if ok else "Ochrona wymaga uwagi", text_color=c.success if ok else c.danger)
            self.state_sub.configure(text="Ochrona w czasie rzeczywistym działa." if s.realtime else "Ochrona w czasie rzeczywistym jest WYŁĄCZONA - włącz ją w Zabezpieczeniach Windows.")
            age = s.sig_age_days
            for name, val, good in (
                ("Ochrona w czasie rzeczywistym", "włączona" if s.realtime else "wyłączona", s.realtime),
                ("Definicje wirusów", f"{s.sig_version}  •  {_ago(s.sig_updated)}", age is not None and age <= 3),
                ("Ostatnie szybkie skanowanie", _ago(s.quick_scan), s.quick_scan is not None),
                ("Ostatnie pełne skanowanie", _ago(s.full_scan), s.full_scan is not None),
                ("Ochrona przed manipulacją", "włączona" if s.tamper else "wyłączona", s.tamper),
            ):
                line = ctk.CTkFrame(self.facts, fg_color="transparent", height=1)
                line.pack(fill="x", pady=1)
                ctk.CTkLabel(line, text="●", width=14, text_color=c.success if good else c.warning).pack(side="left")
                w.label(line, name, "small", c.muted, width=230).pack(side="left", padx=4)
                w.label(line, val, "small", c.text).pack(side="left")
        self.app.bg.run(defender.status, done)
        self.load_threats()

    def load_threats(self) -> None:
        def done(res):
            ok, items = res
            for ch in self.threat_box.winfo_children():
                ch.destroy()
            if not ok:
                w.label(self.threat_box, "Nie udało się odczytać listy zagrożeń.", "small", c.muted).pack(fill="x")
                self.btn_rm.pack_forget()
            elif not items:
                w.label(self.threat_box, "Brak wykrytych zagrożeń.", "body", c.success).pack(fill="x")
                self.btn_rm.pack_forget()
            else:
                self.btn_rm.pack(side="right")
                for t in items:
                    w.label(self.threat_box, f"•  {t.get('name', '?')}  ({'aktywne' if t.get('active') else 'nieaktywne'})", "body", c.danger).pack(fill="x", pady=2)
        self.app.bg.run(defender.threats, done)

    def _run(self, fn, start_msg: str, after=None) -> None:
        if self.busy:
            return
        self._busy(True, start_msg)

        def done(res):
            ok, msg = res
            self._busy(False)
            self.msg.configure(text=msg, text_color=c.success if ok else c.danger)
            self.app.toast.show(msg, "ok" if ok else "warn", 5000)
            self.refresh()

        self.app.bg.run(fn, done, lambda e: (self._busy(False), self.msg.configure(text=f"Błąd: {e}", text_color=c.danger)))

    def scan(self, kind: str) -> None:
        if kind == "full" and not w.confirm(self, "Pełne skanowanie", "Pełne skanowanie może trwać od kilkudziesięciu minut do kilku godzin. "
                                            "Możesz w tym czasie korzystać z komputera. Rozpocząć?", "Skanuj"):
            return
        self._run(lambda: defender.scan(kind), "Skanowanie w toku… to może chwilę potrwać.")

    def scan_folder(self) -> None:
        d = filedialog.askdirectory(title="Wybierz folder do przeskanowania")
        if d:
            self._run(lambda: defender.scan("custom", d), f"Skanuję: {d}")

    def update_sigs(self) -> None:
        self._run(defender.update_signatures, "Aktualizuję definicje wirusów…")

    def remove(self) -> None:
        if w.confirm(self, "Usuń zagrożenia", "Defender usunie lub zablokuje wykryte zagrożenia. Kontynuować?", "Usuń", danger=True):
            self._run(defender.remove_threats, "Usuwam zagrożenia…")

    def audit(self) -> None:
        for ch in self.audit_box.winfo_children():
            ch.destroy()
        w.label(self.audit_box, "Sprawdzam…", "small", c.muted).pack(fill="x")

        def done(res):
            ok, items = res
            for ch in self.audit_box.winfo_children():
                ch.destroy()
            if not ok:
                w.label(self.audit_box, "Nie udało się odczytać autostartu.", "small", c.warning).pack(fill="x")
                return
            if not items:
                w.label(self.audit_box, "Brak programów w autostarcie.", "small", c.muted).pack(fill="x")
            for it in items:
                sig = it.get("sig")
                col = c.success if sig == "Valid" else (c.muted if sig == "nieznany" else c.warning)
                line = ctk.CTkFrame(self.audit_box, fg_color="transparent", height=1)
                line.pack(fill="x", pady=2)
                ctk.CTkLabel(line, text="●", width=14, text_color=col).pack(side="left")
                w.label(line, it.get("name", "?"), "body", c.text, "bold", width=190).pack(side="left", padx=4)
                w.label(line, {"Valid": "podpisany", "nieznany": "nie sprawdzono"}.get(sig, f"niepodpisany ({sig})"), "small", col, width=170).pack(side="left")
                w.label(line, it.get("cmd", ""), "small", c.muted, wraplength=360).pack(side="left", fill="x", expand=True)

        self.app.bg.run(defender.startup_audit, done)

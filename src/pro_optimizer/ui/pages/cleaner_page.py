"""Czyszczenie aplikacji: skan rozmiarów, wybór pozycji, czyszczenie z podsumowaniem."""
from __future__ import annotations

import tkinter as tk

import customtkinter as ctk

from ... import cleaner
from ...cleaner import fmt_bytes
from .. import theme, widgets as w
from ..app import Page
from ..theme import c


class CleanerPage(Page):
    title = "Czyszczenie"
    subtitle = "Zobacz, ile miejsca zajmuje cache każdej aplikacji i wyczyść tylko to, co chcesz."

    def __init__(self, master, app):
        super().__init__(master, app)
        self.rows: dict[str, dict] = {}
        self.results: dict[str, cleaner.EntryResult] = {}
        self.busy = False

        bar = w.card(self)
        bar.pack(fill="x")
        inner = ctk.CTkFrame(bar, fg_color="transparent")
        inner.pack(fill="x", padx=18, pady=14)
        self.btn_scan = w.button(inner, "Skanuj", self.scan, "ghost", width=110)
        self.btn_scan.pack(side="left")
        w.button(inner, "Zaznacz wszystko", lambda: self._set_all(True), "ghost", width=140).pack(side="left", padx=8)
        w.button(inner, "Odznacz", lambda: self._set_all(False), "ghost", width=100).pack(side="left")
        self.btn_clean = w.button(inner, "Wyczyść zaznaczone", self.clean, "primary", width=180)
        self.btn_clean.pack(side="right")
        self.total = w.label(inner, "Do odzyskania: —", "body", c.text, "bold", anchor="e")
        self.total.pack(side="right", padx=18)
        self.bar = w.progress(self)
        self.bar.set(0)
        self.bar.pack(fill="x", pady=(10, 6))

        self.list = w.scroll_frame(self)
        self.list.pack(fill="both", expand=True)
        self.list.grid_columnconfigure(0, weight=1)
        self._build_rows()
        self._scanned = False

    def _build_rows(self) -> None:
        groups: dict[str, list] = {}
        for e in self.app.catalog:
            groups.setdefault(e.get("group", "Inne"), []).append(e)
        r = 0
        for g, entries in groups.items():
            w.label(self.list, g.upper(), "small", c.accent2, "bold").grid(row=r, column=0, sticky="w", padx=6, pady=(14, 4))
            r += 1
            for e in entries:
                row = ctk.CTkFrame(self.list, corner_radius=12, fg_color=c.card, border_width=1, border_color=c.border)
                row.grid(row=r, column=0, sticky="ew", pady=3)
                row.grid_columnconfigure(1, weight=1)
                var = tk.BooleanVar(value=bool(e.get("default")))
                cb = w.checkbox(row, "", var, self._update_total, width=26)
                cb.grid(row=0, column=0, rowspan=2, padx=(14, 4), pady=12)
                w.label(row, e["name"], "body", c.text, "bold").grid(row=0, column=1, sticky="w", pady=(10, 0))
                note = w.label(row, e.get("note", "") or " ", "small", c.muted, wraplength=430)
                note.grid(row=1, column=1, sticky="w", pady=(0, 10))
                size = w.label(row, "—", "body", c.text, "bold", anchor="e")
                size.grid(row=0, column=2, rowspan=2, padx=(8, 8), sticky="e")
                status = w.label(row, "", "small", c.muted, anchor="e", width=150)
                status.grid(row=0, column=3, rowspan=2, padx=(0, 16), sticky="e")
                self.rows[e["id"]] = {"entry": e, "var": var, "cb": cb, "size": size, "status": status}
                r += 1

    def on_show(self) -> None:
        if not self._scanned:
            self.scan()

    # ------------------------------------------------------------------
    def _selected(self) -> list[dict]:
        return [r["entry"] for r in self.rows.values() if r["var"].get()]

    def _set_all(self, v: bool) -> None:
        for r in self.rows.values():
            if r["cb"].cget("state") != "disabled":
                r["var"].set(v)
        self._update_total()

    def _update_total(self) -> None:
        total = sum(self.results[i].size for i, r in self.rows.items()
                    if r["var"].get() and i in self.results and not self.results[i].blocked_by)
        self.total.configure(text=f"Do odzyskania: {fmt_bytes(total)}" if self.results else "Do odzyskania: —")

    def _lock(self, busy: bool) -> None:
        self.busy = busy
        for b in (self.btn_scan, self.btn_clean):
            b.configure(state="disabled" if busy else "normal")

    def _show(self, res: list[cleaner.EntryResult]) -> None:
        self.results = {r.id: r for r in res}
        for r in res:
            row = self.rows.get(r.id)
            if not row:
                continue
            if r.found == 0:
                row["size"].configure(text="—", text_color=c.muted)
                row["status"].configure(text="nie znaleziono", text_color=c.muted)
                row["var"].set(False)
                row["cb"].configure(state="disabled")
            else:
                row["cb"].configure(state="normal")
                row["size"].configure(text=fmt_bytes(r.size), text_color=c.text if r.size else c.muted)
                if r.blocked_by:
                    row["status"].configure(text="uruchomiona - pominę", text_color=c.warning)
                else:
                    row["status"].configure(text="gotowe do czyszczenia" if r.size else "czysto", text_color=c.success if r.size else c.muted)
        self._update_total()

    def scan(self) -> None:
        if self.busy:
            return
        self._lock(True)
        self.bar.set(0)
        self.total.configure(text="Skanowanie…")

        def work():
            return cleaner.scan(self.app.catalog, progress=lambda i, n, r: self.app.bg.call(self.bar.set, i / n))

        def done(res):
            self._scanned = True
            self.bar.set(1)
            self._show(res)
            self._lock(False)

        def fail(e):
            self._lock(False)
            self.app.toast.show(f"Błąd skanowania: {e}", "err")

        self.app.bg.run(work, done, fail)

    def clean(self) -> None:
        if self.busy:
            return
        sel = self._selected()
        if not sel:
            self.app.toast.show("Zaznacz co najmniej jedną pozycję.", "warn")
            return
        est = sum(self.results[e["id"]].size for e in sel if e["id"] in self.results and not self.results[e["id"]].blocked_by)
        if not w.confirm(self, "Wyczyść zaznaczone",
                         f"Wyczyścić cache {len(sel)} pozycji (ok. {fmt_bytes(est)})?\n"
                         "Hasła, historia i zalogowane sesje nie są usuwane. Uruchomione aplikacje zostaną pominięte.",
                         "Wyczyść"):
            return
        self._lock(True)
        self.bar.set(0)

        def work():
            res = cleaner.clean(sel, progress=lambda i, n, r: self.app.bg.call(self.bar.set, i / n))
            return res

        def done(res):
            freed = sum(r.size for r in res)
            skipped = sum(r.skipped for r in res)
            blocked = [r.name.split(" – ")[0] for r in res if r.error]
            msg = f"Zwolniono {fmt_bytes(freed)}."
            if blocked:
                msg += f"\nPominięto uruchomione: {', '.join(dict.fromkeys(blocked))}."
            if skipped:
                msg += f"\n{skipped} plików było w użyciu i zostało pominiętych."
            self.app.toast.show(msg, "ok", 6500)
            self._lock(False)
            self._scanned = False
            self.scan()

        def fail(e):
            self._lock(False)
            self.app.toast.show(f"Błąd czyszczenia: {e}", "err")

        self.app.bg.run(work, done, fail)

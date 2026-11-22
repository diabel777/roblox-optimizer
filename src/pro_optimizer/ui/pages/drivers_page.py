"""Sterowniki, programy i BIOS: wyszukiwanie i instalacja sterowników przez Windows Update, linki producentów, winget, informacje o BIOS."""
from __future__ import annotations

import sys
import tkinter as tk
from datetime import datetime

import customtkinter as ctk

from ... import drivers as dv, hw, winsys
from ...cleaner import fmt_bytes
from .. import theme, widgets as w
from ..app import Page
from ..theme import c

BIOS_CHECKLIST = (
    "1. Aktualizuj BIOS tylko, gdy rozwiązuje Twój problem lub dodaje obsługę sprzętu - „działa” to dobry powód, żeby nie ruszać.\n"
    "2. Pobieraj wyłącznie ze strony producenta płyty i sprawdź, że to dokładnie Twój model i rewizja.\n"
    "3. Podłącz komputer do zasilacza (laptop: do prądu), nie wyłączaj go w trakcie. Najlepiej UPS.\n"
    "4. Wgrywaj z poziomu BIOS-u (Q-Flash / EZ Flash / M-Flash) z pendrive FAT32 - to najbezpieczniejsza metoda.\n"
    "5. Zapisz obecne ustawienia (XMP/EXPO, wentylatory) - po aktualizacji BIOS wraca do domyślnych."
)


class DriversPage(Page):
    title = "Sterowniki"
    subtitle = "Aktualizacje sterowników z Windows Update, sterowniki karty graficznej, programy i informacje o BIOS."

    def __init__(self, master, app):
        super().__init__(master, app)
        body = w.scroll_frame(self)
        body.pack(fill="both", expand=True)
        body.grid_columnconfigure(0, weight=1)
        self.busy = False
        self.checks: dict[str, tk.BooleanVar] = {}

        # --- Windows Update
        uc = w.card(body)
        uc.grid(row=0, column=0, sticky="ew")
        w.label(uc, "Sterowniki z Windows Update", "heading", c.text, "bold").pack(fill="x", padx=22, pady=(18, 2))
        w.label(uc, "Instalacja tylko przez oficjalny Windows Update (podpisane sterowniki). Wyszukiwanie może potrwać kilka minut.",
                "small", c.muted, wraplength=720).pack(fill="x", padx=22)
        r = ctk.CTkFrame(uc, fg_color="transparent", height=1)
        r.pack(fill="x", padx=22, pady=(10, 4))
        self.btn_search = w.button(r, "Szukaj sterowników", self.search, "primary", height=38, width=170)
        self.btn_search.pack(side="left")
        self.btn_install = w.button(r, "Zainstaluj zaznaczone", self.install, "success", height=38, width=180)
        w.button(r, "Windows Update", lambda: self._open_uri("ms-settings:windowsupdate"), "ghost", height=38, width=140).pack(side="right")
        self.bar = w.progress(uc)
        self.bar.configure(mode="indeterminate")
        self.msg = w.label(uc, "", "small", c.muted, wraplength=720)
        self.msg.pack(fill="x", padx=22, pady=(4, 0))
        self.found = ctk.CTkFrame(uc, fg_color="transparent", height=1)
        self.found.pack(fill="x", padx=22, pady=(4, 16))
        self.admin_note = w.label(uc, "", "small", c.warning, wraplength=720)
        if winsys.IS_WINDOWS and not winsys.is_admin():
            self.admin_note.configure(text="Instalacja sterowników wymaga uruchomienia aplikacji jako administrator.")
            self.admin_note.pack(fill="x", padx=22, pady=(0, 6))
            w.button(uc, "Uruchom jako administrator", self.elevate, "ghost", height=32, width=210).pack(anchor="w", padx=22, pady=(0, 14))

        # --- problemy
        pc = w.card(body)
        pc.grid(row=1, column=0, sticky="ew", pady=(14, 0))
        top = ctk.CTkFrame(pc, fg_color="transparent", height=1)
        top.pack(fill="x", padx=22, pady=(18, 4))
        w.label(top, "Urządzenia z problemem i wiek sterowników", "heading", c.text, "bold").pack(side="left")
        w.button(top, "Sprawdź", self.scan_installed, "ghost", height=30, width=90).pack(side="right")
        self.installed = ctk.CTkFrame(pc, fg_color="transparent", height=1)
        self.installed.pack(fill="x", padx=22, pady=(0, 16))

        # --- GPU
        gc = w.card(body)
        gc.grid(row=2, column=0, sticky="ew", pady=(14, 0))
        w.label(gc, "Sterownik karty graficznej", "heading", c.text, "bold").pack(fill="x", padx=22, pady=(18, 2))
        w.label(gc, "Najnowsze sterowniki do gier najlepiej pobierać od producenta karty. Otworzę oficjalną stronę.",
                "small", c.muted, wraplength=720).pack(fill="x", padx=22)
        gr = ctk.CTkFrame(gc, fg_color="transparent", height=1)
        gr.pack(fill="x", padx=22, pady=(10, 16))
        for key, (name, url) in dv.GPU_PAGES.items():
            w.button(gr, f"{name}", lambda u=url: dv.open_url(u), "ghost", height=36, width=110).pack(side="left", padx=(0, 8))
        self.gpu_names = w.label(gr, "", "small", c.muted)
        self.gpu_names.pack(side="left", padx=10)

        # --- programy
        ac = w.card(body)
        ac.grid(row=3, column=0, sticky="ew", pady=(14, 0))
        w.label(ac, "Aktualizacja programów", "heading", c.text, "bold").pack(fill="x", padx=22, pady=(18, 2))
        w.label(ac, "Aktualizuje zainstalowane programy przez winget (Instalator aplikacji Windows) - cicho, w tle.", "small", c.muted,
                wraplength=720).pack(fill="x", padx=22)
        self.btn_winget = w.button(ac, "Zaktualizuj wszystkie programy", self.winget, "primary", height=38, width=250)
        self.btn_winget.pack(anchor="w", padx=22, pady=(10, 4))
        self.winget_msg = w.label(ac, "", "small", c.muted, wraplength=720)
        self.winget_msg.pack(fill="x", padx=22, pady=(0, 16))

        # --- BIOS
        bc = w.card(body)
        bc.grid(row=4, column=0, sticky="ew", pady=(14, 20))
        top = ctk.CTkFrame(bc, fg_color="transparent", height=1)
        top.pack(fill="x", padx=22, pady=(18, 4))
        w.label(top, "BIOS i płyta główna", "heading", c.text, "bold").pack(side="left")
        w.button(top, "Odczytaj", self.load_board, "ghost", height=30, width=90).pack(side="right")
        self.board = ctk.CTkFrame(bc, fg_color="transparent", height=1)
        self.board.pack(fill="x", padx=22)
        self.board_btns = ctk.CTkFrame(bc, fg_color="transparent", height=1)
        self.board_btns.pack(fill="x", padx=22, pady=(8, 4))
        w.label(bc, "Dlaczego nie aktualizuję BIOS-u za Ciebie?", "body", c.text, "bold").pack(fill="x", padx=22, pady=(12, 2))
        w.label(bc, "Nieudana aktualizacja BIOS-u (zanik prądu, zły plik) może unieruchomić płytę. Dlatego aplikacja pokazuje wersję, "
                    "otwiera stronę producenta i prowadzi przez bezpieczną procedurę - samo wgranie robisz z poziomu BIOS-u.\n\n" + BIOS_CHECKLIST,
                "small", c.muted, wraplength=720).pack(fill="x", padx=22, pady=(0, 18))
        self._loaded = False

    def on_show(self) -> None:
        if not self._loaded:
            self._loaded = True
            self.load_board()
            self.app.bg.run(hw.gpu_names_wmi, lambda n: self.gpu_names.configure(text="Wykryto: " + ", ".join(n) if n else ""))

    @staticmethod
    def _open_uri(uri: str) -> None:
        import os
        try:
            if os.name == "nt":
                os.startfile(uri)       # noqa: S606
        except Exception:
            pass

    def elevate(self) -> None:
        if winsys.relaunch_as_admin():
            self.app.destroy()
            sys.exit(0)

    def _busy(self, on: bool, text: str = "") -> None:
        self.busy = on
        for b in (self.btn_search, self.btn_install, self.btn_winget):
            b.configure(state="disabled" if on else "normal")
        if on:
            self.bar.pack(fill="x", padx=22, pady=(4, 0), before=self.msg)
            self.bar.start()
        else:
            self.bar.stop()
            self.bar.pack_forget()
        self.msg.configure(text=text, text_color=c.muted)

    # ------------------------------------------------------------------ Windows Update
    def search(self) -> None:
        if self.busy:
            return
        self._busy(True, "Szukam sterowników w Windows Update… (może potrwać kilka minut)")

        def done(res):
            ok, items = res
            self._busy(False)
            for ch in self.found.winfo_children():
                ch.destroy()
            self.checks.clear()
            if not ok:
                self.msg.configure(text="Nie udało się przeszukać Windows Update: " + str(items)[:200], text_color=c.danger)
                self.btn_install.pack_forget()
                return
            if not items:
                self.msg.configure(text="Brak nowych sterowników - wszystko jest aktualne ✓", text_color=c.success)
                self.btn_install.pack_forget()
                return
            self.msg.configure(text=f"Znaleziono sterowników: {len(items)}", text_color=c.text)
            for it in items:
                v = tk.BooleanVar(value=True)
                self.checks[it["id"]] = v
                w.checkbox(self.found, f"{it['title']}  ({fmt_bytes(it.get('size', 0))})", v).pack(anchor="w", pady=3)
            self.btn_install.pack(side="left", padx=8)

        self.app.bg.run(dv.search_driver_updates, done, lambda e: (self._busy(False), self.msg.configure(text=f"Błąd: {e}", text_color=c.danger)))

    def install(self) -> None:
        ids = [i for i, v in self.checks.items() if v.get()]
        if not ids:
            return
        if not w.confirm(self, "Instalacja sterowników", f"Zainstalować {len(ids)} sterowników z Windows Update?\n"
                         "Ekran może na chwilę zgasnąć. Zalecamy utworzyć punkt przywracania systemu.", "Instaluj"):
            return
        self._busy(True, "Pobieram i instaluję sterowniki…")

        def done(res):
            ok, msg = res
            self._busy(False)
            self.msg.configure(text=msg, text_color=c.success if ok else c.danger)
            self.app.toast.show(msg, "ok" if ok else "warn", 6000)

        self.app.bg.run(lambda: dv.install_driver_updates(ids), done, lambda e: (self._busy(False), self.msg.configure(text=f"Błąd: {e}", text_color=c.danger)))

    # ------------------------------------------------------------------ zainstalowane
    def scan_installed(self) -> None:
        for ch in self.installed.winfo_children():
            ch.destroy()
        w.label(self.installed, "Sprawdzam…", "small", c.muted).pack(fill="x")

        def work():
            return dv.problem_devices(), dv.list_drivers()

        def done(res):
            (pok, probs), (dok, drv) = res
            for ch in self.installed.winfo_children():
                ch.destroy()
            if not pok and not dok:
                w.label(self.installed, "Nie udało się odczytać sterowników (funkcja działa w Windows).", "small", c.warning).pack(fill="x")
                return
            if probs:
                w.label(self.installed, f"Urządzenia z problemem: {len(probs)}", "body", c.warning, "bold").pack(fill="x", pady=(2, 2))
                for p in probs[:8]:
                    w.label(self.installed, f"•  {p.get('name') or p.get('id')}  (kod błędu {p.get('code')})", "small", c.warning).pack(fill="x")
            else:
                w.label(self.installed, "Brak urządzeń zgłaszających błąd sterownika ✓", "body", c.success).pack(fill="x", pady=(2, 6))
            rows = []
            for d in drv:
                dt = dv.parse_dmtf(d.get("date"))
                rows.append((dv.age_years(dt) or 0, d, dt))
            rows.sort(key=lambda x: -x[0])
            if rows:
                w.label(self.installed, "Najstarsze sterowniki (sprawdź, czy są aktualne):", "small", c.muted, "bold").pack(fill="x", pady=(8, 2))
            for age, d, dt in rows[:10]:
                col = c.warning if age >= 3 else c.muted
                line = ctk.CTkFrame(self.installed, fg_color="transparent", height=1)
                line.pack(fill="x", pady=1)
                w.label(line, d.get("name", "?"), "small", c.text, width=300).pack(side="left")
                w.label(line, f"{d.get('ver', '')}", "small", c.muted, width=140).pack(side="left")
                w.label(line, (dt.strftime("%Y-%m-%d") + f"  ({age:.1f} l.)") if dt else "brak daty", "small", col).pack(side="left")

        self.app.bg.run(work, done)

    # ------------------------------------------------------------------ winget
    def winget(self) -> None:
        if self.busy:
            return
        self._busy(True)
        self.winget_msg.configure(text="Aktualizuję programy… (może potrwać kilka minut)", text_color=c.muted)

        def done(res):
            ok, msg = res
            self._busy(False)
            self.winget_msg.configure(text=msg, text_color=c.success if ok else c.warning)

        self.app.bg.run(dv.winget_upgrade_all, done, lambda e: (self._busy(False), self.winget_msg.configure(text=f"Błąd: {e}", text_color=c.danger)))

    # ------------------------------------------------------------------ BIOS
    def load_board(self) -> None:
        def done(res):
            ok, info = res
            for ch in self.board.winfo_children() + self.board_btns.winfo_children():
                ch.destroy()
            if not ok:
                w.label(self.board, "Nie udało się odczytać informacji o BIOS (funkcja działa w Windows).", "small", c.muted).pack(fill="x")
                return
            d = dv.parse_dmtf(info.get("bios_date"))
            age = dv.age_years(d)
            lines = (("Płyta główna", f"{info.get('board_vendor', '')} {info.get('board', '')}".strip()),
                     ("Producent BIOS", info.get("bios_vendor", "")), ("Wersja BIOS", info.get("bios_ver", "")),
                     ("Data BIOS", (d.strftime("%Y-%m-%d") + (f"  ({age:.1f} l. temu)" if age is not None else "")) if d else "—"),
                     ("Komputer", f"{info.get('sys_vendor', '')} {info.get('system', '')}".strip()))
            for k, v in lines:
                ln = ctk.CTkFrame(self.board, fg_color="transparent", height=1)
                ln.pack(fill="x", pady=1)
                w.label(ln, k, "small", c.muted, "bold", width=130).pack(side="left")
                w.label(ln, v or "—", "small", c.text).pack(side="left")
            if age is not None and age > 1.5:
                w.label(self.board, "BIOS ma ponad 1,5 roku - sprawdź na stronie producenta, czy są poprawki dla Twojej płyty.", "small", c.warning).pack(fill="x", pady=(6, 0))
            vendor = info.get("board_vendor") or info.get("sys_vendor") or ""
            prod = info.get("board") or info.get("system") or ""
            w.button(self.board_btns, "Strona wsparcia producenta", lambda: dv.open_url(dv.vendor_support_url(vendor, prod)), "primary", height=34, width=220).pack(side="left")
            w.button(self.board_btns, "Szukaj BIOS dla mojego modelu", lambda: dv.open_url(dv.board_search_url(vendor, prod)), "ghost", height=34, width=230).pack(side="left", padx=8)

        self.app.bg.run(dv.board_info, done)

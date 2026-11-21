"""Ustawienia, aktualizacje, pliki do customizacji, informacje o bezpieczeństwie."""
from __future__ import annotations

import customtkinter as ctk

from ... import paths
from ...security import DEFAULT_HOSTS
from ...update_key import PUBLIC_KEY_HEX
from ...version import APP_NAME, VERSION
from .. import theme, widgets as w
from ..app import Page
from ..theme import c, font


class SettingsPage(Page):
    title = "Ustawienia i aktualizacje"
    subtitle = "Aktualizacje działają w tle, jak w Discordzie - nic nie musisz ustawiać."

    def __init__(self, master, app):
        super().__init__(master, app)
        s = app.settings
        body = w.scroll_frame(self)
        body.pack(fill="both", expand=True)
        body.grid_columnconfigure(0, weight=1)

        # --- aktualizacje
        uc = w.card(body)
        uc.grid(row=0, column=0, sticky="ew")
        top = ctk.CTkFrame(uc, fg_color="transparent")
        top.pack(fill="x", padx=22, pady=(18, 6))
        w.label(top, "Aktualizacje", "heading", c.text, "bold").pack(side="left")
        w.badge(top, f"v{VERSION}", c.accent).pack(side="left", padx=12)
        self.state = w.label(uc, "", "body", c.muted, wraplength=700)
        self.state.pack(fill="x", padx=22, pady=(0, 8))
        self.bar = w.progress(uc)
        row = ctk.CTkFrame(uc, fg_color="transparent")
        row.pack(fill="x", padx=22, pady=(4, 8))
        self.btn_check = w.button(row, "Sprawdź aktualizacje", lambda: app.check_updates(manual=True), "primary", width=190)
        self.btn_check.pack(side="left")
        self.btn_restart = w.button(row, "Uruchom ponownie i zainstaluj", app.restart_now, "success", width=240)
        from ..app import UPDATE_INTERVAL_MIN
        w.label(uc, f"Aktualizacje pobierają się same w tle - aplikacja sprawdza nowe wersje co {UPDATE_INTERVAL_MIN} minut. "
                    "Nowa wersja instaluje się po ponownym uruchomieniu.", "small", c.muted, wraplength=700).pack(fill="x", padx=22, pady=(6, 18))

        # --- bezpieczeństwo
        sc = w.card(body)
        sc.grid(row=1, column=0, sticky="ew", pady=(14, 20))
        w.label(sc, "Bezpieczeństwo", "heading", c.text, "bold").pack(fill="x", padx=22, pady=(18, 8))
        key_ok = bool(PUBLIC_KEY_HEX)
        facts = [
            ("Podpis aktualizacji (Ed25519)", "aktywny - przyjmowane są tylko aktualizacje podpisane Twoim kluczem" if key_ok
             else "NIEAKTYWNY - brak klucza, aktualizacje są odrzucane", c.success if key_ok else c.danger),
            ("Weryfikacja paczki", "SHA-256 z podpisanego manifestu, odporność na zip-slip i zip-bomby", c.text),
            ("Zaufane hosty", ", ".join(sorted(DEFAULT_HOSTS)) + " (tylko HTTPS, także po przekierowaniach)", c.text),
            ("Uprawnienia", "aplikacja działa bez administratora; UAC tylko na żądanie dla wybranych funkcji", c.text),
            ("Wycofanie wadliwej wersji", "launcher automatycznie uruchamia poprzednią wersję, jeśli nowa się wywala", c.text),
            ("Instalacja", str(paths.install_root()), c.muted),
        ]
        for k, v, col in facts:
            line = ctk.CTkFrame(sc, fg_color="transparent")
            line.pack(fill="x", padx=22, pady=3)
            w.label(line, k, "small", c.muted, "bold", width=210).pack(side="left", anchor="n")
            w.label(line, v, "small", col, wraplength=520).pack(side="left", fill="x", expand=True)
        ctk.CTkFrame(sc, height=14, fg_color="transparent").pack()

        app.on_update_change(self._sync)
        self._sync()

    def on_show(self) -> None:
        self._sync()

    def _sync(self) -> None:
        a = self.app
        txt = {"idle": "Nie sprawdzano jeszcze w tej sesji.", "checking": "Sprawdzanie aktualizacji…",
               "uptodate": f"Masz najnowszą wersję ({VERSION}).", "downloading": a.update_text,
               "ready": a.update_text + " Uruchom ponownie aplikację, aby ją zainstalować.", "error": a.update_text}
        col = {"error": c.danger, "ready": c.success, "uptodate": c.success}.get(a.update_state, c.muted)
        self.state.configure(text=txt.get(a.update_state, ""), text_color=col)
        if a.update_state == "downloading":
            self.bar.pack(fill="x", padx=22, pady=(0, 6), before=self.btn_check.master)
            self.bar.set(a.update_progress)
        else:
            self.bar.pack_forget()
        busy = a.update_state in ("checking", "downloading")
        self.btn_check.configure(state="disabled" if busy else "normal")
        if a.update_state == "ready":
            self.btn_restart.pack(side="left", padx=8)
        else:
            self.btn_restart.pack_forget()

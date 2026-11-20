"""Ustawienia, aktualizacje, pliki do customizacji, informacje o bezpieczeństwie."""
from __future__ import annotations

import os
import shutil
import subprocess
import tkinter as tk

import customtkinter as ctk

from ... import config, paths
from ...security import DEFAULT_HOSTS
from ...update_key import PUBLIC_KEY_HEX
from ...version import APP_NAME, VERSION
from .. import theme, widgets as w
from ..app import Page
from ..theme import c, font


class SettingsPage(Page):
    title = "Ustawienia i aktualizacje"
    subtitle = "Aktualizacje działają w tle, jak w Discordzie - nowa wersja wchodzi po restarcie."

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
        self.v_auto = tk.BooleanVar(value=bool(s.get("auto_update")))
        w.switch(uc, "Pobieraj aktualizacje automatycznie w tle", variable=self.v_auto,
                 command=lambda: s.set("auto_update", self.v_auto.get())).pack(anchor="w", padx=22, pady=(6, 4))
        hrow = ctk.CTkFrame(uc, fg_color="transparent")
        hrow.pack(fill="x", padx=22, pady=(4, 18))
        w.label(hrow, "Sprawdzaj co:", "body", c.text).pack(side="left")
        self.hours = ctk.CTkOptionMenu(hrow, values=["1 h", "3 h", "6 h", "12 h", "24 h"], width=90, font=font("body"),
                                       fg_color=theme.blend(c.card, "#FFFFFF", 0.1), button_color=theme.blend(c.card, "#FFFFFF", 0.16),
                                       button_hover_color=theme.blend(c.card, "#FFFFFF", 0.26), text_color=c.text,
                                       dropdown_fg_color=c.card, dropdown_text_color=c.text,
                                       dropdown_hover_color=c.card_hover,
                                       command=lambda v: s.set("update_check_hours", int(v.split()[0])))
        self.hours.set(f"{int(s.get('update_check_hours', 6))} h")
        self.hours.pack(side="left", padx=12)

        # --- pliki do customizacji
        cc = w.card(body)
        cc.grid(row=1, column=0, sticky="ew", pady=(14, 0))
        w.label(cc, "Personalizacja", "heading", c.text, "bold").pack(fill="x", padx=22, pady=(18, 4))
        w.label(cc, "Motyw (kolory, czcionki), własne aplikacje do czyszczenia i własne profile Roblox to zwykłe pliki "
                    "JSON w folderze konfiguracji. Zmień je i uruchom aplikację ponownie - bez przebudowy i bez czekania na aktualizację.",
                "small", c.muted, wraplength=720).pack(fill="x", padx=22)
        r2 = ctk.CTkFrame(cc, fg_color="transparent")
        r2.pack(fill="x", padx=22, pady=(12, 18))
        w.button(r2, "Utwórz pliki do edycji", self.make_templates, "primary", width=190).pack(side="left")
        w.button(r2, "Otwórz folder konfiguracji", lambda: self._open(paths.config_dir()), "ghost", width=210).pack(side="left", padx=8)
        w.button(r2, "Otwórz logi", lambda: self._open(paths.logs_dir()), "ghost", width=130).pack(side="left")

        # --- bezpieczeństwo
        sc = w.card(body)
        sc.grid(row=2, column=0, sticky="ew", pady=(14, 20))
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

    def _open(self, d) -> None:
        d.mkdir(parents=True, exist_ok=True)
        try:
            if os.name == "nt":
                os.startfile(str(d))      # noqa: S606
            else:
                subprocess.Popen(["xdg-open", str(d)])
        except Exception:
            self.app.toast.show(str(d), "info")

    def make_templates(self) -> None:
        d = paths.config_dir()
        d.mkdir(parents=True, exist_ok=True)
        made = []
        theme_src = paths.resource_dir() / "config" / "theme.json"
        if theme_src.exists() and not (d / "theme.json").exists():
            shutil.copy2(theme_src, d / "theme.json")
            made.append("theme.json")
        examples = {
            "apps.user.json": '[\n  {\n    "id": "moja_apka",\n    "name": "Moja aplikacja",\n    "group": "Moje",\n    "default": false,\n'
                              '    "processes": ["MojaApka.exe"],\n    "paths": ["%APPDATA%/MojaApka/Cache"],\n    "note": "Przykład - zmień lub usuń."\n  }\n]\n',
            "presets.user.json": '[\n  {\n    "id": "moj_profil",\n    "name": "Mój profil",\n    "description": "Przykład własnego profilu.",\n'
                                 '    "applies_to": ["player", "studio"],\n    "flags": {\n      "FFlagDebugGraphicsPreferD3D11": true,\n'
                                 '      "DFIntTextureQualityOverride": 2,\n      "DFFlagTextureQualityOverrideEnabled": true\n    }\n  }\n]\n',
        }
        for name, content in examples.items():
            if not (d / name).exists():
                (d / name).write_text(content, encoding="utf-8")
                made.append(name)
        self.app.toast.show("Utworzono: " + ", ".join(made) if made else "Pliki już istnieją - możesz je edytować.", "ok", 5000)
        self._open(d)

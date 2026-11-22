"""Ustawienia, aktualizacje, pliki do customizacji, informacje o bezpieczeństwie."""
from __future__ import annotations

import json
import tkinter.filedialog as fd

import customtkinter as ctk

from ... import automation, fan as fanmod, paths, profiles, winsys
from ...security import DEFAULT_HOSTS
from ...update_key import PUBLIC_KEY_HEX
from ...version import APP_NAME, VERSION
from .. import theme, widgets as w
from ..app import Page
from ..theme import c, font


class SettingsPage(Page):
    def _integrity_text(self) -> str:
        r = getattr(self.app, "integrity_result", None)
        if r is None:
            return "sprawdzane przy starcie (podpisana lista plików)"
        return f"w porządku - {r['checked']} plików zgodnych z podpisem" if r.get("ok") else "ZMIENIONE - " + r.get("reason", "")

    title = "Ustawienia"
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

        # --- udostępnianie profilu
        pc = w.card(body)
        pc.grid(row=1, column=0, sticky="ew", pady=(14, 0))
        w.label(pc, "Udostępnianie profilu", "heading", c.text, "bold").pack(fill="x", padx=22, pady=(18, 4))
        w.label(pc, "Zapisz swoje ustawienia (włączone optymalizacje, profil Robloxa, krzywą wentylatora, automatyzację) "
                    "do małego pliku i wyślij go znajomym - albo wczytaj profil od kogoś, komu ufasz. "
                    "Nic nie jest wysyłane przez internet: plik przekazujesz sam. Przed wczytaniem zobaczysz listę zmian "
                    "i musisz ją zatwierdzić. Plik zawiera tylko ustawienia - bez nazwy komputera, kont i ścieżek.",
                "small", c.muted, wraplength=700).pack(fill="x", padx=22, pady=(0, 8))
        prow = ctk.CTkFrame(pc, fg_color="transparent")
        prow.pack(fill="x", padx=22, pady=(4, 18))
        w.button(prow, "Zapisz mój profil do pliku", self.export_profile, "primary", width=220).pack(side="left")
        w.button(prow, "Wczytaj profil z pliku", self.import_profile, "ghost", width=190).pack(side="left", padx=8)

        # --- bezpieczeństwo
        sc = w.card(body)
        sc.grid(row=2, column=0, sticky="ew", pady=(14, 20))
        w.label(sc, "Bezpieczeństwo", "heading", c.text, "bold").pack(fill="x", padx=22, pady=(18, 8))
        key_ok = bool(PUBLIC_KEY_HEX)
        facts = [
            ("Podpis aktualizacji (Ed25519)", "aktywny - przyjmowane są tylko aktualizacje podpisane Twoim kluczem" if key_ok
             else "NIEAKTYWNY - brak klucza, aktualizacje są odrzucane", c.success if key_ok else c.danger),
            ("Weryfikacja paczki", "SHA-256 z podpisanego manifestu, odporność na zip-slip i zip-bomby", c.text),
            ("Pliki aplikacji", self._integrity_text(), c.text),
            ("Serwer aktualizacji", "zaufany, połączenie szyfrowane (HTTPS); inne adresy są odrzucane", c.text),
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

    # ------------------------------------------------------------------ profile
    def export_profile(self) -> None:
        path = fd.asksaveasfilename(parent=self, title="Zapisz profil", defaultextension=".pouprofile",
                                    initialfile="moj-profil.pouprofile",
                                    filetypes=[("Profil PRO Ultimate Optimizer", "*.pouprofile"), ("JSON", "*.json")])
        if not path:
            return

        def work():
            states = {t.id: winsys.tweak_state(t) for t in winsys.TWEAKS}
            return profiles.export_profile(self.app.settings.get, states, "Mój profil", VERSION)

        def done(prof):
            try:
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(prof, f, indent=2, ensure_ascii=False)
                self.app.toast.show("Profil zapisany. Możesz go wysłać znajomym.", "ok")
            except OSError as e:
                self.app.toast.show(f"Nie udało się zapisać pliku: {e}", "err", 6000)

        self.app.bg.run(work, done, lambda e: self.app.toast.show(f"Błąd: {e}", "err"))

    def import_profile(self) -> None:
        path = fd.askopenfilename(parent=self, title="Wczytaj profil",
                                  filetypes=[("Profil PRO Ultimate Optimizer", "*.pouprofile *.json")])
        if not path:
            return
        try:
            with open(path, "rb") as f:
                raw = f.read(profiles.MAX_BYTES + 1)
            prof = profiles.parse(raw, [t.id for t in winsys.TWEAKS], [p["id"] for p in self.app.presets],
                                  fanmod.CURVES.keys())
        except (OSError, profiles.ProfileError) as e:
            self.app.toast.show(str(e), "err", 6000)
            return
        lines = profiles.describe(prof, {t.id: t.name for t in winsys.TWEAKS},
                                  {p["id"]: p.get("name", p["id"]) for p in self.app.presets},
                                  {k: v["name"] for k, v in fanmod.CURVES.items()}, automation.TASK_LABELS)
        if not w.confirm(self, f"Wczytać profil „{prof['name']}”?",
                         "\n".join("• " + ln for ln in lines) + "\n\nKażdą z optymalizacji możesz potem cofnąć jednym przełącznikiem.",
                         "Zastosuj"):
            return

        def work():
            msgs = []
            for tid in prof["tweaks"]:
                t = next(x for x in winsys.TWEAKS if x.id == tid)
                ok, msg = winsys.apply_tweak(t, self.app.settings)
                msgs.append(f"{t.name}: {'OK' if ok else msg}")
            profiles.apply_settings(prof, self.app.settings)
            return msgs

        def done(msgs):
            bad = [m for m in msgs if not m.endswith("OK")]
            self.app.toast.show("Profil zastosowany." + (f" Pominięto: {len(bad)} (brak uprawnień lub niedostępne)." if bad else ""),
                                "warn" if bad else "ok", 6000)
            pg = self.app.page("system")
            if pg:
                pg.on_show()

        self.app.bg.run(work, done, lambda e: self.app.toast.show(f"Błąd: {e}", "err"))

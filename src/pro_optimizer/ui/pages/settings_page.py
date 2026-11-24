"""Ustawienia, aktualizacje, pliki do customizacji, informacje o bezpieczeństwie."""
from __future__ import annotations

import json
import tkinter as tk
import tkinter.filedialog as fd

import customtkinter as ctk

from ... import automation, fan as fanmod, paths, profiles, winsys
from ...security import DEFAULT_HOSTS
from ...update_key import PUBLIC_KEY_HEX
from ...version import APP_NAME, VERSION
from .. import anim, theme, widgets as w
from ..app import Page
from ..theme import c, font


THEMES = {
    "aderis": {"name": "Aderis", "colors": {"bg": "#0A0B14", "sidebar": "#0E0F1B", "card": "#14152A", "card_hover": "#1B1C36",
               "border": "#26274A", "accent": "#8B5CF6", "accent_hover": "#A78BFA", "accent2": "#C084FC"}},
    "ocean": {"name": "Ocean", "colors": {"bg": "#08111A", "sidebar": "#0B1622", "card": "#0F1D2C", "card_hover": "#142739",
              "border": "#1B3147", "accent": "#0EA5E9", "accent_hover": "#38BDF8", "accent2": "#22D3EE"}},
    "aurora": {"name": "Aurora", "colors": {"bg": "#08140F", "sidebar": "#0B1A14", "card": "#0F2119", "card_hover": "#142B21",
               "border": "#1B3A2D", "accent": "#10B981", "accent_hover": "#34D399", "accent2": "#2DD4BF"}},
    "sunset": {"name": "Zachód", "colors": {"bg": "#150C0C", "sidebar": "#1B0F0F", "card": "#241414", "card_hover": "#2E1A1A",
               "border": "#442424", "accent": "#F97316", "accent_hover": "#FB923C", "accent2": "#F43F5E"}},
    "rose": {"name": "Róż", "colors": {"bg": "#14090F", "sidebar": "#1A0C14", "card": "#23101C", "card_hover": "#2D1524",
             "border": "#44203A", "accent": "#EC4899", "accent_hover": "#F472B6", "accent2": "#A78BFA"}},
    "oled": {"name": "OLED", "colors": {"bg": "#000000", "sidebar": "#050505", "card": "#0C0C0E", "card_hover": "#141417",
             "border": "#1E1E24", "accent": "#8B5CF6", "accent_hover": "#A78BFA", "accent2": "#22D3EE"}},
}


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

        # --- praca w tle
        bc = w.card(body)
        bc.grid(row=3, column=0, sticky="ew", pady=(14, 0))
        w.label(bc, "Praca w tle", "heading", c.text, "bold").pack(fill="x", padx=22, pady=(18, 4))
        w.label(bc, "Po zamknięciu okna aplikacja zostaje przy zegarze i dalej działa: automatyka, doping gier, kolor pada i "
                    "aktualizacje. Pełne wyjście: prawy przycisk na ikonie → Zakończ całkowicie.", "small", c.muted,
                wraplength=700).pack(fill="x", padx=22)
        from ... import background
        self.bg_var = tk.BooleanVar(value=bool(app.settings.get("background", True)))
        self.auto_var = tk.BooleanVar(value=background.autostart_enabled())
        w.switch(bc, "Działaj w tle po zamknięciu okna", variable=self.bg_var,
                 command=lambda: app.settings.set("background", self.bg_var.get())).pack(anchor="w", padx=22, pady=(10, 2))
        w.switch(bc, "Uruchamiaj razem z Windows (od razu w tle)", variable=self.auto_var,
                 command=lambda: (background.set_autostart(self.auto_var.get()) or None)).pack(anchor="w", padx=22, pady=(2, 16))

        # --- wygląd
        ac = w.card(body)
        ac.grid(row=4, column=0, sticky="ew", pady=(14, 0))
        w.label(ac, "Wygląd i tło", "heading", c.text, "bold").pack(fill="x", padx=22, pady=(18, 4))
        w.label(ac, "Wybierz motyw kolorów. Zmiana działa od razu, bez restartu.", "small", c.muted).pack(fill="x", padx=22)
        tr = ctk.CTkFrame(ac, fg_color="transparent")
        tr.pack(fill="x", padx=22, pady=(10, 4))
        for i, (key, th) in enumerate(THEMES.items()):
            col = ctk.CTkFrame(tr, fg_color="transparent")
            col.grid(row=0, column=i, padx=5)
            sw = ctk.CTkButton(col, text="", width=74, height=46, corner_radius=12, fg_color=th["colors"]["card"],
                               hover_color=th["colors"]["card_hover"], border_width=3, border_color=th["colors"]["accent"],
                               command=lambda k=key: self.apply_theme(k))
            sw.pack()
            w.label(col, th["name"], "small", c.muted).pack(pady=(3, 0))
        self.anim_var = tk.BooleanVar(value=anim.enabled())
        w.switch(ac, "Animacje interfejsu", variable=self.anim_var, command=self.toggle_anim).pack(anchor="w", padx=22, pady=(10, 16))

        # --- całkowite usunięcie
        dc = w.card(body, border_color=theme.blend(c.card, c.danger, 0.5))
        dc.grid(row=5, column=0, sticky="ew", pady=(14, 0))
        w.label(dc, "Usuń całkowicie", "heading", c.text, "bold").pack(fill="x", padx=22, pady=(18, 4))
        w.label(dc, "Cofa wszystkie zmiany, które aplikacja zrobiła w Windows i w plikach gier (o ile da się je cofnąć), a potem kasuje "
                    "aplikację razem z ustawieniami, kopiami zapasowymi, logami, skrótami, wpisem w Aplikacjach i autostartem. "
                    "Nic z niej nie zostaje. Tego nie można cofnąć.", "small", c.muted, wraplength=700).pack(fill="x", padx=22)
        self.purge_out = w.label(dc, "", "small", c.muted, wraplength=700)
        self.purge_out.pack(fill="x", padx=22)
        w.button(dc, "Usuń aplikację i wszystkie pliki", self.purge_all, "danger", height=38, width=260).pack(anchor="w", padx=22, pady=(8, 16))

        # --- bezpieczeństwo
        sc = w.card(body)
        sc.grid(row=6, column=0, sticky="ew", pady=(14, 20))
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

    def _write_theme(self, **changes) -> None:
        """Dopisuje nasze zmiany do theme.json, zachowując resztę Twoich ustawień (czcionki, rozmiary okna)."""
        cfgdir = paths.config_dir()
        cfgdir.mkdir(parents=True, exist_ok=True)
        f = cfgdir / "theme.json"
        try:
            cur = json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}
            if not isinstance(cur, dict):
                cur = {}
        except (OSError, ValueError):
            cur = {}
        if "colors" in changes:
            cur["colors"] = {**(cur.get("colors") or {}), **changes.pop("colors")}
        cur.update(changes)
        f.write_text(json.dumps(cur, indent=1, ensure_ascii=False), encoding="utf-8")

    def apply_theme(self, key: str) -> None:
        self._write_theme(colors=THEMES[key]["colors"], _aderis_theme=key)
        self.app.toast.show("Motyw zmieniony.", "ok")
        self.after(50, lambda: self.app.rebuild_ui("settings"))

    def toggle_anim(self) -> None:
        self._write_theme(animations=bool(self.anim_var.get()))
        anim.set_enabled(self.anim_var.get())

    def purge_all(self) -> None:
        if not w.confirm(self, "Usuń całkowicie",
                         "Aplikacja cofnie swoje zmiany i usunie się razem z WSZYSTKIMI danymi (ustawienia, kopie zapasowe, logi).\n\n"
                         "Tego nie można cofnąć. Kontynuować?", "Usuń wszystko"):
            return
        if not w.confirm(self, "Ostatnie potwierdzenie", "Na pewno usunąć Aderis Boost i wszystkie jego pliki?", "Tak, usuń"):
            return
        self.purge_out.configure(text="Pracuję…", text_color=c.muted)

        def work():
            from ... import purge
            return purge.purge(self.app.settings, lambda m: self.after(0, lambda: self.purge_out.configure(text=m)))

        def done(res):
            self.purge_out.configure(text="Gotowe. Aplikacja zamknie się i usunie resztę plików.", text_color=c.success)
            self.after(1500, self.app.quit_app)
        self.app.bg.run(work, done)

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
                                    filetypes=[("Profil Aderis Boost", "*.pouprofile"), ("JSON", "*.json")])
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
                                  filetypes=[("Profil Aderis Boost", "*.pouprofile *.json")])
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

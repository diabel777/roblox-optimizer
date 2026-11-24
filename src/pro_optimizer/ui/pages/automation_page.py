"""Automatyzacja: aplikacja sama zwalnia RAM, czyści DNS i cache, pilnuje optymalizacji i dopinguje gry."""
from __future__ import annotations

import time
import tkinter as tk

import customtkinter as ctk

from ... import automation as au
from .. import theme, widgets as w
from ..app import Page
from ..theme import c


def _hours(h: float) -> str:
    return {1: "co godzinę", 3: "co 3 godziny", 6: "co 6 godzin", 12: "co 12 godzin", 24: "raz dziennie",
            72: "co 3 dni", 168: "raz w tygodniu"}.get(int(h), f"co {int(h)} h")


HOUR_CHOICES = {
    "dns": [1, 3, 6, 12, 24], "clean": [6, 12, 24, 72, 168], "tweaks": [1, 3, 6, 12, 24], "defender": [6, 12, 24],
    "scan": [12, 24, 72, 168],
}
ROWS = [
    ("ram", "Automatyczne zwalnianie RAM", "Zwalnia nieużywaną pamięć: gdy RAM przekroczy wybrany próg, co ustaloną liczbę minut albo oba naraz. Niczego nie zamyka, nie rusza Robloxa."),
    ("dns", "Automatyczne czyszczenie DNS", "Czyści pamięć podręczną DNS - pomaga, gdy strony i gry online źle się łączą."),
    ("clean", "Automatyczne czyszczenie cache", "Czyści cache aplikacji zaznaczonych domyślnie na stronie Czyszczenie (uruchomione aplikacje są pomijane)."),
    ("tweaks", "Automatyczna optymalizacja Windows", "Pilnuje, żeby plan zasilania, tryb gry i wyłączone nagrywanie w tle nie wróciły do ustawień Windows."),
    ("defender", "Automatyczna aktualizacja antywirusa", "Pobiera najnowsze definicje Microsoft Defendera."),
    ("scan", "Automatyczne skanowanie antywirusem", "Robi szybkie skanowanie w tle (np. raz dziennie), żeby zagrożenia były wychwycone bez Twojej pamięci o tym."),
    ("app_opt", "Optymalizacja aplikacji w tle", "Gdy działa gra, przeglądarki, Discord, Spotify i launchery dostają niższy priorytet, a po grze wracają do normy. Niczego nie zamyka."),
    ("game_boost", "Automatyczny doping gier", "Gdy wykryta gra się uruchomi: podnosi jej priorytet i zwalnia pamięć. Szczegóły ustawisz w każdej grze osobno."),
]


class AutomationPage(Page):
    title = "Działa samo"
    subtitle = "Włącz raz - reszta dzieje się w tle, dopóki aplikacja jest uruchomiona."

    def __init__(self, master, app):
        super().__init__(master, app)
        body = w.scroll_frame(self)
        body.pack(fill="both", expand=True)
        body.grid_columnconfigure(0, weight=1)
        self.vars: dict[str, tk.BooleanVar] = {}
        card = w.card(body)
        card.grid(row=0, column=0, sticky="ew")
        top = ctk.CTkFrame(card, fg_color="transparent", height=1)
        top.pack(fill="x", padx=22, pady=(18, 4))
        w.label(top, "Zadania automatyczne", "heading", c.text, "bold").pack(side="left")
        w.button(top, "Włącz zalecane", self.enable_recommended, "primary", height=32, width=140).pack(side="right")
        cfg = au.merged(app.settings.get("auto"))
        for key, title, desc in ROWS:
            row, right = w.setting_row(card, title, desc, 430)
            v = tk.BooleanVar(value=bool(cfg[key]["enabled"]))
            self.vars[key] = v
            w.switch(right, "", variable=v, command=lambda k=key: self._save(k), width=46).pack(side="right")
            w.button(right, "Uruchom teraz", lambda k=key: self.run_now(k), "ghost", height=30, width=118).pack(side="right", padx=10)
            if key == "ram":
                menu = w.option_menu(right, [f"próg {p}%" for p in (70, 75, 80, 85, 90)], width=110,
                                     command=lambda val: self._set("ram", "threshold_pct", int(val.split()[1].rstrip("%"))))
                menu.set(f"próg {cfg['ram']['threshold_pct']}%")
                menu.pack(side="right", padx=(0, 4))
                mins = {"co 5 min": 5, "co 10 min": 10, "co 15 min": 15, "co 30 min": 30, "co 60 min": 60}
                mm = w.option_menu(right, list(mins), width=110, command=lambda val: self._set("ram", "interval_min", mins[val]))
                mm.set(next((k for k, v in mins.items() if v == cfg["ram"]["interval_min"]), "co 15 min"))
                mm.pack(side="right", padx=(0, 4))
                modes = {"gdy RAM ≥ próg": "threshold", "co X minut": "interval", "próg LUB czas": "both"}
                md = w.option_menu(right, list(modes), width=140, command=lambda val: self._set("ram", "mode", modes[val]))
                md.set(next((k for k, v in modes.items() if v == cfg["ram"].get("mode", "threshold")), "gdy RAM ≥ próg"))
                md.pack(side="right", padx=(0, 4))
            elif key in HOUR_CHOICES:
                labels = {_hours(h): h for h in HOUR_CHOICES[key]}
                menu = w.option_menu(right, list(labels), width=150,
                                     command=lambda val, k=key, lb=labels: self._set(k, "interval_hours", lb[val]))
                menu.set(_hours(cfg[key]["interval_hours"]))
                menu.pack(side="right", padx=(0, 4))
        ctk.CTkFrame(card, height=12, fg_color="transparent").pack()

        ac = w.card(body)
        ac.grid(row=1, column=0, sticky="ew", pady=(14, 20))
        w.label(ac, "Ostatnia aktywność", "heading", c.text, "bold").pack(fill="x", padx=22, pady=(18, 6))
        self.feed = ctk.CTkFrame(ac, fg_color="transparent", height=1)
        self.feed.pack(fill="x", padx=22, pady=(0, 16))
        self._draw_feed()
        self.after(2500, self._tick)

    def _tick(self) -> None:
        if self.app.current_page_id() == "automation":
            self._draw_feed()
        self.after(2500, self._tick)

    def on_show(self) -> None:
        self._draw_feed()

    def _draw_feed(self) -> None:
        for ch in self.feed.winfo_children():
            ch.destroy()
        items = list(self.app.activity.items)[:12]
        if not items:
            w.label(self.feed, "Jeszcze nic się nie wydarzyło. Włącz zadania powyżej albo kliknij „Uruchom teraz”.", "small", c.muted).pack(fill="x")
            return
        for ts, task, ok, text in items:
            line = ctk.CTkFrame(self.feed, fg_color="transparent", height=1)
            line.pack(fill="x", pady=2)
            ctk.CTkLabel(line, text="●", width=14, text_color=c.success if ok else c.warning).pack(side="left")
            w.label(line, time.strftime("%H:%M", time.localtime(ts)), "small", c.muted, width=44).pack(side="left", padx=4)
            w.label(line, f"{au.TASK_LABELS.get(task, task)}: {text}", "small", c.text, wraplength=620).pack(side="left", fill="x", expand=True)

    def _cfg(self) -> dict:
        return au.merged(self.app.settings.get("auto"))

    def _set(self, key: str, field: str, val) -> None:
        cfg = self._cfg()
        cfg[key][field] = val
        self.app.settings.set("auto", cfg)

    def _save(self, key: str) -> None:
        self._set(key, "enabled", self.vars[key].get())

    def enable_recommended(self) -> None:
        for k in ("ram", "dns", "tweaks", "defender", "game_boost", "app_opt"):
            self.vars[k].set(True)
            self._set(k, "enabled", True)
        self.app.toast.show("Włączono zalecane zadania. Czyszczenie cache zostaw wyłączone, jeśli wolisz robić je ręcznie.", "ok", 5500)

    def run_now(self, key: str) -> None:
        self.app.run_auto_task(key, manual=True)
        self.after(400, self._draw_feed)

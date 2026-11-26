"""Asystent Aderis (AI): rozmowa po polsku, który zna aplikację i proponuje przyciski. Każdą akcję zatwierdzasz sam."""
from __future__ import annotations

import platform
import threading

import customtkinter as ctk

from ... import ai_actions, cloud, hw
from ...version import VERSION
from .. import theme, widgets as w
from ..app import Page
from ..theme import c

GREETING = ("Cześć! Jestem Aderis. Pomogę Ci przyspieszyć grę, naprawić internet albo znaleźć odpowiednią opcję w aplikacji. "
            "Napisz np. „jak zoptymalizować Roblox?” albo „mam wysoki ping”. Sam niczego nie zmieniam - pokażę przyciski, "
            "a Ty zdecydujesz, co kliknąć.")
SUGGESTIONS = ["Jak zoptymalizować grę?", "Mam wysoki ping", "Co robi ta aplikacja?", "Jak zwolnić miejsce na dysku?"]


def build_context(app) -> dict:
    """Krótki opis komputera dla asystenta (bez nazwy komputera, kont i ścieżek)."""
    ctx: dict = {"app_version": VERSION, "system": f"{platform.system()} {platform.release()}"}
    try:
        import psutil
        ctx["ram_gb"] = round(psutil.virtual_memory().total / 2**30)
        ctx["cpu_threads"] = psutil.cpu_count()
    except Exception:
        pass
    try:
        gpus = hw.gpu_names_wmi()
        if gpus:
            ctx["gpu"] = gpus[:2]
    except Exception:
        pass
    last = (app.settings.get("speed_history") or [])[-1:]
    if last and isinstance(last[0], dict):
        ctx["last_speedtest"] = {k: last[0].get(k) for k in ("down", "up", "ping", "jitter", "loss") if k in last[0]}
    return ctx


class AssistantPage(Page):
    title = "Asystent AI"
    subtitle = "Zapytaj o cokolwiek: gry, internet, ustawienia. Asystent proponuje, Ty zatwierdzasz."

    def __init__(self, master, app):
        super().__init__(master, app)
        self.history: list[dict] = []
        self.busy = False
        self.gate = w.card(self)                     # ekran „zaloguj się”
        w.label(self.gate, "Asystent wymaga konta", "heading", c.text, "bold").pack(fill="x", padx=22, pady=(20, 4))
        w.label(self.gate, "Zaloguj się kodem w Ustawieniach → Konto Aderis. To darmowe i zajmuje minutę.", "body", c.muted,
                wraplength=640).pack(fill="x", padx=22)
        w.button(self.gate, "Przejdź do Ustawień", lambda: app.show_page("settings"), "primary", height=38, width=220).pack(anchor="w", padx=22, pady=(12, 20))

        self.chat = ctk.CTkFrame(self, fg_color="transparent")
        self.log = w.scroll_frame(self.chat)
        self.log.pack(fill="both", expand=True)
        self.chips = ctk.CTkFrame(self.chat, fg_color="transparent", height=1)
        self.chips.pack(fill="x", pady=(8, 0))
        for s in SUGGESTIONS:
            w.button(self.chips, s, lambda t=s: self.send(t), "ghost", height=30, width=10).pack(side="left", padx=(0, 6))
        row = ctk.CTkFrame(self.chat, fg_color="transparent")
        row.pack(fill="x", pady=(8, 0))
        self.entry = w.entry(row, placeholder_text="Napisz wiadomość…")
        self.entry.pack(side="left", fill="x", expand=True)
        self.entry.bind("<Return>", lambda _e: self.send())
        self.btn = w.button(row, "Wyślij", self.send, "primary", height=36, width=100)
        self.btn.pack(side="left", padx=(8, 0))
        self._bubble("assistant", GREETING)
        self._refresh_gate()

    def on_show(self) -> None:
        self._refresh_gate()

    def _refresh_gate(self) -> None:
        if cloud.is_linked():
            self.gate.pack_forget()
            self.chat.pack(fill="both", expand=True)
        else:
            self.chat.pack_forget()
            self.gate.pack(fill="x")

    # ------------------------------------------------------------------ bańki
    def _bubble(self, role: str, text: str, actions: list[dict] | None = None):
        mine = role == "user"
        wrap = ctk.CTkFrame(self.log, fg_color="transparent")
        wrap.pack(fill="x", pady=4)
        box = ctk.CTkFrame(wrap, corner_radius=14, fg_color=theme.blend(c.card, c.accent, 0.35) if mine else c.card)
        box.pack(side="right" if mine else "left", padx=(80, 0) if mine else (0, 80))
        lbl = w.label(box, text, "body", c.text, wraplength=560, justify="left")
        lbl.pack(anchor="w", padx=14, pady=(10, 10 if not actions else 4))
        for a in actions or []:
            w.button(box, "▶  " + a["label"], lambda act=a: self.run_action(act), "primary", height=32, width=10).pack(anchor="w", padx=14, pady=(2, 8))
        self.after(60, lambda: self.log._parent_canvas.yview_moveto(1.0))
        return lbl

    # ------------------------------------------------------------------ wysyłanie
    def send(self, text: str | None = None) -> None:
        text = (text if isinstance(text, str) else self.entry.get()).strip()
        if not text or self.busy:
            return
        self.entry.delete(0, "end")
        self.chips.pack_forget()
        self._bubble("user", text)
        self.history.append({"role": "user", "content": text})
        self.busy = True
        self.btn.configure(state="disabled")
        wait = self._bubble("assistant", "Myślę…")
        ctx = build_context(self.app)
        msgs = list(self.history)

        def work():
            return cloud.ask_ai(msgs, ctx)

        def done(res):
            self.busy = False
            self.btn.configure(state="normal")
            wait.master.master.destroy()
            actions = [a for a in (ai_actions.validate(x) for x in res["actions"]) if a]
            reply = res["reply"] or "Nie mam odpowiedzi - spróbuj inaczej."
            self.history.append({"role": "assistant", "content": reply})
            self._bubble("assistant", reply, actions)

        def fail(e):
            self.busy = False
            self.btn.configure(state="normal")
            wait.master.master.destroy()
            self.history.pop()                       # wiadomość nie poszła - nie zostawiaj jej w historii
            self._bubble("assistant", str(e) if isinstance(e, cloud.CloudError) else "Coś poszło nie tak. Spróbuj za chwilę.")
            self._refresh_gate()
        self.app.bg.run(work, done, fail)

    def run_action(self, act: dict) -> None:
        if act["id"] != "open_page" and not w.confirm(self, act["label"], act["desc"] + "\n\nWykonać?", "Tak, wykonaj"):
            return
        ai_actions.execute(act, self.app, lambda msg, kind="ok": self.app.toast.show(msg, kind))

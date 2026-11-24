"""Profesjonalny test internetu: ping, jitter, utrata pakietów, pobieranie, wysyłanie, opóźnienie pod obciążeniem."""
from __future__ import annotations

import math
import threading
import time
import tkinter as tk
import tkinter.filedialog as fd

import customtkinter as ctk

from ... import speedtest as st
from .. import theme, widgets as w
from ..app import Page
from ..theme import c
from ...version import VERSION

PHASES = {"ping": "Mierzę opóźnienie…", "down": "Test pobierania…", "up": "Test wysyłania…", "done": "Gotowe"}
GAUGE_MAX = (50, 100, 250, 500, 1000, 2500)


class Gauge(tk.Canvas):
    """Półokrągły zegar prędkości z płynnie dobiegającą wskazówką."""

    def __init__(self, master, size=300):
        super().__init__(master, width=size, height=int(size * 0.66), bg=c.card, highlightthickness=0)
        self.size, self.value, self.target, self.max = size, 0.0, 0.0, 100
        self.label = "Mb/s"
        self._job = None
        self._draw()

    def set(self, v: float) -> None:
        self.target = max(0.0, v)
        while self.target > self.max * 0.95 and self.max < GAUGE_MAX[-1]:
            self.max = next(m for m in GAUGE_MAX if m > self.max)
        if self._job is None:
            self._step()

    def _step(self) -> None:
        self.value += (self.target - self.value) * 0.18
        self._draw()
        self._job = self.after(30, self._step) if abs(self.target - self.value) > 0.05 else None

    def _draw(self) -> None:
        self.delete("all")
        s = self.size
        cx, cy, r = s / 2, s * 0.58, s * 0.40
        self.create_arc(cx - r, cy - r, cx + r, cy + r, start=-30, extent=240, style="arc", width=16, outline=c.border)
        frac = min(1.0, self.value / self.max) if self.max else 0
        if frac > 0:
            self.create_arc(cx - r, cy - r, cx + r, cy + r, start=210, extent=-240 * frac, style="arc", width=16, outline=c.accent)
        ang = math.radians(210 - 240 * frac)
        self.create_line(cx, cy, cx + (r - 22) * math.cos(ang), cy - (r - 22) * math.sin(ang), fill=c.text, width=3, capstyle="round")
        self.create_oval(cx - 7, cy - 7, cx + 7, cy + 7, fill=c.accent, outline="")
        self.create_text(cx, cy + r * 0.52, text=f"{self.value:,.1f}".replace(",", " "), fill=c.text, font=theme.font("title", "bold"))
        self.create_text(cx, cy + r * 0.52 + 26, text=self.label, fill=c.muted, font=theme.font("small"))
        for i in range(0, 5):
            a = math.radians(210 - 60 * i)
            self.create_text(cx + (r + 22) * math.cos(a), cy - (r + 22) * math.sin(a), text=f"{self.max * i / 4:.0f}",
                             fill=c.muted, font=theme.font("small"))


class SpeedPage(Page):
    title = "Test internetu"
    subtitle = "Profesjonalny pomiar: ping, jitter, utrata pakietów, pobieranie, wysyłanie i opóźnienie pod obciążeniem."

    def __init__(self, master, app):
        super().__init__(master, app)
        self.stop = threading.Event()
        self.running = False
        body = w.scroll_frame(self)
        body.pack(fill="both", expand=True)
        top = w.card(body)
        top.pack(fill="x")
        self.gauge = Gauge(top)
        self.gauge.pack(pady=(18, 0))
        self.phase = w.label(top, "Kliknij „Start”, aby zmierzyć swoje łącze.", "body", c.muted)
        self.phase.pack(pady=(0, 6))
        self.bar = w.progress(top)
        self.bar.set(0)
        self.bar.pack(fill="x", padx=60, pady=(0, 10))
        row = ctk.CTkFrame(top, fg_color="transparent", height=1)
        row.pack(pady=(0, 18))
        self.btn = w.button(row, "Start", self.toggle, "primary", height=42, width=200)
        self.btn.pack()

        cx = w.card(body)
        cx.pack(fill="x", pady=(14, 0))
        w.label(cx, "Powiedz nam coś o swoim łączu (nieobowiązkowe)", "heading", c.text, "bold").pack(fill="x", padx=22, pady=(16, 2))
        w.label(cx, "Dzięki temu porady są trafniejsze, a raport dla dostawcy internetu zawiera wszystko, o co zwykle pytają.",
                "small", c.muted, wraplength=800).pack(fill="x", padx=22)
        crow = ctk.CTkFrame(cx, fg_color="transparent")
        crow.pack(fill="x", padx=22, pady=(8, 16))
        self.ctx = {}
        for i, (key, label, vals) in enumerate((
                ("conn", "Jak jesteś połączony?", ["Wykryj sam", "Kabel", "Wi-Fi"]),
                ("others", "Ktoś jeszcze korzysta z internetu?", ["Nie wiem", "tak", "nie"]),
                ("restarted", "Restartowałeś router?", ["Nie wiem", "tak", "nie"]))):
            col = ctk.CTkFrame(crow, fg_color="transparent")
            col.grid(row=0, column=i, padx=(0, 18), sticky="w")
            w.label(col, label, "small", c.muted).pack(anchor="w")
            om = w.option_menu(col, vals, width=170)
            om.pack(anchor="w", pady=(3, 0))
            self.ctx[key] = om
        self.last = None

        grid = ctk.CTkFrame(body, fg_color="transparent")
        grid.pack(fill="x", pady=(14, 0))
        self.tiles = {}
        names = [("down", "Pobieranie"), ("up", "Wysyłanie"), ("ping", "Ping"), ("jitter", "Jitter"), ("loss", "Utrata pakietów"),
                 ("loaded_ping", "Ping pod obciążeniem")]
        for i, (key, name) in enumerate(names):
            grid.grid_columnconfigure(i % 3, weight=1, uniform="t")
            card = w.card(grid)
            card.grid(row=i // 3, column=i % 3, sticky="ew", padx=(0 if i % 3 == 0 else 8, 0), pady=(0, 8))
            w.label(card, name, "small", c.muted).pack(anchor="w", padx=16, pady=(12, 0))
            v = w.label(card, "-", "title", c.text, "bold")
            v.pack(anchor="w", padx=16, pady=(0, 12))
            self.tiles[key] = v

        gc = w.card(body)
        gc.pack(fill="x", pady=(6, 0))
        w.label(gc, "Co to znaczy dla Ciebie", "heading", c.text, "bold").pack(fill="x", padx=22, pady=(18, 6))
        self.grade_box = ctk.CTkFrame(gc, fg_color="transparent")
        self.grade_box.pack(fill="x", padx=22, pady=(0, 16))
        w.label(self.grade_box, "Wyniki pojawią się po teście.", "small", c.muted).pack(anchor="w")

        self.adv_card = w.card(body)
        self.adv_card.pack(fill="x", pady=(14, 0))
        w.label(self.adv_card, "Co możesz zrobić", "heading", c.text, "bold").pack(fill="x", padx=22, pady=(18, 6))
        self.adv_box = ctk.CTkFrame(self.adv_card, fg_color="transparent")
        self.adv_box.pack(fill="x", padx=22, pady=(0, 12))
        w.label(self.adv_box, "Porady pojawią się po teście.", "small", c.muted).pack(anchor="w")
        arow = ctk.CTkFrame(self.adv_card, fg_color="transparent")
        arow.pack(fill="x", padx=22, pady=(0, 16))
        w.button(arow, "Zapisz raport dla dostawcy", self.save_report, "primary", height=36, width=220).pack(side="left")
        w.button(arow, "Skopiuj raport", self.copy_report, "ghost", height=36, width=150).pack(side="left", padx=8)

        hc = w.card(body)
        hc.pack(fill="x", pady=(14, 20))
        ht = ctk.CTkFrame(hc, fg_color="transparent", height=1)
        ht.pack(fill="x", padx=22, pady=(18, 6))
        w.label(ht, "Poprzednie testy", "heading", c.text, "bold").pack(side="left")
        w.button(ht, "Usuń historię", self.clear_history, "ghost", height=30, width=130).pack(side="right")
        self.hist = ctk.CTkFrame(hc, fg_color="transparent")
        self.hist.pack(fill="x", padx=22, pady=(0, 16))
        self._render_history()

    # --------------------------------------------------------------- test
    def toggle(self) -> None:
        if self.running:
            self.stop.set()
            self.btn.configure(text="Zatrzymuję…")
            return
        self.stop = threading.Event()
        self.running = True
        self.btn.configure(text="Zatrzymaj")
        for t in self.tiles.values():
            t.configure(text="-")
        self.gauge.label = "Mb/s"
        stop = self.stop

        def on_phase(name, prog, speed):
            self.after(0, lambda: self._phase(name, prog, speed))

        def work():
            info = st.connection_info()
            res = st.run(on_phase, stop)
            res["_info"] = info
            self.after(0, lambda: self._finish(res))
        threading.Thread(target=work, daemon=True).start()

    def _phase(self, name, prog, speed) -> None:
        self.phase.configure(text=PHASES.get(name, ""), text_color=c.text)
        self.bar.set(prog)
        if speed is not None:
            self.gauge.set(speed)
        elif name == "ping":
            self.gauge.set(0)

    def _finish(self, res: dict) -> None:
        self.running = False
        self.btn.configure(text="Start")
        self.bar.set(1)
        self.gauge.set(res.get("down", 0) or 0)
        if res.get("error"):
            self.phase.configure(text=res["error"], text_color=c.warning)
            return
        fmt = {"down": "{:.1f} Mb/s", "up": "{:.1f} Mb/s", "ping": "{:.0f} ms", "jitter": "{:.1f} ms", "loss": "{:.1f} %",
               "loaded_ping": "{:.0f} ms"}
        for k, f in fmt.items():
            v = res.get(k)
            self.tiles[k].configure(text="-" if v is None else f.format(v))
        self.phase.configure(text="Gotowe. Wynik zapisany w historii." if not self.stop.is_set() else "Przerwano.", text_color=c.success)
        for ch in self.grade_box.winfo_children():
            ch.destroy()
        for name, val in st.grade(res).items():
            r = ctk.CTkFrame(self.grade_box, fg_color="transparent")
            r.pack(fill="x", pady=2)
            col = c.success if val in ("Świetnie", "Brak problemu") else (c.warning if val in ("Dobrze", "Lekki") else c.danger)
            w.label(r, name, "body", c.text, width=240).pack(side="left")
            w.label(r, val, "body", col, "bold").pack(side="left")
        self._show_advice(res)
        if not self.stop.is_set():
            hist = list(self.app.settings.get("speed_history") or [])
            hist.append({k: res.get(k) for k in ("time", "down", "up", "ping", "jitter", "loss", "loaded_ping")})
            self.app.settings.set("speed_history", hist[-12:])
            self._render_history()

    def _context(self) -> dict:
        out = {}
        for k, om in self.ctx.items():
            v = om.get()
            if v not in ("Wykryj sam", "Nie wiem"):
                out[k] = v
        return out

    def _show_advice(self, res: dict) -> None:
        info = res.get("_info") or {}
        ctx = self._context()
        self.last = (res, info, ctx)
        for ch in self.adv_box.winfo_children():
            ch.destroy()
        for a in st.advice(res, info, ctx):
            r = ctk.CTkFrame(self.adv_box, fg_color=theme.blend(c.card, "#FFFFFF", 0.05), corner_radius=10)
            r.pack(fill="x", pady=4)
            w.label(r, a["title"], "body", c.text, "bold").pack(fill="x", padx=14, pady=(10, 0))
            w.label(r, a["text"], "small", c.muted, wraplength=820).pack(fill="x", padx=14, pady=(2, 10 if not a["page"] else 4))
            if a["page"]:
                w.button(r, "Przejdź tam →", lambda p=a["page"]: self.app.show_page(p), "ghost", height=30, width=140).pack(anchor="w", padx=14, pady=(0, 10))

    def _report(self) -> str:
        if not self.last:
            return ""
        res, info, ctx = self.last
        return st.report_text(res, info, ctx, VERSION)

    def save_report(self) -> None:
        txt = self._report()
        if not txt:
            self.app.toast.show("Najpierw zrób test.", "warn")
            return
        from ... import paths
        d = paths.reports_dir()
        d.mkdir(parents=True, exist_ok=True)
        path = d / time.strftime("raport-internet-%Y-%m-%d_%H-%M-%S.txt")
        path.write_text(txt, encoding="utf-8")
        self.app.toast.show("Raport zapisany w zakładce „Pobrane”. Dołącz go do zgłoszenia u dostawcy.", "ok", 5500)

    def copy_report(self) -> None:
        txt = self._report()
        if not txt:
            self.app.toast.show("Najpierw zrób test.", "warn")
            return
        self.clipboard_clear()
        self.clipboard_append(txt)
        self.app.toast.show("Raport skopiowany - wklej go w czacie lub mailu do dostawcy.", "ok")

    def clear_history(self) -> None:
        if not (self.app.settings.get("speed_history") or []):
            return
        if w.confirm(self, "Usuń historię", "Usunąć wszystkie zapisane wyniki testów?", "Usuń", danger=True):
            self.app.settings.set("speed_history", [])
            self._render_history()

    def delete_one(self, t) -> None:
        hist = [h for h in (self.app.settings.get("speed_history") or []) if isinstance(h, dict) and h.get("time") != t]
        self.app.settings.set("speed_history", hist)
        self._render_history()

    def _render_history(self) -> None:
        for ch in self.hist.winfo_children():
            ch.destroy()
        hist = [h for h in (self.app.settings.get("speed_history") or []) if isinstance(h, dict)][::-1][:8]
        if not hist:
            w.label(self.hist, "Brak zapisanych testów.", "small", c.muted).pack(anchor="w")
            return
        mx = max((h.get("down") or 0) for h in hist) or 1
        for h in hist:
            r = ctk.CTkFrame(self.hist, fg_color="transparent")
            r.pack(fill="x", pady=2)
            when = time.strftime("%d.%m %H:%M", time.localtime(h.get("time") or 0))
            w.label(r, when, "small", c.muted, width=100).pack(side="left")
            b = w.progress(r, width=220)
            b.set((h.get("down") or 0) / mx)
            b.pack(side="left", padx=8)
            w.label(r, f"↓ {h.get('down') or 0:.0f}  ↑ {h.get('up') or 0:.0f} Mb/s   ping {h.get('ping') or 0:.0f} ms", "small", c.text).pack(side="left")
            w.button(r, "Usuń", lambda t=h.get("time"): self.delete_one(t), "ghost", height=24, width=60).pack(side="right")

    def on_show(self) -> None:
        pass

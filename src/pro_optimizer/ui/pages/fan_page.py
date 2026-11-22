"""Wentylator i GPU: inteligentna krzywa obrotów, tryb ręczny, odczyty na żywo."""
from __future__ import annotations

import tkinter as tk

import customtkinter as ctk

from ... import fan as fanmod, hw, winsys
from .. import theme, widgets as w
from ..app import Page
from ..theme import c


class FanPage(Page):
    title = "Wentylatory"
    subtitle = "Inteligentna krzywa dopasowuje obroty do temperatury karty na bieżąco."

    def __init__(self, master, app):
        super().__init__(master, app)
        body = w.scroll_frame(self)
        body.pack(fill="both", expand=True)
        body.grid_columnconfigure(0, weight=1)
        self.body = body
        cfg = app.settings.get("fan") or {}
        self.mode = tk.StringVar(value=cfg.get("mode", "auto"))
        self.curve = tk.StringVar(value=cfg.get("curve", "balanced"))
        self.manual = tk.IntVar(value=int(cfg.get("manual", 60)))

        self.banner = w.card(body, border_color=theme.blend(c.card, c.warning, 0.6))
        self.banner_txt = w.label(self.banner, "", "small", c.text, wraplength=720)
        self.banner_txt.pack(fill="x", padx=20, pady=(12, 6))
        self.banner_btn = w.button(self.banner, "Uruchom jako administrator", self.elevate, "primary", height=32, width=210)

        # --- odczyty
        row = ctk.CTkFrame(body, fg_color="transparent", height=1)
        row.grid(row=1, column=0, sticky="ew", pady=(0, 12))
        for i in range(4):
            row.grid_columnconfigure(i, weight=1, uniform="g")
        self.t_temp = w.StatTile(row, "Temperatura GPU", bar_color=c.warning)
        self.t_fan = w.StatTile(row, "Wentylator", bar_color=c.accent2)
        self.t_load = w.StatTile(row, "Obciążenie GPU", bar_color=c.accent)
        self.t_pwr = w.StatTile(row, "Pobór mocy", bar_color=c.success)
        for i, t in enumerate((self.t_temp, self.t_fan, self.t_load, self.t_pwr)):
            t.grid(row=0, column=i, sticky="nsew", padx=(0 if i == 0 else 6, 0 if i == 3 else 6))
        self.sub = w.label(body, "", "small", c.muted)
        self.sub.grid(row=2, column=0, sticky="w", pady=(0, 10))

        # --- sterowanie
        mc = w.card(body)
        mc.grid(row=3, column=0, sticky="ew")
        w.label(mc, "Tryb pracy wentylatorów", "heading", c.text, "bold").pack(fill="x", padx=22, pady=(18, 6))
        modes = (("auto", "Automat karty", "Sterownik NVIDIA decyduje sam (ustawienie fabryczne)."),
                 ("smart", "Inteligentny", "Aplikacja co kilka sekund dobiera obroty do temperatury wg krzywej. Chłodniej niż fabrycznie, bez hałasu przy małym obciążeniu."),
                 ("manual", "Ręczny", "Stała prędkość, którą ustawisz suwakiem."))
        for val, name, desc in modes:
            r = ctk.CTkFrame(mc, fg_color="transparent", height=1)
            r.pack(fill="x", padx=22, pady=3)
            ctk.CTkRadioButton(r, text=name, variable=self.mode, value=val, command=self._changed, font=theme.font("body", "bold"),
                               text_color=c.text, fg_color=c.accent, hover_color=c.accent_hover, border_color=c.muted).pack(anchor="w")
            w.label(r, desc, "small", c.muted, wraplength=640).pack(fill="x", padx=28)
        crow = ctk.CTkFrame(mc, fg_color="transparent", height=1)
        crow.pack(fill="x", padx=22, pady=(12, 4))
        w.label(crow, "Krzywa:", "body", c.text).pack(side="left")
        names = {v["name"]: k for k, v in fanmod.CURVES.items()}
        self._curve_names = names
        self.curve_menu = w.option_menu(crow, list(names), command=lambda v: (self.curve.set(names[v]), self._changed()), width=190)
        self.curve_menu.set(fanmod.CURVES.get(self.curve.get(), fanmod.CURVES["balanced"])["name"])
        self.curve_menu.pack(side="left", padx=10)
        mrow = ctk.CTkFrame(mc, fg_color="transparent", height=1)
        mrow.pack(fill="x", padx=22, pady=(6, 4))
        w.label(mrow, "Ręcznie:", "body", c.text).pack(side="left")
        self.slider = ctk.CTkSlider(mrow, from_=fanmod.MIN_PERCENT, to=100, number_of_steps=100 - fanmod.MIN_PERCENT,
                                    variable=self.manual, command=lambda v: self.man_lbl.configure(text=f"{int(v)}%"),
                                    progress_color=c.accent, button_color=c.accent, button_hover_color=c.accent_hover, width=300)
        self.slider.pack(side="left", padx=12)
        self.man_lbl = w.label(mrow, f"{self.manual.get()}%", "body", c.text, "bold", width=50)
        self.man_lbl.pack(side="left")
        self.canvas = tk.Canvas(mc, height=190, bg=theme.blend(c.card, "#000000", 0.3), highlightthickness=0)
        self.canvas.pack(fill="x", padx=22, pady=(10, 6))
        self.canvas.bind("<Configure>", lambda e: self._draw_curve())
        self.status = w.label(mc, "", "small", c.muted, wraplength=700)
        self.status.pack(fill="x", padx=22, pady=(0, 6))
        w.button(mc, "Zastosuj", self.apply, "primary", height=40, width=160).pack(anchor="w", padx=22, pady=(4, 8))
        w.label(mc, "Bezpieczeństwo: minimum 30% obrotów, od 83°C zawsze 100%, brak odczytu temperatury = powrót do automatu. "
                    "Po zamknięciu aplikacji wentylatory wracają do automatu karty - krzywa działa tylko, gdy aplikacja jest uruchomiona "
                    "(może być zminimalizowana).", "small", c.muted, wraplength=700).pack(fill="x", padx=22, pady=(0, 18))
        self.after(1500, self._tick)

    # ------------------------------------------------------------------
    def on_show(self) -> None:
        nv = hw.nvml()
        msgs = []
        if not nv.available:
            msgs.append("Nie wykryto karty NVIDIA z dostępem do NVML - sterowanie wentylatorem karty działa tylko dla kart NVIDIA. " + (nv.error or ""))

            def done(names):
                if names:
                    self.banner_txt.configure(text=self.banner_txt.cget("text") + "\nKarty w tym komputerze: " + ", ".join(names)
                                              + ". Wentylatory procesora i obudowy oraz karty AMD/Intel nie mają publicznego API sterowania.")
            self.app.bg.run(hw.gpu_names_wmi, done)
        elif winsys.IS_WINDOWS and not winsys.is_admin():
            msgs.append("Zmiana obrotów wymaga uprawnień administratora. Odczyty działają bez nich.")
        if msgs:
            self.banner_txt.configure(text="  ".join(msgs))
            self.banner.grid(row=0, column=0, sticky="ew", pady=(0, 12))
            if nv.available:
                self.banner_btn.pack(anchor="w", padx=20, pady=(0, 12))
            else:
                self.banner_btn.pack_forget()
        else:
            self.banner.grid_forget()
        self._draw_curve()

    def elevate(self) -> None:
        import sys
        if winsys.relaunch_as_admin():
            self.app.destroy()
            sys.exit(0)

    def _changed(self) -> None:
        self._draw_curve()

    def _draw_curve(self) -> None:
        cv = self.canvas
        cv.delete("all")
        wd, ht = max(cv.winfo_width(), 300), int(cv.cget("height"))
        pad = 34
        mode = self.mode.get()
        grid = theme.blend(c.card, "#FFFFFF", 0.1)
        for pct in (30, 50, 70, 100):
            y = ht - pad - (pct - 20) / 80 * (ht - 2 * pad)
            cv.create_line(pad, y, wd - 10, y, fill=grid)
            cv.create_text(pad - 6, y, text=f"{pct}%", anchor="e", fill=c.muted, font=("Segoe UI", 8))
        tmin, tmax = 30, 90

        def xy(t, p):
            return pad + (t - tmin) / (tmax - tmin) * (wd - pad - 10), ht - pad - (p - 20) / 80 * (ht - 2 * pad)
        for t in (30, 40, 50, 60, 70, 80, 90):
            x, _ = xy(t, 0)
            cv.create_text(x, ht - pad + 12, text=f"{t}°", fill=c.muted, font=("Segoe UI", 8))
        pts = fanmod.CURVES.get(self.curve.get(), fanmod.CURVES["balanced"])["points"]
        if mode == "manual":
            line = [xy(tmin, self.manual.get()), xy(tmax, self.manual.get())]
        elif mode == "smart":
            line = [xy(max(tmin, min(tmax, t)), p) for t, p in [(tmin, max(fanmod.MIN_PERCENT, pts[0][1]))] + list(pts) + [(tmax, 100)]]
        else:
            line = []
        if len(line) >= 2:
            cv.create_line(*[v for p in line for v in p], fill=c.accent, width=3, smooth=False)
            for x, y in line[1:-1] if mode == "smart" else []:
                cv.create_oval(x - 3, y - 3, x + 3, y + 3, fill=c.accent, outline="")
        else:
            cv.create_text(wd / 2, ht / 2, text="Tryb automatyczny - krzywą prowadzi sterownik karty", fill=c.muted, font=("Segoe UI", 10))
        s = self.app.gpu_sample
        if s and s.temp is not None and s.fan is not None:
            x, y = xy(max(tmin, min(tmax, s.temp)), max(20, s.fan))
            cv.create_oval(x - 6, y - 6, x + 6, y + 6, fill=c.accent2, outline="#FFFFFF")

    def _tick(self) -> None:
        if self.app.current_page_id() == "fan":
            s = self.app.gpu_sample
            if s:
                t = s.temp or 0
                self.t_temp.set(f"{t:.0f}°C", s.name, t / 100, c.danger if t >= 83 else (c.warning if t >= 70 else c.success))
                self.t_fan.set(f"{(s.fan or 0):.0f}%", "tryb: " + {"auto": "automat", "smart": "inteligentny", "manual": "ręczny"}[self.app.fan.mode],
                               (s.fan or 0) / 100)
                self.t_load.set(f"{(s.util or 0):.0f}%", f"VRAM {((s.mem_used or 0) / 2**30):.1f} / {((s.mem_total or 0) / 2**30):.1f} GB", (s.util or 0) / 100)
                self.t_pwr.set(f"{(s.power_w or 0):.0f} W", f"limit {(s.power_limit_w or 0):.0f} W", (s.power_w or 0) / (s.power_limit_w or 1))
                self.sub.configure(text=f"Zegar rdzenia {s.core_mhz or '—'} MHz  •  zegar pamięci {s.mem_mhz or '—'} MHz  •  "
                                        f"wentylatorów: {s.fans}" + ("" if s.can_set_fan else "  •  sterowanie niedostępne na tej karcie"))
            elif not hw.nvml().available:
                self.t_temp.set("—", "brak NVML")
            self._draw_curve()
            if self.app.fan.last_msg and self.app.fan.mode == "auto" and self.mode.get() != "auto":
                self.status.configure(text=self.app.fan.last_msg, text_color=c.warning)
        self.after(2000, self._tick)

    def apply(self) -> None:
        mode, curve, manual = self.mode.get(), self.curve.get(), int(self.manual.get())
        if mode != "auto":
            if not hw.nvml().available:
                self.status.configure(text="Brak dostępu do NVML - nie da się sterować wentylatorem.", text_color=c.danger)
                return
            if winsys.IS_WINDOWS and not winsys.is_admin():
                self.status.configure(text="Wymagane uprawnienia administratora (baner u góry).", text_color=c.warning)
                return
        if mode == "manual" and manual < 50 and not w.confirm(self, "Niska prędkość wentylatora",
                                                             f"Stałe {manual}% przy obciążeniu może przegrzać kartę. Kontynuować?", "Ustaw"):
            return

        def work():
            ok, msg = self.app.fan.configure(mode, curve, manual)
            if ok and mode != "auto":
                s = hw.nvml().sample(0)
                self.app.fan.tick(s.temp if s else None)
            return ok, msg

        def done(res):
            ok, msg = res
            self.app.settings.set("fan", {"mode": mode if ok else "auto", "curve": curve, "manual": manual})
            if not ok:
                self.mode.set("auto")
            err = self.app.fan.last_msg if (ok and self.app.fan.mode == "auto" and mode != "auto") else ""
            if err:
                self.mode.set("auto")
            self.status.configure(text=err or msg, text_color=c.warning if (err or not ok) else c.success)
            self._draw_curve()

        self.app.bg.run(work, done)

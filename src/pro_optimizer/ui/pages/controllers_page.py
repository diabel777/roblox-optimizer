"""Pady i kierownice: ustawienia pada PS4/PS5 (kolor, wibracje, spusty, dźwięk) oraz profile kierownicy do Forzy."""
from __future__ import annotations

import threading
import tkinter as tk

import customtkinter as ctk

from ... import gamepad as gp, wheel as wh
from .. import theme, widgets as w
from ..app import Page
from ..theme import c


def gp_color(pct: int) -> str:
    r, g, b = gp.battery_color(pct)
    return "#%02X%02X%02X" % (r, g, b)


def _slider(parent, var, lo=0, hi=100, width=240):
    s = ctk.CTkSlider(parent, from_=lo, to=hi, number_of_steps=hi - lo, variable=var, width=width,
                      progress_color=c.accent, button_color=c.accent, button_hover_color=c.accent_hover)
    return s


class Orb(tk.Canvas):
    """Okrągły podgląd koloru paska (z poświatą). Odświeża się na żywo - bez zapisywania i bez pada."""

    def __init__(self, master, size=96):
        super().__init__(master, width=size, height=size, bg=c.card, highlightthickness=0)
        self.size = size

    def show(self, rgb) -> None:
        r, g, b = (max(0, min(255, int(x))) for x in rgb)
        self.delete("all")
        mid, s = self.size / 2, self.size
        bg = c.card
        for i in range(7, 0, -1):                      # poświata: koncentryczne kręgi mieszane z tłem
            k = 0.07 * (8 - i) if (r + g + b) else 0
            col = theme.blend(bg, "#%02X%02X%02X" % (r, g, b), min(1, k))
            pad = 2 + (7 - i) * 3
            self.create_oval(pad - 4, pad - 4, s - pad + 4, s - pad + 4, fill=col, outline="")
        inner = "#%02X%02X%02X" % (r, g, b)
        self.create_oval(mid - 24, mid - 24, mid + 24, mid + 24, fill=inner, outline=theme.blend(inner, "#FFFFFF", 0.35), width=2)


class ControllersPage(Page):
    title = "Pady i kierownice"
    subtitle = "Kolor, wibracje i dźwięk pada PS4/PS5 oraz realistyczne ustawienia kierownicy do Forza Horizon."

    def __init__(self, master, app):
        super().__init__(master, app)
        self.pads: list[gp.Pad] = []
        self.cfg = gp.sanitize(app.settings.get("pad"))
        self.tabs = ctk.CTkSegmentedButton(self, values=["Pad PS4 / PS5", "Kierownica (Forza)"], command=self._tab,
                                           font=theme.font("body", "bold"), selected_color=c.accent,
                                           selected_hover_color=c.accent_hover, unselected_color=c.card,
                                           unselected_hover_color=c.card_hover, text_color=c.text)
        self.tabs.set("Pad PS4 / PS5")
        self.tabs.pack(anchor="w", pady=(0, 8))
        self.pad_body = w.scroll_frame(self)
        self.wheel_body = w.scroll_frame(self)
        self.pad_body.pack(fill="both", expand=True)
        self._build_pad(self.pad_body)
        self._build_wheel(self.wheel_body)
        self.after(5000, self._poll_battery)

    def _tab(self, which: str) -> None:
        self.pad_body.pack_forget()
        self.wheel_body.pack_forget()
        (self.pad_body if which.startswith("Pad") else self.wheel_body).pack(fill="both", expand=True)

    def on_show(self) -> None:
        self.refresh_pads()

    # ================================================================== PAD
    def _build_pad(self, body) -> None:
        body.grid_columnconfigure(0, weight=1)
        top = w.card(body)
        top.pack(fill="x")
        w.label(top, "Podłączony pad", "heading", c.text, "bold").pack(fill="x", padx=22, pady=(18, 2))
        self.pad_msg = w.label(top, "Szukam padów…", "body", c.muted, wraplength=720)
        self.pad_msg.pack(fill="x", padx=22)
        strip = ctk.CTkFrame(top, fg_color=theme.blend(c.card, "#FFFFFF", 0.05), corner_radius=12)
        strip.pack(fill="x", padx=22, pady=(8, 2))
        self.st_conn = w.label(strip, "●  Brak pada", "body", c.muted, "bold")
        self.st_conn.pack(side="left", padx=14, pady=12)
        self.batt = w.label(strip, "", "body", c.text, "bold")
        self.batt.pack(side="right", padx=14)
        self.batt_bar = w.progress(strip, width=160)
        self.batt_bar.set(0)
        self.batt_bar.pack(side="right")
        self.pad_menu = w.option_menu(top, ["-"], width=320, command=lambda _v: self.update_battery())
        self.pad_menu.pack(anchor="w", padx=22, pady=(8, 4))
        r = ctk.CTkFrame(top, fg_color="transparent", height=1)
        r.pack(fill="x", padx=22, pady=(4, 16))
        w.button(r, "Odśwież listę", self.refresh_pads, "ghost", height=34, width=130).pack(side="left")
        w.label(top, "Ustawienia trafiają do pada oficjalnym kanałem HID - bez sterowników i bez ingerencji w gry, więc anty-cheaty "
                "ich nie widzą. Pad po odłączeniu wraca do ustawień fabrycznych.", "small", c.muted, wraplength=720
                ).pack(fill="x", padx=22, pady=(0, 14))

        # --- bateria i powiadomienia
        from ... import padbattery as pb
        al = pb.sanitize_alerts(self.app.settings.get("pad_alerts"))
        bc = w.card(body)
        bc.pack(fill="x", pady=(14, 0))
        w.label(bc, "Bateria i powiadomienia", "heading", c.text, "bold").pack(fill="x", padx=22, pady=(18, 2))
        self.est = w.label(bc, "Szacunek czasu pojawi się po kilku minutach pomiarów.", "body", c.muted)
        self.est.pack(fill="x", padx=22, pady=(0, 6))
        self.al_on = tk.BooleanVar(value=al["enabled"])
        self.al_full = tk.BooleanVar(value=al["full"])
        w.switch(bc, "Powiadamiaj o stanie baterii (też gdy okno jest zamknięte)", variable=self.al_on, command=self._save_alerts).pack(anchor="w", padx=22, pady=4)
        ar = ctk.CTkFrame(bc, fg_color="transparent")
        ar.pack(fill="x", padx=22, pady=2)
        w.label(ar, "Powiadom, gdy bateria spadnie o", "body", c.text).pack(side="left")
        self.al_drop = w.option_menu(ar, ["1%", "2%", "5%", "10%", "20%"], command=lambda _v: self._save_alerts(), width=90)
        self.al_drop.set(f"{al['drop']}%" if f"{al['drop']}%" in ("1%", "2%", "5%", "10%", "20%") else "5%")
        self.al_drop.pack(side="left", padx=8)
        w.label(ar, "i gdy zostanie mniej niż", "body", c.text).pack(side="left")
        self.al_low = w.option_menu(ar, ["wyłączone", "10%", "15%", "20%", "30%"], command=lambda _v: self._save_alerts(), width=110)
        self.al_low.set(f"{al['low']}%" if f"{al['low']}%" in ("10%", "15%", "20%", "30%") else ("wyłączone" if al["low"] == 0 else "15%"))
        self.al_low.pack(side="left", padx=8)
        w.switch(bc, "Powiadom, gdy pad jest naładowany", variable=self.al_full, command=self._save_alerts).pack(anchor="w", padx=22, pady=4)
        w.label(bc, "Czas pracy liczymy z tempa rozładowania w ostatnich minutach - im dłużej pad jest podłączony do aplikacji, tym dokładniejszy wynik.",
                "small", c.muted, wraplength=700).pack(fill="x", padx=22, pady=(2, 16))

        # --- kolor
        cc = w.card(body)
        cc.pack(fill="x", pady=(14, 0))
        w.label(cc, "Kolor paska świetlnego", "heading", c.text, "bold").pack(fill="x", padx=22, pady=(18, 6))
        pr = ctk.CTkFrame(cc, fg_color="transparent", height=1)
        pr.pack(fill="x", padx=22)
        for i, (name, rgb) in enumerate(gp.COLOR_PRESETS.items()):
            hexc = "#%02x%02x%02x" % rgb if any(rgb) else "#222222"
            ctk.CTkButton(pr, text="", width=34, height=34, corner_radius=17, fg_color=hexc, hover_color=hexc,
                          border_width=2, border_color=c.border,
                          command=lambda v=rgb: self._set_color(v)).grid(row=0, column=i, padx=3, pady=2)
        self.col = [tk.IntVar(value=v) for v in self.cfg["color"]]
        self.col2 = [tk.IntVar(value=v) for v in self.cfg["color2"]]
        self.bright = tk.IntVar(value=self.cfg["brightness"])
        self.speed = tk.IntVar(value=self.cfg["speed"])
        self.mode = tk.StringVar(value=self.cfg["mode"])
        mid = ctk.CTkFrame(cc, fg_color="transparent")
        mid.pack(fill="x", padx=22, pady=(6, 0))
        left = ctk.CTkFrame(mid, fg_color="transparent")
        left.pack(side="left", fill="x", expand=True)
        for lbl, var in zip(("R", "G", "B"), self.col):
            rr = ctk.CTkFrame(left, fg_color="transparent", height=1)
            rr.pack(fill="x", pady=2)
            w.label(rr, lbl, "body", c.text, "bold", width=24).pack(side="left")
            _slider(rr, var, 0, 255, 320).pack(side="left", padx=8)
        rr = ctk.CTkFrame(left, fg_color="transparent", height=1)
        rr.pack(fill="x", pady=2)
        w.label(rr, "Jasność", "body", c.text, "bold", width=60).pack(side="left")
        _slider(rr, self.bright, 0, 100, 290).pack(side="left", padx=8)
        self.orb = Orb(mid, 120)
        self.orb.pack(side="right", padx=(10, 6))
        w.label(cc, "Podgląd na żywo - widzisz kolor zanim cokolwiek zapiszesz.", "small", c.muted).pack(fill="x", padx=22)

        w.label(cc, "Animacja paska", "heading", c.text, "bold").pack(fill="x", padx=22, pady=(14, 4))
        self.modes = {v: k for k, v in gp.LIGHT_MODES.items()}
        mr = ctk.CTkFrame(cc, fg_color="transparent", height=1)
        mr.pack(fill="x", padx=22)
        mm = w.option_menu(mr, list(self.modes), command=lambda v: (self.mode.set(self.modes[v]), self._preview_reset()), width=280)
        mm.set(gp.LIGHT_MODES[self.mode.get()])
        mm.pack(side="left")
        sr = ctk.CTkFrame(cc, fg_color="transparent", height=1)
        sr.pack(fill="x", padx=22, pady=(6, 0))
        w.label(sr, "Szybkość", "body", c.text, "bold", width=80).pack(side="left")
        _slider(sr, self.speed, 1, 100, 280).pack(side="left", padx=8)
        for lbl, var in zip(("Kolor 2: R", "G", "B"), self.col2):
            r2 = ctk.CTkFrame(cc, fg_color="transparent", height=1)
            r2.pack(fill="x", padx=22, pady=1)
            w.label(r2, lbl, "small", c.muted, width=80).pack(side="left")
            _slider(r2, var, 0, 255, 220).pack(side="left", padx=8)
        w.label(cc, "„Przejście dwóch kolorów” używa koloru 1 i 2. „Kolor wg baterii”: czerwony → żółty → zielony, a przy niskim poziomie pad miga.",
                "small", c.muted, wraplength=700).pack(fill="x", padx=22, pady=(2, 16))
        for v in (*self.col, *self.col2, self.bright, self.speed):
            v.trace_add("write", lambda *_: self._preview_reset())
        self._t0 = __import__("time").time()
        self._batt_pct = None
        self.after(100, self._preview_tick)

        # --- wibracje i spusty
        vc = w.card(body)
        vc.pack(fill="x", pady=(14, 0))
        w.label(vc, "Wibracje i spusty adaptacyjne", "heading", c.text, "bold").pack(fill="x", padx=22, pady=(18, 6))
        self.auto_trig = tk.BooleanVar(value=self.cfg["auto_triggers"])
        w.switch(vc, "Automatyczna siła spustów zależnie od gry", variable=self.auto_trig).pack(anchor="w", padx=22, pady=(0, 2))
        self.auto_state = w.label(vc, "", "small", c.accent2)
        self.auto_state.pack(fill="x", padx=60, pady=(0, 6))
        w.label(vc, "Włączone: gdy uruchomisz grę wyścigową, lewy spust robi się jak hamulec, a prawy lekki jak gaz; w strzelankach prawy "
                "działa jak spust broni. Po wyjściu z gry wracają Twoje ustawienia. Tylko DualSense (PS5).", "small", c.muted,
                wraplength=700).pack(fill="x", padx=60, pady=(0, 8))
        self.rl = tk.IntVar(value=self.cfg["rumble_left"])
        self.rr = tk.IntVar(value=self.cfg["rumble_right"])
        for txt, var in (("Silnik lewy (mocny)", self.rl), ("Silnik prawy (delikatny)", self.rr)):
            rw = ctk.CTkFrame(vc, fg_color="transparent", height=1)
            rw.pack(fill="x", padx=22, pady=2)
            w.label(rw, txt, "body", c.text, width=190).pack(side="left")
            _slider(rw, var).pack(side="left", padx=8)
        w.button(vc, "Test wibracji", self.test_rumble, "ghost", height=32, width=140).pack(anchor="w", padx=22, pady=(6, 2))
        w.label(vc, "Siła wibracji w grach ustawia sama gra - tu możesz ją sprawdzić i przetestować pad.", "small", c.muted,
                wraplength=700).pack(fill="x", padx=22)
        self.tl = tk.StringVar(value=self.cfg["trigger_left"])
        self.tr = tk.StringVar(value=self.cfg["trigger_right"])
        self.tmodes = {v: k for k, v in gp.TRIGGER_MODES.items()}
        for txt, var in (("Spust lewy (L2)", self.tl), ("Spust prawy (R2)", self.tr)):
            rw = ctk.CTkFrame(vc, fg_color="transparent", height=1)
            rw.pack(fill="x", padx=22, pady=(8, 0))
            w.label(rw, txt, "body", c.text, width=190).pack(side="left")
            m = w.option_menu(rw, list(self.tmodes), command=lambda v, var=var: var.set(self.tmodes[v]), width=280)
            m.set(gp.TRIGGER_MODES[var.get()])
            m.pack(side="left", padx=8)
        self.tf = tk.IntVar(value=self.cfg["trigger_force"])
        self.ts = tk.IntVar(value=self.cfg["trigger_start"])
        for txt, var in (("Siła oporu", self.tf), ("Punkt początku oporu", self.ts)):
            rw = ctk.CTkFrame(vc, fg_color="transparent", height=1)
            rw.pack(fill="x", padx=22, pady=2)
            w.label(rw, txt, "body", c.text, width=190).pack(side="left")
            _slider(rw, var).pack(side="left", padx=8)
        w.label(vc, "Spusty adaptacyjne działają tylko w DualSense (PS5).", "small", c.muted).pack(fill="x", padx=22, pady=(4, 16))

        # --- dźwięk
        ac = w.card(body)
        ac.pack(fill="x", pady=(14, 0))
        w.label(ac, "Głośnik, słuchawki i mikrofon pada (DualSense)", "heading", c.text, "bold").pack(fill="x", padx=22, pady=(18, 6))
        self.hp = tk.IntVar(value=self.cfg["headphone"])
        self.sp = tk.IntVar(value=self.cfg["speaker"])
        self.mc = tk.IntVar(value=self.cfg["mic"])
        for txt, var in (("Słuchawki (gniazdo pada)", self.hp), ("Głośnik pada", self.sp), ("Mikrofon pada", self.mc)):
            rw = ctk.CTkFrame(ac, fg_color="transparent", height=1)
            rw.pack(fill="x", padx=22, pady=2)
            w.label(rw, txt, "body", c.text, width=190).pack(side="left")
            _slider(rw, var).pack(side="left", padx=8)
        self.led = tk.BooleanVar(value=self.cfg["mic_led"])
        self.keep = tk.BooleanVar(value=self.cfg["keep"])
        w.switch(ac, "Dioda wyciszenia mikrofonu świeci", variable=self.led).pack(anchor="w", padx=22, pady=(8, 16))

        kc = w.card(body)
        kc.pack(fill="x", pady=(14, 0))
        w.label(kc, "Automatyka", "heading", c.text, "bold").pack(fill="x", padx=22, pady=(18, 6))
        w.switch(kc, "Pilnuj koloru - przywracaj go, gdy coś go zmieni", variable=self.keep).pack(anchor="w", padx=22, pady=4)
        w.label(kc, "Pasek pada wraca do domyślnego po usypieniu Bluetooth albo gdy ustawi go inny program. Aplikacja odświeża kolor co kilka sekund, "
                "nie rusząc wibracji w grach ani głośności.", "small", c.muted, wraplength=700).pack(fill="x", padx=60)
        w.label(kc, "", "small", c.muted).pack(pady=(0, 6))

        bar = ctk.CTkFrame(body, fg_color="transparent", height=1)
        bar.pack(fill="x", pady=(14, 20))
        w.button(bar, "Zastosuj do pada", self.apply_pad, "primary", height=40, width=190).pack(side="left")
        w.button(bar, "Przywróć domyślne", self.reset_pad, "ghost", height=40, width=170).pack(side="left", padx=8)
        w.label(bar, "Przemapowania przycisków tu nie ma celowo - wymaga sterownika wirtualnego, który psuje się z anty-cheatami.",
                "small", c.muted, wraplength=420).pack(side="left", padx=10)

    def _preview_reset(self) -> None:
        self._t0 = __import__("time").time()

    def _preview_tick(self) -> None:
        """Podgląd koloru na żywo (także animacji) - działa tylko, gdy strona jest widoczna."""
        try:
            if self.app.current_page_id() == "controllers":
                cfg = {"mode": self.mode.get(), "speed": self.speed.get(), "color": [v.get() for v in self.col],
                       "color2": [v.get() for v in self.col2]}
                rgb = gp.frame_color(cfg, __import__("time").time() - self._t0, self._batt_pct)
                k = self.bright.get() / 100
                self.orb.show([x * k for x in rgb])
        except Exception:
            pass
        self.after(60, self._preview_tick)

    def _set_color(self, rgb) -> None:
        for v, x in zip(self.col, rgb):
            v.set(int(x))

    def _collect(self) -> dict:
        cfg = {
            "color": [v.get() for v in self.col], "brightness": self.bright.get(),
            "rumble_left": self.rl.get(), "rumble_right": self.rr.get(),
            "trigger_left": self.tl.get(), "trigger_right": self.tr.get(),
            "trigger_force": self.tf.get(), "trigger_start": self.ts.get(),
            "headphone": self.hp.get(), "speaker": self.sp.get(), "mic": self.mc.get(), "mic_led": self.led.get(),
            "keep": self.keep.get(), "auto_triggers": self.auto_trig.get(),
            "mode": self.mode.get(), "speed": self.speed.get(), "color2": [v.get() for v in self.col2],
        }
        return gp.sanitize(cfg)

    def refresh_pads(self) -> None:
        if not gp.available():
            self.pad_msg.configure(text="Obsługa padów nie jest dostępna w tej wersji (brak biblioteki HID).")
            return
        self.pads = gp.detect()
        if not self.pads:
            self.pad_msg.configure(text="Nie znaleziono pada PS4/PS5. Podłącz go kablem USB lub przez Bluetooth i kliknij „Odśwież listę”.")
            self.pad_menu.configure(values=["-"])
            self.pad_menu.set("-")
            self.batt.configure(text="")
            self.batt_bar.set(0)
            self.st_conn.configure(text="●  Brak pada", text_color=c.muted)
            return
        names = [f"{p.name} ({'Bluetooth' if p.bluetooth else 'USB'})" for p in self.pads]
        self.pad_menu.configure(values=names)
        self.pad_menu.set(names[0])
        self.pad_msg.configure(text=f"Znaleziono: {len(self.pads)}")
        p0 = self.pads[0]
        self.st_conn.configure(text=f"●  {p0.name}  •  {'Bluetooth' if p0.bluetooth else 'USB'}", text_color=c.success)
        self.update_battery()

    def update_battery(self) -> None:
        pad = self._current_quiet()
        if not pad:
            self.batt.configure(text="")
            return

        def work():
            return gp.battery(pad)

        def done(b):
            if not b:
                self.batt.configure(text="Bateria: brak odczytu (podłącz kablem lub poczekaj chwilę)", text_color=c.muted)
                return
            state = {"charging": "ładowanie", "full": "naładowany", "discharging": "rozładowuje się"}[b["state"]]
            col = c.danger if b["percent"] <= 15 and b["state"] == "discharging" else (c.success if b["state"] != "discharging" else c.text)
            self.batt.configure(text=f"{b['percent']}%  ({state})", text_color=col)
            self._batt_pct = b["percent"]
            self.batt_bar.configure(progress_color=col if col != c.text else gp_color(b["percent"]))
            self.batt_bar.set(b["percent"] / 100)
        self.app.bg.run(work, done)

    def _save_alerts(self) -> None:
        low = self.al_low.get()
        self.app.settings.set("pad_alerts", {
            "enabled": self.al_on.get(), "full": self.al_full.get(),
            "drop": int(self.al_drop.get().rstrip("%")), "low": 0 if low == "wyłączone" else int(low.rstrip("%"))})

    def _refresh_status(self) -> None:
        from ... import padbattery as pb
        watch = getattr(self.app, "pad_watch", None)
        if watch:
            self.est.configure(text=pb.describe(watch.tracker), text_color=c.text if watch.tracker.minutes_left() else c.muted)
        keeper = getattr(self.app, "pad_keeper", None)
        try:
            ov = gp.trigger_overrides(keeper._get_games()) if keeper else {}
        except Exception:
            ov = {}
        if not self.auto_trig.get():
            txt = "Automatyka wyłączona - spusty mają Twoje ręczne ustawienia."
        elif ov:
            txt = "● Wykryto grę - spusty ustawione automatycznie (" + ("wyścigi" if ov.get("trigger_right") == "rigid" else "strzelanka") + ")."
        else:
            txt = "Czekam na grę - żadna znana gra nie jest teraz uruchomiona."
        self.auto_state.configure(text=txt)

    def _poll_battery(self) -> None:
        self._refresh_status()
        self._tick = getattr(self, "_tick", 0) + 1
        if self._tick % 4 == 0 and self.app.current_page_id() == "controllers" and self.pads and not self.app.settings.get("_pad_busy"):
            self.update_battery()
        self.after(5000, self._poll_battery)

    def _current_quiet(self):
        if not self.pads:
            return None
        try:
            idx = list(self.pad_menu.cget("values")).index(self.pad_menu.get())
        except ValueError:
            idx = 0
        return self.pads[min(idx, len(self.pads) - 1)]

    def _current(self):
        if not self.pads:
            self.refresh_pads()
        if not self.pads:
            self.app.toast.show("Nie znaleziono pada.", "warn")
            return None
        try:
            idx = list(self.pad_menu.cget("values")).index(self.pad_menu.get())
        except ValueError:
            idx = 0
        return self.pads[min(idx, len(self.pads) - 1)]

    def apply_pad(self) -> None:
        pad = self._current()
        if not pad:
            return
        cfg = self._collect()
        self.app.settings.set("pad", cfg)
        if not getattr(self.app, "pad_keeper", None):
            self.app._start_pad_keeper()
        ok, msg = gp.apply(pad, cfg)
        self.app.toast.show(msg, "ok" if ok else "err")

    def test_rumble(self) -> None:
        pad = self._current()
        if not pad:
            return
        cfg = self._collect()
        if not cfg["rumble_left"] and not cfg["rumble_right"]:
            cfg["rumble_left"] = cfg["rumble_right"] = 100          # test przy zerowych suwakach nic by nie pokazał

        def run():
            ok, msg = gp.pulse(pad, cfg)
            self.after(0, lambda: self.app.toast.show("Test wibracji wykonany." if ok else msg, "ok" if ok else "err"))
        threading.Thread(target=run, daemon=True).start()

    def reset_pad(self) -> None:
        d = gp.sanitize(None)
        self._set_color(d["color"])
        for var, k in ((self.bright, "brightness"), (self.rl, "rumble_left"), (self.rr, "rumble_right"), (self.tf, "trigger_force"),
                       (self.ts, "trigger_start"), (self.hp, "headphone"), (self.sp, "speaker"), (self.mc, "mic")):
            var.set(d[k])
        self.tl.set("off")
        self.tr.set("off")
        self.led.set(False)
        self.app.toast.show("Przywrócono wartości domyślne (kliknij „Zastosuj do pada”).", "info")

    # ================================================================== KIEROWNICA
    def _build_wheel(self, body) -> None:
        cfg = self.app.settings.get("wheel") or {}
        self.w_brand = tk.StringVar(value=cfg.get("brand", "g29") if cfg.get("brand") in wh.BRANDS else "g29")
        self.w_game = tk.StringVar(value=cfg.get("game", "fh5") if cfg.get("game") in wh.GAMES else "fh5")
        self.w_style = tk.StringVar(value=cfg.get("style", "real") if cfg.get("style") in wh.STYLES else "real")
        sc = w.card(body)
        sc.pack(fill="x")
        w.label(sc, "Realistyczna kierownica w Forza Horizon", "heading", c.text, "bold").pack(fill="x", padx=22, pady=(18, 2))
        w.label(sc, "Forza nie pozwala bezpiecznie zmieniać ustawień z zewnątrz, więc dostajesz gotową ściągę wartości do wpisania "
                "w sterowniku kierownicy i w menu gry.", "small", c.muted, wraplength=720).pack(fill="x", padx=22)
        self.bmap = {v["name"]: k for k, v in wh.BRANDS.items()}
        self.gmap = {v: k for k, v in wh.GAMES.items()}
        self.smap = {v[0]: k for k, v in wh.STYLES.items()}
        for txt, var, mp, src in (("Kierownica", self.w_brand, self.bmap, {k: v["name"] for k, v in wh.BRANDS.items()}),
                                  ("Gra", self.w_game, self.gmap, wh.GAMES),
                                  ("Styl jazdy", self.w_style, self.smap, {k: v[0] for k, v in wh.STYLES.items()})):
            rw = ctk.CTkFrame(sc, fg_color="transparent", height=1)
            rw.pack(fill="x", padx=22, pady=4)
            w.label(rw, txt, "body", c.text, "bold", width=110).pack(side="left")
            m = w.option_menu(rw, list(mp), command=lambda v, var=var, mp=mp: (var.set(mp[v]), self._show_wheel()), width=320)
            m.set(src[var.get()])
            m.pack(side="left", padx=8)
        self.style_desc = w.label(sc, "", "small", c.muted, wraplength=700)
        self.style_desc.pack(fill="x", padx=22, pady=(4, 16))

        self.out = w.card(body)
        self.out.pack(fill="x", pady=(14, 0))
        self.wheel_inner = ctk.CTkFrame(self.out, fg_color="transparent")
        self.wheel_inner.pack(fill="x", padx=22, pady=16)
        bar = ctk.CTkFrame(body, fg_color="transparent", height=1)
        bar.pack(fill="x", pady=(14, 20))
        w.button(bar, "Kopiuj do schowka", self.copy_wheel, "primary", height=38, width=170).pack(side="left")
        w.button(bar, "Zapisz jako plik", self.save_wheel, "ghost", height=38, width=150).pack(side="left", padx=8)
        w.button(bar, "Kalibracja kontrolerów Windows", self.open_joy, "ghost", height=38, width=240).pack(side="left")
        self._show_wheel()

    def _profile(self) -> dict:
        return wh.profile(self.w_brand.get(), self.w_game.get(), self.w_style.get())

    def _show_wheel(self) -> None:
        self.app.settings.set("wheel", {"brand": self.w_brand.get(), "game": self.w_game.get(), "style": self.w_style.get()})
        p = self._profile()
        self.style_desc.configure(text=wh.STYLES[self.w_style.get()][1])
        for ch in self.wheel_inner.winfo_children():
            ch.destroy()
        w.label(self.wheel_inner, "Sterownik kierownicy", "heading", c.text, "bold").pack(fill="x", pady=(0, 4))
        for k, v in p["driver"]:
            w.label(self.wheel_inner, f"{k}: {v}", "body", c.text).pack(fill="x")
        w.label(self.wheel_inner, "Ustawienia w grze", "heading", c.text, "bold").pack(fill="x", pady=(12, 4))
        for name, val, desc in p["game_rows"]:
            rw = ctk.CTkFrame(self.wheel_inner, fg_color="transparent")
            rw.pack(fill="x", pady=2)
            w.badge(rw, str(val), c.accent).pack(side="right")
            w.label(rw, name, "body", c.text, "bold").pack(fill="x")
            w.label(rw, desc, "small", c.muted, wraplength=620).pack(fill="x")
        w.label(self.wheel_inner, "Wskazówki", "heading", c.text, "bold").pack(fill="x", pady=(12, 4))
        for n in p["notes"]:
            w.label(self.wheel_inner, "• " + n, "small", c.muted, wraplength=700).pack(fill="x", pady=1)

    def copy_wheel(self) -> None:
        self.clipboard_clear()
        self.clipboard_append(wh.to_text(self._profile()))
        self.app.toast.show("Skopiowano ustawienia do schowka.", "ok")

    def save_wheel(self) -> None:
        from tkinter import filedialog
        path = filedialog.asksaveasfilename(parent=self, defaultextension=".txt", initialfile="ustawienia-kierownicy.txt",
                                            filetypes=[("Tekst", "*.txt")])
        if path:
            with open(path, "w", encoding="utf-8") as f:
                f.write(wh.to_text(self._profile()))
            self.app.toast.show("Zapisano plik.", "ok")

    def open_joy(self) -> None:
        import os
        import subprocess
        if os.name == "nt":
            from ...ps import system_exe
            subprocess.Popen([system_exe("control"), "joy.cpl"], creationflags=0x08000000)

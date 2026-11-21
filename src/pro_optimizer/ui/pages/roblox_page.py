"""Roblox i Studio: profile FastFlag, limit FPS, automatyczne przywracanie po aktualizacji Robloxa."""
from __future__ import annotations

import json
import tkinter as tk

import customtkinter as ctk

from ... import backups, cleaner, roblox
from .. import theme, widgets as w
from ..app import Page
from ..theme import c, font


class RobloxPage(Page):
    title = "Roblox i Studio"
    subtitle = "Profile grafiki i FPS dla Roblox Player oraz Roblox Studio."

    def __init__(self, master, app, embedded: bool = False):
        super().__init__(master, app)
        s = app.settings
        prof = s.get("roblox_profile")
        self.sel = tk.StringVar(value=prof.get("preset", "balanced"))
        self.v_player = tk.BooleanVar(value="player" in prof.get("targets", []))
        self.v_studio = tk.BooleanVar(value="studio" in prof.get("targets", []))
        self.v_merge = tk.BooleanVar(value=prof.get("merge", True))
        self.v_auto = tk.BooleanVar(value=bool(s.get("auto_reapply_roblox")))
        self.installs = roblox.find_installs()

        body = ctk.CTkFrame(self, fg_color="transparent") if embedded else w.scroll_frame(self)
        body.pack(fill="both", expand=True)
        body.grid_columnconfigure(0, weight=1)

        # --- status instalacji
        st = ctk.CTkFrame(body, fg_color="transparent")
        st.grid(row=0, column=0, sticky="ew")
        st.grid_columnconfigure((0, 1), weight=1, uniform="s")
        self.status = {}
        for i, (kind, name) in enumerate((("player", "Roblox Player"), ("studio", "Roblox Studio"))):
            cd = w.card(st)
            cd.grid(row=0, column=i, sticky="nsew", padx=(0 if i == 0 else 8, 8 if i == 0 else 0))
            w.label(cd, name, "heading", c.text, "bold").pack(fill="x", padx=20, pady=(16, 2))
            lbl = w.label(cd, "", "small", c.muted)
            lbl.pack(fill="x", padx=20, pady=(0, 16))
            self.status[kind] = lbl

        # --- profile
        pc = w.card(body)
        pc.grid(row=1, column=0, sticky="ew", pady=(14, 0))
        w.label(pc, "Profil graficzny", "heading", c.text, "bold").pack(fill="x", padx=22, pady=(18, 8))
        self.preset_cards = {}
        for p in app.presets:
            box = ctk.CTkFrame(pc, corner_radius=12, border_width=2, border_color=c.border,
                               fg_color=theme.blend(c.card, "#000000", 0.2))
            box.pack(fill="x", padx=22, pady=5)
            top = ctk.CTkFrame(box, fg_color="transparent")
            top.pack(fill="x", padx=14, pady=(10, 0))
            ctk.CTkRadioButton(top, text=p["name"], variable=self.sel, value=p["id"], command=self._refresh,
                               font=font("body", "bold"), text_color=c.text, fg_color=c.accent,
                               hover_color=c.accent_hover, border_color=c.muted).pack(side="left")
            if p.get("experimental"):
                w.badge(top, "eksperymentalny", c.warning).pack(side="left", padx=10)
            w.label(box, p.get("description", ""), "small", c.muted, wraplength=520).pack(fill="x", padx=44, pady=(2, 10))
            self.preset_cards[p["id"]] = box

        # --- opcje
        oc = w.card(body)
        oc.grid(row=2, column=0, sticky="ew", pady=(14, 0))
        w.label(oc, "Opcje", "heading", c.text, "bold").pack(fill="x", padx=22, pady=(18, 8))
        row = ctk.CTkFrame(oc, fg_color="transparent")
        row.pack(fill="x", padx=22, pady=(0, 6))
        w.label(row, "Limit FPS (0 = bez zmian):", "body", c.text).pack(side="left")
        self.fps = w.entry(row, width=90, justify="center")
        self.fps.insert(0, str(prof.get("fps", 0)))
        self.fps.pack(side="left", padx=12)
        self.fps.bind("<KeyRelease>", lambda e: self._refresh())
        w.label(oc, "Roblox może ignorować tę flagę - zależy od wersji klienta.", "small", c.muted).pack(fill="x", padx=22)

        trow = ctk.CTkFrame(oc, fg_color="transparent")
        trow.pack(fill="x", padx=22, pady=6)
        w.label(trow, "Zastosuj dla:", "body", c.text).pack(side="left", padx=(0, 14))
        w.checkbox(trow, "Roblox Player", self.v_player, self._refresh).pack(side="left", padx=(0, 18))
        w.checkbox(trow, "Roblox Studio", self.v_studio, self._refresh).pack(side="left")
        w.switch(oc, "Zachowaj moje dotychczasowe flagi (scal z profilem)", variable=self.v_merge,
                 command=self._refresh).pack(anchor="w", padx=22, pady=(10, 4))
        w.switch(oc, "Automatycznie przywracaj profil po aktualizacji Robloxa", variable=self.v_auto,
                 command=lambda: app.settings.set("auto_reapply_roblox", self.v_auto.get())).pack(anchor="w", padx=22, pady=(4, 6))
        self.warn = w.label(oc, "", "small", c.warning, wraplength=540)
        self.warn.pack(fill="x", padx=22, pady=(4, 16))

        # --- podgląd
        vc = w.card(body)
        vc.grid(row=3, column=0, sticky="ew", pady=(14, 0))
        w.label(vc, "Podgląd pliku ClientAppSettings.json", "heading", c.text, "bold").pack(fill="x", padx=22, pady=(18, 8))
        self.preview = ctk.CTkTextbox(vc, height=150, corner_radius=10, fg_color=theme.blend(c.card, "#000000", 0.35),
                                      text_color=c.accent2, font=ctk.CTkFont(family="Consolas", size=12), wrap="none")
        self.preview.pack(fill="x", padx=22, pady=(0, 18))

        # --- przyciski
        br = ctk.CTkFrame(body, fg_color="transparent")
        br.grid(row=4, column=0, sticky="ew", pady=(14, 20))
        w.button(br, "Zastosuj profil", self.apply, "primary", height=44).pack(side="left", padx=(0, 8))
        w.button(br, "Utwórz kopię zapasową", self.backup_now, "ghost", height=44).pack(side="left", padx=8)
        w.button(br, "Resetuj ustawienia Robloxa", self.reset, "danger", height=44).pack(side="right")

        self._refresh()

    # ------------------------------------------------------------------ logika
    def on_show(self) -> None:
        self.installs = roblox.find_installs()
        self._refresh()

    def _selected_preset(self) -> dict:
        return next((p for p in self.app.presets if p["id"] == self.sel.get()), self.app.presets[0])

    def _fps(self) -> int:
        t = self.fps.get().strip()
        return int(t) if t.isdigit() else 0

    def _targets(self) -> list[str]:
        return [k for k, v in (("player", self.v_player.get()), ("studio", self.v_studio.get())) if v]

    def _refresh(self) -> None:
        for kind, lbl in self.status.items():
            inst = self.installs.get(kind)
            lbl.configure(text=(f"Wykryto  •  {inst.version}" if inst else "Nie wykryto - uruchom program raz, aby go wykryć"),
                          text_color=c.success if inst else c.warning)
        sel = self.sel.get()
        for pid, box in self.preset_cards.items():
            box.configure(border_color=c.accent if pid == sel else c.border)
        preset = self._selected_preset()
        targets = self._targets() or ["player"]
        first = targets[0]
        inst = self.installs.get(first)
        existing = roblox.read_flags(inst) if inst else {}
        flags = roblox.build_flags(preset["flags"], self._fps(), existing, self.v_merge.get())
        self.preview.configure(state="normal")
        self.preview.delete("1.0", "end")
        self.preview.insert("1.0", json.dumps(flags, indent=2))
        self.preview.configure(state="disabled")
        warn = []
        mine = {**preset["flags"], **({roblox.FPS_FLAG: 1} if self._fps() else {})}
        if "player" in self._targets():
            ign = roblox.ignored_by_player(mine)
            if ign:
                warn.append(f"Roblox Player stosuje allowlistę flag - {len(ign)} z nich może być ignorowanych: "
                            + ", ".join(ign[:4]) + ("…" if len(ign) > 4 else "") + ".")
        if not self._targets():
            warn.append("Zaznacz Roblox Player i/lub Roblox Studio.")
        self.warn.configure(text="  ".join(warn))

    def apply(self) -> None:
        targets = self._targets()
        if not targets:
            self.app.toast.show("Zaznacz Roblox Player i/lub Roblox Studio.", "warn")
            return
        preset = self._selected_preset()
        fps = self._fps()
        merge = self.v_merge.get()
        keep = int(self.app.settings.get("max_backups", 30))
        self.installs = roblox.find_installs()

        def work():
            done, missing, running = [], [], cleaner.running_processes()
            for kind in targets:
                inst = self.installs.get(kind)
                if not inst:
                    missing.append(kind)
                    continue
                flags = roblox.build_flags(preset["flags"], fps, roblox.read_flags(inst), merge)
                roblox.apply_flags(inst, flags, keep)
                done.append(kind)
            return done, missing, {n for n in ("robloxplayerbeta.exe", "robloxstudiobeta.exe") if n in running}

        def ok(res):
            done, missing, running = res
            self.app.settings.set("roblox_profile", {"preset": preset["id"], "fps": fps, "targets": targets, "merge": merge})
            if done:
                self.app.settings.set("roblox_applied", True)
            if done:
                msg = f"Zapisano profil „{preset['name']}” ({', '.join(done)})."
                if running:
                    msg += " Zrestartuj Robloxa/Studio, aby zmiany zadziałały."
                self.app.toast.show(msg + (f"\nNie wykryto: {', '.join(missing)}." if missing else ""), "ok", 6000)
            else:
                self.app.toast.show("Nie wykryto Robloxa ani Studio - uruchom je raz i spróbuj ponownie.", "warn", 6000)
            self._refresh()

        self.app.bg.run(work, ok, lambda e: self.app.toast.show(f"Nie udało się zapisać: {e}", "err", 7000))

    def backup_now(self) -> None:
        n = 0
        for kind in self._targets() or ["player", "studio"]:
            inst = self.installs.get(kind)
            if inst and roblox.manual_backup(inst):
                n += 1
        self.app.toast.show(f"Utworzono kopii: {n}." if n else "Brak aktywnych plików ustawień do skopiowania.",
                            "ok" if n else "warn")
        pg = self.app.page("backups")
        if pg and hasattr(pg, "reload"):
            pg.reload()

    def reset(self) -> None:
        if not w.confirm(self, "Reset ustawień Robloxa",
                         "Usunąć plik ClientAppSettings.json dla Playera i Studio?\n"
                         "Przed usunięciem powstanie kopia zapasowa. Zapisany profil przestanie być przywracany automatycznie.",
                         "Resetuj", danger=True):
            return
        n = 0
        for kind in ("player", "studio"):
            inst = self.installs.get(kind)
            if inst and roblox.reset(inst):
                n += 1
        prof = dict(self.app.settings.get("roblox_profile"))
        prof["targets"] = []
        self.app.settings.set("roblox_profile", prof)
        self.v_player.set(False)
        self.v_studio.set(False)
        self.app.toast.show(f"Zresetowano ustawienia Robloxa (usunięto plików: {n}).", "ok")
        self._refresh()

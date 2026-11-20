"""Panel główny: statystyki na żywo, wykryte aplikacje i szybka optymalizacja."""
from __future__ import annotations

import customtkinter as ctk

from ... import cleaner, roblox, winsys
from ...cleaner import fmt_bytes
from .. import theme, widgets as w
from ..app import Page
from ..theme import c


class DashboardPage(Page):
    title = "Panel główny"
    subtitle = "Podgląd komputera na żywo i optymalizacja jednym kliknięciem."

    def __init__(self, master, app):
        super().__init__(master, app)
        self.cpu = winsys.CpuMeter()
        self.grid_columnconfigure(0, weight=1)

        row = ctk.CTkFrame(self, fg_color="transparent")
        row.grid(row=0, column=0, sticky="ew")
        for i in range(4):
            row.grid_columnconfigure(i, weight=1, uniform="tiles")
        self.t_ram = w.StatTile(row, "Pamięć RAM", bar_color=c.accent)
        self.t_cpu = w.StatTile(row, "Procesor", bar_color=c.accent2)
        self.t_disk = w.StatTile(row, "Dysk systemowy", bar_color=c.success)
        self.t_cache = w.StatTile(row, "Cache do odzyskania", with_bar=False)
        for i, t in enumerate((self.t_ram, self.t_cpu, self.t_disk, self.t_cache)):
            t.grid(row=0, column=i, sticky="nsew", padx=(0 if i == 0 else 8, 0 if i == 3 else 8))

        bottom = ctk.CTkFrame(self, fg_color="transparent")
        bottom.grid(row=1, column=0, sticky="nsew", pady=(16, 0))
        self.grid_rowconfigure(1, weight=1)
        bottom.grid_columnconfigure(0, weight=3, uniform="b")
        bottom.grid_columnconfigure(1, weight=2, uniform="b")
        bottom.grid_rowconfigure(0, weight=1)

        # --- szybka optymalizacja
        q = w.card(bottom)
        q.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        w.label(q, "Szybka optymalizacja", "heading", c.text, "bold").pack(fill="x", padx=22, pady=(20, 4))
        w.label(q, "Czyści cache zaznaczonych domyślnie aplikacji (Roblox, Discord, Opera, przeglądarki, launchery…) "
                   "i zwalnia pamięć RAM. Uruchomione aplikacje są pomijane - nic nie zostanie przerwane.",
                "body", c.muted, wraplength=400).pack(fill="x", padx=22)
        self.q_btn = w.button(q, "⚡  Optymalizuj teraz", self.quick, "primary", height=48)
        self.q_btn.pack(fill="x", padx=22, pady=(18, 10))
        self.q_bar = w.progress(q)
        self.q_bar.set(0)
        self.q_bar.pack(fill="x", padx=22)
        self.q_res = w.label(q, "Gotowe do działania.", "body", c.muted, wraplength=400)
        self.q_res.pack(fill="x", padx=22, pady=(10, 0))
        w.divider(q).pack(fill="x", padx=22, pady=18)
        links = ctk.CTkFrame(q, fg_color="transparent")
        links.pack(fill="x", padx=22, pady=(0, 20))
        for txt, pid in (("Ustaw profil Robloxa", "roblox"), ("Wybierz aplikacje do czyszczenia", "cleaner")):
            w.button(links, txt, lambda p=pid: app.show_page(p), "ghost", height=34).pack(side="left", padx=(0, 8))

        # --- wykryte aplikacje
        d = w.card(bottom)
        d.grid(row=0, column=1, sticky="nsew", padx=(8, 0))
        w.label(d, "Wykryte na tym komputerze", "heading", c.text, "bold").pack(fill="x", padx=22, pady=(20, 8))
        self.detect = ctk.CTkFrame(d, fg_color="transparent")
        self.detect.pack(fill="both", expand=True, padx=22, pady=(0, 16))

        self._scanned = False
        self.after(300, self._tick)

    # ------------------------------------------------------------------ odświeżanie
    def on_show(self) -> None:
        self._refresh_detected()
        if not self._scanned:
            self._scanned = True
            self._scan_cache()

    def _tick(self) -> None:
        if self.app.current_page_id() == "dashboard":
            mem = winsys.memory_status()
            if mem:
                total, avail = mem
                used = total - avail
                self.t_ram.set(f"{used / total * 100:.0f}%", f"{fmt_bytes(used)} z {fmt_bytes(total)}", used / total,
                               c.danger if used / total > 0.9 else (c.warning if used / total > 0.75 else c.accent))
            cpu = self.cpu.sample()
            if cpu is not None:
                self.t_cpu.set(f"{cpu:.0f}%", "Obciążenie całkowite", cpu / 100,
                               c.danger if cpu > 90 else (c.warning if cpu > 70 else c.accent2))
            disk = winsys.disk_free()
            if disk:
                total, free = disk
                self.t_disk.set(fmt_bytes(free), f"wolne z {fmt_bytes(total)}", (total - free) / total,
                                c.danger if free / total < 0.1 else c.success)
        self.after(1500, self._tick)

    def _scan_cache(self) -> None:
        entries = [e for e in self.app.catalog if e.get("default")]
        self.t_cache.set("…", "skanowanie")

        def done(res):
            ready = [r for r in res if not r.blocked_by and r.size]
            held = sum(r.size for r in res if r.blocked_by)
            sub = f"w {len(ready)} aplikacjach"
            if held:
                sub += f"  (+{fmt_bytes(held)} w uruchomionych)"
            self.t_cache.set(fmt_bytes(sum(r.size for r in ready)), sub)

        self.app.bg.run(lambda: cleaner.scan(entries), done, lambda e: self.t_cache.set("—", "błąd skanowania"))

    def _refresh_detected(self) -> None:
        def work():
            return roblox.find_installs(), cleaner.running_processes()

        def done(res):
            installs, running = res
            for ch in self.detect.winfo_children():
                ch.destroy()
            rows = []
            for kind, name in (("player", "Roblox Player"), ("studio", "Roblox Studio")):
                inst = installs.get(kind)
                rows.append((name, ("Wykryty • " + inst.version[-8:]) if inst else "Nie wykryto", bool(inst)))
            live = [e["name"].split(" – ")[0] for e in self.app.catalog if cleaner.blocking(e, running)]
            for n in dict.fromkeys(live):
                rows.append((n, "Uruchomiony teraz", True))
            for name, state, ok in rows[:9]:
                line = ctk.CTkFrame(self.detect, fg_color="transparent")
                line.pack(fill="x", pady=4)
                ctk.CTkLabel(line, text="●", width=16, text_color=c.success if ok else c.muted).pack(side="left")
                w.label(line, name, "body", c.text, "bold").pack(side="left", padx=(4, 0))
                w.label(line, state, "small", c.muted, anchor="e").pack(side="right")

        self.app.bg.run(work, done)

    # ------------------------------------------------------------------ szybka optymalizacja
    def quick(self) -> None:
        entries = [e for e in self.app.catalog if e.get("default")]
        if not w.confirm(self, "Szybka optymalizacja",
                         f"Wyczyścić cache {len(entries)} aplikacji i zwolnić pamięć RAM?\n"
                         "Aplikacje, które są teraz uruchomione, zostaną pominięte.", "Optymalizuj"):
            return
        self.q_btn.configure(state="disabled")
        self.q_res.configure(text="Czyszczenie…", text_color=c.muted)
        self.q_bar.set(0)

        def work():
            def prog(i, n, r):
                self.app.bg.call(self.q_bar.set, i / n * 0.9)
            res = cleaner.clean(entries, progress=prog)
            ram = winsys.trim_ram()
            return res, ram

        def done(out):
            res, ram = out
            freed = sum(r.size for r in res)
            skipped = [r.name.split(" – ")[0] for r in res if r.error]
            msg = f"Zwolniono {fmt_bytes(freed)} z dysku"
            if ram.get("ok"):
                msg += f" i {fmt_bytes(ram.get('freed', 0))} pamięci RAM"
            msg += "."
            if skipped:
                msg += f"\nPominięto (uruchomione): {', '.join(dict.fromkeys(skipped))}."
            self.q_bar.set(1)
            self.q_res.configure(text=msg, text_color=c.success)
            self.q_btn.configure(state="normal")
            self.app.toast.show(f"Gotowe - zwolniono {fmt_bytes(freed)}.", "ok")
            self._scan_cache()

        def fail(e):
            self.q_btn.configure(state="normal")
            self.q_res.configure(text=f"Błąd: {e}", text_color=c.danger)

        self.app.bg.run(work, done, fail)

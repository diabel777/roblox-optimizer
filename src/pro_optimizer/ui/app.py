"""Okno główne: pasek boczny, strony, toasty i logika automatycznych aktualizacji."""
from __future__ import annotations

import ctypes
import logging
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Callable, Optional

import customtkinter as ctk

from .. import config, paths, roblox, winsys
from ..cleaner import running_processes
from ..security import SecurityError
from ..settings import Settings
from ..updater import UpdateError, UpdateInfo, Updater, installed_versions
from ..version import APP_NAME, LAUNCHER_EXE, VERSION
from . import theme, widgets as w
from .theme import c, font

log = logging.getLogger(__name__)


class Page(ctk.CTkFrame):
    title = ""
    subtitle = ""

    def __init__(self, master, app: "App"):
        super().__init__(master, fg_color="transparent")
        self.app = app

    def on_show(self) -> None:
        pass


class App(ctk.CTk):
    def __init__(self):
        theme.load()
        super().__init__(fg_color=c.bg)
        self.title(f"{APP_NAME}  v{VERSION}")
        self.geometry(f"{theme.win.width}x{theme.win.height}")
        self.minsize(theme.win.min_width, theme.win.min_height)

        self.settings = Settings()
        self.bg = w.Bg(self)
        self.toast = w.Toast(self)
        self.updater = Updater()
        self.catalog = config.load_apps()
        self.presets = config.load_presets()

        # stan aktualizacji: idle | checking | downloading | ready | uptodate | error
        self.update_state = "idle"
        self.update_text = ""
        self.update_progress = 0.0
        self.update_info: Optional[UpdateInfo] = None
        self._update_listeners: list[Callable[[], None]] = []

        self._pages: dict[str, Page] = {}
        self._nav: dict[str, ctk.CTkButton] = {}
        self._current: Optional[str] = None

        self._build_layout()
        self.show_page("dashboard")

        self.after(400, self._style_window)
        self.after(1800, self._startup_tasks)

    # ------------------------------------------------------------------ okno
    def _style_window(self) -> None:
        if os.name != "nt":
            return
        try:  # ciemny pasek tytułu Windows 10/11
            hwnd = ctypes.windll.user32.GetParent(self.winfo_id())
            val = ctypes.c_int(1)
            for attr in (20, 19):
                ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(val), ctypes.sizeof(val))
        except Exception:
            pass
        ico = paths.resource_dir() / "assets" / "icon.ico"
        if ico.exists():
            try:
                self.iconbitmap(str(ico))
            except Exception:
                pass

    def report_callback_exception(self, exc, val, tb):  # błąd w callbacku nie może zabić aplikacji
        log.error("Nieobsłużony wyjątek w UI", exc_info=(exc, val, tb))
        self.toast.show(f"Wystąpił błąd: {val}", "err")

    # ------------------------------------------------------------------ układ
    def _build_layout(self) -> None:
        from .pages import backups_page, cleaner_page, dashboard, roblox_page, settings_page, system_page
        self.page_defs = [
            ("dashboard", "Panel główny", dashboard.DashboardPage),
            ("roblox", "Roblox i Studio", roblox_page.RobloxPage),
            ("cleaner", "Czyszczenie aplikacji", cleaner_page.CleanerPage),
            ("system", "Windows i sieć", system_page.SystemPage),
            ("backups", "Kopie zapasowe", backups_page.BackupsPage),
            ("settings", "Ustawienia i aktualizacje", settings_page.SettingsPage),
        ]
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # --- pasek boczny
        side = ctk.CTkFrame(self, width=244, corner_radius=0, fg_color=c.sidebar)
        side.grid(row=0, column=0, sticky="nsw")
        side.grid_propagate(False)
        ctk.CTkFrame(self, width=1, corner_radius=0, fg_color=c.border).grid(row=0, column=0, sticky="nse")

        logo = ctk.CTkFrame(side, fg_color="transparent")
        logo.pack(fill="x", padx=20, pady=(26, 22))
        ctk.CTkLabel(logo, text="⚡", width=42, height=42, corner_radius=12, fg_color=c.accent,
                     text_color="#FFFFFF", font=ctk.CTkFont(size=20)).pack(side="left")
        names = ctk.CTkFrame(logo, fg_color="transparent")
        names.pack(side="left", padx=12)
        w.label(names, "PRO Ultimate", "heading", c.text, "bold").pack(anchor="w")
        w.label(names, "Optimizer", "small", c.accent2, "bold").pack(anchor="w")

        w.label(side, "MENU", "small", c.muted, "bold").pack(fill="x", padx=24, pady=(0, 6))
        for pid, title, _cls in self.page_defs:
            b = ctk.CTkButton(side, text=title, anchor="w", height=42, corner_radius=10, font=font("body", "bold"),
                              fg_color="transparent", hover_color=theme.blend(c.sidebar, "#FFFFFF", 0.07),
                              text_color=c.muted, command=lambda p=pid: self.show_page(p))
            b.pack(fill="x", padx=14, pady=2)
            self._nav[pid] = b

        # --- stopka z aktualizacją
        foot = w.card(side, fg_color=theme.blend(c.sidebar, "#FFFFFF", 0.04))
        foot.pack(side="bottom", fill="x", padx=14, pady=16)
        self.upd_label = w.label(foot, "", "small", c.muted, wraplength=190)
        self.upd_label.pack(fill="x", padx=14, pady=(12, 4))
        slot = ctk.CTkFrame(foot, fg_color="transparent", height=1)   # height=1: pusta ramka nie może mieć domyślnych 200 px
        slot.pack(fill="x")
        self.upd_bar = w.progress(slot)
        self.upd_btn = w.button(slot, "Uruchom ponownie i zaktualizuj", self.restart_now, "success", height=34)
        w.label(foot, f"Wersja {VERSION}  •  © Diabeł", "small", c.muted).pack(fill="x", padx=14, pady=(2, 12))
        self._refresh_update_widgets()

        # --- część główna
        main = ctk.CTkFrame(self, fg_color="transparent")
        main.grid(row=0, column=1, sticky="nsew", padx=(28, 28), pady=(24, 20))
        main.grid_columnconfigure(0, weight=1)
        main.grid_rowconfigure(1, weight=1)
        head = ctk.CTkFrame(main, fg_color="transparent")
        head.grid(row=0, column=0, sticky="ew", pady=(0, 16))
        self.h_title = w.label(head, "", "title", c.text, "bold")
        self.h_title.pack(fill="x")
        self.h_sub = w.label(head, "", "body", c.muted)
        self.h_sub.pack(fill="x")
        self.container = ctk.CTkFrame(main, fg_color="transparent")
        self.container.grid(row=1, column=0, sticky="nsew")
        self.container.grid_columnconfigure(0, weight=1)
        self.container.grid_rowconfigure(0, weight=1)

    def show_page(self, pid: str) -> None:
        if pid not in self._pages:
            cls = next(cl for p, _t, cl in self.page_defs if p == pid)
            page = cls(self.container, self)
            page.grid(row=0, column=0, sticky="nsew")
            self._pages[pid] = page
        page = self._pages[pid]
        page.tkraise()
        self._current = pid
        self.h_title.configure(text=page.title)
        self.h_sub.configure(text=page.subtitle)
        for p, b in self._nav.items():
            active = p == pid
            b.configure(fg_color=theme.blend(c.sidebar, c.accent, 0.22) if active else "transparent",
                        text_color=c.text if active else c.muted)
        page.on_show()

    def current_page_id(self) -> Optional[str]:
        return self._current

    def page(self, pid: str) -> Optional[Page]:
        return self._pages.get(pid)

    # ------------------------------------------------------------------ zadania startowe
    def _startup_tasks(self) -> None:
        self.bg.run(lambda: self.updater.cleanup_old(2))
        self.reapply_roblox(silent_if_none=True)
        self.after(5 * 60 * 1000, self._periodic_roblox)
        if self.settings.get("auto_update"):
            self.check_updates(manual=False)
        self.after(30 * 60 * 1000, self._periodic_update)

    def _periodic_update(self) -> None:
        hours = max(1, int(self.settings.get("update_check_hours", 6)))
        if self.settings.get("auto_update") and self.update_state in ("idle", "uptodate", "error") \
                and time.time() - self.settings.get("last_update_check", 0) > hours * 3600:
            self.check_updates(manual=False)
        self.after(30 * 60 * 1000, self._periodic_update)

    def _periodic_roblox(self) -> None:
        self.reapply_roblox(silent_if_none=True)
        self.after(5 * 60 * 1000, self._periodic_roblox)

    def reapply_roblox(self, silent_if_none: bool = False) -> None:
        if not self.settings.get("auto_reapply_roblox"):
            return
        prof = self.settings.get("roblox_profile")
        self.bg.run(lambda: roblox.reapply_if_needed(prof, self.presets),
                    lambda done: done and self.toast.show(
                        "Roblox się zaktualizował - przywrócono Twój profil ustawień: " + ", ".join(done), "info"))

    # ------------------------------------------------------------------ aktualizacje
    def on_update_change(self, cb: Callable[[], None]) -> None:
        self._update_listeners.append(cb)

    def _set_update(self, state: str, text: str = "", prog: float = 0.0) -> None:
        self.update_state, self.update_text, self.update_progress = state, text, prog
        self._refresh_update_widgets()
        for cb in list(self._update_listeners):
            try:
                cb()
            except Exception:
                pass

    def _refresh_update_widgets(self) -> None:
        st = self.update_state
        texts = {"idle": "Aktualizacje: automatyczne", "checking": "Sprawdzam aktualizacje…",
                 "uptodate": "Masz najnowszą wersję ✓", "downloading": self.update_text or "Pobieram aktualizację…",
                 "ready": self.update_text or "Aktualizacja gotowa", "error": self.update_text or "Błąd aktualizacji"}
        self.upd_label.configure(text=texts.get(st, ""),
                                 text_color=c.danger if st == "error" else (c.success if st in ("ready", "uptodate") else c.muted))
        if st == "downloading":
            self.upd_bar.pack(fill="x", padx=14, pady=(0, 10))
            self.upd_bar.set(self.update_progress)
        else:
            self.upd_bar.pack_forget()
        if st == "ready":
            self.upd_btn.pack(fill="x", padx=14, pady=(0, 10))
        else:
            self.upd_btn.pack_forget()

    def check_updates(self, manual: bool = False) -> None:
        if self.update_state in ("checking", "downloading"):
            return
        self._set_update("checking")

        def work():
            return self.updater.check()

        def done(info: Optional[UpdateInfo]):
            self.settings.set("last_update_check", int(time.time()))
            if info is None:
                self._set_update("uptodate")
                if manual:
                    self.toast.show(f"Masz najnowszą wersję (v{VERSION}).", "ok")
                return
            self.update_info = info
            if self.settings.get("auto_update") or manual:
                self._download(info)
            else:
                self._set_update("ready", f"Dostępna wersja {info.version}")

        def fail(e: Exception):
            msg = "Aktualizacje wyłączone: brak klucza podpisu." if "klucza" in str(e) else (
                "Odrzucono aktualizację (weryfikacja bezpieczeństwa)." if isinstance(e, SecurityError) else
                "Nie udało się sprawdzić aktualizacji (brak sieci?).")
            self._set_update("error", msg)
            if manual:
                self.toast.show(f"{msg}\n{e}", "err", 7000)

        self.bg.run(work, done, fail)

    def _download(self, info: UpdateInfo) -> None:
        self._set_update("downloading", f"Pobieram wersję {info.version}…", 0.0)

        def work():
            def prog(done, total):
                self.bg.call(self._set_update, "downloading", f"Pobieram wersję {info.version}…",
                             done / total if total else 0)
            return self.updater.stage(info, prog)

        def done(_path):
            if getattr(sys, "frozen", False):
                self._set_update("ready", f"Wersja {info.version} gotowa do instalacji")
                self.toast.show(f"Pobrano wersję {info.version}. Uruchom ponownie aplikację, aby ją zainstalować.", "ok")
            else:
                self._set_update("uptodate", "Tryb deweloperski - paczka rozpakowana")

        def fail(e: Exception):
            self._set_update("error", "Pobieranie aktualizacji nie powiodło się.")
            self.toast.show(f"Aktualizacja odrzucona: {e}", "err", 7000)

        self.bg.run(work, done, fail)

    def restart_now(self) -> None:
        launcher = paths.install_root() / LAUNCHER_EXE
        target = launcher
        if not launcher.exists():
            vers = installed_versions()
            if not vers:
                self.toast.show("Nie znaleziono nowej wersji do uruchomienia.", "err")
                return
            from ..version import APP_EXE
            target = vers[-1][1] / APP_EXE
        flags = 0x00000008 | 0x00000200 if os.name == "nt" else 0   # DETACHED_PROCESS | NEW_PROCESS_GROUP
        subprocess.Popen([str(target)], close_fds=True, creationflags=flags)
        self.destroy()
        sys.exit(0)

"""Setup - instalator Aderis Boost.

Dwuklik = instalacja (albo naprawa/aktualizacja, jeśli aplikacja już jest). Bez uprawnień administratora.
Pobiera NAJNOWSZĄ wersję z internetu, sprawdza podpis cyfrowy i sumę SHA-256, instaluje w
%LOCALAPPDATA%\\ProUltimateOptimizer, robi skróty i wpis w Ustawienia > Aplikacje.

Opcje wiersza poleceń:
    --silent        instalacja bez okna (kod wyjścia 0 = OK)
    --no-desktop    bez skrótu na pulpicie        --no-start-menu   bez skrótu w Menu Start
    --no-launch     nie uruchamiaj po instalacji
"""
from __future__ import annotations

import argparse
import logging
import os
import subprocess
import sys
import traceback
from pathlib import Path

if not getattr(sys, "frozen", False):                       # uruchamianie z kodu: python installer/installer.py
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from pro_optimizer import install, paths                    # noqa: E402
from pro_optimizer.security import SecurityError            # noqa: E402
from pro_optimizer.updater import Updater                   # noqa: E402
from pro_optimizer.version import APP_NAME                  # noqa: E402

log = logging.getLogger("setup")

STEPS = [("connect", "Łączenie z serwerem"),
         ("download", "Pobieranie i weryfikacja (podpis + SHA-256)"),
         ("install", "Instalowanie plików"),
         ("shortcuts", "Skróty i rejestracja w Windows"),
         ("done", "Gotowe")]


def friendly_error(e: Exception) -> str:
    """Zamienia wyjątek na komunikat, z którym zwykły użytkownik coś zrobi."""
    msg = str(e)
    if isinstance(e, SecurityError):
        if "klucza" in msg:
            return ("Ten instalator został zbudowany bez klucza podpisu aktualizacji.\n"
                    "Zbuduj go ponownie skryptem build.ps1 (krok keygen robi się sam).")
        return ("Pobrane pliki NIE przeszły weryfikacji bezpieczeństwa i zostały odrzucone.\n"
                f"Nic nie zostało zainstalowane.\n\nSzczegóły: {msg}")
    if isinstance(e, PermissionError):
        return "Brak dostępu do folderu instalacji. Zamknij aplikację (jeśli działa) i spróbuj ponownie."
    name = type(e).__name__
    if "URLError" in name or "timeout" in msg.lower() or "Nie udało się pobrać" in msg or isinstance(e, OSError):
        return f"Nie udało się połączyć z serwerem. Sprawdź internet i spróbuj ponownie.\n\nSzczegóły: {msg}"
    return msg or name


def setup_logging() -> None:
    try:
        paths.logs_dir().mkdir(parents=True, exist_ok=True)
        logging.basicConfig(filename=paths.logs_dir() / "setup.log", level=logging.INFO, encoding="utf-8",
                            format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    except OSError:
        logging.basicConfig(level=logging.INFO)


def launch_app() -> None:
    lp = install.launcher_path()
    if lp.exists():
        flags = 0x00000008 | 0x00000200 if os.name == "nt" else 0          # DETACHED_PROCESS | NEW_PROCESS_GROUP
        subprocess.Popen([str(lp)], close_fds=True, creationflags=flags, cwd=str(lp.parent))


# --------------------------------------------------------------------------- tryb bez okna
def run_silent(opts: install.InstallOptions) -> int:
    try:
        r = install.install(opts, progress=lambda s, f, t: print(f"[{int(f * 100):3d}%] {t}"))
    except Exception as e:                                                 # noqa: BLE001
        log.exception("Instalacja nie powiodła się")
        print("BŁĄD:", friendly_error(e), file=sys.stderr)
        return 1
    print(f"Zainstalowano {APP_NAME} {r.version} w {r.root}")
    if opts.launch:
        launch_app()
    return 0


# --------------------------------------------------------------------------- GUI
def run_gui(opts: install.InstallOptions, on_ready=None) -> int:
    import customtkinter as ctk
    from pro_optimizer.ui import theme, widgets as w
    from pro_optimizer.ui.theme import c

    theme.load()

    class Setup(ctk.CTk):
        W, H = 640, 640

        def __init__(self):
            super().__init__(fg_color=c.bg)
            self.title(f"Instalator – {APP_NAME}")
            sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
            self.geometry(f"{self.W}x{self.H}+{(sw - self.W) // 2}+{max(0, (sh - self.H) // 3)}")
            self.resizable(False, False)
            self.bg = w.Bg(self)
            self.v_desktop = ctk.BooleanVar(value=opts.desktop)
            self.v_start = ctk.BooleanVar(value=opts.start_menu)
            self.v_launch = ctk.BooleanVar(value=opts.launch)
            self.latest = None
            self.installed = install.is_installed()
            self.body = ctk.CTkFrame(self, fg_color="transparent")
            self.body.pack(fill="both", expand=True, padx=32, pady=(28, 24))
            self.after(300, self._style_window)
            self.welcome()
            self.after(250, self._probe_latest)

        def _style_window(self):
            if os.name != "nt":
                return
            try:
                import ctypes
                hwnd = ctypes.windll.user32.GetParent(self.winfo_id())
                val = ctypes.c_int(1)
                for attr in (20, 19):
                    ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(val), ctypes.sizeof(val))
                ico = install.find_payload("icon.ico")
                if ico:
                    self.iconbitmap(str(ico))
            except Exception:
                pass

        def clear(self):
            for ch in self.body.winfo_children():
                ch.destroy()

        def header(self, title: str, sub: str):
            row = ctk.CTkFrame(self.body, fg_color="transparent")
            row.pack(fill="x")
            img = None
            try:
                from PIL import Image
                ico = install.find_payload("icon.ico")
                if ico:
                    big = Image.open(ico)
                    big.size = max(big.info.get("sizes", {(256, 256)}))
                    img = ctk.CTkImage(big.convert("RGBA"), size=(64, 64))
                    self._hdr_img = img
            except Exception:
                img = None
            if img:
                ctk.CTkLabel(row, text="", image=img, width=64, height=64).pack(side="left")
            else:
                ctk.CTkLabel(row, text="⚡", width=64, height=64, corner_radius=18, fg_color=c.accent, text_color="#FFFFFF",
                             font=ctk.CTkFont(size=30)).pack(side="left")
            col = ctk.CTkFrame(row, fg_color="transparent")
            col.pack(side="left", padx=16)
            w.label(col, title, "title", c.text, "bold").pack(anchor="w")
            w.label(col, sub, "body", c.muted).pack(anchor="w")

        # ---------------- ekran 1: powitanie
        def welcome(self):
            self.clear()
            self.header("Aderis Boost", "Naprawa / aktualizacja" if self.installed else "Instalator")
            # pasek przycisków pakujemy PIERWSZY - inaczej zawartość wypycha go poza okno
            row = ctk.CTkFrame(self.body, fg_color="transparent")
            row.pack(side="bottom", fill="x")
            self.btn_go = w.button(row, "Napraw / zaktualizuj" if self.installed else "Zainstaluj", self.start,
                                   "primary", height=46, width=220)
            self.btn_go.pack(side="right")
            w.button(row, "Zamknij", self.destroy, "ghost", height=46, width=120).pack(side="right", padx=10)
            box = w.card(self.body)
            box.pack(fill="x", pady=(20, 10))
            for t, s in (("Aktualizuje się sam", "w tle, jak Discord – bez ponownego pobierania instalatora"),
                         ("Bez uprawnień administratora", "instalacja tylko dla Twojego konta"),
                         ("Podpisane aktualizacje", "każda paczka jest weryfikowana podpisem Ed25519 i sumą SHA-256"),
                         ("Wycofanie wadliwej wersji", "jeśli nowa wersja się wywali, wraca poprzednia")):
                r = ctk.CTkFrame(box, fg_color="transparent")
                r.pack(fill="x", padx=20, pady=3)
                ctk.CTkLabel(r, text="✓", width=24, text_color=c.success, font=ctk.CTkFont(size=16, weight="bold")).pack(side="left")
                tx = ctk.CTkFrame(r, fg_color="transparent")
                tx.pack(side="left", padx=8)
                w.label(tx, t, "body", c.text, "bold").pack(anchor="w")
                w.label(tx, s, "small", c.muted).pack(anchor="w")
            ctk.CTkFrame(box, height=6, fg_color="transparent").pack()

            opt = w.card(self.body)
            opt.pack(fill="x", pady=(0, 10))
            for var, text in ((self.v_desktop, "Skrót na pulpicie"), (self.v_start, "Skrót w Menu Start"),
                              (self.v_launch, "Uruchom po zakończeniu instalacji")):
                w.checkbox(opt, text, variable=var).pack(anchor="w", padx=20, pady=(12, 0))
            ctk.CTkFrame(opt, height=12, fg_color="transparent").pack()

            self.lbl_ver = w.label(self.body, "Sprawdzam najnowszą wersję…", "small", c.muted)
            self.lbl_ver.pack(fill="x", pady=(2, 10))

        def _probe_latest(self):
            def work():
                return Updater(current_version="0").check()

            def done(info):
                self.latest = info
                self.lbl_ver.configure(text=f"Najnowsza wersja: {info.version}" + (f"   •   {info.notes}" if info.notes else ""),
                                       text_color=c.success)

            def fail(e):
                self.lbl_ver.configure(text=friendly_error(e).split("\n")[0], text_color=c.warning)
            self.bg.run(work, done, fail)

        # ---------------- ekran 2: instalacja
        def start(self):
            o = install.InstallOptions(self.v_desktop.get(), self.v_start.get(), self.v_launch.get())
            self.opts_now = o
            self.clear()
            self.header("Instaluję…", "To zajmie chwilę. Nie zamykaj okna.")
            card = w.card(self.body)
            card.pack(fill="x", pady=(28, 12))
            self.pbar = w.progress(card)
            self.pbar.pack(fill="x", padx=22, pady=(24, 8))
            self.pbar.set(0)
            self.lbl_status = w.label(card, "Start…", "body", c.text)
            self.lbl_status.pack(fill="x", padx=22, pady=(0, 14))
            self.step_lbls = {}
            for key, name in STEPS[:-1]:
                lb = w.label(card, f"○  {name}", "body", c.muted)
                lb.pack(fill="x", padx=22, pady=3)
                self.step_lbls[key] = (lb, name)
            ctk.CTkFrame(card, height=14, fg_color="transparent").pack()

            def prog(stage, frac, text):
                self.bg.call(self._on_progress, stage, frac, text)

            self.bg.run(lambda: install.install(o, progress=prog), self.finished, self.failed)

        def _on_progress(self, stage, frac, text):
            self.pbar.set(frac)
            self.lbl_status.configure(text=text)
            keys = [k for k, _ in STEPS]
            cur = keys.index(stage) if stage in keys else 0
            for i, (k, (lb, name)) in enumerate(self.step_lbls.items()):
                if i < cur:
                    lb.configure(text=f"✓  {name}", text_color=c.success)
                elif i == cur and stage != "done":
                    lb.configure(text=f"●  {name}", text_color=c.text)
                elif stage == "done":
                    lb.configure(text=f"✓  {name}", text_color=c.success)

        # ---------------- ekran 3: koniec
        def finished(self, res: install.InstallResult):
            self.clear()
            self.header("Gotowe!", f"{APP_NAME} {res.version} jest zainstalowany")
            card = w.card(self.body)
            card.pack(fill="x", pady=(28, 12))
            lines = [("Lokalizacja", str(res.root)),
                     ("Skróty", ", ".join({"desktop": "Pulpit", "start_menu": "Menu Start"}[s] for s in res.shortcuts) or "brak"),
                     ("Aktualizacje", "automatyczne, w tle")]
            for k, v in lines:
                r = ctk.CTkFrame(card, fg_color="transparent")
                r.pack(fill="x", padx=22, pady=(12, 0))
                w.label(r, k, "small", c.muted, "bold", width=110).pack(side="left")
                w.label(r, v, "body", c.text, wraplength=380).pack(side="left")
            ctk.CTkFrame(card, height=14, fg_color="transparent").pack()
            row = ctk.CTkFrame(self.body, fg_color="transparent")
            row.pack(side="bottom", fill="x")
            w.button(row, "Uruchom", lambda: (launch_app(), self.destroy()), "primary", height=46, width=200).pack(side="right")
            w.button(row, "Zamknij", self.destroy, "ghost", height=46, width=120).pack(side="right", padx=10)
            if self.opts_now.launch:
                self.after(900, lambda: (launch_app(), self.destroy()))

        def failed(self, e: Exception):
            log.error("Instalacja nie powiodła się: %s", "".join(traceback.format_exception(e)))
            self.clear()
            self.header("Coś poszło nie tak", "Instalacja została przerwana")
            card = w.card(self.body, border_color=c.danger)
            card.pack(fill="x", pady=(28, 12))
            w.label(card, friendly_error(e), "body", c.text, wraplength=540).pack(fill="x", padx=22, pady=20)
            row = ctk.CTkFrame(self.body, fg_color="transparent")
            row.pack(side="bottom", fill="x")
            w.button(row, "Spróbuj ponownie", self.welcome, "primary", height=46, width=200).pack(side="right")
            w.button(row, "Otwórz log", self._open_log, "ghost", height=46, width=130).pack(side="right", padx=10)
            w.button(row, "Zamknij", self.destroy, "ghost", height=46, width=110).pack(side="right")

        def _open_log(self):
            try:
                os.startfile(str(paths.logs_dir()))      # type: ignore[attr-defined]
            except Exception:
                pass

    app = Setup()
    if on_ready:                                  # haczyk dla testów GUI
        on_ready(app)
    app.mainloop()
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=f"Instalator {APP_NAME}")
    ap.add_argument("--silent", action="store_true")
    ap.add_argument("--no-desktop", action="store_true")
    ap.add_argument("--no-start-menu", action="store_true")
    ap.add_argument("--no-launch", action="store_true")
    a = ap.parse_args(argv)
    opts = install.InstallOptions(not a.no_desktop, not a.no_start_menu, not a.no_launch)
    setup_logging()
    return run_silent(opts) if a.silent else run_gui(opts)


if __name__ == "__main__":
    sys.exit(main())

"""Pobrane: paczki aktualizacji i zapisane raporty w jednym miejscu - z możliwością otwarcia i usunięcia."""
from __future__ import annotations

import os
import shutil
import time
from pathlib import Path

import customtkinter as ctk

from ... import paths
from .. import widgets as w
from ..app import Page
from ..theme import c


def _fmt(n: int) -> str:
    return f"{n / 1048576:.1f} MB" if n >= 1048576 else f"{max(1, n // 1024)} KB"


def _open(p: Path) -> None:
    try:
        os.startfile(str(p))              # type: ignore[attr-defined]  # tylko Windows
    except Exception:
        pass


class DownloadsPage(Page):
    title = "Pobrane"
    subtitle = "Pobrane aktualizacje i zapisane raporty - wszystko w jednym miejscu, możesz to otworzyć albo usunąć."

    def __init__(self, master, app):
        super().__init__(master, app)
        body = w.scroll_frame(self)
        body.pack(fill="both", expand=True)
        self.upd = w.card(body)
        self.upd.pack(fill="x")
        self.rep = w.card(body)
        self.rep.pack(fill="x", pady=(14, 20))
        self._fill()

    def on_show(self) -> None:
        self._fill()

    def _section(self, card, title: str, hint: str, folder: Path, files: list[Path], empty: str, clear_text: str) -> None:
        for ch in card.winfo_children():
            ch.destroy()
        top = ctk.CTkFrame(card, fg_color="transparent", height=1)
        top.pack(fill="x", padx=22, pady=(18, 2))
        w.label(top, title, "heading", c.text, "bold").pack(side="left")
        w.button(top, "Otwórz folder", lambda: (folder.mkdir(parents=True, exist_ok=True), _open(folder)), "ghost", height=30, width=130).pack(side="right")
        if files:
            w.button(top, clear_text, lambda: self._clear(files), "ghost", height=30, width=150).pack(side="right", padx=8)
        w.label(card, hint, "small", c.muted, wraplength=760).pack(fill="x", padx=22)
        box = ctk.CTkFrame(card, fg_color="transparent", height=1)
        box.pack(fill="x", padx=22, pady=(8, 16))
        if not files:
            w.label(box, empty, "small", c.muted).pack(anchor="w")
        for f in files:
            r = ctk.CTkFrame(box, fg_color="transparent", height=1)
            r.pack(fill="x", pady=2)
            try:
                st = f.stat()
                size, when = (st.st_size if f.is_file() else sum(x.stat().st_size for x in f.rglob("*") if x.is_file())), st.st_mtime
            except OSError:
                continue
            w.label(r, time.strftime("%d.%m %H:%M", time.localtime(when)), "small", c.muted, width=90).pack(side="left")
            w.label(r, f.name, "small", c.text, width=330).pack(side="left")
            w.label(r, _fmt(size), "small", c.muted, width=80).pack(side="left")
            w.button(r, "Usuń", lambda p=f: self._clear([p]), "ghost", height=24, width=60).pack(side="right")
            if f.is_file():
                w.button(r, "Otwórz", lambda p=f: _open(p), "ghost", height=24, width=70).pack(side="right", padx=6)

    def _fill(self) -> None:
        ddir, rdir = paths.downloads_dir(), paths.reports_dir()
        dl = sorted([p for p in ddir.glob("*") if p.exists()], key=lambda p: p.stat().st_mtime, reverse=True) if ddir.exists() else []
        rp = sorted(rdir.glob("*.txt"), key=lambda p: p.stat().st_mtime, reverse=True) if rdir.exists() else []
        self._section(self.upd, "Aktualizacje aplikacji",
                      "Paczki nowych wersji pobrane z serwera aktualizacji. Po instalacji nie są już potrzebne - możesz je usunąć, aplikacja pobierze je ponownie, gdy będzie trzeba.",
                      ddir, dl, "Brak pobranych paczek.", "Usuń wszystkie")
        self._section(self.rep, "Raporty",
                      "Raporty z testu internetu zapisane przyciskiem „Zapisz raport dla dostawcy”. Możesz je otworzyć i wysłać do swojego dostawcy.",
                      rdir, rp, "Brak zapisanych raportów. Zrób test internetu i kliknij „Zapisz raport”.", "Usuń wszystkie")

    def _clear(self, files: list[Path]) -> None:
        if not w.confirm(self, "Usuń", f"Usunąć {len(files)} {'pozycję' if len(files) == 1 else 'pozycji'}? Tego nie można cofnąć.", "Usuń", danger=True):
            return
        for f in files:
            try:
                shutil.rmtree(f, ignore_errors=True) if f.is_dir() else f.unlink(missing_ok=True)
            except OSError:
                pass
        self._fill()

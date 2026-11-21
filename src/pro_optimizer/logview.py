"""Podgląd logów aplikacji: czyta końcówkę app.log (+ rotowane), filtruje po poziomie."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from . import paths

LEVELS = {"Wszystko": 0, "Info i wyżej": 20, "Ostrzeżenia i błędy": 30, "Tylko błędy": 40}
_LV = {"DEBUG": 10, "INFO": 20, "WARNING": 30, "ERROR": 40, "CRITICAL": 50}
_LINE = re.compile(r"^\d{4}-\d{2}-\d{2} [\d:,]+ (DEBUG|INFO|WARNING|ERROR|CRITICAL) ")


def level_of(line: str) -> Optional[int]:
    m = _LINE.match(line)
    return _LV[m.group(1)] if m else None


def read_tail(max_lines: int = 600, min_level: int = 0, log_dir: Optional[Path] = None) -> list[tuple[str, int]]:
    """Zwraca [(linia, poziom)] - najnowsze na końcu. Linie bez nagłówka (traceback) dziedziczą poziom poprzedniej."""
    d = log_dir or paths.logs_dir()
    files = [d / "app.log"] + [d / f"app.log.{i}" for i in (1, 2, 3)]
    lines: list[str] = []
    for f in reversed(files):                      # od najstarszego
        try:
            lines += f.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
    out: list[tuple[str, int]] = []
    cur = 20
    for ln in lines[-max_lines * 3:]:
        lv = level_of(ln)
        if lv is not None:
            cur = lv
        out.append((ln, cur))
    out = [(ln, lv) for ln, lv in out if lv >= min_level]
    return out[-max_lines:]


def clear(log_dir: Optional[Path] = None) -> None:
    d = log_dir or paths.logs_dir()
    for f in [d / "app.log"] + [d / f"app.log.{i}" for i in (1, 2, 3)]:
        try:
            f.write_text("", encoding="utf-8") if f.name == "app.log" else f.unlink()
        except OSError:
            pass

"""Wersja aplikacji. Podbijaj ją przed każdym wydaniem (tools/release.py bierze ją stąd)."""

VERSION = "4.1.0"
APP_NAME = "PRO Ultimate Optimizer"
APP_ID = "ProUltimateOptimizer"
APP_EXE = "ProUltimateOptimizerApp.exe"   # exe aplikacji wewnątrz folderu app-X.Y.Z
LAUNCHER_EXE = "ProUltimateOptimizer.exe"  # mały launcher w katalogu głównym instalacji
SETUP_EXE = "ProUltimateOptimizer-Setup.exe"


def parse_version(v: str) -> tuple:
    """'4.0.1' -> (4, 0, 1). Brakujące człony traktowane jak 0 (3.3 == 3.3.0)."""
    parts = [int(x) for x in str(v).strip().lstrip("v").split(".")]
    while len(parts) < 4:
        parts.append(0)
    return tuple(parts)

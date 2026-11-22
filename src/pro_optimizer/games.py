"""Optymalizacja pojedynczych gier: osobne ustawienia dla każdej (wykrywanie exe, GPU, tryb pełnoekranowy, priorytet).

Wszystko jest odwracalne: dla każdej opcji wiemy, jaką wartość rejestru ustawiliśmy i jak ją usunąć.
  gpu_high  - Ustawienia grafiki Windows: "Wysoka wydajność" dla tego exe (HKCU, bez admina)
  fso_off   - wyłącz optymalizacje pełnoekranowe dla exe (HKCU AppCompat Layers, bez admina)
  prio_high - stały wysoki priorytet CPU (HKLM Image File Execution Options -> PerfOptions, wymaga admina)
Dodatkowo `auto_boost` (w automatyzacji) podnosi priorytet uruchomionej gry bez admina i zwalnia RAM."""
from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Callable, Iterable, Optional

log = logging.getLogger(__name__)
IS_WINDOWS = os.name == "nt"

if IS_WINDOWS:
    import winreg

GPU_KEY = r"Software\Microsoft\DirectX\UserGpuPreferences"
LAYERS_KEY = r"Software\Microsoft\Windows NT\CurrentVersion\AppCompatFlags\Layers"
IFEO_KEY = r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Image File Execution Options"
FSO_TOKEN = "DISABLEDXMAXIMIZEDWINDOWEDMODE"

OPTIONS = [
    ("gpu_high", "Wysoka wydajność GPU", "Windows uruchamia tę grę na mocniejszej karcie (ważne przy laptopach i procesorach z wbudowaną grafiką).", False),
    ("fso_off", "Wyłącz optymalizacje pełnoekranowe", "Daje grze prawdziwy pełny ekran - zwykle mniejsze opóźnienie wejścia i mniej przycięć.", False),
    ("prio_high", "Stały wysoki priorytet CPU", "Gra zawsze startuje z wysokim priorytetem procesora.", True),
]


# --------------------------------------------------------------------------- czysta logika (testowana na Linuksie)
def layers_add(existing: str, token: str = FSO_TOKEN) -> str:
    """Dodaje flagę zgodności do wartości Layers zachowując cudze flagi. Zwraca nowy ciąg ('~ A B')."""
    toks = [t for t in (existing or "").split() if t != "~"]
    if token not in toks:
        toks.append(token)
    return "~ " + " ".join(toks)


def layers_remove(existing: str, token: str = FSO_TOKEN) -> str:
    """Usuwa flagę. Pusty wynik ('') oznacza: usuń wartość całkiem."""
    toks = [t for t in (existing or "").split() if t not in ("~", token)]
    return ("~ " + " ".join(toks)) if toks else ""


def layers_has(existing: str, token: str = FSO_TOKEN) -> bool:
    return token in (existing or "").split()


def gpu_pref_value(high: bool = True) -> str:
    return "GpuPreference=2;" if high else "GpuPreference=0;"


# Procesy systemowe - nigdy nie ustawiamy dla nich priorytetu/GPU/pełnego ekranu (IFEO na nich = ryzyko niestabilności).
_CRITICAL_EXES = {"csrss.exe", "smss.exe", "wininit.exe", "winlogon.exe", "lsass.exe", "services.exe", "svchost.exe",
                  "explorer.exe", "dwm.exe", "taskmgr.exe", "cmd.exe", "powershell.exe", "pwsh.exe", "regedit.exe",
                  "reg.exe", "msiexec.exe", "rundll32.exe", "conhost.exe", "sihost.exe", "fontdrvhost.exe",
                  "ctfmon.exe", "audiodg.exe", "spoolsv.exe", "wuauclt.exe", "msmpeng.exe", "mpcmdrun.exe"}
_EXE_NAME = re.compile(r"^[A-Za-z0-9_.\- ]{1,80}\.exe$")


def safe_exe_name(name: str) -> bool:
    return bool(_EXE_NAME.match(name or "")) and name.lower() not in _CRITICAL_EXES


def safe_exe_path(p: str) -> bool:
    """Tylko bezwzględna ścieżka do zwykłego .exe (nie systemowego) bez znaków sterujących."""
    if not p or len(p) > 400 or any(ch in p for ch in "\r\n\0\"") or not p.lower().endswith(".exe"):
        return False
    if not (os.path.isabs(p) or re.match(r"^[A-Za-z]:[\\/]", p)):
        return False
    base = re.split(r"[\\/]", p)[-1]
    if not safe_exe_name(base):
        return False
    win = (os.environ.get("SystemRoot") or os.environ.get("WINDIR") or "").lower().rstrip("\\/")
    return not (win and p.lower().replace("/", "\\").startswith(win + "\\"))


# --------------------------------------------------------------------------- wykrywanie
def _steam_libraries() -> list[Path]:
    out: list[Path] = []
    for base in (os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramFiles")):
        if not base:
            continue
        vdf = Path(base) / "Steam" / "steamapps" / "libraryfolders.vdf"
        try:
            text = vdf.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        out.append(vdf.parent / "common")
        for m in re.finditer(r'"path"\s+"([^"]+)"', text):
            out.append(Path(m.group(1).replace("\\\\", "\\")) / "steamapps" / "common")
    return out


def candidate_roots() -> list[Path]:
    roots: list[Path] = []
    env = os.environ
    for k in ("ProgramFiles", "ProgramFiles(x86)"):
        if env.get(k):
            roots += [Path(env[k]), Path(env[k]) / "Epic Games", Path(env[k]) / "Riot Games"]
    if env.get("LOCALAPPDATA"):
        roots += [Path(env["LOCALAPPDATA"]) / "Roblox" / "Versions", Path(env["LOCALAPPDATA"]) / "Programs"]
    if env.get("APPDATA"):
        roots.append(Path(env["APPDATA"]) / ".minecraft")
    roots += _steam_libraries()
    for d in "CDEFGH":                       # typowe biblioteki gier na innych dyskach
        for sub in ("SteamLibrary/steamapps/common", "Games", "Epic Games", "Program Files/Epic Games", "XboxGames"):
            roots.append(Path(f"{d}:/") / sub)
    seen, uniq = set(), []
    for r in roots:
        key = str(r).lower()
        if key not in seen:
            seen.add(key)
            uniq.append(r)
    return uniq


def _walk_find(root: Path, names: set[str], depth: int, budget: list[int]) -> Optional[Path]:
    if depth < 0 or budget[0] <= 0:
        return None
    try:
        with os.scandir(root) as it:
            subdirs = []
            for e in it:
                budget[0] -= 1
                try:
                    if e.is_file(follow_symlinks=False) and e.name.lower() in names:
                        return Path(e.path)
                    if e.is_dir(follow_symlinks=False):
                        subdirs.append(Path(e.path))
                except OSError:
                    continue
    except OSError:
        return None
    for d in subdirs:
        hit = _walk_find(d, names, depth - 1, budget)
        if hit:
            return hit
    return None


def find_exe(game: dict, roots: Optional[Iterable[Path]] = None, depth: int = 4) -> Optional[Path]:
    """Szuka exe gry w typowych katalogach (ograniczona głębokość i liczba wpisów - nie mieli całego dysku)."""
    names = {e.lower() for e in game.get("exes", [])}
    hints = [h.lower() for h in game.get("hints", [])]
    budget = [20000]
    for root in (roots if roots is not None else candidate_roots()):
        if not root.is_dir():
            continue
        if game.get("kind", "").startswith("roblox"):
            hit = _walk_find(root, names, 2, budget)
            if hit:
                return hit
            continue
        if root.name.lower() in ("games", "xboxgames", "programs") or "program files" in str(root).lower():
            try:
                subs = [d for d in root.iterdir() if d.is_dir()]
            except OSError:
                continue
            subs = [d for d in subs if any(h in d.name.lower() for h in hints)] if hints else []
        else:
            try:
                subs = [d for d in root.iterdir() if d.is_dir() and (not hints or any(h in d.name.lower() for h in hints))]
            except OSError:
                continue
        for d in subs:
            hit = _walk_find(d, names, depth, budget)
            if hit:
                return hit
    return None


def running_game_exes(games: list[dict], running: set[str]) -> list[dict]:
    """Które gry z katalogu są teraz uruchomione (po nazwie procesu)."""
    out = []
    for g in games:
        if g.get("id") == "minecraft":   # javaw.exe to też inne programy - wykrywamy tylko po ścieżce użytkownika
            continue
        if any(e.lower() in running for e in g.get("exes", [])):
            out.append(g)
    return out


# --------------------------------------------------------------------------- rejestr (tylko Windows)
def _need_win() -> Optional[tuple[bool, str]]:
    return None if IS_WINDOWS else (False, "Dostępne tylko w Windows.")


def _get(hive, key: str, name: str) -> Optional[str]:
    try:
        with winreg.OpenKey(hive, key, 0, winreg.KEY_READ) as k:
            return winreg.QueryValueEx(k, name)[0]
    except OSError:
        return None


def _set(hive, key: str, name: str, value, vtype=None) -> None:
    vtype = vtype or winreg.REG_SZ
    with winreg.CreateKeyEx(hive, key, 0, winreg.KEY_SET_VALUE) as k:
        winreg.SetValueEx(k, name, 0, vtype, value)


def _del(hive, key: str, name: str) -> None:
    try:
        with winreg.OpenKey(hive, key, 0, winreg.KEY_SET_VALUE) as k:
            winreg.DeleteValue(k, name)
    except OSError:
        pass


def _admin() -> bool:
    from . import winsys
    return winsys.is_admin()


def option_state(opt: str, exe: str) -> Optional[bool]:
    if not IS_WINDOWS or not safe_exe_path(exe):
        return None
    if opt == "gpu_high":
        return "GpuPreference=2" in (_get(winreg.HKEY_CURRENT_USER, GPU_KEY, exe) or "")
    if opt == "fso_off":
        return layers_has(_get(winreg.HKEY_CURRENT_USER, LAYERS_KEY, exe) or "")
    if opt == "prio_high":
        v = _get(winreg.HKEY_LOCAL_MACHINE, IFEO_KEY + "\\" + os.path.basename(exe) + r"\PerfOptions", "CpuPriorityClass")
        return v == 3
    return None


def set_option(opt: str, exe: str, on: bool) -> tuple[bool, str]:
    bad = _need_win()
    if bad:
        return bad
    if not safe_exe_path(exe):
        return False, "Nieprawidłowa ścieżka do pliku exe."
    try:
        if opt == "gpu_high":
            if on:
                _set(winreg.HKEY_CURRENT_USER, GPU_KEY, exe, gpu_pref_value(True))
            else:
                _del(winreg.HKEY_CURRENT_USER, GPU_KEY, exe)
        elif opt == "fso_off":
            cur = _get(winreg.HKEY_CURRENT_USER, LAYERS_KEY, exe) or ""
            new = layers_add(cur) if on else layers_remove(cur)
            if new:
                _set(winreg.HKEY_CURRENT_USER, LAYERS_KEY, exe, new)
            else:
                _del(winreg.HKEY_CURRENT_USER, LAYERS_KEY, exe)
        elif opt == "prio_high":
            if not _admin():
                return False, "Wymaga uprawnień administratora."
            key = IFEO_KEY + "\\" + os.path.basename(exe) + r"\PerfOptions"
            if on:
                _set(winreg.HKEY_LOCAL_MACHINE, key, "CpuPriorityClass", 3, winreg.REG_DWORD)
            else:
                _del(winreg.HKEY_LOCAL_MACHINE, key, "CpuPriorityClass")
        else:
            return False, "Nieznana opcja."
        return True, "Zastosowano." if on else "Cofnięto."
    except OSError as e:
        log.warning("set_option %s %s: %s", opt, exe, e)
        return False, f"Błąd rejestru: {e}"


def boost_running(exe_names: Iterable[str]) -> int:
    """Podnosi priorytet uruchomionych procesów gry (HIGH) - bez admina dla procesów tego samego użytkownika."""
    try:
        import psutil
    except ImportError:
        return 0
    names = {n.lower() for n in exe_names}
    n = 0
    for p in psutil.process_iter(["name"]):
        try:
            if (p.info["name"] or "").lower() in names:
                if IS_WINDOWS:
                    p.nice(psutil.HIGH_PRIORITY_CLASS)
                else:
                    p.nice(-1)
                n += 1
        except (psutil.Error, PermissionError, OSError):
            continue
    return n

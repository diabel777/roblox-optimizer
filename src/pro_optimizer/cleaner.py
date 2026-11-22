"""Skanowanie i czyszczenie cache aplikacji na podstawie katalogu config/apps.json.

Bezpieczeństwo:
  * kasujemy ZAWARTOŚĆ folderów cache (sam folder zostaje),
  * ścieżka musi leżeć w dozwolonych korzeniach (AppData/ProgramData/TEMP) - nigdy sam korzeń,
  * nie podążamy za symlinkami ani junctionami,
  * aplikacje, które są uruchomione, są pomijane (nie ruszamy plików w użyciu).
"""
from __future__ import annotations

import glob
import logging
import os
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, Optional

from .ps import system_exe

log = logging.getLogger(__name__)

_REPARSE = 0x400
_SINGLE_COMPONENT_OK = {"d3dscache", "crashdumps"}   # foldery cache leżące bezpośrednio w LOCALAPPDATA


def fmt_bytes(n: float) -> str:
    n = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


# --------------------------------------------------------------------------- ścieżki
def expand(p: str) -> str:
    return re.sub(r"%([A-Za-z0-9_()]+)%", lambda m: os.environ.get(m.group(1), m.group(0)), p)


def _norm(p: str | Path) -> str:
    return os.path.normcase(os.path.normpath(os.path.abspath(str(p))))


def _env_path(name: str) -> Optional[str]:
    v = os.environ.get(name)
    return _norm(v) if v else None


def _allowed_roots() -> list[str]:
    return [r for r in (_env_path("LOCALAPPDATA"), _env_path("APPDATA"), _env_path("PROGRAMDATA")) if r]


def _exact_roots() -> set[str]:
    out = {r for r in (_env_path("TEMP"), _env_path("TMP")) if r}
    win = os.environ.get("WINDIR") or os.environ.get("SystemRoot")
    if win:
        out.add(_norm(Path(win) / "Temp"))
    return out


# Foldery z danymi logowania, certyfikatami i naszymi kopiami - nie czyścimy ich NIGDY, niezależnie od konfiguracji.
_DENY_COMPONENTS = {"credentials", "protect", "vault", "crypto", "systemcertificates", "packages", "identitycrl",
                    "proultimateoptimizer", "backups", "keychain", "dpapi"}


def _denied(parts: list[str]) -> bool:
    return any(x.lower() in _DENY_COMPONENTS for x in parts)


def is_safe_target(path: str | Path, user: bool = False) -> bool:
    """Czy wolno czyścić zawartość tego folderu. Wpisy użytkownika (user=True) mają dodatkowe, ostrzejsze reguły:
    głębokość >= 3, bez ProgramData i bez wildcardów w pierwszych dwóch składnikach."""
    n = _norm(path)
    if n in _exact_roots():
        return not user
    for root in _allowed_roots():
        if user and root == _env_path("PROGRAMDATA"):
            continue
        if n.startswith(root + os.sep):
            rel = n[len(root) + 1:].split(os.sep)
            if _denied(rel):
                return False
            if user:
                return len(rel) >= 3
            if len(rel) >= 2 or rel[0].lower() in _SINGLE_COMPONENT_OK:
                return True
    return False


def _chain_has_reparse(path: Path) -> bool:
    """True, jeśli sam folder LUB którykolwiek jego przodek (aż do korzenia AppData itp.) jest linkiem/junctionem.
    Chroni przed podmianą folderu cache na junction do cudzego katalogu."""
    roots = set(_allowed_roots()) | _exact_roots()
    cur = Path(os.path.abspath(str(path)))
    for _ in range(40):
        try:
            st = os.lstat(cur)
        except OSError:
            return True
        if os.path.islink(cur) or bool(getattr(st, "st_file_attributes", 0) & _REPARSE):
            return True
        if _norm(cur) in roots or cur.parent == cur:
            break
        cur = cur.parent
    return False


def _is_reparse(entry: os.DirEntry) -> bool:
    try:
        if entry.is_symlink():
            return True
        return bool(getattr(entry.stat(follow_symlinks=False), "st_file_attributes", 0) & _REPARSE)
    except OSError:
        return True


def _wild_too_early(raw: str) -> bool:
    """Wildcard w pierwszych dwóch składnikach po zmiennej środowiskowej (np. %APPDATA%\\*\\*) = za szeroko."""
    parts = [x for x in re.split(r"[\\/]+", raw) if x]
    tail = parts[1:] if parts and parts[0].startswith("%") else parts
    return any(any(ch in x for ch in "*?[") for x in tail[:2])


def resolve_paths(entry: dict) -> list[Path]:
    """Rozwija zmienne środowiskowe i wildcardy; zwraca istniejące, bezpieczne foldery."""
    found: list[Path] = []
    seen: set[str] = set()
    user = bool(entry.get("user"))
    for raw in (r for r in entry.get("paths", []) if isinstance(r, str)):
        p = expand(raw)
        if "%" in p:                       # nierozwiązana zmienna
            continue
        for m in (glob.glob(p) if any(c in p for c in "*?[") else [p]):
            mp = Path(m)
            key = _norm(mp)
            if key in seen or not mp.is_dir() or _chain_has_reparse(mp):
                continue
            if user and any(ch in raw for ch in "*?[") and _wild_too_early(raw):
                continue
            if not is_safe_target(mp, user):
                log.warning("Pominięto niebezpieczną ścieżkę: %s", mp)
                continue
            seen.add(key)
            found.append(mp)
    return found


# --------------------------------------------------------------------------- procesy
def running_processes() -> set[str]:
    if os.name != "nt":
        return set()
    try:
        out = subprocess.run([system_exe("tasklist"), "/FO", "CSV", "/NH"], capture_output=True, text=True, errors="ignore",
                             timeout=15, creationflags=0x08000000).stdout
    except Exception:
        return set()
    names = set()
    for line in out.splitlines():
        m = re.match(r'^"([^"]+)"', line)
        if m:
            names.add(m.group(1).lower())
    return names


def blocking(entry: dict, running: set[str]) -> list[str]:
    return [p for p in entry.get("processes", []) if p.lower() in running]


# --------------------------------------------------------------------------- skan / czyszczenie
@dataclass
class EntryResult:
    id: str
    name: str
    group: str
    size: int = 0
    files: int = 0
    skipped: int = 0
    blocked_by: list[str] = field(default_factory=list)
    found: int = 0           # ile folderów istnieje na tym komputerze
    error: str = ""


def _scan_dir(path: Path, claimed: set[str]) -> tuple[int, int]:
    size = files = 0
    stack = [path]
    while stack:
        cur = stack.pop()
        try:
            with os.scandir(cur) as it:
                for e in it:
                    if _is_reparse(e):
                        continue
                    if e.is_dir(follow_symlinks=False):
                        if _norm(e.path) in claimed:
                            continue
                        stack.append(Path(e.path))
                    else:
                        try:
                            size += e.stat(follow_symlinks=False).st_size
                            files += 1
                        except OSError:
                            pass
        except OSError:
            pass
    return size, files


def _clean_dir(path: Path, claimed: set[str], res: EntryResult) -> None:
    try:
        with os.scandir(path) as it:
            entries = list(it)
    except OSError:
        return
    for e in entries:
        if _is_reparse(e):
            continue
        if e.is_dir(follow_symlinks=False):
            if _norm(e.path) in claimed:
                continue
            _clean_dir(Path(e.path), claimed, res)
            try:
                os.rmdir(e.path)            # tylko gdy pusty
            except OSError:
                pass
        else:
            try:
                sz = e.stat(follow_symlinks=False).st_size
            except OSError:
                sz = 0
            try:
                try:
                    os.unlink(e.path)
                except PermissionError:
                    os.chmod(e.path, 0o666)
                    os.unlink(e.path)
                res.size += sz
                res.files += 1
            except OSError:
                res.skipped += 1


def _prepare(entries: Iterable[dict], running: set[str]):
    """Zwraca listę (entry, ścieżki, claimed-przed-nim) w kolejności katalogu - bez podwójnego liczenia."""
    out = []
    claimed: set[str] = set()
    for e in entries:
        pl = resolve_paths(e)
        out.append((e, pl, set(claimed)))
        claimed.update(_norm(p) for p in pl)
    return out


def scan(entries: list[dict], running: Optional[set[str]] = None,
         progress: Optional[Callable[[int, int, EntryResult], None]] = None) -> list[EntryResult]:
    running = running if running is not None else running_processes()
    plan = _prepare(entries, running)
    results = []
    for i, (e, pl, claimed) in enumerate(plan):
        r = EntryResult(e["id"], e.get("name", e["id"]), e.get("group", "Inne"), found=len(pl),
                        blocked_by=blocking(e, running))
        for p in pl:
            s, f = _scan_dir(p, claimed)
            r.size += s
            r.files += f
        results.append(r)
        if progress:
            progress(i + 1, len(plan), r)
    return results


def clean(entries: list[dict], running: Optional[set[str]] = None, force: bool = False,
          progress: Optional[Callable[[int, int, EntryResult], None]] = None) -> list[EntryResult]:
    running = running if running is not None else running_processes()
    plan = _prepare(entries, running)
    results = []
    for i, (e, pl, claimed) in enumerate(plan):
        r = EntryResult(e["id"], e.get("name", e["id"]), e.get("group", "Inne"), found=len(pl),
                        blocked_by=blocking(e, running))
        if r.blocked_by and not force:
            r.error = "Uruchomiona: " + ", ".join(r.blocked_by)
        else:
            for p in pl:
                if not is_safe_target(p, bool(e.get("user"))) or _chain_has_reparse(p):   # kontrola tuż przed kasowaniem
                    continue
                _clean_dir(p, claimed, r)
            log.info("Wyczyszczono %s: %s (%d plików, pominięto %d)", r.id, fmt_bytes(r.size), r.files, r.skipped)
        results.append(r)
        if progress:
            progress(i + 1, len(plan), r)
    return results

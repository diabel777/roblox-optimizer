"""Pełne kopie zapasowe („punkty przywracania programu"): wybierasz, co zabezpieczyć, a potem możesz to cofnąć.

Kopia to folder  Backups\\Snapshots\\<data>\\  z plikiem manifest.json (lista plików + sumy SHA-256).
Przy przywracaniu sprawdzamy sumy i nazwy plików (żaden plik nie może wyjść poza folder kopii).

Części kopii:
  roblox   - ClientAppSettings.json Roblox Playera i Studio
  windows  - klucze rejestru, które zmienia program (tryb gry, priorytety, HAGS…) + aktywny plan zasilania
  games    - ustawienia GPU i pełnego ekranu dla gier (HKCU) oraz priorytety gier
  app      - ustawienia programu (settings.json) i Twoje pliki w folderze config
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from . import paths

log = logging.getLogger(__name__)
IS_WINDOWS = os.name == "nt"
_NOWIN = 0x08000000

PARTS: dict[str, tuple[str, str]] = {
    "roblox": ("Roblox i Studio", "Ustawienia FastFlag i limit FPS obu programów."),
    "windows": ("Ustawienia Windows", "Wpisy rejestru zmieniane przez program oraz plan zasilania."),
    "games": ("Ustawienia gier", "Preferencje GPU, pełny ekran i priorytety gier."),
    "app": ("Ustawienia tego programu", "Twoje ustawienia, automatyzacja i pliki w folderze config."),
}

_GUID = re.compile(r"^[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}$")
_SAFE_NAME = re.compile(r"^[A-Za-z0-9_\-][A-Za-z0-9_.\-]{0,78}\.(json|reg|txt)$")   # bez '.', '..' i dziwnych rozszerzeń
_SAFE_TARGET = re.compile(r"^[A-Za-z0-9_\-]{1,60}(\.user)?\.json$")                 # pliki z folderu config
_KINDS = {"roblox_player", "roblox_studio", "registry", "power", "app_settings", "app_config"}
MAX_FILE = 8 * 1024 * 1024


def snapshots_dir() -> Path:
    return paths.backups_dir() / "Snapshots"


@dataclass
class Snapshot:
    id: str
    path: Path
    created: float
    label: str
    parts: list[str]
    files: list[dict] = field(default_factory=list)

    @property
    def size(self) -> int:
        return sum(int(f.get("size", 0)) for f in self.files)


# --------------------------------------------------------------------------- pomocnicze
def _sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _run(cmd: list[str], timeout: int = 60) -> tuple[int, str]:
    try:
        from .ps import system_exe
        exe = cmd[0] if os.path.isabs(cmd[0]) else system_exe(cmd[0])
        r = subprocess.run([exe, *cmd[1:]], capture_output=True, text=True, errors="ignore", timeout=timeout,
                           creationflags=_NOWIN if IS_WINDOWS else 0)
        return r.returncode, (r.stdout or "") + (r.stderr or "")
    except Exception as e:  # noqa: BLE001
        return 1, str(e)


def _sys32(name: str) -> str:
    """Pełna ścieżka do narzędzia systemowego - nie wywołujemy programów po samej nazwie (podmiana w CWD/PATH)."""
    from . import ps
    return ps.system_exe(name)


# --------------------------------------------------------------------------- walidacja .reg
_REG_HIVES = {"HKEY_LOCAL_MACHINE": "HKLM", "HKEY_CURRENT_USER": "HKCU"}


def _allowed_reg_prefixes() -> list[str]:
    from . import games as gm
    keys = [k.lower() for k in registry_keys()]
    keys += [f"hkcu\\{gm.GPU_KEY}".lower(), f"hkcu\\{gm.LAYERS_KEY}".lower()]
    return keys


def validate_reg(path: Path) -> str:
    """Zwraca opis problemu albo '' gdy plik .reg dotyka tylko kluczy, które program sam zmienia.
    Odrzuca: usuwanie kluczy ([-...]), klucze spoza listy, nagłówki inne niż wersja 5.00, pliki > MAX_FILE."""
    from . import games as gm
    try:
        raw = path.read_bytes()
    except OSError:
        return "nie można odczytać"
    if len(raw) > MAX_FILE:
        return "plik za duży"
    text = raw.decode("utf-16", "ignore") if raw[:2] in (b"\xff\xfe", b"\xfe\xff") else raw.decode("utf-8", "ignore")
    text = text.lstrip("\ufeff")
    first = next((ln.strip() for ln in text.splitlines() if ln.strip()), "")
    if first != "Windows Registry Editor Version 5.00":
        return "nieprawidłowy nagłówek"
    allowed = _allowed_reg_prefixes()
    ifeo = ("hklm\\" + gm.IFEO_KEY).lower() + "\\"
    n = 0
    for ln in text.splitlines():
        ln = ln.strip()
        if ln.startswith("[-"):
            return "usuwanie kluczy"
        if ln.startswith("[") and ln.endswith("]"):
            n += 1
            key = ln[1:-1]
            hive, _, rest = key.partition("\\")
            short = _REG_HIVES.get(hive.upper())
            if not short:
                return "obcy gałąź rejestru"
            full = (short + "\\" + rest).lower()
            ok = any(full == a or full.startswith(a + "\\") for a in allowed)
            if not ok and full.startswith(ifeo):
                m = re.fullmatch(r"([^\\]+)\\perfoptions", full[len(ifeo):])
                ok = bool(m) and gm.safe_exe_name(m.group(1))
            if not ok:
                return "klucz spoza listy: " + key[:60]
    return "" if n else "brak kluczy"


def registry_keys(games: Optional[list[dict]] = None) -> list[str]:
    """Pełne nazwy kluczy (HKLM\\… / HKCU\\…) obejmowane kopią 'windows' i 'games'."""
    from . import games as gm, winsys
    keys: list[str] = []
    for t in winsys.TWEAKS:
        for v in t.values:
            keys.append(f"{v.hive}\\{v.key}")
    seen, out = set(), []
    for k in keys:
        if k.lower() not in seen:
            seen.add(k.lower())
            out.append(k)
    return out


def game_registry_keys(games: list[dict]) -> list[str]:
    from . import games as gm
    keys = [f"HKCU\\{gm.GPU_KEY}", f"HKCU\\{gm.LAYERS_KEY}"]
    for g in games:
        if g.get("kind", "").startswith("roblox"):
            continue
        for e in g.get("exes", []):
            if re.fullmatch(r"[A-Za-z0-9_.\- ]{1,80}\.exe", e):
                keys.append(f"HKLM\\{gm.IFEO_KEY}\\{e}\\PerfOptions")
    return keys


def _export_reg(key: str, dest: Path) -> bool:
    """reg export <klucz> <plik>. Brak klucza = nic do zabezpieczenia (nie błąd)."""
    if not IS_WINDOWS:
        return False
    rc, _ = _run(["reg", "export", key, str(dest), "/y"])
    return rc == 0 and dest.exists()


def _merge_reg(files: list[Path], dest: Path) -> bool:
    """Skleja wiele eksportów .reg w jeden plik (jeden nagłówek)."""
    parts = []
    for f in files:
        try:
            raw = f.read_bytes()
        except OSError:
            continue
        text = raw.decode("utf-16", "ignore") if raw[:2] in (b"\xff\xfe", b"\xfe\xff") else raw.decode("utf-8", "ignore")
        parts.append(text.replace("Windows Registry Editor Version 5.00", "").strip())
    if not parts:
        return False
    dest.write_bytes(("﻿Windows Registry Editor Version 5.00\r\n\r\n" + "\r\n\r\n".join(parts) + "\r\n").encode("utf-16-le"))
    return True


# --------------------------------------------------------------------------- tworzenie
def create(parts: list[str], *, settings_path: Optional[Path] = None, roblox_settings: Optional[dict[str, Path]] = None,
           games: Optional[list[dict]] = None, label: str = "", root: Optional[Path] = None) -> Snapshot:
    """Tworzy kopię wskazanych części. `roblox_settings`: {"player": Path, "studio": Path}."""
    parts = [p for p in parts if p in PARTS]
    if not parts:
        raise ValueError("Zaznacz, co chcesz zabezpieczyć.")
    base = root or snapshots_dir()
    base.mkdir(parents=True, exist_ok=True)
    sid = time.strftime("%Y-%m-%d_%H-%M-%S")
    d = base / sid
    n = 1
    while d.exists():
        d = base / f"{sid}_{n}"
        n += 1
    d.mkdir()
    files: list[dict] = []

    def add(name: str, kind: str, target: str = "") -> None:
        p = d / name
        if p.exists():
            files.append({"name": name, "kind": kind, "target": target, "sha256": _sha256(p), "size": p.stat().st_size})

    try:
        if "roblox" in parts:
            for kind, src in (roblox_settings or {}).items():
                if src and Path(src).is_file() and Path(src).stat().st_size <= MAX_FILE:
                    shutil.copy2(src, d / f"roblox_{kind}.json")
                    add(f"roblox_{kind}.json", f"roblox_{kind}")
        if "windows" in parts:
            tmp = []
            for i, k in enumerate(registry_keys()):
                f = d / f"_w{i}.tmp"
                if _export_reg(k, f):
                    tmp.append(f)
            if _merge_reg(tmp, d / "windows.reg"):
                add("windows.reg", "registry")
            for f in tmp:
                f.unlink(missing_ok=True)
            rc, out = _run(["powercfg", "/getactivescheme"]) if IS_WINDOWS else (1, "")
            m = re.search(r"[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}", out)
            if m:
                (d / "power.txt").write_text(m.group(0).lower(), encoding="ascii")
                add("power.txt", "power")
        if "games" in parts:
            tmp = []
            for i, k in enumerate(game_registry_keys(games or [])):
                f = d / f"_g{i}.tmp"
                if _export_reg(k, f):
                    tmp.append(f)
            if _merge_reg(tmp, d / "games.reg"):
                add("games.reg", "registry")
            for f in tmp:
                f.unlink(missing_ok=True)
        if "app" in parts:
            sp = Path(settings_path) if settings_path else paths.settings_file()
            if sp.is_file():
                shutil.copy2(sp, d / "settings.json")
                add("settings.json", "app_settings")
            cfg = paths.config_dir()
            if cfg.is_dir():
                for p in sorted(cfg.glob("*.json"))[:20]:
                    if p.is_file() and p.stat().st_size <= MAX_FILE and _SAFE_TARGET.match(p.name):
                        shutil.copy2(p, d / f"config_{p.name}")
                        add(f"config_{p.name}", "app_config", p.name)
        manifest = {"version": 1, "created": time.time(), "label": label[:80], "parts": parts, "files": files}
        (d / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception:
        shutil.rmtree(d, ignore_errors=True)
        raise
    log.info("Utworzono kopię zapasową %s (%d plików)", d.name, len(files))
    return Snapshot(d.name, d, manifest["created"], manifest["label"], parts, files)


# --------------------------------------------------------------------------- lista / odczyt
def load(d: Path) -> Optional[Snapshot]:
    try:
        m = json.loads((d / "manifest.json").read_text(encoding="utf-8"))
        files = [f for f in m.get("files", []) if isinstance(f, dict) and _SAFE_NAME.match(str(f.get("name", "")))
                 and f.get("kind") in _KINDS and (f.get("kind") != "app_config" or _SAFE_TARGET.match(str(f.get("target", ""))))]
        return Snapshot(d.name, d, float(m["created"]), str(m.get("label", "")),
                        [p for p in m.get("parts", []) if p in PARTS], files)
    except Exception:
        return None


def list_snapshots(root: Optional[Path] = None) -> list[Snapshot]:
    base = root or snapshots_dir()
    out = []
    if base.is_dir():
        for d in base.iterdir():
            if d.is_dir() and not d.is_symlink():
                s = load(d)
                if s:
                    out.append(s)
    return sorted(out, key=lambda s: s.created, reverse=True)


def delete(s: Snapshot) -> None:
    if s.path.is_dir() and not s.path.is_symlink() and s.path.parent.name == "Snapshots":
        shutil.rmtree(s.path, ignore_errors=True)


def prune(keep: int = 20, root: Optional[Path] = None) -> None:
    for s in list_snapshots(root)[keep:]:
        delete(s)


# --------------------------------------------------------------------------- przywracanie
def verify(s: Snapshot) -> list[str]:
    """Zwraca listę problemów (pusta = kopia nienaruszona)."""
    bad = []
    for f in s.files:
        p = s.path / f["name"]
        try:
            if p.is_symlink() or not p.is_file() or _sha256(p) != f.get("sha256"):
                bad.append(f["name"])
        except OSError:
            bad.append(f["name"])
    return bad


def restore(s: Snapshot, parts: Optional[list[str]] = None, *, roblox_targets: Optional[dict[str, Path]] = None,
            settings_path: Optional[Path] = None) -> list[str]:
    """Przywraca wybrane części. Zwraca listę komunikatów. Błąd integralności przerywa wszystko przed zmianami."""
    bad = verify(s)
    if bad:
        raise RuntimeError("Kopia jest uszkodzona lub zmieniona (" + ", ".join(bad[:3]) + "). Nie przywracam.")
    want = set(parts) if parts else set(s.parts)
    msgs: list[str] = []
    for f in s.files:
        kind, p = f["kind"], s.path / f["name"]
        if kind.startswith("roblox_") and "roblox" in want:
            tgt = (roblox_targets or {}).get(kind.split("_", 1)[1])
            if tgt:
                Path(tgt).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(p, tgt)
                msgs.append(f"Przywrócono ustawienia: {kind.split('_', 1)[1]}.")
            else:
                msgs.append(f"Pominięto {kind}: nie znaleziono zainstalowanego programu.")
        elif kind == "registry" and (("windows" in want and f["name"] == "windows.reg") or ("games" in want and f["name"] == "games.reg")):
            if not IS_WINDOWS:
                msgs.append("Import rejestru działa tylko w Windows.")
                continue
            # Import dopiero po sprawdzeniu ZAWARTOŚCI: kopia pliku do prywatnego folderu, walidacja kluczy, import tej kopii.
            tmpd = Path(tempfile.mkdtemp(prefix="pou_reg_"))
            try:
                safe = tmpd / "import.reg"
                shutil.copy2(p, safe)
                problem = validate_reg(safe)
                if problem:
                    raise RuntimeError("Plik rejestru w kopii zawiera niedozwolone wpisy (" + problem + "). Nie przywracam.")
                rc, out = _run([_sys32("reg.exe"), "import", str(safe)])
            finally:
                shutil.rmtree(tmpd, ignore_errors=True)
            msgs.append("Przywrócono wpisy rejestru." if rc == 0 else
                        "Część wpisów rejestru wymaga uruchomienia programu jako administrator.")
        elif kind == "power" and "windows" in want:
            guid = p.read_text(encoding="ascii", errors="ignore").strip()
            if _GUID.match(guid) and IS_WINDOWS:
                rc, _ = _run([_sys32("powercfg.exe"), "-setactive", guid])
                msgs.append("Przywrócono plan zasilania." if rc == 0 else "Nie udało się przywrócić planu zasilania.")
        elif kind == "app_settings" and "app" in want:
            dst = Path(settings_path) if settings_path else paths.settings_file()
            shutil.copy2(p, dst)
            msgs.append("Przywrócono ustawienia programu (uruchom program ponownie).")
        elif kind == "app_config" and "app" in want and _SAFE_TARGET.match(str(f.get("target", ""))):
            cfg = paths.config_dir()
            cfg.mkdir(parents=True, exist_ok=True)
            dst = cfg / f["target"]
            if dst.resolve().parent != cfg.resolve() or dst.is_symlink():
                raise RuntimeError("Nieprawidłowy cel przywracania pliku konfiguracji.")
            shutil.copy2(p, dst)
            msgs.append(f"Przywrócono plik konfiguracji {f['target']}.")
    return msgs or ["Nie było nic do przywrócenia w wybranych częściach."]

"""Aktualizacje w stylu Discorda/Squirrel.

Układ instalacji:
    %LOCALAPPDATA%\\ProUltimateOptimizer\\
        ProUltimateOptimizer.exe        <- launcher (skróty wskazują na niego)
        app-4.0.0\\ProUltimateOptimizerApp.exe
        app-4.1.0\\...                  <- nowa wersja wchodzi OBOK, nic nie nadpisuje
        Backups\\  config\\  logs\\  settings.json   <- dane użytkownika, przetrwają aktualizacje

Przepływ: pobranie podpisanego manifestu -> weryfikacja podpisu -> pobranie paczki ->
weryfikacja SHA-256 -> rozpakowanie do app-X.Y.Z.partial -> zmiana nazwy na app-X.Y.Z.
Launcher przy następnym starcie uruchamia najnowszy folder (a gdy ten się wywala - poprzedni).
Działająca aplikacja nigdy nie jest nadpisywana, więc nie ma problemu z zablokowanymi plikami.
"""
from __future__ import annotations

import logging
import re
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from . import paths
from .security import (DEFAULT_POLICY, FetchPolicy, SecurityError, download_file, fetch_bytes,
                       safe_extract, sha256_file, verify_manifest)
from .update_key import PUBLIC_KEY_HEX
from .version import APP_EXE, VERSION, parse_version

log = logging.getLogger(__name__)

MANIFEST_URL = "https://raw.githubusercontent.com/diabel777/roblox-optimizer/main/version.json"
MAX_PACKAGE_BYTES = 400 * 1024 * 1024
_VERSION_RE = re.compile(r"^\d+(\.\d+){1,3}$")


class UpdateError(Exception):
    pass


@dataclass
class UpdateInfo:
    version: str
    url: str
    sha256: str
    size: int
    notes: str = ""


def installed_versions(root: Optional[Path] = None) -> list[tuple[tuple, Path]]:
    root = root or paths.install_root()
    out = []
    if root.exists():
        for d in root.iterdir():
            m = re.fullmatch(r"app-(\d+(?:\.\d+)*)", d.name)
            if m and d.is_dir() and (d / APP_EXE).exists():
                out.append((parse_version(m.group(1)), d))
    return sorted(out, key=lambda t: t[0])


class Updater:
    def __init__(self, current_version: str = VERSION, root: Optional[Path] = None,
                 policy: FetchPolicy = DEFAULT_POLICY, public_key_hex: str = PUBLIC_KEY_HEX,
                 manifest_url: str = MANIFEST_URL):
        self.current = current_version
        self.root = Path(root) if root else paths.install_root()
        self.policy = policy
        self.public_key_hex = public_key_hex
        self.manifest_url = manifest_url

    # ---- sprawdzanie
    def check(self) -> Optional[UpdateInfo]:
        """Zwraca UpdateInfo gdy jest NOWSZA wersja, inaczej None. Rzuca UpdateError/SecurityError."""
        if not self.public_key_hex:      # bez klucza nie ma sensu nawet pytać serwera
            raise SecurityError("Brak klucza publicznego - aktualizacje wyłączone (uruchom: tools/release.py keygen)")
        url = f"{self.manifest_url}?t={int(time.time())}"  # omija cache CDN
        try:
            raw = fetch_bytes(url, self.policy, max_bytes=64 * 1024, timeout=8)
        except SecurityError:
            raise
        except Exception as e:
            raise UpdateError(f"Nie udało się pobrać informacji o aktualizacji: {e}") from e
        m = verify_manifest(raw, self.public_key_hex)
        ver = str(m.get("version", ""))
        pkg = m.get("package") or {}
        if not _VERSION_RE.match(ver):
            raise SecurityError(f"Nieprawidłowy numer wersji w manifeście: {ver!r}")
        if parse_version(ver) <= parse_version(self.current):   # nigdy nie cofamy wersji
            return None
        try:
            info = UpdateInfo(ver, str(pkg["url"]), str(pkg["sha256"]).lower(), int(pkg["size"]),
                              str(m.get("notes", "")))
        except Exception as e:
            raise SecurityError(f"Manifest nie zawiera poprawnego opisu paczki: {e}") from e
        if not re.fullmatch(r"[0-9a-f]{64}", info.sha256) or not 0 < info.size <= MAX_PACKAGE_BYTES:
            raise SecurityError("Manifest zawiera nieprawidłowy hash lub rozmiar paczki")
        if (self.root / f"app-{ver}" / ".bad").exists():   # ta wersja już się wywaliła - nie zapętlamy
            log.warning("Wersja %s została oznaczona jako uszkodzona - pomijam", ver)
            return None
        return info

    # ---- pobranie i przygotowanie
    def stage(self, info: UpdateInfo, progress: Optional[Callable[[int, int], None]] = None) -> Path:
        """Pobiera, weryfikuje i rozpakowuje wersję do app-X.Y.Z. Zwraca katalog."""
        final = self.root / f"app-{info.version}"
        if (final / APP_EXE).exists():
            return final
        dl = self.root / "downloads"
        dl.mkdir(parents=True, exist_ok=True)
        zip_path = dl / f"{info.version}.zip"
        part = self.root / f"app-{info.version}.partial"
        try:
            got = download_file(info.url, zip_path, self.policy, max_bytes=min(info.size + 1024, MAX_PACKAGE_BYTES),
                                progress=progress)
            if got != info.sha256:
                raise SecurityError("Suma kontrolna SHA-256 paczki nie zgadza się z manifestem - odrzucono")
            if part.exists():
                shutil.rmtree(part, ignore_errors=True)
            safe_extract(zip_path, part)
            if not (part / APP_EXE).exists():
                raise UpdateError("Paczka nie zawiera pliku aplikacji")
            if final.exists():
                shutil.rmtree(final, ignore_errors=True)
            part.rename(final)
            log.info("Zainstalowano wersję %s w %s", info.version, final)
            return final
        except Exception:
            shutil.rmtree(part, ignore_errors=True)
            raise
        finally:
            try:
                zip_path.unlink(missing_ok=True)
            except OSError:
                pass

    def cleanup_old(self, keep: int = 2) -> None:
        """Zostawia `keep` najnowszych wersji (bieżąca + jedna do wycofania)."""
        vers = installed_versions(self.root)
        for _, d in vers[:-keep] if keep else vers:
            if d.name == f"app-{self.current}":
                continue
            shutil.rmtree(d, ignore_errors=True)
        for p in self.root.glob("app-*.partial"):
            shutil.rmtree(p, ignore_errors=True)

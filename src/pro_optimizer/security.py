"""Warstwa bezpieczeństwa: bezpieczne pobieranie, weryfikacja podpisu, bezpieczne rozpakowanie.

Zasady:
  * tylko HTTPS i tylko zaufane hosty (także po każdym przekierowaniu),
  * manifest aktualizacji musi mieć poprawny podpis Ed25519,
  * paczka musi zgadzać się z SHA-256 z podpisanego manifestu,
  * rozpakowanie odporne na zip-slip, symlinki i zip-bomby.
"""
from __future__ import annotations

import hashlib
import json
import re
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Callable, Optional

from . import ed25519

DEFAULT_HOSTS = frozenset({
    "raw.githubusercontent.com",
    "github.com",
    "objects.githubusercontent.com",
    "release-assets.githubusercontent.com",
})

USER_AGENT = "ProUltimateOptimizer-Updater/4"


class SecurityError(Exception):
    """Naruszenie zasad bezpieczeństwa (zły host, zły podpis, zły hash, złośliwe archiwum)."""


@dataclass(frozen=True)
class FetchPolicy:
    allowed_hosts: frozenset = DEFAULT_HOSTS
    require_https: bool = True


DEFAULT_POLICY = FetchPolicy()


def check_url(url: str, policy: FetchPolicy = DEFAULT_POLICY) -> None:
    u = urllib.parse.urlsplit(url)
    if policy.require_https and u.scheme != "https":
        raise SecurityError(f"Niedozwolony protokół: {u.scheme!r} (wymagany https)")
    if u.scheme not in ("https", "http"):
        raise SecurityError(f"Niedozwolony protokół: {u.scheme!r}")
    if u.username or u.password:
        raise SecurityError("Adres z danymi logowania jest niedozwolony")
    host = (u.hostname or "").lower()
    if host not in policy.allowed_hosts:
        raise SecurityError(f"Host spoza listy zaufanych: {host!r}")


class _SafeRedirect(urllib.request.HTTPRedirectHandler):
    def __init__(self, policy: FetchPolicy):
        self.policy = policy

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        check_url(newurl, self.policy)  # każdy przeskok też musi być zaufany
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _open(url: str, policy: FetchPolicy, timeout: float):
    check_url(url, policy)
    opener = urllib.request.build_opener(_SafeRedirect(policy))
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Cache-Control": "no-cache"})
    return opener.open(req, timeout=timeout)


def fetch_bytes(url: str, policy: FetchPolicy = DEFAULT_POLICY, max_bytes: int = 1_000_000,
                timeout: float = 10.0) -> bytes:
    with _open(url, policy, timeout) as r:
        data = r.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise SecurityError("Odpowiedź serwera jest zbyt duża")
    return data


def download_file(url: str, dest: Path, policy: FetchPolicy = DEFAULT_POLICY, *, max_bytes: int,
                  progress: Optional[Callable[[int, int], None]] = None, timeout: float = 20.0) -> str:
    """Pobiera strumieniowo do `dest`, zwraca SHA-256. Nie ładuje całości do pamięci."""
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    h = hashlib.sha256()
    done = 0
    with _open(url, policy, timeout) as r, open(dest, "wb") as out:
        total = int(r.headers.get("Content-Length") or 0)
        if total and total > max_bytes:
            raise SecurityError("Paczka jest większa niż zadeklarowano w manifeście")
        while True:
            chunk = r.read(256 * 1024)
            if not chunk:
                break
            done += len(chunk)
            if done > max_bytes:
                raise SecurityError("Paczka przekroczyła dozwolony rozmiar")
            h.update(chunk)
            out.write(chunk)
            if progress:
                progress(done, total or max_bytes)
    return h.hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# --------------------------------------------------------------------------- manifest
def canonical_json(obj: dict) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def sign_manifest(manifest: dict, secret: bytes) -> dict:
    body = {k: v for k, v in manifest.items() if k != "signature"}
    out = dict(body)
    out["signature"] = ed25519.sign(secret, canonical_json(body)).hex()
    return out


def verify_manifest(raw: bytes, public_key_hex: str) -> dict:
    """Zwraca zweryfikowany manifest albo rzuca SecurityError."""
    if not public_key_hex:
        raise SecurityError("Brak klucza publicznego - aktualizacje wyłączone (uruchom: tools/release.py keygen)")
    try:
        data = json.loads(raw.decode("utf-8"))
        sig = bytes.fromhex(data.pop("signature"))
        pub = bytes.fromhex(public_key_hex)
    except Exception as e:
        raise SecurityError(f"Uszkodzony manifest: {e}") from e
    if not ed25519.verify(pub, canonical_json(data), sig):
        raise SecurityError("Nieprawidłowy podpis manifestu - aktualizacja odrzucona")
    return data


# --------------------------------------------------------------------------- zip
_DRIVE = re.compile(r"^[A-Za-z]:")


def safe_extract(zip_path: Path, dest: Path, *, max_total: int = 900 * 1024 * 1024,
                 max_files: int = 20000) -> int:
    """Rozpakowuje zip odpornie na zip-slip / symlinki / zip-bomby. Zwraca liczbę plików."""
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    root = dest.resolve()
    written_total = 0
    count = 0
    with zipfile.ZipFile(zip_path) as z:
        infos = z.infolist()
        if len(infos) > max_files:
            raise SecurityError("Archiwum zawiera zbyt wiele plików")
        if sum(i.file_size for i in infos) > max_total:
            raise SecurityError("Archiwum rozpakowuje się do zbyt dużego rozmiaru")
        for info in infos:
            name = info.filename.replace("\\", "/")
            parts = PurePosixPath(name).parts
            if name.startswith("/") or _DRIVE.match(name) or ".." in parts:
                raise SecurityError(f"Niebezpieczna ścieżka w archiwum: {info.filename!r}")
            if (info.external_attr >> 16) & 0o170000 == 0o120000:
                raise SecurityError(f"Symlinki w archiwum są niedozwolone: {info.filename!r}")
            target = (root / name).resolve()
            if root != target and root not in target.parents:
                raise SecurityError(f"Ścieżka wychodzi poza katalog docelowy: {info.filename!r}")
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with z.open(info) as src, open(target, "wb") as out:
                while True:
                    chunk = src.read(1 << 20)
                    if not chunk:
                        break
                    written_total += len(chunk)
                    if written_total > max_total:
                        raise SecurityError("Przekroczono limit rozpakowanych danych")
                    out.write(chunk)
            count += 1
    return count

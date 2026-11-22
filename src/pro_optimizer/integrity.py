"""Kontrola integralności: lista plików aplikacji z sumami SHA-256 jest podpisana kluczem wydawcy (Ed25519).
Przy starcie sprawdzamy, czy ktoś nie podmienił / nie dopisał pliku w folderze aplikacji (np. złośliwy wstrzyknięty kod).
To wykrywanie manipulacji, nie szyfrowanie - ale bez klucza prywatnego nie da się wygenerować poprawnego podpisu."""
from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path

from . import security
from .update_key import PUBLIC_KEY_HEX

log = logging.getLogger(__name__)
FILE = "integrity.json"
IGNORED_PREFIXES = (".",)        # np. .bad zapisywany przez launcher


def _skip(rel: str) -> bool:
    return rel == FILE or any(part.startswith(IGNORED_PREFIXES) for part in rel.split("/")) or rel.endswith(".pyc") and "__pycache__" in rel


def hash_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def build(app_dir: Path, secret: bytes) -> dict:
    """Używane przez tools/release.py - zwraca podpisany słownik do zapisania jako integrity.json."""
    files = {}
    for f in sorted(Path(app_dir).rglob("*")):
        if f.is_file():
            rel = f.relative_to(app_dir).as_posix()
            if not _skip(rel):
                files[rel] = hash_file(f)
    return security.sign_manifest({"files": files}, secret)


def verify(app_dir: Path, public_key_hex: str = PUBLIC_KEY_HEX) -> dict:
    """Zwraca {'ok': bool, 'checked': int, 'modified': [...], 'missing': [...], 'extra': [...], 'reason': str}."""
    app_dir = Path(app_dir)
    res = {"ok": True, "checked": 0, "modified": [], "missing": [], "extra": [], "reason": ""}
    p = app_dir / FILE
    if not p.exists():
        return dict(res, ok=False, reason="brak pliku integralności")
    try:
        data = security.verify_manifest(p.read_bytes(), public_key_hex)
        files = data["files"]
    except Exception as e:  # noqa: BLE001
        return dict(res, ok=False, reason=f"podpis listy plików jest nieprawidłowy ({e})")
    seen = set()
    for rel, digest in files.items():
        fp = app_dir / rel
        seen.add(rel)
        if not fp.is_file():
            res["missing"].append(rel)
        elif hash_file(fp) != digest:
            res["modified"].append(rel)
        res["checked"] += 1
    for f in app_dir.rglob("*"):
        if f.is_file():
            rel = f.relative_to(app_dir).as_posix()
            if rel not in seen and not _skip(rel):
                res["extra"].append(rel)
    res["ok"] = not (res["modified"] or res["missing"] or res["extra"])
    if not res["ok"]:
        res["reason"] = f"zmienione: {len(res['modified'])}, brakujące: {len(res['missing'])}, dodatkowe: {len(res['extra'])}"
    return res


def check_running_app() -> dict | None:
    """Sprawdza folder, z którego działa zbudowana aplikacja. W trybie deweloperskim zwraca None."""
    import sys
    if not getattr(sys, "frozen", False):
        return None
    return verify(Path(sys.executable).parent)

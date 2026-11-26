"""Konto Aderis w chmurze: logowanie kodem z witryny, synchronizacja testów internetu / kopii zapasowych i asystent AI.

Bezpieczeństwo:
- adres serwera jest stałą w kodzie (nie da się go podmienić plikiem ani ustawieniem), tylko HTTPS, bez przekierowań;
- token urządzenia leży w pliku zaszyfrowanym przez Windows DPAPI (czyta go tylko Twoje konto Windows na tym komputerze),
  NIE w settings.json i NIE trafia do kopii zapasowych;
- limity rozmiaru odpowiedzi, krótkie timeouty; błąd chmury nigdy nie przerywa pracy aplikacji."""
from __future__ import annotations

import base64
import io
import json
import logging
import os
import re
import socket
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from typing import Any, Optional

from . import paths
from .version import APP_NAME, VERSION

log = logging.getLogger(__name__)

CLOUD_BASE = "https://aderis-boost.dev-pl.workers.dev"
MAX_RESPONSE = 3 * 1024 * 1024
MAX_UPLOAD = 1_400_000                      # znaków (base64) - zgodnie z limitem serwera
TOKEN_RE = re.compile(r"^[0-9a-f]{64}$")
CODE_RE = re.compile(r"^[A-Z2-9]{10}$")


class CloudError(Exception):
    def __init__(self, message: str, status: int = 0):
        super().__init__(message)
        self.status = status


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


_opener = urllib.request.build_opener(_NoRedirect)


# --------------------------------------------------------------------------- token (DPAPI)
def _token_file() -> Path:
    return paths.install_root() / "cloud.bin"


def _protect(data: bytes) -> bytes:
    if os.name != "nt":
        return base64.b64encode(data)
    import ctypes
    from ctypes import wintypes

    class BLOB(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]
    buf = ctypes.create_string_buffer(data, len(data))
    inb, outb = BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char))), BLOB()
    if not ctypes.windll.crypt32.CryptProtectData(ctypes.byref(inb), "AderisBoost", None, None, None, 0, ctypes.byref(outb)):
        raise OSError("DPAPI: nie udało się zaszyfrować tokenu")
    try:
        return ctypes.string_at(outb.pbData, outb.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(outb.pbData)


def _unprotect(data: bytes) -> bytes:
    if os.name != "nt":
        return base64.b64decode(data)
    import ctypes
    from ctypes import wintypes

    class BLOB(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]
    buf = ctypes.create_string_buffer(data, len(data))
    inb, outb = BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char))), BLOB()
    if not ctypes.windll.crypt32.CryptUnprotectData(ctypes.byref(inb), None, None, None, None, 0, ctypes.byref(outb)):
        raise OSError("DPAPI: nie udało się odczytać tokenu")
    try:
        return ctypes.string_at(outb.pbData, outb.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(outb.pbData)


def save_account(token: str, nick: str, email: str) -> None:
    if not TOKEN_RE.match(token):
        raise CloudError("Serwer zwrócił nieprawidłowy token.")
    f = _token_file()
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_bytes(_protect(json.dumps({"token": token, "nick": nick, "email": email}).encode("utf-8")))


def load_account() -> Optional[dict]:
    try:
        d = json.loads(_unprotect(_token_file().read_bytes()).decode("utf-8"))
        return d if isinstance(d, dict) and TOKEN_RE.match(str(d.get("token", ""))) else None
    except Exception:
        return None


def is_linked() -> bool:
    return load_account() is not None


def logout() -> None:
    try:
        _token_file().unlink(missing_ok=True)
    except OSError:
        pass


# --------------------------------------------------------------------------- HTTP
def _request(method: str, path: str, body: Optional[dict] = None, token: Optional[str] = None, timeout: float = 25.0) -> dict:
    if not path.startswith("/api/"):
        raise CloudError("Niedozwolony adres.")
    headers = {"User-Agent": f"{APP_NAME}/{VERSION}", "Accept": "application/json"}
    data = None
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = "Bearer " + token
    req = urllib.request.Request(CLOUD_BASE + path, data=data, method=method, headers=headers)
    try:
        with _opener.open(req, timeout=timeout) as r:
            raw = r.read(MAX_RESPONSE + 1)
    except urllib.error.HTTPError as e:
        raw = e.read(65536)
        msg = ""
        try:
            msg = json.loads(raw.decode("utf-8", "replace")).get("error", "")
        except Exception:
            pass
        raise CloudError(msg or f"Błąd serwera ({e.code})", e.code)
    except (urllib.error.URLError, socket.timeout, OSError):
        raise CloudError("Brak połączenia z serwerem Aderis. Sprawdź internet i spróbuj za chwilę.")
    if len(raw) > MAX_RESPONSE:
        raise CloudError("Odpowiedź serwera jest zbyt duża.")
    try:
        out = json.loads(raw.decode("utf-8"))
    except ValueError:
        raise CloudError("Serwer zwrócił nieczytelną odpowiedź.")
    if not isinstance(out, dict) or not out.get("ok", False):
        raise CloudError(str((out or {}).get("error") or "Nie udało się."))
    return out


def _auth() -> str:
    acc = load_account()
    if not acc:
        raise CloudError("Najpierw zaloguj się kodem w Ustawieniach.", 401)
    return acc["token"]


def _authed(method: str, path: str, body: Optional[dict] = None, timeout: float = 25.0) -> dict:
    try:
        return _request(method, path, body, _auth(), timeout)
    except CloudError as e:
        if e.status == 401:
            logout()                             # token unieważniony (np. odłączono urządzenie na stronie)
        raise


# --------------------------------------------------------------------------- konto
def normalize_code(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9]", "", text or "").upper()


def link(code: str, device_name: str) -> dict:
    c = normalize_code(code)
    if not CODE_RE.match(c):
        raise CloudError("Kod ma 10 znaków (litery i cyfry), np. ABCDE-23456.")
    out = _request("POST", "/api/device/link", {"code": c, "name": device_name[:40] or "Komputer"})
    save_account(str(out.get("token", "")), str(out.get("nick", "")), str(out.get("email_masked", "")))
    return {"nick": out.get("nick", ""), "email": out.get("email_masked", "")}


def me() -> dict:
    return _authed("GET", "/api/app/me")


def device_name() -> str:
    return re.sub(r"[^\w .-]", "", os.environ.get("COMPUTERNAME") or socket.gethostname() or "Komputer")[:40] or "Komputer"


# --------------------------------------------------------------------------- dane
def put_item(kind: str, name: str, data: str, meta: Optional[dict] = None) -> int:
    if len(data) > MAX_UPLOAD:
        raise CloudError("Dane są za duże, żeby wysłać je do chmury.")
    out = _authed("POST", "/api/app/items", {"kind": kind, "name": name[:80], "data": data, "meta": meta or {}}, timeout=60)
    return int(out.get("id", 0))


def list_items(kind: str) -> list[dict]:
    return list(_authed("GET", f"/api/app/items?kind={kind}").get("items", []))


def get_item(item_id: int) -> dict:
    return dict(_authed("GET", f"/api/app/items/{int(item_id)}", timeout=60).get("item", {}))


def delete_item(item_id: int) -> None:
    _authed("DELETE", f"/api/app/items/{int(item_id)}")


# --------------------------------------------------------------------------- testy internetu
def sync_speedtest(res: dict) -> int:
    keep = {k: res.get(k) for k in ("time", "down", "up", "ping", "jitter", "loss", "loaded_ping")}
    info = res.get("_info") or {}
    keep["connection"] = info.get("type")
    keep["adapter"] = info.get("adapter")
    keep["link_mbps"] = info.get("link_mbps")
    keep["wifi_signal"] = info.get("wifi_signal")
    name = time.strftime("Test %d.%m.%Y %H:%M", time.localtime(res.get("time") or time.time()))
    meta = {"down": res.get("down"), "up": res.get("up"), "ping": res.get("ping")}
    return put_item("speedtest", name, json.dumps(keep, ensure_ascii=False), meta)


# --------------------------------------------------------------------------- kopie zapasowe (folder -> zip -> base64)
_SAFE_MEMBER = re.compile(r"^[A-Za-z0-9._ -]{1,120}$")


def pack_dir(folder: Path) -> str:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for p in sorted(folder.iterdir()):
            if p.is_file() and not p.is_symlink() and _SAFE_MEMBER.match(p.name):
                z.write(p, p.name)
    out = base64.b64encode(buf.getvalue()).decode("ascii")
    if len(out) > MAX_UPLOAD:
        raise CloudError("Kopia jest za duża na chmurę (limit ok. 1 MB).")
    return out


def unpack_to(data: str, dest: Path) -> int:
    """Rozpakowuje kopię z chmury do pustego folderu. Tylko płaskie, bezpieczne nazwy plików (bez ścieżek)."""
    raw = base64.b64decode(data.encode("ascii"), validate=True)
    n = 0
    dest.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        total = 0
        for info in z.infolist():
            if info.is_dir() or not _SAFE_MEMBER.match(info.filename):
                raise CloudError("Kopia z chmury zawiera niedozwolone pliki - przerwano.")
            total += info.file_size
            if total > 20 * 1024 * 1024:
                raise CloudError("Kopia z chmury jest podejrzanie duża - przerwano.")
            (dest / info.filename).write_bytes(z.read(info))
            n += 1
    return n


def sync_snapshot(s) -> int:
    meta = {"label": s.label, "parts": s.parts, "created": s.created}
    name = (s.label or time.strftime("Kopia %d.%m.%Y %H:%M", time.localtime(s.created)))
    return put_item("backup", name, pack_dir(s.path), meta)


# --------------------------------------------------------------------------- asystent AI
def ask_ai(messages: list[dict], context: dict) -> dict:
    msgs = [{"role": m["role"], "content": str(m["content"])[:4000]} for m in messages[-12:]
            if m.get("role") in ("user", "assistant") and m.get("content")]
    out = _authed("POST", "/api/app/ai", {"messages": msgs, "context": context}, timeout=60)
    acts = [a for a in out.get("actions", []) if isinstance(a, dict) and isinstance(a.get("id"), str)]
    return {"reply": str(out.get("reply", "")), "actions": acts[:4]}

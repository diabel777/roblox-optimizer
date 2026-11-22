"""Uruchamianie PowerShella: skrypt idzie jako -EncodedCommand (UTF-16LE base64) - bez problemów z cudzysłowami i znakami."""
from __future__ import annotations

import base64
import json
import logging
import os
import subprocess
from typing import Any, Optional

log = logging.getLogger(__name__)
IS_WINDOWS = os.name == "nt"
_NOWIN = 0x08000000

PREAMBLE = "$ProgressPreference='SilentlyContinue';$ErrorActionPreference='Stop';[Console]::OutputEncoding=[Text.Encoding]::UTF8;"


def system_exe(name: str) -> str:
    """Pełna ścieżka do programu systemowego (System32). Nie uruchamiamy narzędzi po samej nazwie, bo Windows
    szuka najpierw w bieżącym folderze - ktoś mógłby podłożyć własny reg.exe / powershell.exe obok aplikacji."""
    if not IS_WINDOWS:
        return name
    root = os.environ.get("SystemRoot") or os.environ.get("WINDIR") or r"C:\Windows"
    base = name if name.lower().endswith(".exe") else name + ".exe"
    if base.lower() == "powershell.exe":
        return os.path.join(root, "System32", "WindowsPowerShell", "v1.0", "powershell.exe")
    return os.path.join(root, "System32", base)


def encode(script: str) -> str:
    return base64.b64encode((PREAMBLE + script).encode("utf-16-le")).decode("ascii")


def run(script: str, timeout: int = 60, env: Optional[dict] = None) -> tuple[int, str]:
    """`env` - dodatkowe zmienne środowiskowe dla skryptu (tak przekazujemy dane od użytkownika, nigdy przez sklejanie tekstu)."""
    if not IS_WINDOWS:
        return 1, "PowerShell jest dostępny tylko w Windows."
    try:
        r = subprocess.run([system_exe("powershell"), "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                            "-EncodedCommand", encode(script)],
                           capture_output=True, timeout=timeout, creationflags=_NOWIN,
                           env={**os.environ, **env} if env else None)
        out = (r.stdout or b"").decode("utf-8", "ignore") + (r.stderr or b"").decode("utf-8", "ignore")
        return r.returncode, out.strip()
    except subprocess.TimeoutExpired:
        return 124, "Przekroczono czas oczekiwania."
    except Exception as e:  # noqa: BLE001
        return 1, str(e)


def run_json(script: str, timeout: int = 60) -> tuple[bool, Any]:
    """Skrypt ma wypisać JSON (ConvertTo-Json). Zwraca (ok, dane_lub_komunikat). Pojedynczy obiekt -> lista jednoelementowa."""
    rc, out = run(script, timeout)
    if rc != 0:
        return False, out[:400] or f"kod {rc}"
    out = out.strip()
    if not out:
        return True, []
    try:
        data = json.loads(out)
    except ValueError:
        return False, "Nieczytelna odpowiedź PowerShella."
    return True, data if isinstance(data, list) else [data]

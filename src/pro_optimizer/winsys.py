"""Optymalizacje systemowe Windows - każda zmiana jest odwracalna (oryginał zapisywany w settings.json).

Poza Windowsem moduł się importuje (do testów), ale funkcje rejestru/ctypes zwracają "niedostępne".
"""
from __future__ import annotations

import ctypes
import logging
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field

from .ps import system_exe
from typing import Any, Optional

log = logging.getLogger(__name__)

IS_WINDOWS = os.name == "nt"
_NOWIN = 0x08000000  # CREATE_NO_WINDOW

if IS_WINDOWS:
    import winreg


# --------------------------------------------------------------------------- admin
def is_admin() -> bool:
    if not IS_WINDOWS:
        return os.geteuid() == 0 if hasattr(os, "geteuid") else False
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def relaunch_as_admin() -> bool:
    """Uruchamia aplikację ponownie z UAC. Zwraca True, jeśli użytkownik zatwierdził."""
    if not IS_WINDOWS:
        return False
    exe = sys.executable
    params = "--elevated" if getattr(sys, "frozen", False) else f'"{os.path.abspath(sys.argv[0])}" --elevated'
    rc = ctypes.windll.shell32.ShellExecuteW(None, "runas", exe, params, None, 1)
    return rc > 32


def _run(cmd: list[str], timeout: int = 60) -> tuple[int, str]:
    try:
        r = subprocess.run([system_exe(cmd[0]), *cmd[1:]], capture_output=True, text=True, errors="ignore", timeout=timeout,
                           creationflags=_NOWIN if IS_WINDOWS else 0)
        return r.returncode, (r.stdout or "") + (r.stderr or "")
    except Exception as e:
        return 1, str(e)


# --------------------------------------------------------------------------- statystyki
class _MEMSTAT(ctypes.Structure):
    _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                ("sullAvailExtendedVirtual", ctypes.c_ulonglong)]


def memory_status() -> Optional[tuple[int, int]]:
    """(całkowita, dostępna) pamięć fizyczna w bajtach."""
    if IS_WINDOWS:
        try:
            s = _MEMSTAT()
            s.dwLength = ctypes.sizeof(s)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(s))
            return int(s.ullTotalPhys), int(s.ullAvailPhys)
        except Exception:
            return None
    try:  # Linux - tylko do testów
        info = {}
        with open("/proc/meminfo") as f:
            for line in f:
                k, v = line.split(":")
                info[k] = int(v.split()[0]) * 1024
        return info["MemTotal"], info["MemAvailable"]
    except Exception:
        return None


class _FT(ctypes.Structure):
    _fields_ = [("lo", ctypes.c_ulong), ("hi", ctypes.c_ulong)]


class CpuMeter:
    """Obciążenie CPU w % - różnica pomiędzy kolejnymi wywołaniami sample()."""

    def __init__(self):
        self._last: Optional[tuple[int, int, int]] = None

    def _times(self):
        if IS_WINDOWS:
            i, k, u = _FT(), _FT(), _FT()
            ctypes.windll.kernel32.GetSystemTimes(ctypes.byref(i), ctypes.byref(k), ctypes.byref(u))
            c = lambda t: (t.hi << 32) | t.lo
            return c(i), c(k), c(u)
        with open("/proc/stat") as f:
            v = [int(x) for x in f.readline().split()[1:]]
        return v[3], v[2], v[0]  # idle, kernel, user

    def sample(self) -> Optional[float]:
        try:
            cur = self._times()
        except Exception:
            return None
        last, self._last = self._last, cur
        if not last:
            return None
        di, dk, du = (cur[0] - last[0], cur[1] - last[1], cur[2] - last[2])
        total = dk + du if IS_WINDOWS else (di + dk + du)   # na Windows kernel zawiera idle
        busy = total - di
        return max(0.0, min(100.0, 100.0 * busy / total)) if total > 0 else None


def disk_free() -> Optional[tuple[int, int]]:
    try:
        drive = os.environ.get("SystemDrive", "C:") + "\\" if IS_WINDOWS else "/"
        u = shutil.disk_usage(drive)
        return u.total, u.free
    except Exception:
        return None


# --------------------------------------------------------------------------- RAM
def trim_ram() -> dict:
    """Prawdziwe zmniejszenie working-setów procesów (EmptyWorkingSet). Pomija Robloxa.

    Uwaga: Windows i tak oddaje pamięć na żądanie - efekt jest chwilowy, ale realny i mierzalny.
    """
    if not IS_WINDOWS:
        return {"ok": False, "msg": "Dostępne tylko w Windows."}
    from ctypes import wintypes
    psapi, k32 = ctypes.windll.psapi, ctypes.windll.kernel32
    k32.OpenProcess.restype = wintypes.HANDLE
    before = memory_status()
    arr = (wintypes.DWORD * 4096)()
    needed = wintypes.DWORD()
    if not psapi.EnumProcesses(ctypes.byref(arr), ctypes.sizeof(arr), ctypes.byref(needed)):
        return {"ok": False, "msg": "Nie udało się wyliczyć procesów."}
    own = os.getpid()
    trimmed = 0
    for pid in arr[: needed.value // ctypes.sizeof(wintypes.DWORD)]:
        if pid in (0, 4, own):
            continue
        h = k32.OpenProcess(0x0100 | 0x0400 | 0x0010, False, pid)  # SET_QUOTA|QUERY_INFO|VM_READ
        if not h:
            continue
        try:
            buf = ctypes.create_unicode_buffer(260)
            psapi.GetModuleBaseNameW(h, None, buf, 260)
            if buf.value.lower().startswith("roblox"):
                continue
            if psapi.EmptyWorkingSet(h):
                trimmed += 1
        finally:
            k32.CloseHandle(h)
    time.sleep(0.4)
    after = memory_status()
    freed = max(0, (after[1] - before[1])) if before and after else 0
    return {"ok": True, "freed": freed, "processes": trimmed}


def is_laptop() -> bool:
    """Czy komputer ma baterię (laptop/tablet)."""
    if not IS_WINDOWS:
        return False

    class _SPS(ctypes.Structure):
        _fields_ = [("AC", ctypes.c_ubyte), ("Flag", ctypes.c_ubyte), ("Pct", ctypes.c_ubyte), ("Sav", ctypes.c_ubyte),
                    ("Life", ctypes.c_ulong), ("Full", ctypes.c_ulong)]
    try:
        st = _SPS()
        return bool(ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(st))) and st.Flag != 128
    except Exception:
        return False


# --------------------------------------------------------------------------- sieć
def flush_dns() -> tuple[bool, str]:
    rc, out = _run(["ipconfig", "/flushdns"])
    return rc == 0, "Wyczyszczono pamięć podręczną DNS." if rc == 0 else out.strip()[:300]


def reset_network() -> tuple[bool, str]:
    """Winsock + stos IP + DNS. Wymaga admina i restartu komputera. Zwraca rzeczywisty wynik."""
    if not is_admin():
        return False, "Ta operacja wymaga uprawnień administratora."
    results = []
    for cmd in (["netsh", "winsock", "reset"], ["netsh", "int", "ip", "reset"], ["ipconfig", "/flushdns"]):
        rc, out = _run(cmd)
        results.append(rc == 0)
    ok = all(results)
    return ok, ("Zresetowano Winsock i stos IP. Zrestartuj komputer, aby zmiany zadziałały."
                if ok else "Część poleceń zakończyła się błędem - sprawdź logi.")


# --------------------------------------------------------------------------- tweaki
@dataclass
class RegValue:
    hive: str          # "HKLM" | "HKCU"
    key: str
    name: str
    vtype: str         # "DWORD" | "SZ"
    value: Any


@dataclass
class Tweak:
    id: str
    name: str
    desc: str
    admin: bool = False
    reboot: bool = False
    values: list[RegValue] = field(default_factory=list)
    special: str = ""   # "power"


_SP = r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Multimedia\SystemProfile"
_IFEO = r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Image File Execution Options"

TWEAKS: list[Tweak] = [
    Tweak("power", "Plan zasilania: Najwyższa wydajność",
          "Wyłącza oszczędzanie energii procesora. Poprzedni plan zostaje zapamiętany.", special="power"),
    Tweak("gamemode", "Tryb gry Windows",
          "Windows nadaje priorytet aktywnej grze i wstrzymuje zadania w tle.",
          values=[RegValue("HKCU", r"Software\Microsoft\GameBar", "AllowAutoGameMode", "DWORD", 1),
                  RegValue("HKCU", r"Software\Microsoft\GameBar", "AutoGameModeEnabled", "DWORD", 1)]),
    Tweak("gamedvr", "Wyłącz nagrywanie w tle (Xbox Game Bar)",
          "Zdejmuje narzut nagrywania klipów w tle - mniej przycięć w grach.",
          values=[RegValue("HKCU", r"System\GameConfigStore", "GameDVR_Enabled", "DWORD", 0),
                  RegValue("HKCU", r"Software\Microsoft\Windows\CurrentVersion\GameDVR", "AppCaptureEnabled", "DWORD", 0)]),
    Tweak("mmcss", "Priorytet multimediów i sieci",
          "SystemResponsiveness=0 oraz wyłączenie ograniczania sieci - więcej zasobów dla aplikacji pierwszoplanowych.",
          admin=True,
          values=[RegValue("HKLM", _SP, "SystemResponsiveness", "DWORD", 0),
                  RegValue("HKLM", _SP, "NetworkThrottlingIndex", "DWORD", 0xFFFFFFFF)]),
    Tweak("mmcss_games", "Priorytet zadań 'Games' (MMCSS)",
          "Wyższy priorytet GPU/CPU dla procesów gier.", admin=True,
          values=[RegValue("HKLM", _SP + r"\Tasks\Games", "GPU Priority", "DWORD", 8),
                  RegValue("HKLM", _SP + r"\Tasks\Games", "Priority", "DWORD", 6),
                  RegValue("HKLM", _SP + r"\Tasks\Games", "Scheduling Category", "SZ", "High"),
                  RegValue("HKLM", _SP + r"\Tasks\Games", "SFIO Priority", "SZ", "High")]),
    Tweak("roblox_priority", "Wysoki priorytet CPU dla Roblox i Studio",
          "Roblox Player i Studio zawsze startują z wysokim priorytetem procesora.", admin=True,
          values=[RegValue("HKLM", _IFEO + r"\RobloxPlayerBeta.exe\PerfOptions", "CpuPriorityClass", "DWORD", 3),
                  RegValue("HKLM", _IFEO + r"\RobloxStudioBeta.exe\PerfOptions", "CpuPriorityClass", "DWORD", 3)]),
    Tweak("hags", "Sprzętowe planowanie GPU (HAGS)",
          "Zmniejsza opóźnienia renderowania na nowszych kartach. Wymaga restartu komputera.",
          admin=True, reboot=True,
          values=[RegValue("HKLM", r"SYSTEM\CurrentControlSet\Control\GraphicsDrivers", "HwSchMode", "DWORD", 2)]),
    Tweak("transparency", "Wyłącz przezroczystość okien",
          "Odciąża GPU/CPU w interfejsie Windows (przydatne na słabszych komputerach).",
          values=[RegValue("HKCU", r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize", "EnableTransparency", "DWORD", 0)]),
    Tweak("fse", "Pełny ekran bez optymalizacji Windows",
          "Gry w pełnym ekranie dostają obraz bezpośrednio - mniejsze opóźnienie i mniej przycięć.",
          values=[RegValue("HKCU", r"System\GameConfigStore", "GameDVR_FSEBehaviorMode", "DWORD", 2),
                  RegValue("HKCU", r"System\GameConfigStore", "GameDVR_HonorUserFSEBehaviorMode", "DWORD", 1),
                  RegValue("HKCU", r"System\GameConfigStore", "GameDVR_FSEBehavior", "DWORD", 2),
                  RegValue("HKCU", r"System\GameConfigStore", "GameDVR_DXGIHonorFSEWindowsCompatible", "DWORD", 1)]),
    Tweak("power_throttling", "Wyłącz ograniczanie mocy procesora",
          "Windows przestaje przycinać wydajność programów, które uzna za działające w tle.", admin=True,
          values=[RegValue("HKLM", r"SYSTEM\CurrentControlSet\Control\Power\PowerThrottling", "PowerThrottlingOff", "DWORD", 1)]),
    Tweak("prio_sep", "Priorytet programu na pierwszym planie",
          "Aktywna gra dostaje dłuższe porcje czasu procesora niż programy w tle.", admin=True,
          values=[RegValue("HKLM", r"SYSTEM\CurrentControlSet\Control\PriorityControl", "Win32PrioritySeparation", "DWORD", 38)]),
    Tweak("mouse_accel", "Wyłącz przyspieszanie myszy",
          "Ruch kursora jest wprost proporcjonalny do ruchu myszy - celniej w grach.",
          values=[RegValue("HKCU", r"Control Panel\Mouse", "MouseSpeed", "SZ", "0"),
                  RegValue("HKCU", r"Control Panel\Mouse", "MouseThreshold1", "SZ", "0"),
                  RegValue("HKCU", r"Control Panel\Mouse", "MouseThreshold2", "SZ", "0")]),
    Tweak("bg_apps", "Zablokuj aplikacje działające w tle",
          "Aplikacje ze Sklepu nie pracują w tle, więc zostaje więcej RAM i procesora dla gry.",
          values=[RegValue("HKCU", r"Software\Microsoft\Windows\CurrentVersion\BackgroundAccessApplications",
                           "GlobalUserDisabled", "DWORD", 1)]),
    Tweak("min_anim", "Wyłącz animacje okien Windows",
          "Okna otwierają się i zamykają natychmiast - mniej pracy dla GPU i szybszy pulpit.",
          values=[RegValue("HKCU", r"Control Panel\Desktop\WindowMetrics", "MinAnimate", "SZ", "0")]),
]


def _hive(name: str):
    return winreg.HKEY_LOCAL_MACHINE if name == "HKLM" else winreg.HKEY_CURRENT_USER


def _read(v: RegValue) -> tuple[bool, Any]:
    try:
        with winreg.OpenKey(_hive(v.hive), v.key, 0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as k:
            data, _ = winreg.QueryValueEx(k, v.name)
            return True, data
    except OSError:
        return False, None


def _write(v: RegValue) -> None:
    with winreg.CreateKeyEx(_hive(v.hive), v.key, 0, winreg.KEY_WRITE | winreg.KEY_WOW64_64KEY) as k:
        winreg.SetValueEx(k, v.name, 0, winreg.REG_DWORD if v.vtype == "DWORD" else winreg.REG_SZ, v.value)


def _delete(v: RegValue) -> None:
    try:
        with winreg.OpenKey(_hive(v.hive), v.key, 0, winreg.KEY_WRITE | winreg.KEY_WOW64_64KEY) as k:
            winreg.DeleteValue(k, v.name)
    except OSError:
        pass


# --- plan zasilania
_ULTIMATE = "e9a42b02-d5df-448d-aa00-03f14749eb61"
_HIGHPERF = "8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c"
_GUID = r"[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}"
_PERF_NAME = re.compile(r"ultimate|najwy|maksym|high perf|wysok", re.I)


def _power_active() -> tuple[str, str]:
    rc, out = _run(["powercfg", "/getactivescheme"])
    m = re.search(rf"({_GUID})\s*\(([^)]*)\)", out)
    return (m.group(1).lower(), m.group(2)) if m else ("", "")


def _power_schemes() -> list[tuple[str, str]]:
    rc, out = _run(["powercfg", "/list"])
    return [(g.lower(), n) for g, n in re.findall(rf"({_GUID})\s*\(([^)]*)\)", out)]


def _power_applied() -> bool:
    return bool(_PERF_NAME.search(_power_active()[1]))


def _power_apply(backup: dict) -> tuple[bool, str]:
    active, _ = _power_active()
    if "power" not in backup and active:
        backup["power"] = active
    target = next((g for g, n in _power_schemes() if _PERF_NAME.search(n)), "")
    if not target:
        for src in (_ULTIMATE, _HIGHPERF):
            rc, out = _run(["powercfg", "-duplicatescheme", src])
            m = re.search(_GUID, out)
            if rc == 0 and m:
                target = m.group(0).lower()
                break
    if not target:
        return False, "Ten komputer nie udostępnia planu wysokiej wydajności."
    rc, out = _run(["powercfg", "-setactive", target])
    return rc == 0, "Włączono plan wysokiej wydajności." if rc == 0 else out.strip()[:200]


def _power_revert(backup: dict) -> tuple[bool, str]:
    guid = backup.pop("power", "")
    if not guid:
        return False, "Brak zapisanego poprzedniego planu."
    rc, out = _run(["powercfg", "-setactive", guid])
    return rc == 0, "Przywrócono poprzedni plan zasilania." if rc == 0 else out.strip()[:200]


# --- API tweaków
def tweak_state(t: Tweak) -> Optional[bool]:
    """True/False = włączony/wyłączony, None = niedostępny na tym systemie."""
    if not IS_WINDOWS:
        return None
    if t.special == "power":
        return _power_applied()
    for v in t.values:
        ok, data = _read(v)
        if not ok or data != v.value:
            return False
    return True


def apply_tweak(t: Tweak, settings) -> tuple[bool, str]:
    if not IS_WINDOWS:
        return False, "Dostępne tylko w Windows."
    if t.admin and not is_admin():
        return False, "Wymaga uprawnień administratora."
    backup_all = settings.get("tweaks_backup") or {}
    try:
        if t.special == "power":
            ok, msg = _power_apply(backup_all.setdefault("_power", {}))
        else:
            backup = backup_all.setdefault(t.id, {})
            if not backup:  # zapisujemy oryginał tylko raz - żeby nie nadpisać go własną zmianą
                backup["values"] = []
                for v in t.values:
                    existed, data = _read(v)
                    backup["values"].append({"existed": existed, "data": data})
            for v in t.values:
                _write(v)
            ok, msg = True, "Zastosowano." + (" Zrestartuj komputer." if t.reboot else "")
        settings.set("tweaks_backup", backup_all)
        return ok, msg
    except Exception as e:
        log.exception("apply_tweak %s", t.id)
        return False, f"Błąd: {e}"


def revert_tweak(t: Tweak, settings) -> tuple[bool, str]:
    if not IS_WINDOWS:
        return False, "Dostępne tylko w Windows."
    if t.admin and not is_admin():
        return False, "Wymaga uprawnień administratora."
    backup_all = settings.get("tweaks_backup") or {}
    try:
        if t.special == "power":
            ok, msg = _power_revert(backup_all.setdefault("_power", {}))
        else:
            saved = (backup_all.get(t.id) or {}).get("values")
            for i, v in enumerate(t.values):
                if saved and i < len(saved) and saved[i]["existed"]:
                    _write(RegValue(v.hive, v.key, v.name, v.vtype, saved[i]["data"]))
                else:
                    _delete(v)       # wartość nie istniała przed zmianą - usuwamy
            backup_all.pop(t.id, None)
            ok, msg = True, "Przywrócono ustawienia sprzed zmiany."
        settings.set("tweaks_backup", backup_all)
        return ok, msg
    except Exception as e:
        log.exception("revert_tweak %s", t.id)
        return False, f"Błąd: {e}"

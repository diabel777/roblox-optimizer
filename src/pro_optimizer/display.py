"""Częstotliwość odświeżania monitora (ctypes, EnumDisplaySettings). Częsty problem: monitor 144/180 Hz działa na 60 Hz."""
from __future__ import annotations

import ctypes
import logging
import os
from ctypes import wintypes
from typing import Optional

log = logging.getLogger(__name__)
IS_WINDOWS = os.name == "nt"

ENUM_CURRENT = -1
DM_DISPLAYFREQUENCY = 0x400000
CDS_UPDATEREGISTRY, CDS_TEST = 0x1, 0x2
DISP_CHANGE_SUCCESSFUL = 0


class DEVMODEW(ctypes.Structure):
    _fields_ = [("dmDeviceName", ctypes.c_wchar * 32), ("dmSpecVersion", wintypes.WORD), ("dmDriverVersion", wintypes.WORD),
                ("dmSize", wintypes.WORD), ("dmDriverExtra", wintypes.WORD), ("dmFields", wintypes.DWORD),
                ("dmPositionX", ctypes.c_long), ("dmPositionY", ctypes.c_long),
                ("dmColor", ctypes.c_short), ("dmDuplex", ctypes.c_short), ("dmYResolution", ctypes.c_short),
                ("dmTTOption", ctypes.c_short), ("dmCollate", ctypes.c_short), ("dmFormName", ctypes.c_wchar * 32),
                ("dmLogPixels", wintypes.WORD), ("dmBitsPerPel", wintypes.DWORD), ("dmPelsWidth", wintypes.DWORD),
                ("dmPelsHeight", wintypes.DWORD), ("dmDisplayFlags", wintypes.DWORD), ("dmDisplayFrequency", wintypes.DWORD),
                ("dmICMMethod", wintypes.DWORD), ("dmICMIntent", wintypes.DWORD), ("dmMediaType", wintypes.DWORD),
                ("dmDitherType", wintypes.DWORD), ("dmReserved1", wintypes.DWORD), ("dmReserved2", wintypes.DWORD),
                ("dmPanningWidth", wintypes.DWORD), ("dmPanningHeight", wintypes.DWORD)]


def _dm() -> DEVMODEW:
    d = DEVMODEW()
    d.dmSize = ctypes.sizeof(DEVMODEW)
    return d


def current() -> Optional[dict]:
    """{'w','h','hz','max_hz','modes':[hz...]} dla monitora głównego, w bieżącej rozdzielczości."""
    if not IS_WINDOWS:
        return None
    try:
        u = ctypes.windll.user32
        cur = _dm()
        if not u.EnumDisplaySettingsW(None, ENUM_CURRENT, ctypes.byref(cur)):
            return None
        hz = set()
        i = 0
        while True:
            m = _dm()
            if not u.EnumDisplaySettingsW(None, i, ctypes.byref(m)):
                break
            if m.dmPelsWidth == cur.dmPelsWidth and m.dmPelsHeight == cur.dmPelsHeight and m.dmBitsPerPel == cur.dmBitsPerPel:
                hz.add(int(m.dmDisplayFrequency))
            i += 1
        hz = sorted(h for h in hz if h > 1)
        return {"w": cur.dmPelsWidth, "h": cur.dmPelsHeight, "hz": int(cur.dmDisplayFrequency),
                "max_hz": max(hz) if hz else int(cur.dmDisplayFrequency), "modes": hz}
    except Exception:
        log.exception("display.current")
        return None


def set_refresh(hz: int) -> tuple[bool, str]:
    if not IS_WINDOWS:
        return False, "Dostępne tylko w Windows."
    info = current()
    if not info or hz not in info["modes"]:
        return False, "Monitor nie obsługuje tej częstotliwości w bieżącej rozdzielczości."
    u = ctypes.windll.user32
    dm = _dm()
    u.EnumDisplaySettingsW(None, ENUM_CURRENT, ctypes.byref(dm))
    dm.dmDisplayFrequency = hz
    dm.dmFields = DM_DISPLAYFREQUENCY
    if u.ChangeDisplaySettingsExW(None, ctypes.byref(dm), None, CDS_TEST, None) != DISP_CHANGE_SUCCESSFUL:
        return False, "Sterownik odrzucił tę częstotliwość."
    rc = u.ChangeDisplaySettingsExW(None, ctypes.byref(dm), None, CDS_UPDATEREGISTRY, None)
    return rc == DISP_CHANGE_SUCCESSFUL, f"Ustawiono {hz} Hz." if rc == DISP_CHANGE_SUCCESSFUL else f"Nie udało się (kod {rc})."

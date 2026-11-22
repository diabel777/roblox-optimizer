"""Czujniki sprzętu: CPU/RAM/dyski (psutil) i karta NVIDIA (NVML - biblioteka dołączona do sterownika).

Wentylatorami karty NVIDIA da się sterować tylko przez NVML (wymaga admina i obsługi przez sterownik/kartę).
Karty AMD/Intel i wentylatory procesora/obudowy nie mają publicznego API - aplikacja pokaże to uczciwie.
Poza Windowsem moduł się importuje, a funkcje zwracają None/puste (testy)."""
from __future__ import annotations

import ctypes
import logging
import os
import subprocess
import threading
from dataclasses import dataclass, field
from typing import Optional

from .ps import system_exe

log = logging.getLogger(__name__)
IS_WINDOWS = os.name == "nt"
_NOWIN = 0x08000000


@dataclass
class GpuSample:
    index: int
    name: str
    temp: Optional[float] = None
    util: Optional[float] = None
    mem_util: Optional[float] = None
    fan: Optional[float] = None          # % obrotów
    power_w: Optional[float] = None
    power_limit_w: Optional[float] = None
    mem_used: Optional[int] = None       # bajty
    mem_total: Optional[int] = None
    core_mhz: Optional[int] = None
    mem_mhz: Optional[int] = None
    fans: int = 0
    can_set_fan: bool = False


class _Util(ctypes.Structure):
    _fields_ = [("gpu", ctypes.c_uint), ("memory", ctypes.c_uint)]


class _Mem(ctypes.Structure):
    _fields_ = [("total", ctypes.c_ulonglong), ("free", ctypes.c_ulonglong), ("used", ctypes.c_ulonglong)]


class Nvml:
    """Cienka nakładka na nvml.dll. Każde wywołanie jest opakowane - brak funkcji w starszym sterowniku nie wywala aplikacji."""

    PATHS = (r"C:\Windows\System32\nvml.dll", r"C:\Program Files\NVIDIA Corporation\NVSMI\nvml.dll")

    def __init__(self):
        self.lib = None
        self.handles: list = []
        self.error = ""
        self._lock = threading.Lock()
        self._init()

    def _init(self) -> None:
        if not IS_WINDOWS:
            self.error = "NVML dostępny tylko w Windows."
            return
        for p in self.PATHS:
            if os.path.exists(p):
                try:
                    self.lib = ctypes.WinDLL(p)
                    break
                except OSError as e:
                    self.error = str(e)
        if not self.lib:
            self.error = self.error or "Nie znaleziono nvml.dll (brak sterownika NVIDIA)."
            return
        try:
            rc = self.lib.nvmlInit_v2()
            if rc != 0:
                self.error = f"nvmlInit: {rc}"
                self.lib = None
                return
            n = ctypes.c_uint()
            self.lib.nvmlDeviceGetCount_v2(ctypes.byref(n))
            for i in range(n.value):
                h = ctypes.c_void_p()
                if self.lib.nvmlDeviceGetHandleByIndex_v2(i, ctypes.byref(h)) == 0:
                    self.handles.append(h)
        except Exception as e:  # noqa: BLE001
            self.error = str(e)
            self.lib = None

    @property
    def available(self) -> bool:
        return bool(self.lib and self.handles)

    def _u(self, fn: str, h, *extra) -> Optional[int]:
        try:
            v = ctypes.c_uint()
            if getattr(self.lib, fn)(h, *extra, ctypes.byref(v)) == 0:
                return v.value
        except Exception:
            pass
        return None

    def sample(self, idx: int = 0) -> Optional[GpuSample]:
        if not self.available or idx >= len(self.handles):
            return None
        h = self.handles[idx]
        with self._lock:
            buf = ctypes.create_string_buffer(96)
            name = "NVIDIA GPU"
            try:
                if self.lib.nvmlDeviceGetName(h, buf, 96) == 0:
                    name = buf.value.decode(errors="ignore")
            except Exception:
                pass
            s = GpuSample(idx, name)
            s.temp = self._u("nvmlDeviceGetTemperature", h, 0)
            try:
                u = _Util()
                if self.lib.nvmlDeviceGetUtilizationRates(h, ctypes.byref(u)) == 0:
                    s.util, s.mem_util = float(u.gpu), float(u.memory)
            except Exception:
                pass
            s.fan = self._u("nvmlDeviceGetFanSpeed", h)
            s.fans = self._u("nvmlDeviceGetNumFans", h) or 0
            mw = self._u("nvmlDeviceGetPowerUsage", h)
            s.power_w = mw / 1000 if mw is not None else None
            lim = self._u("nvmlDeviceGetEnforcedPowerLimit", h)
            s.power_limit_w = lim / 1000 if lim is not None else None
            try:
                m = _Mem()
                if self.lib.nvmlDeviceGetMemoryInfo(h, ctypes.byref(m)) == 0:
                    s.mem_used, s.mem_total = m.used, m.total
            except Exception:
                pass
            s.core_mhz = self._u("nvmlDeviceGetClockInfo", h, 0)
            s.mem_mhz = self._u("nvmlDeviceGetClockInfo", h, 2)
            s.can_set_fan = s.fans > 0 and hasattr(self.lib, "nvmlDeviceSetFanSpeed_v2")
            return s

    def set_fan(self, idx: int, percent: int) -> tuple[bool, str]:
        """Ustawia stałą prędkość WSZYSTKICH wentylatorów karty. Wymaga admina."""
        if not self.available:
            return False, self.error or "Brak NVML."
        percent = int(max(30, min(100, percent)))          # nigdy poniżej 30% - ochrona przed przegrzaniem
        h = self.handles[idx]
        with self._lock:
            n = self._u("nvmlDeviceGetNumFans", h) or 0
            if n == 0:
                return False, "Ta karta nie udostępnia sterowania wentylatorami."
            for f in range(n):
                rc = self.lib.nvmlDeviceSetFanSpeed_v2(h, f, percent)
                if rc != 0:
                    return False, ("Sterownik odmówił zmiany prędkości (kod %d). Uruchom aplikację jako administrator." % rc
                                   if rc == 4 else f"Sterownik odrzucił zmianę prędkości (kod {rc}).")
        return True, f"Wentylatory: {percent}%"

    def set_auto(self, idx: int) -> tuple[bool, str]:
        """Oddaje wentylatory sterownikowi (domyślna krzywa karty)."""
        if not self.available:
            return False, self.error or "Brak NVML."
        h = self.handles[idx]
        with self._lock:
            n = self._u("nvmlDeviceGetNumFans", h) or 0
            for f in range(n):
                try:
                    rc = self.lib.nvmlDeviceSetDefaultFanSpeed_v2(h, f)
                except Exception:
                    return False, "Sterownik nie obsługuje przywracania automatu."
                if rc != 0:
                    return False, f"Nie udało się przywrócić automatu (kod {rc})."
        return True, "Wentylatory: automat sterownika."

    def shutdown(self) -> None:
        if self.lib:
            try:
                self.lib.nvmlShutdown()
            except Exception:
                pass


_nvml: Optional[Nvml] = None


def nvml() -> Nvml:
    global _nvml
    if _nvml is None:
        _nvml = Nvml()
    return _nvml


def gpu_names_wmi() -> list[str]:
    """Wszystkie karty widziane przez Windows (także AMD/Intel - bez sensorów)."""
    if not IS_WINDOWS:
        return []
    try:
        out = subprocess.run([system_exe("powershell"), "-NoProfile", "-Command",
                              "(Get-CimInstance Win32_VideoController).Name -join '|'"],
                             capture_output=True, text=True, timeout=20, creationflags=_NOWIN).stdout
        return [x.strip() for x in out.split("|") if x.strip()]
    except Exception:
        return []


def cpu_temp() -> Optional[float]:
    """Temperatura CPU z ACPI (WMI). Wiele płyt jej nie udostępnia - wtedy None, zamiast zgadywać."""
    if not IS_WINDOWS:
        return None
    try:
        out = subprocess.run(
            [system_exe("powershell"), "-NoProfile", "-Command",
             "(Get-CimInstance -Namespace root/wmi -ClassName MSAcpi_ThermalZoneTemperature -ErrorAction Stop "
             "| Select -First 1).CurrentTemperature"],
            capture_output=True, text=True, timeout=15, creationflags=_NOWIN).stdout.strip()
        v = float(out) / 10 - 273.15
        return v if 0 < v < 120 else None
    except Exception:
        return None


@dataclass
class History:
    """Ostatnie N próbek do wykresów."""
    n: int = 90
    data: dict = field(default_factory=dict)

    def push(self, key: str, v: Optional[float]) -> None:
        d = self.data.setdefault(key, [])
        d.append(v if v is not None else 0.0)
        if len(d) > self.n:
            del d[: len(d) - self.n]

    def get(self, key: str) -> list[float]:
        return list(self.data.get(key, []))

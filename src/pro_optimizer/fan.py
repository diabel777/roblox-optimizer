"""Inteligentne sterowanie wentylatorem karty: krzywa temperatura -> obroty, histereza, zabezpieczenia.

Logika (`FanPolicy`) jest czysta i testowana bez sprzętu; `FanController` łączy ją z NVML.
Zabezpieczenia: minimum 30%, od 83°C zawsze 100%, brak odczytu temperatury => oddaj sterowanie sterownikowi,
wyjście z aplikacji => oddaj sterowanie sterownikowi."""
from __future__ import annotations

import logging
import threading
from typing import Callable, Optional

from . import hw

log = logging.getLogger(__name__)

MIN_PERCENT = 30
EMERGENCY_TEMP = 83

CURVES: dict[str, dict] = {
    "quiet": {"name": "Cichy", "points": [(40, 30), (55, 35), (65, 45), (72, 60), (78, 80), (83, 100)]},
    "balanced": {"name": "Zbalansowany", "points": [(40, 30), (50, 40), (60, 55), (70, 75), (78, 90), (83, 100)]},
    "performance": {"name": "Wydajny (chłodniej)", "points": [(35, 40), (45, 55), (55, 70), (65, 85), (72, 100)]},
}


def interpolate(points: list[tuple[float, float]], temp: float) -> float:
    pts = sorted(points)
    if temp <= pts[0][0]:
        return pts[0][1]
    if temp >= pts[-1][0]:
        return pts[-1][1]
    for (t0, s0), (t1, s1) in zip(pts, pts[1:]):
        if t0 <= temp <= t1:
            return s0 + (s1 - s0) * (temp - t0) / (t1 - t0)
    return pts[-1][1]


class FanPolicy:
    """Zwraca docelowe obroty z histerezą (nie 'pompuje' przy wahaniach temperatury) i ograniczeniem tempa spadku."""

    def __init__(self, points: list[tuple[float, float]], hysteresis: float = 3.0, step_down: int = 5):
        self.points = [(float(t), float(s)) for t, s in points]
        self.hyst = hysteresis
        self.step_down = step_down
        self.current: Optional[int] = None
        self._ref_temp: Optional[float] = None

    def target(self, temp: float) -> int:
        if temp >= EMERGENCY_TEMP:
            self.current, self._ref_temp = 100, temp
            return 100
        want = int(round(max(MIN_PERCENT, min(100, interpolate(self.points, temp)))))
        if self.current is None:
            self.current, self._ref_temp = want, temp
            return want
        if want > self.current:                      # robi się goręcej - reaguj od razu
            self.current, self._ref_temp = want, temp
        elif want < self.current and temp <= (self._ref_temp or temp) - self.hyst:
            self.current = max(want, self.current - self.step_down)   # chłodzenie zwalnia stopniowo
            self._ref_temp = temp
        return self.current


class FanController:
    """mode: 'auto' (sterownik) | 'smart' (krzywa) | 'manual' (stałe %)."""

    def __init__(self, on_event: Optional[Callable[[str], None]] = None):
        self.mode = "auto"
        self.curve_id = "balanced"
        self.manual = 60
        self.index = 0
        self.policy = FanPolicy(CURVES["balanced"]["points"])
        self.last_applied: Optional[int] = None
        self.last_msg = ""
        self.on_event = on_event or (lambda m: None)
        self._lock = threading.Lock()

    def configure(self, mode: str, curve_id: str = "balanced", manual: int = 60) -> tuple[bool, str]:
        with self._lock:
            prev = self.mode
            self.mode, self.manual = mode, int(manual)
            if curve_id != self.curve_id or mode == "smart":
                self.curve_id = curve_id if curve_id in CURVES else "balanced"
                self.policy = FanPolicy(CURVES[self.curve_id]["points"])
            self.last_applied = None
        if mode == "auto":
            ok, msg = hw.nvml().set_auto(self.index)
            self.last_msg = msg
            return ok, msg
        if prev == "auto" and not hw.nvml().available:
            return False, hw.nvml().error
        return True, "Zapisano."

    def tick(self, temp: Optional[float]) -> Optional[str]:
        """Wywoływane co kilka sekund. Zwraca komunikat tylko przy zmianie/problemie."""
        if self.mode == "auto":
            return None
        nv = hw.nvml()
        if not nv.available:
            return None
        if temp is None:                              # brak odczytu - bezpieczniej oddać karcie
            self.mode = "auto"
            nv.set_auto(self.index)
            msg = "Brak odczytu temperatury - wentylatory wróciły do automatu sterownika."
            self.on_event(msg)
            return msg
        pct = self.manual if self.mode == "manual" else self.policy.target(temp)
        if temp >= EMERGENCY_TEMP:
            pct = 100
        pct = int(max(MIN_PERCENT, min(100, pct)))
        if pct == self.last_applied:
            return None
        ok, msg = nv.set_fan(self.index, pct)
        if ok:
            self.last_applied = pct
            return None
        self.mode = "auto"                            # nie da się sterować (np. brak admina) - nie próbuj w kółko
        nv.set_auto(self.index)
        self.last_msg = msg
        self.on_event(msg)
        return msg

    def release(self) -> None:
        """Zawsze oddaj wentylatory sterownikowi przy zamykaniu aplikacji."""
        if self.mode != "auto" or self.last_applied is not None:
            try:
                hw.nvml().set_auto(self.index)
            except Exception:
                log.debug("release fan", exc_info=True)
        self.mode = "auto"

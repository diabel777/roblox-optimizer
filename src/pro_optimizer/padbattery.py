"""Bateria pada: historia pomiarów, szacunek czasu pracy / ładowania i alerty (spadek o N%, niski poziom, naładowany).
Logika jest czysta (bez GUI i bez HID), dlatego da się ją przetestować."""
from __future__ import annotations

import threading
import time
from typing import Callable, Optional

ALERT_DEFAULTS = {"enabled": True, "drop": 5, "low": 15, "full": True}


def sanitize_alerts(cfg: Optional[dict]) -> dict:
    src = cfg if isinstance(cfg, dict) else {}
    out = dict(ALERT_DEFAULTS)
    out["enabled"] = bool(src.get("enabled", True))
    out["full"] = bool(src.get("full", True))
    for k, lo, hi in (("drop", 1, 50), ("low", 0, 50)):
        try:
            out[k] = max(lo, min(hi, int(src.get(k, ALERT_DEFAULTS[k]))))
        except (TypeError, ValueError):
            pass
    return out


class Tracker:
    """Zbiera próbki (czas, %, stan) i liczy tempo zmian. Tempo bierzemy z ostatnich ~30 min tego samego stanu."""

    def __init__(self, window: float = 1800.0):
        self.samples: list[tuple[float, int, str]] = []
        self.window = window
        self._base: Optional[int] = None       # % przy ostatnim alercie spadku
        self._low_sent = False
        self._full_sent = False

    def add(self, pct: int, state: str, now: Optional[float] = None) -> None:
        now = time.time() if now is None else now
        if self.samples and self.samples[-1][2] != state:
            self.samples = []                  # zmiana stanu (np. podłączono kabel) - liczymy tempo od nowa
        self.samples.append((now, int(pct), state))
        self.samples = [s for s in self.samples if now - s[0] <= self.window * 2][-240:]

    def rate_per_min(self) -> Optional[float]:
        """Zmiana % na minutę (ujemna przy rozładowywaniu). None, gdy za mało danych."""
        if len(self.samples) < 2:
            return None
        t0, p0, _ = self.samples[0]
        t1, p1, _ = self.samples[-1]
        if t1 - t0 < 180 or p0 == p1:
            return None
        return (p1 - p0) / ((t1 - t0) / 60)

    def minutes_left(self) -> Optional[int]:
        """Ile minut jeszcze popracuje (przy rozładowywaniu) albo ile do pełna (przy ładowaniu)."""
        if not self.samples:
            return None
        _, pct, state = self.samples[-1]
        r = self.rate_per_min()
        if r is None:
            return None
        if state == "discharging" and r < 0:
            return round(pct / -r)
        if state == "charging" and r > 0:
            return round((100 - pct) / r)
        return None

    def alerts(self, cfg: dict) -> list[str]:
        """Zwraca teksty alertów do pokazania TERAZ (każdy tylko raz)."""
        cfg = sanitize_alerts(cfg)
        if not cfg["enabled"] or not self.samples:
            return []
        _, pct, state = self.samples[-1]
        out: list[str] = []
        if state == "discharging":
            self._full_sent = False
            if self._base is None:
                self._base = pct
            if self._base - pct >= cfg["drop"]:
                out.append(f"Bateria pada spadła do {pct}%.")
                self._base = pct
            if cfg["low"] and pct <= cfg["low"] and not self._low_sent:
                out.append(f"Niski poziom baterii pada: {pct}%. Podłącz ładowarkę.")
                self._low_sent = True
        else:
            self._base = None
            if pct > (cfg["low"] or 0) + 5:
                self._low_sent = False
            if state in ("full",) or (state == "charging" and pct >= 100):
                if cfg["full"] and not self._full_sent:
                    out.append("Pad jest w pełni naładowany.")
                    self._full_sent = True
        return out


def describe(tracker: Tracker) -> str:
    """Zdanie dla człowieka: 'Wystarczy jeszcze na ok. 3 h 20 min' itp."""
    m = tracker.minutes_left()
    if m is None or not tracker.samples:
        return "Szacunek czasu pojawi się po kilku minutach pomiarów."
    h, mm = divmod(m, 60)
    txt = f"{h} h {mm} min" if h else f"{mm} min"
    return ("Wystarczy jeszcze na ok. " if tracker.samples[-1][2] == "discharging" else "Do pełnego naładowania ok. ") + txt


class Watcher:
    """Wątek w tle: co minutę czyta baterię pierwszego pada, karmi Tracker i wywołuje on_alert(tekst)."""

    def __init__(self, get_alert_cfg: Callable[[], dict], on_alert: Callable[[str], None], interval: float = 60.0):
        self.tracker = Tracker()
        self._cfg, self._on_alert, self.interval = get_alert_cfg, on_alert, interval
        self._stop = threading.Event()
        self._t = threading.Thread(target=self._run, daemon=True)
        self.last: Optional[dict] = None

    def start(self) -> None:
        if not self._t.is_alive():
            self._t.start()

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        from . import gamepad as gp
        while not self._stop.wait(self.interval):
            try:
                if not gp.available():
                    continue
                pads = gp.detect()
                if not pads:
                    self.tracker = Tracker()
                    self.last = None
                    continue
                b = gp.battery(pads[0])
                if not b:
                    continue
                self.last = b
                self.tracker.add(b["percent"], b["state"])
                for msg in self.tracker.alerts(self._cfg()):
                    self._on_alert(msg)
            except Exception:
                pass

"""Pady PlayStation (DualShock 4 / DualSense / DualSense Edge): kolor paska, wibracje, spusty adaptacyjne,
głośność głośnika/słuchawek/mikrofonu i dioda wyciszenia.

Zasada bezpieczeństwa: rozmawiamy z padem WYŁĄCZNIE przez oficjalny raport wyjściowy HID (ten sam, którego używa
Steam i sterownik Linuksa). Nie instalujemy żadnych sterowników, nie wstrzykujemy się do gier - dlatego anty-cheaty
nie mają się do czego przyczepić. Wszystkie wartości są przycinane do dozwolonych zakresów, zanim trafią do pada.
Budowanie raportów jest czystą funkcją (testowalną bez pada); dopiero `apply` dotyka sprzętu."""
from __future__ import annotations

import logging
import zlib
from dataclasses import dataclass, field
from typing import Any, Optional

log = logging.getLogger(__name__)

SONY = 0x054C
MODELS = {0x05C4: "DualShock 4", 0x09CC: "DualShock 4 (v2)", 0x0CE6: "DualSense (PS5)", 0x0DF2: "DualSense Edge (PS5)"}
DUALSENSE = {0x0CE6, 0x0DF2}

TRIGGER_MODES = {
    "off": "Wyłączony (zwykły spust)",
    "rigid": "Sztywny opór (jak hamulec)",
    "section": "Opór w zakresie (jak spust broni)",
}

COLOR_PRESETS = {
    "Fioletowy": (120, 70, 255), "Niebieski": (0, 90, 255), "Turkus": (0, 220, 220), "Zielony": (0, 255, 80),
    "Żółty": (255, 210, 0), "Pomarańczowy": (255, 110, 0), "Czerwony": (255, 20, 30), "Różowy": (255, 60, 170),
    "Biały": (255, 255, 255), "Wyłączony": (0, 0, 0),
}

DEFAULTS: dict[str, Any] = {
    "color": [120, 70, 255], "brightness": 100,
    "rumble_left": 100, "rumble_right": 100,        # siła wibracji (test), % - wartość do jednorazowego pulsu
    "trigger_left": "off", "trigger_right": "off", "trigger_force": 60, "trigger_start": 30,
    "headphone": 70, "speaker": 70, "mic": 70, "mic_led": False,
    "keep": True, "auto_triggers": True,
    "mode": "static", "speed": 40, "color2": [0, 200, 255],
}

LIGHT_MODES = {
    "static": "Jeden kolor",
    "rainbow": "Tęcza (RGB)",
    "breathe": "Oddychanie",
    "pulse2": "Przejście dwóch kolorów",
    "battery": "Kolor wg baterii",
}


def clamp(v: Any, lo: int, hi: int, default: int) -> int:
    try:
        n = int(float(v))
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, n))


def sanitize(cfg: Optional[dict]) -> dict:
    """Zwraca poprawny słownik ustawień - cokolwiek by w nim było."""
    src = cfg if isinstance(cfg, dict) else {}
    out = dict(DEFAULTS)
    col = src.get("color")
    if isinstance(col, (list, tuple)) and len(col) == 3:
        out["color"] = [clamp(x, 0, 255, 0) for x in col]
    out["brightness"] = clamp(src.get("brightness", 100), 0, 100, 100)
    for k in ("rumble_left", "rumble_right", "trigger_force", "trigger_start", "headphone", "speaker", "mic"):
        out[k] = clamp(src.get(k, DEFAULTS[k]), 0, 100, DEFAULTS[k])
    for k in ("trigger_left", "trigger_right"):
        out[k] = src.get(k) if src.get(k) in TRIGGER_MODES else "off"
    out["mic_led"] = bool(src.get("mic_led", False))
    out["mode"] = src.get("mode") if src.get("mode") in LIGHT_MODES else "static"
    out["speed"] = clamp(src.get("speed", 40), 1, 100, 40)
    c2 = src.get("color2")
    if isinstance(c2, (list, tuple)) and len(c2) == 3:
        out["color2"] = [clamp(x, 0, 255, 0) for x in c2]
    for k, v in src.items():                      # pola robocze (_trig, _rgb) przechodzą dalej
        if isinstance(k, str) and k.startswith("_"):
            out[k] = v
    out["keep"] = bool(src.get("keep", True))
    out["auto_triggers"] = bool(src.get("auto_triggers", True))
    return out


def _scale255(pct: int) -> int:
    return round(clamp(pct, 0, 100, 0) * 255 / 100)


def _rgb(cfg: dict) -> tuple[int, int, int]:
    k = cfg["brightness"] / 100
    base = cfg.get("_rgb") or cfg["color"]
    return tuple(max(0, min(255, round(x * k))) for x in base)  # type: ignore[return-value]


# --------------------------------------------------------------------------- animacje światła
def _hsv(h: float, s: float = 1.0, v: float = 1.0) -> list[int]:
    import colorsys
    r, g, b = colorsys.hsv_to_rgb(h % 1.0, s, v)
    return [round(r * 255), round(g * 255), round(b * 255)]


def _mix(a, b, t: float) -> list[int]:
    return [round(x + (y - x) * t) for x, y in zip(a, b)]


def battery_color(pct: int) -> list[int]:
    """0% czerwony -> 50% żółty -> 100% zielony (płynnie)."""
    pct = max(0, min(100, int(pct)))
    return _mix([255, 30, 30], [255, 200, 0], pct / 50) if pct < 50 else _mix([255, 200, 0], [30, 255, 90], (pct - 50) / 50)


def frame_color(cfg: dict, t: float, battery_pct: Optional[int] = None) -> list[int]:
    """Kolor paska w chwili t (sekundy) dla wybranego trybu. Czysta funkcja - używa jej i podgląd w UI, i wątek pada."""
    import math
    mode, speed = cfg.get("mode", "static"), clamp(cfg.get("speed", 40), 1, 100, 40)
    col = cfg.get("color", [120, 70, 255])
    if mode == "rainbow":
        return _hsv(t * speed / 100 * 0.5)
    if mode == "breathe":
        k = 0.12 + 0.88 * (0.5 + 0.5 * math.sin(t * speed / 100 * 4.0))
        return [round(x * k) for x in col]
    if mode == "pulse2":
        return _mix(col, cfg.get("color2", [0, 200, 255]), 0.5 + 0.5 * math.sin(t * speed / 100 * 4.0))
    if mode == "battery":
        base = battery_color(battery_pct if battery_pct is not None else 100)
        if battery_pct is not None and battery_pct <= 15:           # niski poziom: miganie
            k = 0.25 + 0.75 * (0.5 + 0.5 * math.sin(t * 5))
            return [round(x * k) for x in base]
        return base
    return list(col)


def _crc_bt(payload: bytes) -> bytes:
    """Bluetooth: CRC32 liczone z bajtem 0xA2 na początku, zapisane little-endian na końcu raportu."""
    return zlib.crc32(b"\xa2" + payload).to_bytes(4, "little")


def _trigger_bytes(mode: str, start: int, force: int) -> bytes:
    """11 bajtów opisu spustu DualSense: tryb + 10 parametrów. Zakresy 0-255 jak w dokumentacji Sony/Linuksa."""
    s, f = _scale255(start), _scale255(force)
    if mode == "rigid":
        return bytes([0x01, s, f]) + bytes(8)
    if mode == "section":
        end = min(255, s + 70)
        return bytes([0x02, s, end, f]) + bytes(7)
    return bytes(11)


def build_dualsense(cfg: dict, bluetooth: bool = False, seq: int = 0, mode: str = "apply") -> bytes:
    """mode: "apply" (kolor+spusty+dźwięk), "keep" (tylko kolor i spusty włączone przez użytkownika - nie rusza wibracji
    gier ani głośności), "rumble" (jak apply, ale z wibracją - do testu)."""
    trig = cfg.get("_trig") if isinstance(cfg, dict) else None
    cfg = sanitize(cfg)
    if trig:
        cfg["_trig"] = trig
    c = bytearray(47)
    # valid_flag0: 0 wibracje, 2 spust prawy, 3 spust lewy, 4 słuchawki, 5 głośnik, 6 mikrofon, 7 sterowanie audio
    f0 = 0
    if mode == "rumble":
        f0 |= 0b00000011          # wibracje + wybór haptyki (jak w sterowniku Linuksa)
    if mode != "keep" or cfg["trigger_right"] != "off":
        f0 |= 0b00000100
    if mode != "keep" or cfg["trigger_left"] != "off":
        f0 |= 0b00001000
    if mode != "keep":
        f0 |= 0b11110000
    c[0] = f0
    # valid_flag1: 0 dioda mikrofonu, 2 pasek świetlny
    c[1] = 0b00000101
    c[2] = _scale255(cfg["rumble_right"])
    c[3] = _scale255(cfg["rumble_left"])
    c[4] = _scale255(cfg["headphone"])
    c[5] = _scale255(cfg["speaker"])
    c[6] = _scale255(cfg["mic"])
    c[7] = 0x10 if cfg["mic"] else 0x00
    c[8] = 1 if cfg["mic_led"] else 0
    tr = cfg.get("_trig") or {}
    rs, rf = tr.get("right", (cfg["trigger_start"], cfg["trigger_force"]))
    ls, lf = tr.get("left", (cfg["trigger_start"], cfg["trigger_force"]))
    c[10:21] = _trigger_bytes(cfg["trigger_right"], rs, rf)
    c[21:32] = _trigger_bytes(cfg["trigger_left"], ls, lf)
    c[38] = 0b00000010     # valid_flag2: ustawienie paska świetlnego
    if mode == "rumble":
        c[38] |= 0b00000100   # "compatible vibration 2" - wymagane przez nowszy firmware DualSense
    c[41] = 0x02
    c[42] = 0x00           # jasność diod gracza (0 = maks.)
    c[44:47] = bytes(_rgb(cfg))
    if not bluetooth:
        return b"\x02" + bytes(c) + bytes(15)               # raport 0x02, 63 bajty
    body = bytes([0x31, (seq & 0x0F) << 4, 0x10]) + bytes(c) + bytes(78 - 4 - 3 - 47)
    return body + _crc_bt(body)                              # raport 0x31, 78 bajtów


def build_dualshock4(cfg: dict, bluetooth: bool = False, mode: str = "apply") -> bytes:
    cfg = sanitize(cfg)
    r, g, b = _rgb(cfg)
    weak, strong = _scale255(cfg["rumble_right"]), _scale255(cfg["rumble_left"])
    if not bluetooth:
        rep = bytearray(32)
        rep[0], rep[1] = 0x05, (0x07 if mode == "rumble" else 0x06)
        rep[4], rep[5] = weak, strong
        rep[6:9] = bytes((r, g, b))
        return bytes(rep)
    rep = bytearray(78)
    rep[0], rep[1], rep[3] = 0x11, 0xC0, (0x07 if mode == "rumble" else 0x06)
    rep[6], rep[7] = weak, strong
    rep[8:11] = bytes((r, g, b))
    return bytes(rep[:74]) + _crc_bt(bytes(rep[:74]))


@dataclass
class Pad:
    path: bytes
    product: int
    bluetooth: bool
    name: str = ""
    serial: str = ""
    extra: dict = field(default_factory=dict)

    @property
    def is_dualsense(self) -> bool:
        return self.product in DUALSENSE


def _hid():
    try:
        import hid  # type: ignore
        return hid
    except Exception:
        return None


def available() -> bool:
    return _hid() is not None


def is_bluetooth(d: dict) -> bool:
    """Rozpoznanie połączenia: nowsze hidapi podaje bus_type (1=USB, 2=Bluetooth); starsze - po ścieżce urządzenia Windows."""
    bus = d.get("bus_type")
    if bus in (1, 2):
        return bus == 2
    path = str(d.get("path", b"")).lower()
    return "bthenum" in path or "00001124" in path or "bthledevice" in path


def detect() -> list[Pad]:
    hid = _hid()
    if not hid:
        return []
    pads, seen = [], set()
    try:
        for d in hid.enumerate(SONY, 0):
            pid = d.get("product_id")
            if pid not in MODELS or d.get("path") in seen:
                continue
            # kontroler ma kilka interfejsów HID; interesuje nas ten z padem (usage page 1, usage 5)
            if d.get("usage_page") not in (1, 0) or d.get("usage") not in (5, 0):
                continue
            seen.add(d["path"])
            bt = is_bluetooth(d)
            pads.append(Pad(d["path"], pid, bt, MODELS[pid], str(d.get("serial_number") or "")))
    except Exception:
        log.warning("Wyszukiwanie padów nie powiodło się", exc_info=True)
    return pads


def apply(pad: Pad, cfg: dict, seq: int = 0, rumble: bool = False, mode: str = "") -> tuple[bool, str]:
    hid = _hid()
    if not hid:
        return False, "Brak biblioteki HID - zainstaluj wersję aplikacji z obsługą padów."
    mode = mode or ("rumble" if rumble else "apply")
    trig = cfg.get("_trig") if isinstance(cfg, dict) else None
    cfg = sanitize(cfg)
    if trig:
        cfg["_trig"] = trig
    if mode != "rumble" and not rumble:     # zwykłe zastosowanie nie ma wibrować - wibracje tylko w teście
        cfg = dict(cfg, rumble_left=0, rumble_right=0)
    report = (build_dualsense(cfg, pad.bluetooth, seq, mode) if pad.is_dualsense else build_dualshock4(cfg, pad.bluetooth, mode))
    try:
        dev = hid.device()
        dev.open_path(pad.path)
        try:
            n = dev.write(report)
        finally:
            dev.close()
        return (n > 0), ("Zastosowano." if n > 0 else "Pad nie przyjął ustawień.")
    except Exception as e:
        log.warning("Zapis do pada nie powiódł się: %s", e)
        return False, f"Nie udało się wysłać ustawień do pada: {e}"


def pulse(pad: Pad, cfg: dict) -> tuple[bool, str]:
    """Krótki test wibracji: wysyła ustawienia z wibracją, po 0,6 s wyłącza silniki."""
    import time
    ok, msg = apply(pad, cfg, rumble=True)
    if not ok:
        return ok, msg
    time.sleep(0.7)
    off = dict(sanitize(cfg), rumble_left=0, rumble_right=0)
    # zatrzymanie MUSI iść w trybie "rumble" (z flagą wibracji), inaczej pad dostaje zera "do wiadomości" i dalej wibruje
    ok2, _ = apply(pad, off, mode="rumble")
    return ok2, "Test wibracji wykonany." if ok2 else "Nie udało się zatrzymać wibracji."


# --------------------------------------------------------------------------- automatyczna siła spustów wg gry
RACING = {"forza5", "forza4", "ets2", "ats", "ac", "acc", "beamng", "nfsunbound", "crew", "motortown"}
SHOOTER = {"cs2", "valorant", "warzone", "cod", "apex", "r6", "fortnite", "pubg", "tarkov", "bf2042", "overwatch2", "marvelrivals",
           "tf2", "l4d2", "helldivers2", "deltaforce", "r6x", "deadlock"}


def trigger_overrides(game_ids) -> dict:
    """Wyścigi: lewy spust (hamulec) twardy, prawy (gaz) lekki z oporem. Strzelanki: prawy jak spust broni. Inaczej: bez zmian."""
    ids = set(game_ids or ())
    if ids & RACING:
        return {"trigger_left": "rigid", "trigger_right": "rigid", "_l": (15, 75), "_r": (10, 30)}
    if ids & SHOOTER:
        return {"trigger_left": "rigid", "trigger_right": "section", "_l": (20, 35), "_r": (30, 70)}
    return {}


def effective_config(cfg: dict, game_ids) -> dict:
    cfg = sanitize(cfg)
    if not cfg["auto_triggers"]:
        return cfg
    ov = trigger_overrides(game_ids)
    if not ov:
        return cfg
    out = dict(cfg)
    out["trigger_left"], out["trigger_right"] = ov["trigger_left"], ov["trigger_right"]
    out["_trig"] = {"left": ov["_l"], "right": ov["_r"]}
    return out


class Keeper:
    """Wątek, który co kilka sekund odświeża kolor i spusty - pasek świetlny pada wraca do domyślnego, gdy cokolwiek
    (Steam, gra, usypianie Bluetooth) go przestawi. Nie dotyka wibracji gier ani głośności."""

    def __init__(self, get_cfg, get_games, interval: float = 3.0):
        import threading
        self._get_cfg, self._get_games, self.interval = get_cfg, get_games, interval
        self._stop = threading.Event()
        self._t = threading.Thread(target=self._run, daemon=True)
        self.last_error = ""

    def start(self) -> None:
        if not self._t.is_alive():
            self._t.start()

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        import time
        seq, pads, pads_at, batt, batt_at, t0 = 0, [], 0.0, None, 0.0, time.time()
        wait = self.interval
        while not self._stop.wait(wait):
            try:
                cfg = sanitize(self._get_cfg())
                animated = cfg["mode"] != "static"
                wait = (0.22 if animated else self.interval)
                if not cfg["keep"] and not animated or not available():
                    wait = self.interval
                    continue
                now = time.time()
                if now - pads_at > (4 if animated else 0):
                    pads, pads_at = detect(), now
                if cfg["mode"] == "battery" and pads and now - batt_at > 25:
                    info = battery(pads[0])
                    batt = info["percent"] if info else batt
                    batt_at = now
                eff = effective_config(cfg, self._get_games())
                if animated:
                    eff["_rgb"] = frame_color(cfg, now - t0, batt)
                for pad in pads:
                    seq = (seq + 1) & 0x0F
                    apply(pad, eff, seq, mode="keep")
            except Exception:
                log.debug("Keeper: błąd odświeżania pada", exc_info=True)


# --------------------------------------------------------------------------- bateria
def parse_battery(report: bytes, pad: Pad) -> Optional[dict]:
    """Czyta poziom baterii z raportu wejściowego. Zwraca {'percent': int, 'state': 'discharging'|'charging'|'full'} lub None."""
    if not report:
        return None
    rid = report[0]
    if pad.is_dualsense:
        idx = {0x01: 53, 0x31: 54}.get(rid)
        if idx is None or len(report) <= idx:
            return None
        v = report[idx]
        level, st = v & 0x0F, (v >> 4) & 0x0F
        if st == 2:
            return {"percent": 100, "state": "full"}
        if st in (0, 1):
            return {"percent": min(100, level * 10 + 5), "state": "charging" if st == 1 else "discharging"}
        return None
    idx = {0x01: 30, 0x11: 32}.get(rid)
    if idx is None or len(report) <= idx:
        return None
    v = report[idx]
    level, cable = v & 0x0F, bool(v & 0x10)
    if cable:
        pct = min(100, level * 100 // 11)
        return {"percent": 100 if level >= 11 else pct, "state": "full" if level >= 11 else "charging"}
    return {"percent": min(100, level * 100 // 8), "state": "discharging"}


def battery(pad: Pad) -> Optional[dict]:
    """Odczyt baterii (po zapisie raportu pad przełącza się na pełne raporty - przez Bluetooth jest to konieczne)."""
    hid = _hid()
    if not hid:
        return None
    try:
        dev = hid.device()
        dev.open_path(pad.path)
        try:
            for _ in range(6):
                data = bytes(dev.read(96, 250) or b"")
                r = parse_battery(data, pad)
                if r:
                    return r
        finally:
            dev.close()
    except Exception:
        log.debug("Odczyt baterii nie powiódł się", exc_info=True)
    return None

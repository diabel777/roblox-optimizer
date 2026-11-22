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
    return out


def _scale255(pct: int) -> int:
    return round(clamp(pct, 0, 100, 0) * 255 / 100)


def _rgb(cfg: dict) -> tuple[int, int, int]:
    k = cfg["brightness"] / 100
    return tuple(round(x * k) for x in cfg["color"])  # type: ignore[return-value]


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


def build_dualsense(cfg: dict, bluetooth: bool = False, seq: int = 0) -> bytes:
    cfg = sanitize(cfg)
    c = bytearray(47)
    # valid_flag0: 0 wibracje, 2 spust prawy, 3 spust lewy, 4 słuchawki, 5 głośnik, 6 mikrofon, 7 sterowanie audio
    c[0] = 0b11111101
    # valid_flag1: 0 dioda mikrofonu, 2 pasek świetlny
    c[1] = 0b00000101
    c[2] = _scale255(cfg["rumble_right"])
    c[3] = _scale255(cfg["rumble_left"])
    c[4] = _scale255(cfg["headphone"])
    c[5] = _scale255(cfg["speaker"])
    c[6] = _scale255(cfg["mic"])
    c[7] = 0x10 if cfg["mic"] else 0x00
    c[8] = 1 if cfg["mic_led"] else 0
    c[10:21] = _trigger_bytes(cfg["trigger_right"], cfg["trigger_start"], cfg["trigger_force"])
    c[21:32] = _trigger_bytes(cfg["trigger_left"], cfg["trigger_start"], cfg["trigger_force"])
    c[38] = 0b00000010     # valid_flag2: ustawienie paska świetlnego
    c[41] = 0x02
    c[42] = 0x00           # jasność diod gracza (0 = maks.)
    c[44:47] = bytes(_rgb(cfg))
    if not bluetooth:
        return b"\x02" + bytes(c) + bytes(15)               # raport 0x02, 63 bajty
    body = bytes([0x31, (seq & 0x0F) << 4, 0x10]) + bytes(c) + bytes(78 - 4 - 3 - 47)
    return body + _crc_bt(body)                              # raport 0x31, 78 bajtów


def build_dualshock4(cfg: dict, bluetooth: bool = False) -> bytes:
    cfg = sanitize(cfg)
    r, g, b = _rgb(cfg)
    weak, strong = _scale255(cfg["rumble_right"]), _scale255(cfg["rumble_left"])
    if not bluetooth:
        rep = bytearray(32)
        rep[0], rep[1] = 0x05, 0xFF
        rep[4], rep[5] = weak, strong
        rep[6:9] = bytes((r, g, b))
        return bytes(rep)
    rep = bytearray(78)
    rep[0], rep[1], rep[3] = 0x11, 0xC0, 0x07
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
            bt = (d.get("interface_number", 0) in (-1,)) or "bth" in str(d.get("path", b"")).lower()
            pads.append(Pad(d["path"], pid, bt, MODELS[pid], str(d.get("serial_number") or "")))
    except Exception:
        log.warning("Wyszukiwanie padów nie powiodło się", exc_info=True)
    return pads


def apply(pad: Pad, cfg: dict, seq: int = 0, rumble: bool = False) -> tuple[bool, str]:
    hid = _hid()
    if not hid:
        return False, "Brak biblioteki HID - zainstaluj wersję aplikacji z obsługą padów."
    cfg = sanitize(cfg)
    if not rumble:            # zwykłe zastosowanie nie ma wibrować - wibracje tylko w teście
        cfg = dict(cfg, rumble_left=0, rumble_right=0)
    report = (build_dualsense(cfg, pad.bluetooth, seq) if pad.is_dualsense else build_dualshock4(cfg, pad.bluetooth))
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
    time.sleep(0.6)
    off = dict(sanitize(cfg), rumble_left=0, rumble_right=0)
    return apply(pad, off)

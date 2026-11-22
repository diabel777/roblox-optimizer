"""Udostępnianie profili: eksport i import zestawu ustawień jako mały plik JSON.

Nic nie jest wysyłane przez sieć - plik wysyłasz (albo nie) sam. Import jest ostrożny:
* plik jest tylko DANYMI - nie zawiera kodu, ścieżek ani poleceń, a każde pole jest sprawdzane względem listy dozwolonych,
* nieznane klucze są ignorowane, liczby mają twarde zakresy, rozmiar pliku jest ograniczony,
* przed zastosowaniem użytkownik widzi czytelną listę zmian i musi ją zatwierdzić."""
from __future__ import annotations

import json
import re
import time
from typing import Any, Iterable

FORMAT = "pou-profile"
VERSION = 1
MAX_BYTES = 64 * 1024
_ID = re.compile(r"^[A-Za-z0-9_.\-]{1,64}$")

AUTO_BOOL = {"ram", "dns", "clean", "tweaks", "defender", "game_boost"}
AUTO_NUM = {("ram", "threshold_pct"): (50, 95), ("ram", "min_interval_min"): (1, 120),
            ("dns", "interval_hours"): (1, 168), ("clean", "interval_hours"): (1, 168),
            ("tweaks", "interval_hours"): (1, 168), ("defender", "interval_hours"): (1, 168)}


class ProfileError(ValueError):
    pass


def _num(v: Any, lo: float, hi: float) -> float:
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not (lo <= v <= hi):
        raise ProfileError("liczba poza dozwolonym zakresem")
    return v


def _name(v: Any) -> str:
    s = re.sub(r"[\x00-\x1f\x7f]", " ", str(v or "")).strip()
    return s[:60]


def export_profile(settings_get, tweak_states: dict, name: str = "", app_version: str = "") -> dict:
    """settings_get - funkcja settings.get. tweak_states: {id: True/False/None}."""
    rb = settings_get("roblox_profile") or {}
    fan = settings_get("fan") or {}
    auto = settings_get("auto") or {}
    out: dict[str, Any] = {
        "format": FORMAT, "version": VERSION, "app_version": app_version, "created": int(time.time()),
        "name": _name(name) or "Mój profil",
        "tweaks": sorted(k for k, v in tweak_states.items() if v is True),
        "roblox": {"preset": str(rb.get("preset", "balanced")), "fps": int(rb.get("fps", 0) or 0)},
        "fan": {"curve": str(fan.get("curve", "balanced"))},
        "auto": {},
    }
    for k in AUTO_BOOL:
        sec = auto.get(k)
        if isinstance(sec, dict):
            out["auto"][k] = {kk: vv for kk, vv in sec.items()
                              if kk == "enabled" or (k, kk) in AUTO_NUM}
    return out


def parse(raw: bytes | str, known_tweaks: Iterable[str], presets: Iterable[str], curves: Iterable[str]) -> dict:
    """Waliduje i normalizuje profil. Zwraca czysty słownik albo rzuca ProfileError."""
    if isinstance(raw, str):
        raw = raw.encode("utf-8")
    if len(raw) > MAX_BYTES:
        raise ProfileError("Plik profilu jest za duży.")
    try:
        d = json.loads(raw.decode("utf-8"))
    except Exception:
        raise ProfileError("To nie jest poprawny plik profilu.") from None
    if not isinstance(d, dict) or d.get("format") != FORMAT:
        raise ProfileError("To nie jest plik profilu PRO Ultimate Optimizer.")
    if d.get("version") != VERSION:
        raise ProfileError("Profil pochodzi z nowszej wersji programu - zaktualizuj aplikację.")
    known, presets, curves = set(known_tweaks), set(presets), set(curves)
    out: dict[str, Any] = {"name": _name(d.get("name")) or "Profil", "tweaks": [], "auto": {}}
    tw = d.get("tweaks", [])
    if not isinstance(tw, list) or len(tw) > 64:
        raise ProfileError("Nieprawidłowa lista optymalizacji.")
    out["tweaks"] = [t for t in dict.fromkeys(tw) if isinstance(t, str) and _ID.match(t) and t in known]
    rb = d.get("roblox")
    if isinstance(rb, dict):
        preset = rb.get("preset")
        if isinstance(preset, str) and preset in presets:
            out["roblox"] = {"preset": preset, "fps": int(_num(rb.get("fps", 0), 0, 1000))}
    fan = d.get("fan")
    if isinstance(fan, dict) and isinstance(fan.get("curve"), str) and fan["curve"] in curves:
        out["fan"] = {"curve": fan["curve"]}
    auto = d.get("auto")
    if isinstance(auto, dict):
        for k in AUTO_BOOL:
            sec = auto.get(k)
            if not isinstance(sec, dict):
                continue
            clean: dict[str, Any] = {}
            if isinstance(sec.get("enabled"), bool):
                clean["enabled"] = sec["enabled"]
            for (kk, nn), (lo, hi) in AUTO_NUM.items():
                if kk == k and nn in sec:
                    clean[nn] = _num(sec[nn], lo, hi)
            if clean:
                out["auto"][k] = clean
    return out


def describe(p: dict, tweak_names: dict[str, str], preset_names: dict[str, str], curve_names: dict[str, str],
             auto_labels: dict[str, str]) -> list[str]:
    lines = []
    if p["tweaks"]:
        lines.append("Włączy optymalizacje: " + ", ".join(tweak_names.get(t, t) for t in p["tweaks"]) + ".")
    if "roblox" in p:
        fps = p["roblox"]["fps"]
        lines.append(f"Roblox: profil „{preset_names.get(p['roblox']['preset'], p['roblox']['preset'])}”"
                     + (f", limit {fps} FPS." if fps else "."))
    if "fan" in p:
        lines.append(f"Krzywa wentylatora: {curve_names.get(p['fan']['curve'], p['fan']['curve'])}.")
    for k, sec in p["auto"].items():
        if "enabled" in sec:
            lines.append(f"Automatyzacja „{auto_labels.get(k, k)}”: {'włączona' if sec['enabled'] else 'wyłączona'}.")
    return lines or ["Ten profil nic nie zmienia."]


def apply_settings(p: dict, settings) -> None:
    """Zapisuje część ustawieniową profilu (bez rejestru - optymalizacje włącza wywołujący przez winsys)."""
    if "roblox" in p:
        prof = dict(settings.get("roblox_profile") or {})
        prof.update(p["roblox"])
        settings.set("roblox_profile", prof)
    if "fan" in p:
        f = dict(settings.get("fan") or {})
        f["curve"] = p["fan"]["curve"]
        settings.set("fan", f)
    if p["auto"]:
        from . import automation
        cur = automation.merged(settings.get("auto"))
        for k, sec in p["auto"].items():
            cur[k].update(sec)
        settings.set("auto", cur)

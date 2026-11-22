"""„Dopasuj do mojego komputera": wybiera bezpieczne optymalizacje na podstawie sprzętu i uprawnień. Zwraca PLAN (czyste dane);
wykonuje go dopiero UI po potwierdzeniu użytkownika."""
from __future__ import annotations

from typing import Optional

from . import winsys

SAFE_FOR_ALL = ["gamemode", "gamedvr", "mouse_accel", "bg_apps", "fse"]
HIGH_PERF = ["power", "power_throttling", "prio_sep", "mmcss"]


def plan(ram_gb: Optional[float], laptop: bool, admin: bool) -> dict:
    ids = list(SAFE_FOR_ALL)
    reasons = {"gamemode": "Windows daje priorytet grze", "gamedvr": "mniej przycięć bez nagrywania w tle",
               "mouse_accel": "równa, przewidywalna mysz", "bg_apps": "mniej programów w tle", "fse": "lepszy tryb pełnego ekranu"}
    skipped = []
    if laptop:
        skipped.append("Plan „Najwyższa wydajność” pominięty - laptop szybciej by się grzał i rozładowywał.")
    else:
        for t in HIGH_PERF:
            (ids if admin else skipped).append(t if admin else f"{t}: wymaga administratora")
        reasons.update({"power": "procesor bez oszczędzania", "power_throttling": "brak dławienia aplikacji",
                        "prio_sep": "pierwszy plan ma pierwszeństwo", "mmcss": "gry i sieć bez ograniczeń systemu"})
    if admin and "transparency" not in ids and ram_gb is not None and ram_gb < 12:
        ids.append("transparency")
        reasons["transparency"] = "mało RAM - wyłączamy przezroczystość"
    known = {t.id for t in winsys.TWEAKS}
    ids = [i for i in ids if i in known]
    return {"tweaks": ids, "reasons": reasons, "skipped": skipped}

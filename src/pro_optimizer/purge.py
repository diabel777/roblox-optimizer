"""Całkowite usunięcie: najpierw cofa to, co aplikacja zmieniła w systemie i w grach, potem kasuje siebie razem z danymi.
Cel: po tej operacji nic z aplikacji nie zostaje (skróty, wpis w Aplikacjach, autostart, ustawienia, kopie, logi)."""
from __future__ import annotations

import logging
from typing import Callable, Optional

from . import appopt, background, config, install, roblox, winsys

log = logging.getLogger(__name__)


def _our_flag_names() -> set[str]:
    names: set[str] = set()
    for p in config.load_presets():
        names |= set((p.get("flags") or {}).keys())
    return names | {"DFIntTaskSchedulerTargetFps"}


def _is_only_ours(flags: dict, ours: set[str]) -> bool:
    return bool(flags) and all(k in ours for k in flags)


def revert_everything(settings, progress: Optional[Callable[[str], None]] = None) -> list[str]:
    """Cofa zmiany. Zwraca listę opisów (także tych, których nie dało się cofnąć)."""
    say = progress or (lambda m: None)
    out: list[str] = []

    say("Przywracam ustawienia Windows…")
    backups = settings.get("tweaks_backup") or {}
    for t in winsys.TWEAKS:
        if t.id in backups or (t.special == "power" and "_power" in backups):
            ok, msg = winsys.revert_tweak(t, settings)
            out.append(f"{t.name}: {'cofnięto' if ok else 'nie cofnięto - ' + msg}")

    say("Sprawdzam pliki Robloxa…")
    ours = _our_flag_names()
    try:
        for kind, inst in roblox.find_installs().items():
            if not inst or not inst.settings_path.exists():
                continue
            flags = roblox.read_flags(inst)
            if _is_only_ours(flags, ours):
                inst.settings_path.unlink(missing_ok=True)
                out.append(f"Roblox ({kind}): usunięto plik ustawień utworzony przez aplikację")
            elif flags:
                out.append(f"Roblox ({kind}): plik ma też Twoje własne flagi - zostawiono bez zmian")
    except Exception:
        log.warning("purge: Roblox", exc_info=True)

    say("Przywracam priorytety programów…")
    try:
        appopt.restore_background()
    except Exception:
        pass
    background.set_autostart(False)
    out.append("Autostart z Windows: wyłączony")
    return out


def purge(settings, progress: Optional[Callable[[str], None]] = None) -> list[str]:
    """Cofa zmiany i odinstalowuje aplikację razem z danymi (po zamknięciu procesu kasuje katalog)."""
    out = revert_everything(settings, progress)
    (progress or (lambda m: None))("Usuwam aplikację i wszystkie jej pliki…")
    out += install.uninstall(remove_data=True)
    return out

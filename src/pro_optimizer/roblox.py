"""Wykrywanie Robloxa/Studio i zarządzanie ClientAppSettings.json (FastFlags).

Ważne (powód przepisania modułu z v3.x):
  * ustawienia muszą leżeć w folderze AKTUALNEJ wersji:  Versions\\version-xxxx\\ClientSettings\\
    (v3.x brało pierwszy folder z glob-a - często starą wersję, a Playera zapisywało w złym miejscu),
  * każda aktualizacja Robloxa tworzy nowy folder wersji i ustawienia "znikają" - dlatego
    reapply_if_needed() odtwarza zapisany profil automatycznie,
  * Roblox Player stosuje allowlistę flag - nieznane flagi są po cichu ignorowane.
"""
from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from . import backups, paths

log = logging.getLogger(__name__)

FLAG_NAME = re.compile(r"^(?:D|S)?F(Flag|Int|String|Log)[A-Za-z0-9_]+$")

# Flagi, które według publicznej allowlisty Roblox są respektowane przez Playera (stan na 2026,
# lista może się zmieniać). Użyte tylko do oznaczania "może być ignorowane" w interfejsie.
PLAYER_ALLOWLIST = {
    "FFlagDebugGraphicsPreferD3D11", "FFlagDebugGraphicsPreferVulkan", "FFlagDebugGraphicsPreferOpenGL",
    "DFFlagTextureQualityOverrideEnabled", "DFIntTextureQualityOverride",
    "DFIntCSGLevelOfDetailSwitchingDistance", "DFIntCSGLevelOfDetailSwitchingDistanceL12",
    "DFIntCSGLevelOfDetailSwitchingDistanceL23", "DFIntCSGLevelOfDetailSwitchingDistanceL34",
    "FFlagHandleAltEnterFullscreenManually", "DFFlagDisableDPIScale", "FIntDebugForceMSAASamples",
    "FFlagDebugSkyGray", "DFFlagDebugPauseVoxelizer", "DFIntDebugFRMQualityLevelOverride",
    "FIntFRMMaxGrassDistance", "FIntFRMMinGrassDistance", "FIntGrassMovementReducedMotionFactor",
}
FPS_FLAG = "DFIntTaskSchedulerTargetFps"


@dataclass
class Install:
    kind: str            # "player" | "studio"
    dir: Path            # ...\Versions\version-xxxx
    exe: Path

    @property
    def version(self) -> str:
        return self.dir.name

    @property
    def settings_path(self) -> Path:
        return self.dir / "ClientSettings" / "ClientAppSettings.json"


def _version_roots() -> list[Path]:
    cands = []
    la = os.environ.get("LOCALAPPDATA")
    if la:
        cands.append(Path(la) / "Roblox" / "Versions")
    for env in ("PROGRAMFILES(X86)", "PROGRAMFILES"):
        v = os.environ.get(env)
        if v:
            cands.append(Path(v) / "Roblox" / "Versions")
    return [c for c in cands if c.is_dir()]


def find_installs() -> dict[str, Optional[Install]]:
    """Najnowsza instalacja (wg daty pliku exe) dla Playera i Studio."""
    best: dict[str, tuple[float, Install]] = {}
    for root in _version_roots():
        for d in root.glob("version-*"):
            for kind, exe_name in (("player", "RobloxPlayerBeta.exe"), ("studio", "RobloxStudioBeta.exe")):
                exe = d / exe_name
                if exe.exists():
                    try:
                        mt = exe.stat().st_mtime
                    except OSError:
                        continue
                    if kind not in best or mt > best[kind][0]:
                        best[kind] = (mt, Install(kind, d, exe))
    return {"player": best.get("player", (0, None))[1], "studio": best.get("studio", (0, None))[1]}


# --------------------------------------------------------------------------- flagi
def validate_flags(flags: dict) -> list[str]:
    errors = []
    for k, v in flags.items():
        m = FLAG_NAME.match(k)
        if not m:
            errors.append(f"Nieprawidłowa nazwa flagi: {k}")
            continue
        kind = m.group(1)          # typ wynika z PREFIKSU nazwy (FFlag/FInt/FString/FLog)
        if kind == "Flag" and not isinstance(v, bool):
            errors.append(f"{k}: wartość musi być true/false")
        elif kind == "Int" and (isinstance(v, bool) or not isinstance(v, int)):
            errors.append(f"{k}: wartość musi być liczbą całkowitą")
        elif kind == "String" and not isinstance(v, str):
            errors.append(f"{k}: wartość musi być tekstem")
    return errors


def ignored_by_player(flags: dict) -> list[str]:
    """Flagi, które Player najpewniej zignoruje (spoza allowlisty)."""
    return [k for k in flags if k not in PLAYER_ALLOWLIST]


def read_flags(inst: Install) -> dict:
    try:
        with open(inst.settings_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except FileNotFoundError:
        return {}
    except Exception as e:
        log.warning("Nie można odczytać %s: %s", inst.settings_path, e)
        return {}


def build_flags(preset_flags: dict, fps: int = 0, existing: Optional[dict] = None, merge: bool = True) -> dict:
    out = dict(existing or {}) if merge else {}
    out.update(preset_flags)
    if fps and fps > 0:
        out[FPS_FLAG] = int(fps)
    return out


def apply_flags(inst: Install, flags: dict, keep: int = 30) -> Path:
    errs = validate_flags(flags)
    if errs:
        raise ValueError("; ".join(errs))
    sp = inst.settings_path
    sp.parent.mkdir(parents=True, exist_ok=True)
    if sp.exists():
        backups.make_backup(sp, inst.kind.capitalize())
        backups.prune(keep)
    tmp = sp.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(flags, f, indent=2)
    os.replace(tmp, sp)                          # zapis atomowy
    return sp


def manual_backup(inst: Install) -> Optional[Path]:
    return backups.make_backup(inst.settings_path, f"Manual_{inst.kind.capitalize()}")


def reset(inst: Install) -> bool:
    sp = inst.settings_path
    if sp.exists():
        backups.make_backup(sp, f"BeforeReset_{inst.kind.capitalize()}")
        sp.unlink()
        return True
    return False


# --------------------------------------------------------------------------- reapply po aktualizacji Robloxa
def reapply_if_needed(profile: dict, presets: list[dict]) -> list[str]:
    """Jeśli w aktualnej wersji brakuje zapisanego profilu (np. po update Robloxa) - zapisuje go ponownie."""
    preset = next((p for p in presets if p["id"] == profile.get("preset")), None)
    if not preset:
        return []
    done = []
    installs = find_installs()
    for kind in profile.get("targets", []):
        inst = installs.get(kind)
        if not inst or kind not in preset.get("applies_to", ["player", "studio"]):
            continue
        existing = read_flags(inst)
        wanted = build_flags(preset["flags"], profile.get("fps", 0), existing, profile.get("merge", True))
        if existing != wanted:
            try:
                apply_flags(inst, wanted)
                done.append(f"{kind} ({inst.version})")
            except Exception as e:
                log.error("reapply %s: %s", kind, e)
    return done

"""Samonaprawa instalacji: po każdym starcie aplikacja pilnuje, żeby launcher, skróty i wpis w Aplikacjach istniały.

Dlaczego: launcher (ProUltimateOptimizer.exe) jest małym, niepodpisanym plikiem. Gdy antywirus lub czyszczenie dysku
go usunie, skrót przestaje działać ("Problem ze skrótem"). Aplikacja trzyma więc jego kopię zapasową i sama ją
przywraca; gdy kopii nie ma, skróty wskazują bezpośrednio na najnowszą wersję aplikacji."""
from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import Optional

from . import paths, shell
from .install import launcher_path, replace_file
from .updater import installed_versions
from .version import APP_EXE, LAUNCHER_EXE, VERSION

log = logging.getLogger(__name__)
BACKUP = "launcher.bak"


def _newest_app(root: Path) -> Optional[Path]:
    vers = [d for _, d in installed_versions(root) if not (d / ".bad").exists()]
    return (vers[-1] / APP_EXE) if vers else None


def ensure(root: Optional[Path] = None, last_shortcut_version: str = "") -> dict:
    """Zwraca opis tego, co naprawiono: {'launcher': bool, 'shortcuts': bool, 'registry': bool}."""
    root = Path(root) if root else paths.install_root()
    fixed = {"launcher": False, "shortcuts": False, "registry": False}
    if not root.exists():
        return fixed
    lp = launcher_path(root)
    bak = root / BACKUP
    try:
        if lp.exists():
            if not bak.exists() or bak.stat().st_size != lp.stat().st_size:
                shutil.copy2(lp, bak)
        elif bak.exists():
            replace_file(bak, lp)
            fixed["launcher"] = True
            log.warning("Przywrócono launcher z kopii zapasowej")
    except OSError:
        log.warning("Nie udało się sprawdzić launchera", exc_info=True)

    target = lp if lp.exists() else _newest_app(root)
    if not target:
        return fixed
    icon = root / "app.ico"
    icon = icon if icon.exists() else None
    existing = shell.shortcut_paths()
    need = (not lp.exists()) or last_shortcut_version != VERSION or any(not p.exists() for p in existing.values())
    if need:
        made = shell.create_shortcuts(target, icon, True, True)
        fixed["shortcuts"] = bool(made)
    if shell.NT:
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, shell.UNINSTALL_KEY):
                pass
        except OSError:
            fixed["registry"] = shell.register_uninstall(root, VERSION, target, icon)
    return fixed

"""Kopie zapasowe ustawień (FFlags) i ich przywracanie. Folder: %LOCALAPPDATA%\\ProUltimateOptimizer\\Backups"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from . import paths

log = logging.getLogger(__name__)


@dataclass
class BackupItem:
    name: str
    path: Path
    size: int
    mtime: float

    @property
    def kind(self) -> str:
        n = self.name.lower()
        if n.endswith(".reg"):
            return "registry"
        return "studio" if "studio" in n else "player"


def make_backup(src: Path, prefix: str) -> Optional[Path]:
    """Kopiuje plik `src` do Backups jako <prefix>_ClientAppSettings_<data>.json.bak."""
    src = Path(src)
    if not src.exists():
        return None
    paths.backups_dir().mkdir(parents=True, exist_ok=True)
    dst = paths.backups_dir() / f"{prefix}_ClientAppSettings_{time.strftime('%Y-%m-%d_%H-%M-%S')}.json.bak"
    n = 1
    while dst.exists():                       # dwie kopie w tej samej sekundzie
        dst = dst.with_name(dst.name.replace(".json.bak", f"_{n}.json.bak"))
        n += 1
    shutil.copy2(src, dst)
    return dst


def list_backups() -> list[BackupItem]:
    d = paths.backups_dir()
    items = []
    if d.exists():
        for p in d.iterdir():
            if p.is_file():
                st = p.stat()
                items.append(BackupItem(p.name, p, st.st_size, st.st_mtime))
    return sorted(items, key=lambda b: b.mtime, reverse=True)


def prune(max_keep: int) -> None:
    items = [b for b in list_backups() if b.kind != "registry"]
    for b in items[max_keep:]:
        try:
            b.path.unlink()
        except OSError:
            pass


def delete_backup(item: BackupItem) -> None:
    item.path.unlink(missing_ok=True)


def restore(item: BackupItem, target: Optional[Path]) -> str:
    """Przywraca kopię. Dla JSON potrzebny `target` (ClientAppSettings.json), dla .reg import do rejestru."""
    if item.kind == "registry":
        if os.name != "nt":
            raise RuntimeError("Import rejestru działa tylko w Windows")
        r = subprocess.run(["reg", "import", str(item.path)], capture_output=True, text=True,
                           creationflags=0x08000000)
        if r.returncode != 0:
            raise RuntimeError((r.stderr or r.stdout or "reg import nie powiódł się").strip())
        return "Przywrócono wpisy rejestru."
    if target is None:
        raise RuntimeError("Nie znaleziono zainstalowanego Robloxa/Studio dla tej kopii.")
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(item.path, target)
    return f"Przywrócono ustawienia do {target}"

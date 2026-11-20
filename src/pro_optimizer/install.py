"""Logika instalacji / odinstalowania (bez GUI - używa jej instalator, launcher i testy).

Układ po instalacji (identyczny jak w Discordzie):
    %LOCALAPPDATA%\\ProUltimateOptimizer\\
        ProUltimateOptimizer.exe     launcher - na niego wskazują skróty i wpis w „Aplikacje”
        app.ico                      ikona skrótów
        app-4.0.0\\...               aplikacja (kolejne wersje lądują obok, nic się nie nadpisuje)
        Backups\\ config\\ logs\\ settings.json     Twoje dane - aktualizacje ich nie ruszają
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from . import paths, shell
from .version import APP_EXE, APP_ID, LAUNCHER_EXE

log = logging.getLogger(__name__)

Progress = Callable[[str, float, str], None]     # (etap, 0..1, tekst dla użytkownika)

# Pliki zostawione przez v3.x (jednoplikowy exe + bat-updater). Ustawienia/kopie (Backups) zostają.
LEGACY_FILES = ("RobloxStudioOptimizer.exe", "optimizer_updater.exe", "update.bat")


@dataclass
class InstallOptions:
    desktop: bool = True
    start_menu: bool = True
    launch: bool = True


@dataclass
class InstallResult:
    version: str
    root: Path
    launcher: Path
    shortcuts: list[str] = field(default_factory=list)
    registered: bool = False


def launcher_path(root: Optional[Path] = None) -> Path:
    return (root or paths.install_root()) / LAUNCHER_EXE


def is_installed(root: Optional[Path] = None) -> bool:
    from .updater import installed_versions
    root = root or paths.install_root()
    return launcher_path(root).exists() and bool(installed_versions(root))


def find_payload(name: str) -> Optional[Path]:
    """Szuka pliku dołączonego do Setup.exe (launcher, ikona). W dev także w dist/ i assets/."""
    base = paths.resource_dir()
    for p in (base / "payload" / name, base / "dist" / name, base / "assets" / name):
        if p.exists():
            return p
    return None


def replace_file(src: Path, dest: Path) -> None:
    """Podmienia plik także wtedy, gdy stary jest właśnie uruchomiony (Windows pozwala go przemianować)."""
    tmp = dest.with_name(dest.name + ".new")
    shutil.copy2(src, tmp)
    try:
        os.replace(tmp, dest)
    except PermissionError:
        old = dest.with_name(dest.name + ".old")
        try:
            old.unlink(missing_ok=True)
        except OSError:
            pass
        os.replace(dest, old)
        os.replace(tmp, dest)


def migrate_legacy(root: Path) -> list[str]:
    """Sprząta po v3.x. Nie rusza Backups/ - kopie zapasowe użytkownika zostają."""
    removed = []
    for name in LEGACY_FILES:
        p = root / name
        if p.exists():
            try:
                p.unlink()
                removed.append(name)
            except OSError:
                log.info("Nie można usunąć %s (jest używany) - zostanie pominięty", name)
    return removed


def install(opts: Optional[InstallOptions] = None, progress: Optional[Progress] = None,
            updater=None, launcher_src: Optional[Path] = None, icon_src: Optional[Path] = None,
            root: Optional[Path] = None) -> InstallResult:
    """Pełna instalacja / naprawa / aktualizacja do najnowszej wersji. Rzuca wyjątek z czytelnym komunikatem."""
    from .updater import Updater
    opts = opts or InstallOptions()
    root = Path(root) if root else paths.install_root()
    say = progress or (lambda *_: None)

    paths.ensure_dirs() if root == paths.install_root() else root.mkdir(parents=True, exist_ok=True)
    say("connect", 0.02, "Łączenie z serwerem aktualizacji…")
    up = updater or Updater(current_version="0", root=root)       # "0" => zawsze bierz najnowszą wersję
    info = up.check()
    if info is None:
        raise RuntimeError("Serwer nie zwrócił żadnej wersji do zainstalowania.")

    say("download", 0.05, f"Pobieranie wersji {info.version}…")

    def dl(done: int, total: int) -> None:
        frac = done / total if total else 0
        say("download", 0.05 + 0.70 * min(frac, 1.0), f"Pobieranie wersji {info.version}…  {done / 1048576:.0f} MB")

    up.stage(info, dl)                                            # pobranie + SHA-256 + rozpakowanie

    say("install", 0.80, "Instalowanie…")
    shell.stop_running_app() if launcher_path(root).exists() else None
    migrate_legacy(root)
    src = launcher_src or find_payload(LAUNCHER_EXE)
    lp = launcher_path(root)
    if src and Path(src).exists():
        replace_file(Path(src), lp)
    elif not lp.exists():
        raise RuntimeError("Instalator jest uszkodzony: brakuje launchera. Pobierz Setup ponownie.")
    ico_src = icon_src or find_payload("icon.ico")
    ico = root / "app.ico"
    if ico_src and Path(ico_src).exists():
        try:
            replace_file(Path(ico_src), ico)
        except OSError:
            log.warning("Nie udało się zapisać ikony", exc_info=True)
    icon = ico if ico.exists() else None

    say("shortcuts", 0.90, "Tworzenie skrótów…")
    made = shell.create_shortcuts(lp, icon, opts.desktop, opts.start_menu)
    registered = shell.register_uninstall(root, info.version, lp, icon)
    try:
        up.cleanup_old(2)
    except Exception:
        log.debug("cleanup_old", exc_info=True)

    say("done", 1.0, "Gotowe!")
    log.info("Zainstalowano %s (skróty: %s, wpis w Aplikacjach: %s)", info.version, made, registered)
    return InstallResult(info.version, root, lp, made, registered)


# --------------------------------------------------------------------------- odinstalowanie
def _cmd_safe(p: Path) -> bool:
    return not any(ch in str(p) for ch in '"&%^|<>\r\n')


def _delete_after_exit(targets: list[Path]) -> None:
    """Launcher nie może skasować samego siebie - robi to osobny cmd po ok. 2 s."""
    targets = [t for t in targets if t.exists() and _cmd_safe(t)]
    if not targets:
        return
    if not shell.NT:                               # testy / Linux: nic nie blokuje plików
        for t in targets:
            shutil.rmtree(t, ignore_errors=True) if t.is_dir() else t.unlink(missing_ok=True)
        return
    # Wiersz poleceń podajemy jako GOTOWY TEKST. Przy liście argumentów Python zamieniłby cudzysłowy w ścieżce
    # na \" - a cmd.exe tego nie rozumie, więc nic by się nie skasowało. Składnia /s /c "..." jest właściwa dla cmd.
    subprocess.Popen(deferred_delete_cmdline(targets),
                     creationflags=shell.NO_WINDOW | 0x00000200, close_fds=True,     # bez okna; NEW_PROCESS_GROUP
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def deferred_delete_cmdline(targets: list[Path]) -> str:
    parts = [f'rmdir /s /q "{t}"' if t.is_dir() else f'del /f /q "{t}"' for t in targets]
    return 'cmd.exe /d /s /c "ping -n 3 127.0.0.1 >nul & ' + " & ".join(parts) + '"'


def _is_our_root(root: Path) -> bool:
    """Ochrona: kasujemy tylko katalog, który faktycznie jest katalogiem aplikacji."""
    if os.environ.get("PRO_OPT_HOME"):
        return True                                # tryb testowy
    return root.name.lower() == APP_ID.lower() and len(root.parts) > 2


def uninstall(remove_data: bool = False, root: Optional[Path] = None) -> list[str]:
    """Usuwa aplikację. Zwraca listę tego, co zrobiono. Dane (Backups, config...) tylko gdy remove_data."""
    root = Path(root) if root else paths.install_root()
    if not _is_our_root(root):
        raise RuntimeError(f"Odmowa usunięcia nieoczekiwanego katalogu: {root}")
    done = []
    shell.stop_running_app()
    shell.remove_shortcuts()
    shell.unregister_uninstall()
    done.append("skróty i wpis w Aplikacjach")

    if remove_data:
        _delete_after_exit([root])
        done.append("cały katalog aplikacji wraz z danymi")
        return done

    for d in list(root.glob("app-*")) + [root / "downloads"]:
        shutil.rmtree(d, ignore_errors=True)
    leftovers = [root / n for n in (LAUNCHER_EXE, LAUNCHER_EXE + ".old", LAUNCHER_EXE + ".new",
                                    "app.ico", "app.ico.old", "app.ico.new")]
    _delete_after_exit(leftovers)
    done.append("aplikacja (Twoje ustawienia i kopie zapasowe zostały)")
    return done

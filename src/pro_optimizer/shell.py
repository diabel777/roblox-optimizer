"""Integracja z Windows: skróty, wpis w „Aplikacje i funkcje”, zatrzymanie aplikacji.

Tylko biblioteka standardowa (używa go też maleńki launcher). Poza Windows wszystko to
bezpieczne „nic nie rób” - dzięki temu logikę instalatora da się testować na Linuksie.
Wszystko per-użytkownik (HKCU, Menu Start użytkownika) - żadna operacja nie wymaga admina.
"""
from __future__ import annotations

import logging
import os
import subprocess
from pathlib import Path
from typing import Optional

from .ps import system_exe
from .version import APP_EXE, APP_ID, APP_NAME, VERSION

log = logging.getLogger(__name__)

NT = os.name == "nt"
NO_WINDOW = 0x08000000                       # CREATE_NO_WINDOW
UNINSTALL_KEY = r"Software\Microsoft\Windows\CurrentVersion\Uninstall" + "\\" + APP_ID
PUBLISHER = "Diabeł"

_CSIDL_PROGRAMS = 0x0002                     # Menu Start\Programy (użytkownika)
_CSIDL_DESKTOP = 0x0010                      # Pulpit (z uwzględnieniem OneDrive)

# Skrypt tworzący skrót przez IShellLinkW (Unicode). Stary sposób (WScript.Shell) zamienia litery spoza systemowej strony
# kodowej ANSI - np. „ł” w nazwie użytkownika „Diabeł” - i skrót wskazuje wtedy w nieistniejące miejsce.
# Wszystkie dane idą przez zmienne środowiskowe (Unicode), a NIE przez sklejanie tekstu - nic nie może wstrzyknąć kodu.
_PS_LINK_W = r"""
$code = @'
using System;
using System.Runtime.InteropServices;
using System.Text;
public static class AderisLnk {
  [ComImport, Guid("00021401-0000-0000-C000-000000000046")] class CShellLink {}
  [ComImport, Guid("000214F9-0000-0000-C000-000000000046"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
  interface IShellLinkW {
    void GetPath([Out, MarshalAs(UnmanagedType.LPWStr)] StringBuilder pszFile, int cch, IntPtr pfd, uint fFlags);
    void GetIDList(out IntPtr ppidl);
    void SetIDList(IntPtr pidl);
    void GetDescription([Out, MarshalAs(UnmanagedType.LPWStr)] StringBuilder pszName, int cch);
    void SetDescription([MarshalAs(UnmanagedType.LPWStr)] string pszName);
    void GetWorkingDirectory([Out, MarshalAs(UnmanagedType.LPWStr)] StringBuilder pszDir, int cch);
    void SetWorkingDirectory([MarshalAs(UnmanagedType.LPWStr)] string pszDir);
    void GetArguments([Out, MarshalAs(UnmanagedType.LPWStr)] StringBuilder pszArgs, int cch);
    void SetArguments([MarshalAs(UnmanagedType.LPWStr)] string pszArgs);
    void GetHotkey(out short pwHotkey);
    void SetHotkey(short wHotkey);
    void GetShowCmd(out int piShowCmd);
    void SetShowCmd(int iShowCmd);
    void GetIconLocation([Out, MarshalAs(UnmanagedType.LPWStr)] StringBuilder pszIconPath, int cch, out int piIcon);
    void SetIconLocation([MarshalAs(UnmanagedType.LPWStr)] string pszIconPath, int iIcon);
    void SetRelativePath([MarshalAs(UnmanagedType.LPWStr)] string pszPathRel, uint dwReserved);
    void Resolve(IntPtr hwnd, uint fFlags);
    void SetPath([MarshalAs(UnmanagedType.LPWStr)] string pszFile);
  }
  [ComImport, Guid("0000010b-0000-0000-C000-000000000046"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
  interface IPersistFile {
    void GetClassID(out Guid pClassID);
    [PreserveSig] int IsDirty();
    void Load([MarshalAs(UnmanagedType.LPWStr)] string pszFileName, uint dwMode);
    void Save([MarshalAs(UnmanagedType.LPWStr)] string pszFileName, [MarshalAs(UnmanagedType.Bool)] bool fRemember);
    void SaveCompleted([MarshalAs(UnmanagedType.LPWStr)] string pszFileName);
    void GetCurFile([MarshalAs(UnmanagedType.LPWStr)] out string ppszFileName);
  }
  public static string Create(string lnk, string target, string wd, string icon, string desc) {
    var l = (IShellLinkW)new CShellLink();
    l.SetPath(target); l.SetWorkingDirectory(wd); l.SetIconLocation(icon, 0); l.SetDescription(desc);
    ((IPersistFile)l).Save(lnk, true);
    var r = (IShellLinkW)new CShellLink();
    ((IPersistFile)r).Load(lnk, 0);
    var sb = new StringBuilder(1024);
    r.GetPath(sb, 1024, IntPtr.Zero, 0);
    return sb.ToString();
  }
}
'@
Add-Type -TypeDefinition $code -ErrorAction Stop
$o = [AderisLnk]::Create($env:POU_LNK, $env:POU_TARGET, $env:POU_WD, $env:POU_ICON_PATH, $env:POU_DESC)
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
Write-Output ("TARGET=" + $o)
"""

# Zapasowy sposób (stary): działa tylko dla nazw z liter ze strony kodowej ANSI, dlatego używamy go po krótkiej ścieżce 8.3.
_PS_LINK = ("$s=(New-Object -ComObject WScript.Shell).CreateShortcut($env:POU_LNK);"
            "$s.TargetPath=$env:POU_TARGET;$s.WorkingDirectory=$env:POU_WD;"
            "$s.IconLocation=$env:POU_ICON;$s.Description=$env:POU_DESC;$s.Save()")


def _short(p: Path) -> str:
    """Krótka (8.3, same znaki ASCII) wersja ścieżki, jeśli system ją ma; inaczej zwykła."""
    if not NT:
        return str(p)
    try:
        import ctypes
        buf = ctypes.create_unicode_buffer(1024)
        if ctypes.windll.kernel32.GetShortPathNameW(str(p), buf, 1024) and buf.value:
            return buf.value
    except Exception:
        pass
    return str(p)


def _special_folder(csidl: int) -> Optional[Path]:
    if not NT:
        return None
    try:
        import ctypes
        buf = ctypes.create_unicode_buffer(260)
        if ctypes.windll.shell32.SHGetFolderPathW(0, csidl, 0, 0, buf) == 0 and buf.value:
            return Path(buf.value)
    except Exception:
        log.debug("SHGetFolderPathW nie zadziałało", exc_info=True)
    return None


def shortcut_paths() -> dict[str, Path]:
    out: dict[str, Path] = {}
    name = f"{APP_NAME}.lnk"
    for key, csidl in (("desktop", _CSIDL_DESKTOP), ("start_menu", _CSIDL_PROGRAMS)):
        base = _special_folder(csidl)
        if base:
            out[key] = base / name
    return out


def _run_ps(script: str, env: dict) -> tuple[int, str]:
    r = subprocess.run([system_exe("powershell"), "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", script],
                       env=env, creationflags=NO_WINDOW, timeout=60, capture_output=True, text=True, encoding="utf-8", errors="replace")
    return r.returncode, ((r.stdout or "") + (r.stderr or "")).strip()


def _same_file(a: str, b: Path) -> bool:
    try:
        return os.path.normcase(os.path.realpath(a)) == os.path.normcase(os.path.realpath(str(b))) and Path(a).exists()
    except OSError:
        return False


def create_shortcut(lnk: Path, target: Path, icon: Optional[Path] = None, description: str = APP_NAME) -> bool:
    """Tworzy skrót i SPRAWDZA, że wskazuje istniejący plik. Najpierw Unicode (IShellLinkW), potem zapasowo po ścieżce 8.3."""
    if not NT:
        return False
    try:
        lnk.parent.mkdir(parents=True, exist_ok=True)
        ico = icon or target
        base = dict(os.environ, POU_LNK=str(lnk), POU_TARGET=str(target), POU_WD=str(target.parent),
                    POU_ICON_PATH=str(ico), POU_ICON=f"{ico},0", POU_DESC=description)
        good = False
        try:
            code, out = _run_ps(_PS_LINK_W, base)
            line = next((ln for ln in out.splitlines() if ln.startswith("TARGET=")), "")
            read_back = line[len("TARGET="):].strip()
            good = code == 0 and lnk.exists() and _same_file(read_back, target)
            log.info("Skrót (Unicode) %s: kod %s, odczytany cel=%r, zgodny=%s%s", lnk.name, code, read_back, good,
                     "" if good else f" ({out[:200]})")
        except Exception as e:
            log.warning("Skrót (Unicode) %s nie powiódł się: %s", lnk, e)
        if not good:
            alt = dict(base, POU_TARGET=_short(target), POU_WD=_short(target.parent), POU_ICON=f"{_short(ico)},0")
            code, out = _run_ps(_PS_LINK, alt)
            log.info("Skrót (zapasowy, 8.3) %s: kod %s %s", lnk.name, code, out[:200])
    except Exception as e:
        log.warning("Nie udało się utworzyć skrótu %s: %s", lnk, e)
    ok = lnk.exists()
    log.info("Skrót %s -> %s : %s", lnk, target, "utworzony" if ok else "BRAK")
    return ok


def describe_shortcuts() -> list[str]:
    """Do logu: gdzie są skróty i czy ich cele istnieją (diagnostyka znikających skrótów)."""
    out = []
    for key, p in shortcut_paths().items():
        out.append(f"{key}: {p} istnieje={p.exists()}")
    return out


LEGACY_SHORTCUT_NAMES = ("PRO Ultimate Optimizer.lnk",)     # skróty sprzed zmiany nazwy na Aderis Boost


def _remove_legacy_shortcuts() -> None:
    for key, csidl in (("desktop", _CSIDL_DESKTOP), ("start_menu", _CSIDL_PROGRAMS)):
        base = _special_folder(csidl)
        for name in LEGACY_SHORTCUT_NAMES:
            if base:
                try:
                    (base / name).unlink(missing_ok=True)
                except OSError:
                    pass


def create_shortcuts(target: Path, icon: Optional[Path], desktop: bool, start_menu: bool) -> list[str]:
    """Zwraca listę utworzonych skrótów (do pokazania w podsumowaniu)."""
    _remove_legacy_shortcuts()
    made = []
    for key, want in (("desktop", desktop), ("start_menu", start_menu)):
        p = shortcut_paths().get(key)
        if want and p and create_shortcut(p, target, icon):
            made.append(key)
    return made


def remove_shortcuts() -> None:
    _remove_legacy_shortcuts()
    for p in shortcut_paths().values():
        try:
            p.unlink(missing_ok=True)
        except OSError as e:
            log.warning("Nie udało się usunąć skrótu %s: %s", p, e)


def _dir_size_kb(root: Path) -> int:
    total = 0
    for dirpath, _dirs, files in os.walk(root):
        for fn in files:
            try:
                total += os.path.getsize(os.path.join(dirpath, fn))
            except OSError:
                pass
    return total // 1024


def register_uninstall(install_root: Path, version: str, launcher: Path, icon: Optional[Path]) -> bool:
    """Wpis w Ustawienia > Aplikacje (HKCU - bez admina)."""
    if not NT:
        return False
    try:
        import winreg
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY, 0, winreg.KEY_SET_VALUE) as k:
            def s(name, val):
                winreg.SetValueEx(k, name, 0, winreg.REG_SZ, str(val))
            s("DisplayName", APP_NAME)
            s("DisplayVersion", version)
            s("Publisher", PUBLISHER)
            s("InstallLocation", install_root)
            s("DisplayIcon", icon or launcher)
            s("UninstallString", f'"{launcher}" --uninstall')
            s("QuietUninstallString", f'"{launcher}" --uninstall --quiet')
            winreg.SetValueEx(k, "NoModify", 0, winreg.REG_DWORD, 1)
            winreg.SetValueEx(k, "NoRepair", 0, winreg.REG_DWORD, 1)
            winreg.SetValueEx(k, "EstimatedSize", 0, winreg.REG_DWORD, _dir_size_kb(install_root))
        return True
    except Exception as e:
        log.warning("Nie udało się zarejestrować aplikacji w Windows: %s", e)
        return False


def unregister_uninstall() -> None:
    if not NT:
        return
    try:
        import winreg
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY)
    except FileNotFoundError:
        pass
    except Exception as e:
        log.warning("Nie udało się usunąć wpisu odinstalowania: %s", e)


def stop_running_app() -> None:
    """Zamyka działającą aplikację (przed aktualizacją launchera / odinstalowaniem)."""
    if not NT:
        return
    try:
        subprocess.run([system_exe("taskkill"), "/IM", APP_EXE, "/F"], creationflags=NO_WINDOW, timeout=15,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass


def message_box(text: str, title: str = APP_NAME, flags: int = 0x40) -> int:
    """MessageBox z ikoną (0x40 info, 0x10 błąd, 0x24 pytanie Tak/Nie). Poza Windows: stdout, 6 (=Tak)."""
    if NT:
        try:
            import ctypes
            return int(ctypes.windll.user32.MessageBoxW(0, text, title, flags))
        except Exception:
            pass
    print(f"[{title}] {text}")
    return 6

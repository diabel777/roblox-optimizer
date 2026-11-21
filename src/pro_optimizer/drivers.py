"""Sterowniki, Windows Update dla sterowników, programy (winget) i informacje o BIOS.

Sterowniki instalujemy WYŁĄCZNIE przez Windows Update (oficjalne, podpisane przez Microsoft). Sterowniki kart graficznych
najlepiej brać od producenta - dajemy bezpośrednie linki. BIOS-u celowo NIE wgrywamy z poziomu Windowsa: nieudana
aktualizacja może unieruchomić płytę, więc pokazujemy wersję, stronę producenta i listę kontrolną."""
from __future__ import annotations

import logging
import re
import shutil
import subprocess
import webbrowser
from datetime import datetime
from typing import Optional
from urllib.parse import quote_plus

from . import ps

log = logging.getLogger(__name__)
_GUID = re.compile(r"^[0-9a-fA-F]{8}-([0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}$")

GPU_PAGES = {
    "nvidia": ("NVIDIA", "https://www.nvidia.com/Download/index.aspx"),
    "amd": ("AMD", "https://www.amd.com/en/support/download/drivers.html"),
    "intel": ("Intel", "https://www.intel.com/content/www/us/en/download-center/home.html"),
}
BOARD_PAGES = {
    "gigabyte": "https://www.gigabyte.com/Support", "asus": "https://www.asus.com/support/",
    "msi": "https://www.msi.com/support/download", "micro-star": "https://www.msi.com/support/download",
    "asrock": "https://www.asrock.com/support/index.asp", "dell": "https://www.dell.com/support",
    "hp": "https://support.hp.com/drivers", "hewlett": "https://support.hp.com/drivers",
    "lenovo": "https://support.lenovo.com", "acer": "https://www.acer.com/support",
}


def vendor_support_url(manufacturer: str, product: str) -> str:
    m = (manufacturer or "").lower()
    for key, url in BOARD_PAGES.items():
        if key in m:
            return url
    return "https://www.google.com/search?q=" + quote_plus(f"{manufacturer} {product} BIOS update")


def board_search_url(manufacturer: str, product: str) -> str:
    return "https://www.google.com/search?q=" + quote_plus(f"{manufacturer} {product} BIOS download")


def open_url(url: str) -> None:
    if url.startswith("https://"):
        webbrowser.open(url)


def parse_dmtf(v) -> Optional[datetime]:
    """'20260923000000.000000+000' lub ISO -> datetime."""
    if not v or not isinstance(v, str):
        return None
    m = re.match(r"^(\d{4})(\d{2})(\d{2})", v)
    if m:
        try:
            return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None
    try:
        return datetime.fromisoformat(v.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None


def age_years(d: Optional[datetime], now: Optional[datetime] = None) -> Optional[float]:
    if not d:
        return None
    return ((now or datetime.now()) - d).days / 365.25


def board_info() -> tuple[bool, dict]:
    script = ("$b=Get-CimInstance Win32_BIOS;$m=Get-CimInstance Win32_BaseBoard;$s=Get-CimInstance Win32_ComputerSystem;"
              "[pscustomobject]@{bios_vendor=[string]$b.Manufacturer;bios_ver=[string]$b.SMBIOSBIOSVersion;"
              "bios_date=$b.ReleaseDate.ToString('yyyyMMdd');board_vendor=[string]$m.Manufacturer;board=[string]$m.Product;"
              "system=[string]$s.Model;sys_vendor=[string]$s.Manufacturer} | ConvertTo-Json")
    ok, data = ps.run_json(script, 40)
    return (True, data[0]) if ok and data else (False, {"error": str(data)})


def list_drivers() -> tuple[bool, list[dict]]:
    """Sterowniki urządzeń (bez wbudowanych Microsoftu) z datą i wersją."""
    script = ("$d=Get-CimInstance Win32_PnPSignedDriver | Where-Object { $_.DeviceName -and $_.Manufacturer -and "
              "$_.Manufacturer -notmatch '^Microsoft' -and $_.DeviceClass -in 'DISPLAY','NET','MEDIA','BLUETOOTH','HIDCLASS','USB','SYSTEM','AUDIOENDPOINT' } | "
              "ForEach-Object { [pscustomobject]@{name=$_.DeviceName;vendor=$_.Manufacturer;ver=$_.DriverVersion;"
              "date=$(if($_.DriverDate){$_.DriverDate.ToString('yyyyMMdd')}else{''});cls=$_.DeviceClass;signed=[bool]$_.IsSigned} };"
              "@($d) | ConvertTo-Json")
    ok, data = ps.run_json(script, 90)
    return ok, ([d for d in data if d] if ok else [])


def problem_devices() -> tuple[bool, list[dict]]:
    script = ("$p=Get-CimInstance Win32_PnPEntity | Where-Object { $_.ConfigManagerErrorCode -ne 0 } | "
              "ForEach-Object { [pscustomobject]@{name=[string]$_.Name;id=[string]$_.DeviceID;code=[int]$_.ConfigManagerErrorCode} };"
              "@($p) | ConvertTo-Json")
    ok, data = ps.run_json(script, 60)
    return ok, ([d for d in data if d] if ok else [])


def search_driver_updates() -> tuple[bool, list[dict]]:
    """Windows Update: dostępne sterowniki. Może trwać kilka minut."""
    script = ("$s=New-Object -ComObject Microsoft.Update.Session;$q=$s.CreateUpdateSearcher();"
              "$r=$q.Search(\"IsInstalled=0 and Type='Driver'\");"
              "$o=foreach($u in $r.Updates){ [pscustomobject]@{id=$u.Identity.UpdateID;title=[string]$u.Title;"
              "size=[int64]$u.MaxDownloadSize;model=[string]$u.DriverModel;ver=[string]$u.DriverVerDate} };"
              "@($o) | ConvertTo-Json")
    ok, data = ps.run_json(script, 600)
    return ok, ([d for d in data if d] if ok else [])


def install_driver_updates(ids: list[str]) -> tuple[bool, str]:
    """Pobiera i instaluje wskazane sterowniki z Windows Update. Wymaga administratora."""
    ids = [i for i in ids if _GUID.match(i or "")]
    if not ids:
        return False, "Nie wybrano żadnych sterowników."
    from . import winsys
    if not winsys.is_admin():
        return False, "Instalacja sterowników wymaga uprawnień administratora."
    idlist = ",".join(f"'{i}'" for i in ids)             # GUID-y zwalidowane regexem - brak wstrzyknięcia
    script = ("$s=New-Object -ComObject Microsoft.Update.Session;$q=$s.CreateUpdateSearcher();"
              "$r=$q.Search(\"IsInstalled=0 and Type='Driver'\");$c=New-Object -ComObject Microsoft.Update.UpdateColl;"
              f"$want=@({idlist});foreach($u in $r.Updates){{ if($want -contains $u.Identity.UpdateID){{ [void]$c.Add($u) }} }};"
              "if($c.Count -eq 0){ 'NONE'; exit 0 };"
              "$d=$s.CreateUpdateDownloader();$d.Updates=$c;[void]$d.Download();"
              "$i=$s.CreateUpdateInstaller();$i.Updates=$c;$res=$i.Install();"
              "\"RESULT:$($res.ResultCode):$($res.RebootRequired)\"")
    rc, out = ps.run(script, 3600)
    if rc != 0:
        return False, out[:240] or "Instalacja nie powiodła się."
    if "NONE" in out:
        return False, "Wybrane sterowniki nie są już dostępne."
    m = re.search(r"RESULT:(\d+):(\w+)", out)
    if m and m.group(1) in ("2", "3"):          # 2 = Succeeded, 3 = SucceededWithErrors
        return True, "Zainstalowano sterowniki." + (" Zrestartuj komputer." if m.group(2).lower() == "true" else "")
    return False, "Windows Update nie zainstalował sterowników (kod %s)." % (m.group(1) if m else "?")


def have_winget() -> bool:
    return shutil.which("winget") is not None


def winget_upgrade_all() -> tuple[bool, str]:
    """Aktualizuje zainstalowane programy przez winget (tryb cichy)."""
    exe = shutil.which("winget")
    if not exe:
        return False, "Nie znaleziono winget (Instalator aplikacji) - zainstaluj go ze sklepu Microsoft Store."
    try:
        r = subprocess.run([exe, "upgrade", "--all", "--silent", "--accept-package-agreements",
                            "--accept-source-agreements", "--disable-interactivity"],
                           capture_output=True, text=True, errors="ignore", timeout=3600, creationflags=0x08000000)
    except Exception as e:  # noqa: BLE001
        return False, str(e)
    if r.returncode == 0:
        return True, "Zaktualizowano programy."
    if "No applicable upgrade" in (r.stdout or "") or r.returncode == -1978335212:
        return True, "Wszystkie programy są aktualne."
    return False, "winget zakończył się kodem %d - część programów mogła nie zostać zaktualizowana." % r.returncode


def gpu_vendor(name: str) -> str:
    n = (name or "").lower()
    if "nvidia" in n or "geforce" in n:
        return "nvidia"
    if "radeon" in n or "amd" in n:
        return "amd"
    if "intel" in n:
        return "intel"
    return ""

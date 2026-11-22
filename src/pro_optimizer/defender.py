"""Antywirus: obsługa Microsoft Defendera (wbudowany w Windows) - stan, aktualizacja definicji, skanowanie, zagrożenia.

Nie piszemy własnego silnika AV (to nierealne i niebezpieczne) - Defender to pełnoprawny antywirus Microsoftu;
aplikacja daje do niego wygodny interfejs i dodatkowo sprawdza autostart pod kątem niepodpisanych programów."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from . import ps

log = logging.getLogger(__name__)

_ISO = "ToUniversalTime().ToString('o')"


@dataclass
class DefenderStatus:
    available: bool = False
    antivirus: bool = False
    realtime: bool = False
    tamper: bool = False
    sig_version: str = ""
    sig_updated: Optional[datetime] = None
    quick_scan: Optional[datetime] = None
    full_scan: Optional[datetime] = None
    message: str = ""

    @property
    def sig_age_days(self) -> Optional[float]:
        if not self.sig_updated:
            return None
        return (datetime.now(timezone.utc) - self.sig_updated).total_seconds() / 86400


def parse_dt(v) -> Optional[datetime]:
    if not v or not isinstance(v, str):
        return None
    try:
        d = datetime.fromisoformat(v.replace("Z", "+00:00"))
        if d.year < 2000:
            return None
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def status() -> DefenderStatus:
    script = (
        "$s=Get-MpComputerStatus;"
        "function D($x){ if($x){ $x." + _ISO + " } else { $null } };"
        "[pscustomobject]@{av=[bool]$s.AntivirusEnabled; rt=[bool]$s.RealTimeProtectionEnabled; tamper=[bool]$s.IsTamperProtected;"
        "ver=[string]$s.AntivirusSignatureVersion; upd=(D $s.AntivirusSignatureLastUpdated);"
        "quick=(D $s.QuickScanEndTime); full=(D $s.FullScanEndTime)} | ConvertTo-Json")
    ok, data = ps.run_json(script, 30)
    if not ok:
        return DefenderStatus(message="Nie można odczytać stanu Defendera (może być zastąpiony innym antywirusem). " + str(data)[:160])
    d = data[0]
    return DefenderStatus(True, d.get("av", False), d.get("rt", False), d.get("tamper", False), d.get("ver", ""),
                          parse_dt(d.get("upd")), parse_dt(d.get("quick")), parse_dt(d.get("full")))


HARDEN_ITEMS = {
    "pua": ("Blokowanie niechcianych programów (adware, „optymalizatory”)", "Set-MpPreference -PUAProtection Enabled"),
    "cloud": ("Ochrona w chmurze (szybsze wykrywanie nowych wirusów)", "Set-MpPreference -MAPSReporting Advanced;Set-MpPreference -CloudBlockLevel High"),
    "network": ("Ochrona sieci (blokada groźnych stron i serwerów)", "Set-MpPreference -EnableNetworkProtection Enabled"),
    "firewall": ("Zapora Windows włączona dla wszystkich sieci", "Set-NetFirewallProfile -Profile Domain,Private,Public -Enabled True"),
    "ransomware": ("Ochrona folderów przed ransomware (Dokumenty, Zdjęcia…)", "Set-MpPreference -EnableControlledFolderAccess Enabled"),
}
_HARDEN_STATUS = ("$p=Get-MpPreference;$f=@(Get-NetFirewallProfile);"
                  "[pscustomobject]@{pua=([int]$p.PUAProtection -eq 1);cloud=([int]$p.MAPSReporting -eq 2);"
                  "network=([int]$p.EnableNetworkProtection -eq 1);firewall=(@($f|Where-Object{-not $_.Enabled}).Count -eq 0);"
                  "ransomware=([int]$p.EnableControlledFolderAccess -eq 1)} | ConvertTo-Json")


def harden_status() -> tuple[bool, dict]:
    ok, data = ps.run_json(_HARDEN_STATUS, 30)
    return ok, (data[0] if ok and data else {})


def harden(keys: list[str]) -> tuple[bool, str]:
    """Włącza wybrane zabezpieczenia (stałe polecenia z listy, wymaga admina). Wszystko cofa się w Zabezpieczeniach Windows."""
    keys = [k for k in keys if k in HARDEN_ITEMS]
    if not keys:
        return False, "Nic nie wybrano."
    rc, out = ps.run(";".join(HARDEN_ITEMS[k][1] for k in keys), 60)
    return rc == 0, "Włączono wybrane zabezpieczenia." if rc == 0 else (out[:240] or "Wymaga uprawnień administratora.")


def update_signatures() -> tuple[bool, str]:
    rc, out = ps.run("Update-MpSignature", 300)
    return rc == 0, "Definicje wirusów zaktualizowane." if rc == 0 else (out[:240] or "Aktualizacja nie powiodła się.")


def scan(kind: str = "quick", path: Optional[str] = None) -> tuple[bool, str]:
    """kind: quick | full | custom (path). Blokuje do końca skanu - wołaj z wątku w tle."""
    if kind == "custom":
        if not path or len(path) > 400 or any(ord(ch) < 32 for ch in path) or not os.path.isabs(path) or not os.path.isdir(path):
            return False, "Nieprawidłowa ścieżka."
        # ścieżka idzie przez zmienną środowiskową, a nie przez sklejanie tekstu skryptu - nie da się wstrzyknąć poleceń
        rc, out = ps.run("Start-MpScan -ScanType CustomScan -ScanPath $env:POU_SCANPATH", 4 * 3600, env={"POU_SCANPATH": path})
        return rc == 0, "Skanowanie zakończone." if rc == 0 else (out[:240] or "Skanowanie przerwane.")
    else:
        cmd = "Start-MpScan -ScanType " + ("FullScan" if kind == "full" else "QuickScan")
    rc, out = ps.run(cmd, 4 * 3600)
    return rc == 0, "Skanowanie zakończone." if rc == 0 else (out[:240] or "Skanowanie przerwane.")


def threats() -> tuple[bool, list[dict]]:
    script = ("$t=@(Get-MpThreat | ForEach-Object { [pscustomobject]@{id=$_.ThreatID; name=$_.ThreatName; "
              "severity=[int]$_.SeverityID; active=[bool]$_.IsActive} }); if($t.Count -eq 0){'[]'}else{$t | ConvertTo-Json -AsArray}")
    ok, data = ps.run_json(script.replace(" -AsArray", ""), 30)   # PS 5.1 nie zna -AsArray; ps.run_json i tak zawija w listę
    return ok, (data if ok else [])


def remove_threats() -> tuple[bool, str]:
    rc, out = ps.run("Remove-MpThreat", 300)
    return rc == 0, "Usunięto wykryte zagrożenia." if rc == 0 else (out[:240] or "Nie udało się usunąć (wymaga administratora).")


def startup_audit() -> tuple[bool, list[dict]]:
    """Programy startujące z Windowsem + status podpisu cyfrowego. Niepodpisane = warto sprawdzić (nie znaczy: wirus)."""
    script = r"""
$items=@()
foreach($k in 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run','HKLM:\Software\Microsoft\Windows\CurrentVersion\Run'){
  if(Test-Path $k){ $p=Get-ItemProperty $k; foreach($n in $p.PSObject.Properties){ if($n.Name -notmatch '^PS'){ $items+=[pscustomobject]@{name=$n.Name;cmd=[string]$n.Value;where=$k.Substring(0,4)} } } } }
foreach($d in "$env:APPDATA\Microsoft\Windows\Start Menu\Programs\Startup"){ if(Test-Path $d){ Get-ChildItem $d -File | ForEach-Object { $items+=[pscustomobject]@{name=$_.BaseName;cmd=$_.FullName;where='Folder'} } } }
$out=foreach($i in $items){
  $exe=$null; if($i.cmd -match '^\s*"([^"]+)"'){ $exe=$Matches[1] } elseif($i.cmd -match '^\s*(\S+\.(exe|lnk|bat|cmd))'){ $exe=$Matches[1] }
  $sig='nieznany'; if($exe -and (Test-Path $exe) -and $exe -match '\.exe$'){ $sig=[string](Get-AuthenticodeSignature $exe).Status }
  [pscustomobject]@{name=$i.name;cmd=$i.cmd;where=$i.where;sig=$sig}
}
@($out) | ConvertTo-Json
"""
    ok, data = ps.run_json(script, 90)
    return ok, ([d for d in data if d] if ok else [])

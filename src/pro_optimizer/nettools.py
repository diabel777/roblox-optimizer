"""Narzędzia sieciowe: pomiar pingu, szybki DNS, strojenie TCP. Tylko stałe, sprawdzone wartości - nic z wejścia użytkownika
nie trafia do poleceń (dostawca DNS wybierany z listy)."""
from __future__ import annotations

import re
import statistics
from typing import Optional

from . import ps, winsys

PING_TARGETS = {"Cloudflare": "1.1.1.1", "Google": "8.8.8.8", "Quad9": "9.9.9.9"}
DNS_PROVIDERS = {
    "cloudflare": ("Cloudflare (najszybszy w większości domów)", ("1.1.1.1", "1.0.0.1")),
    "google": ("Google", ("8.8.8.8", "8.8.4.4")),
    "quad9": ("Quad9 (z blokadą złośliwych stron)", ("9.9.9.9", "149.112.112.112")),
}


def parse_ping(text: str) -> Optional[float]:
    """Średni czas z odpowiedzi polskiego i angielskiego ping.exe (np. 'Średni = 12ms' / 'Average = 12ms')."""
    m = re.search(r"(?:Średni|Srednia|Average)\s*=\s*(\d+)\s*ms", text, re.I)
    if m:
        return float(m.group(1))
    times = [int(x) for x in re.findall(r"(?:czas|time)[=<]\s*(\d+)\s*ms", text, re.I)]
    return float(statistics.mean(times)) if times else None


def ping(host: str, count: int = 4) -> Optional[float]:
    if host not in PING_TARGETS.values():
        return None
    rc, out = winsys._run(["ping", "-n", str(count), host], timeout=20)
    return parse_ping(out)


def ping_all() -> dict[str, Optional[float]]:
    return {name: ping(host) for name, host in PING_TARGETS.items()}


def verdict(ms: Optional[float]) -> tuple[str, str]:
    if ms is None:
        return "Brak odpowiedzi", "err"
    if ms < 25:
        return "Świetnie", "ok"
    if ms < 60:
        return "Dobrze", "ok"
    if ms < 120:
        return "Średnio", "warn"
    return "Słabo", "err"


_DNS_SCRIPT = ("$a=Get-NetAdapter | Where-Object {$_.Status -eq 'Up' -and $_.HardwareInterface};"
               "foreach($i in $a){Set-DnsClientServerAddress -InterfaceIndex $i.ifIndex -ServerAddresses ($env:POU_DNS -split ',')};"
               "Clear-DnsClientCache")
_DNS_RESET = ("$a=Get-NetAdapter | Where-Object {$_.Status -eq 'Up' -and $_.HardwareInterface};"
              "foreach($i in $a){Set-DnsClientServerAddress -InterfaceIndex $i.ifIndex -ResetServerAddresses};Clear-DnsClientCache")


def set_dns(provider: str) -> tuple[bool, str]:
    if provider not in DNS_PROVIDERS:
        return False, "Nieznany dostawca DNS."
    if not winsys.is_admin():
        return False, "Zmiana DNS wymaga uprawnień administratora."
    rc, out = ps.run(_DNS_SCRIPT, 40, env={"POU_DNS": ",".join(DNS_PROVIDERS[provider][1])})
    return rc == 0, ("Ustawiono DNS: " + DNS_PROVIDERS[provider][0]) if rc == 0 else f"Nie udało się: {out[:200]}"


def reset_dns() -> tuple[bool, str]:
    if not winsys.is_admin():
        return False, "Zmiana DNS wymaga uprawnień administratora."
    rc, out = ps.run(_DNS_RESET, 40)
    return rc == 0, "Przywrócono automatyczny DNS (od dostawcy internetu)." if rc == 0 else f"Nie udało się: {out[:200]}"


TCP_COMMANDS = (["netsh", "int", "tcp", "set", "global", "autotuninglevel=normal"],
                ["netsh", "int", "tcp", "set", "global", "rss=enabled"],
                ["netsh", "int", "tcp", "set", "global", "ecncapability=disabled"],
                ["netsh", "int", "tcp", "set", "global", "timestamps=disabled"])


def tune_tcp() -> tuple[bool, str]:
    """Bezpieczne, odwracalne ustawienia TCP (wartości zalecane dla gier; można je cofnąć `netsh int tcp reset`)."""
    if not winsys.is_admin():
        return False, "Strojenie sieci wymaga uprawnień administratora."
    ok = all(winsys._run(c)[0] == 0 for c in TCP_COMMANDS)
    return ok, "Zoptymalizowano ustawienia TCP." if ok else "Część ustawień nie zadziałała - sprawdź logi."


def best_hint(results: dict[str, Optional[float]]) -> str:
    good = {k: v for k, v in results.items() if v is not None}
    if not good:
        return "Brak odpowiedzi - sprawdź połączenie z internetem."
    name, ms = min(good.items(), key=lambda kv: kv[1])
    return f"Najkrócej: {name} ({ms:.0f} ms)."

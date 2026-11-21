"""Analiza komputera i gier: zbiera fakty, a czysta funkcja `analyze` zamienia je w listę problemów z gotową naprawą.

To heurystyki, nie wyrocznia: każdy wpis tłumaczy, DLACZEGO coś zgłaszamy, i ma przycisk naprawy albo link do właściwej strony."""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Optional

log = logging.getLogger(__name__)
GB = 1024 ** 3

SEV_ORDER = {"crit": 0, "warn": 1, "info": 2, "ok": 3}
SEV_PENALTY = {"crit": 18, "warn": 8, "info": 2, "ok": 0}


@dataclass
class Finding:
    id: str
    severity: str          # crit | warn | info | ok
    title: str
    detail: str
    fix: Optional[dict] = None       # {"type": "tweak"|"ram"|"dns"|"refresh"|"defender_update"|"page", ...}
    fix_label: str = ""


def analyze(f: dict) -> list[Finding]:
    """f - słownik faktów (patrz collect_facts). Brakujący klucz = nie badamy tego punktu."""
    out: list[Finding] = []
    add = lambda *a, **k: out.append(Finding(*a, **k))

    disk = f.get("disk")                                   # (total, free)
    if disk:
        total, free = disk
        pct = free / total * 100 if total else 100
        if free < 15 * GB or pct < 5:
            add("disk_low", "crit", "Prawie pełny dysk systemowy",
                f"Wolne {free / GB:.1f} GB ({pct:.0f}%). Windows i gry potrzebują miejsca na plik stronicowania, "
                "aktualizacje i cache shaderów - przy tak małej ilości rośnie ryzyko przycięć i błędów aktualizacji.",
                {"type": "page", "id": "cleaner"}, "Wyczyść cache")
        elif pct < 12:
            add("disk_low", "warn", "Mało wolnego miejsca na dysku", f"Wolne {free / GB:.1f} GB ({pct:.0f}%).",
                {"type": "page", "id": "cleaner"}, "Wyczyść cache")
    hib = f.get("hiberfil_bytes")
    if hib and hib > 4 * GB and disk and disk[1] < 40 * GB:
        add("hiberfil", "info", "Plik hibernacji zajmuje dużo miejsca",
            f"hiberfil.sys ma {hib / GB:.1f} GB. Jeśli nie używasz hibernacji ani szybkiego uruchamiania, "
            "możesz go wyłączyć poleceniem 'powercfg /h off' w wierszu poleceń administratora.")
    cache = f.get("cache_bytes")
    if cache and cache > 2 * GB:
        add("cache_big", "info", "Dużo cache do odzyskania", f"W cache aplikacji jest ok. {cache / GB:.1f} GB do zwolnienia.",
            {"type": "page", "id": "cleaner"}, "Otwórz czyszczenie")

    ram = f.get("ram_used_pct")
    if ram is not None:
        if ram >= 90:
            add("ram_high", "warn", "Pamięć RAM prawie pełna",
                f"Zajęte {ram:.0f}%. Windows zaczyna używać wolniejszego pliku stronicowania, co powoduje przycięcia.",
                {"type": "ram"}, "Zwolnij RAM")
        hogs = f.get("top_ram") or []
        if ram >= 75 and hogs:
            n, mb = hogs[0]
            add("ram_hog", "info", "Największy zjadacz pamięci", f"{n} zajmuje ok. {mb / 1024:.1f} GB.")
    up = f.get("uptime_days")
    if up is not None and up >= 7:
        add("uptime", "info", "Komputer działa od dawna bez restartu",
            f"Ostatni restart {up:.0f} dni temu. Restart czyści wycieki pamięci i dokańcza aktualizacje.")
    if f.get("pending_reboot"):
        add("reboot", "warn", "Windows czeka na restart", "Są zainstalowane zmiany, które wejdą w życie dopiero po restarcie.")

    d = f.get("display")
    if d and d.get("max_hz") and d["hz"] < d["max_hz"] - 5:
        add("refresh", "warn", "Monitor działa wolniej, niż potrafi",
            f"Ustawione {d['hz']} Hz, a w tej rozdzielczości monitor obsługuje {d['max_hz']} Hz. "
            "To najczęstsza przyczyna wrażenia 'mała płynność' mimo wysokiego FPS.",
            {"type": "refresh", "hz": d["max_hz"]}, f"Ustaw {d['max_hz']} Hz")

    ts = f.get("tweaks") or {}
    names = {"power": "Plan zasilania: Najwyższa wydajność", "gamemode": "Tryb gry Windows",
             "gamedvr": "Nagrywanie w tle (Game Bar) wyłączone"}
    why = {"power": "Plan oszczędzania energii ogranicza taktowanie procesora w grach.",
           "gamemode": "Tryb gry pomaga Windowsowi dać grze priorytet.",
           "gamedvr": "Nagrywanie klipów w tle zabiera zasoby i potrafi powodować przycięcia."}
    for tid in ("power", "gamemode", "gamedvr"):
        if ts.get(tid) is False:
            add("tweak_" + tid, "warn" if tid != "gamemode" else "info", f"Wyłączone: {names[tid]}", why[tid],
                {"type": "tweak", "id": tid}, "Włącz")

    g = f.get("gpu")
    if g:
        t = g.get("temp")
        if t is not None and t >= 85:
            add("gpu_hot", "crit", "Karta graficzna jest bardzo gorąca",
                f"{t:.0f}°C. Powyżej ok. 85°C karta obniża taktowanie (spada FPS). Sprawdź przepływ powietrza i krzywą wentylatorów.",
                {"type": "page", "id": "fan"}, "Wentylator GPU")
        elif t is not None and t >= 78 and (g.get("fan") or 0) < 40:
            add("gpu_fan_low", "warn", "Wysoka temperatura przy niskich obrotach wentylatora",
                f"{t:.0f}°C przy {g.get('fan')}% wentylatora. Inteligentna krzywa podniesie obroty w porę.",
                {"type": "page", "id": "fan"}, "Ustaw krzywą")
    ct = f.get("cpu_temp")
    if ct is not None and ct >= 90:
        add("cpu_hot", "crit", "Procesor jest bardzo gorący", f"{ct:.0f}°C. Sprawdź chłodzenie i pastę termoprzewodzącą.")

    av = f.get("defender")
    if av is not None:
        if not av.get("available"):
            add("av_unknown", "info", "Nie odczytano stanu antywirusa", "Może działać inny antywirus zamiast Defendera.")
        elif not av.get("realtime"):
            add("av_off", "crit", "Ochrona w czasie rzeczywistym jest wyłączona",
                "Komputer nie jest chroniony przed nowym złośliwym oprogramowaniem.", {"type": "page", "id": "antivirus"}, "Antywirus")
        elif (av.get("sig_age_days") or 0) > 3:
            add("av_old", "warn", "Stare definicje antywirusa", f"Ostatnia aktualizacja {av['sig_age_days']:.0f} dni temu.",
                {"type": "defender_update"}, "Aktualizuj")
        if av.get("available") and av.get("quick_age_days") is None:
            add("av_noscan", "info", "Nie wykonano jeszcze skanowania", "Uruchom szybkie skanowanie, aby sprawdzić komputer.",
                {"type": "page", "id": "antivirus"}, "Skanuj")
    st = f.get("startup_unsigned")
    if st:
        add("startup", "info", f"Niepodpisane programy w autostarcie: {len(st)}",
            "Niepodpisany nie znaczy groźny, ale warto sprawdzić: " + ", ".join(st[:4]) + ("…" if len(st) > 4 else ""),
            {"type": "page", "id": "antivirus"}, "Zobacz")
    if f.get("startup_count") and f["startup_count"] > 12:
        add("startup_many", "info", "Dużo programów w autostarcie", f"{f['startup_count']} pozycji spowalnia start komputera.")

    gdrv = f.get("drivers_problem")
    if gdrv:
        add("drv_problem", "warn", f"Urządzenia z problemem sterownika: {gdrv}", "Brakujący lub uszkodzony sterownik.",
            {"type": "page", "id": "drivers"}, "Sterowniki")

    for gm in f.get("games_unoptimized") or []:
        add("game_" + gm["id"], "info", f"Gra bez optymalizacji: {gm['name']}",
            "Wykryta na komputerze, ale bez żadnych ustawień wydajności.", {"type": "game", "id": gm["id"]}, "Optymalizuj")
    if f.get("roblox_installed") and not f.get("roblox_profile_applied"):
        add("roblox_profile", "info", "Roblox bez profilu graficznego", "Profil FastFlag i limit FPS mogą poprawić płynność.",
            {"type": "game", "id": "roblox_player"}, "Ustaw profil")
    return sorted(out, key=lambda x: SEV_ORDER[x.severity])


def score(findings: list[Finding]) -> int:
    return max(0, 100 - sum(SEV_PENALTY[x.severity] for x in findings))


def collect_facts(app) -> dict:
    """Zbiera fakty z komputera (wołać z wątku w tle). Każdy punkt jest niezależny - błąd jednego nie psuje reszty."""
    from . import cleaner, defender, display, games as gm, hw, roblox, winsys
    f: dict = {}

    def safe(key, fn):
        try:
            v = fn()
            if v is not None:
                f[key] = v
        except Exception:  # noqa: BLE001
            log.debug("analyzer %s", key, exc_info=True)

    safe("disk", winsys.disk_free)
    mem = winsys.memory_status()
    if mem:
        f["ram_used_pct"] = (mem[0] - mem[1]) / mem[0] * 100
    safe("display", display.current)
    safe("tweaks", lambda: {t.id: winsys.tweak_state(t) for t in winsys.TWEAKS} if winsys.IS_WINDOWS else None)

    def uptime():
        import psutil, time
        return (time.time() - psutil.boot_time()) / 86400
    safe("uptime_days", uptime)

    def top_ram():
        import psutil
        agg: dict[str, int] = {}
        for p in psutil.process_iter(["name", "memory_info"]):
            try:
                agg[p.info["name"]] = agg.get(p.info["name"], 0) + p.info["memory_info"].rss
            except Exception:
                continue
        return sorted(((n, b / 1024 / 1024) for n, b in agg.items()), key=lambda x: -x[1])[:3]
    safe("top_ram", top_ram)

    def hib():
        p = os.path.join(os.environ.get("SystemDrive", "C:") + os.sep, "hiberfil.sys")
        return os.stat(p).st_size if os.path.exists(p) else None
    safe("hiberfil_bytes", hib)

    def reboot():
        if not winsys.IS_WINDOWS:
            return None
        import winreg
        for hive, key in ((winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Component Based Servicing\RebootPending"),
                          (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\WindowsUpdate\Auto Update\RebootRequired")):
            try:
                winreg.CloseKey(winreg.OpenKey(hive, key))
                return True
            except OSError:
                continue
        return False
    safe("pending_reboot", reboot)

    def gpu():
        s = hw.nvml().sample(0)
        return {"temp": s.temp, "fan": s.fan, "name": s.name} if s else None
    safe("gpu", gpu)
    safe("cpu_temp", hw.cpu_temp)

    def av():
        s = defender.status()
        quick = s.quick_scan
        import datetime as dt
        qa = (dt.datetime.now(dt.timezone.utc) - quick).days if quick else None
        return {"available": s.available, "realtime": s.realtime, "sig_age_days": s.sig_age_days, "quick_age_days": qa}
    safe("defender", av)

    def startup():
        ok, items = defender.startup_audit()
        if not ok:
            return None
        f["startup_count"] = len(items)
        return [i["name"] for i in items if i.get("sig") not in ("Valid", "nieznany")]
    safe("startup_unsigned", startup)

    def games_un():
        saved = app.settings.get("games") or {}
        found = []
        for g in app.games:
            if g.get("kind", "").startswith("roblox"):
                continue
            entry = saved.get(g["id"]) or {}
            exe = entry.get("exe")
            if exe and os.path.exists(exe) and not any((entry.get("opts") or {}).values()):
                found.append({"id": g["id"], "name": g["name"]})
        return found
    safe("games_unoptimized", games_un)

    installs = roblox.find_installs()
    f["roblox_installed"] = any(installs.values())
    f["roblox_profile_applied"] = bool(app.settings.get("roblox_applied"))
    return f

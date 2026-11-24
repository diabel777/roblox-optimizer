"""Profesjonalny test internetu: opóźnienie (ping), jitter, utrata pakietów, pobieranie, wysyłanie i opóźnienie pod obciążeniem
(bufferbloat) - czyli to, co naprawdę decyduje o grach online i streamingu. Serwery: wyłącznie speed.cloudflare.com (HTTPS)
- adres jest stały, nic z zewnątrz nie zmienia celu testu. Ruch jest ograniczony limitem bajtów i czasu."""
from __future__ import annotations

import statistics
import threading
import time
import urllib.request
from typing import Callable, Optional

HOST = "speed.cloudflare.com"
DOWN = f"https://{HOST}/__down?bytes="
UP = f"https://{HOST}/__up"
UA = "AderisBoost-SpeedTest/1"
MAX_BYTES = 600 * 1024 * 1024            # twardy limit całego testu


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):          # przekierowanie = podejrzane, test przerywamy
        return None


_opener = urllib.request.build_opener(_NoRedirect)


def mbps(nbytes: int, seconds: float) -> float:
    return (nbytes * 8 / 1_000_000) / seconds if seconds > 0 else 0.0


def jitter(samples: list[float]) -> float:
    """Średnia różnica kolejnych pomiarów (jak w RFC 3550)."""
    if len(samples) < 2:
        return 0.0
    return statistics.mean(abs(b - a) for a, b in zip(samples, samples[1:]))


def grade(res: dict) -> dict:
    """Zamienia liczby na ocenę dla zwykłego człowieka: gry, wideorozmowy, streaming 4K."""
    ping, jit = res.get("ping"), res.get("jitter", 0)
    down, up, loss, loaded = res.get("down", 0), res.get("up", 0), res.get("loss", 0), res.get("loaded_ping")

    def lvl(ok_good, ok_mid):
        return "Świetnie" if ok_good else ("Dobrze" if ok_mid else "Słabo")
    gaming = lvl(ping is not None and ping < 35 and jit < 8 and loss == 0, ping is not None and ping < 70 and jit < 20 and loss < 2)
    video = lvl(up >= 8 and jit < 15 and loss == 0, up >= 3 and loss < 3)
    stream = lvl(down >= 50, down >= 20)
    bloat = None
    if ping is not None and loaded is not None:
        extra = loaded - ping
        bloat = "Brak problemu" if extra < 30 else ("Lekki" if extra < 100 else "Duży - włącz QoS/SQM w routerze")
    return {"Gry online": gaming, "Rozmowy wideo": video, "Streaming 4K": stream, "Opóźnienie pod obciążeniem": bloat or "-"}


def _ping_once(timeout: float = 4.0) -> Optional[float]:
    t = time.perf_counter()
    try:
        req = urllib.request.Request(DOWN + "0", headers={"User-Agent": UA, "Cache-Control": "no-cache"})
        with _opener.open(req, timeout=timeout) as r:
            r.read(1)
        return (time.perf_counter() - t) * 1000
    except Exception:
        return None


def measure_ping(n: int = 12, progress: Optional[Callable[[float], None]] = None) -> dict:
    ok, lost = [], 0
    for i in range(n):
        v = _ping_once()
        if v is None:
            lost += 1
        else:
            ok.append(v)
        if progress:
            progress((i + 1) / n)
    if not ok:
        return {"ping": None, "jitter": 0.0, "loss": 100.0}
    return {"ping": statistics.median(ok), "jitter": jitter(ok), "loss": round(lost / n * 100, 1)}


class _Counter:
    def __init__(self):
        self.bytes = 0
        self.lock = threading.Lock()

    def add(self, n: int) -> None:
        with self.lock:
            self.bytes += n


def _run_parallel(worker, threads: int, seconds: float, on_tick: Callable[[float, float], None], stop: threading.Event) -> tuple[int, float]:
    ctr = _Counter()
    deadline = time.perf_counter() + seconds
    ts = [threading.Thread(target=worker, args=(ctr, deadline, stop), daemon=True) for _ in range(threads)]
    start = time.perf_counter()
    for t in ts:
        t.start()
    last_b, last_t = 0, start
    while time.perf_counter() < deadline and not stop.is_set():
        time.sleep(0.2)
        now = time.perf_counter()
        b = ctr.bytes
        on_tick(mbps(b - last_b, now - last_t), min(1.0, (now - start) / seconds))
        last_b, last_t = b, now
    stop_flag = time.perf_counter()
    for t in ts:
        t.join(timeout=3)
    # średnia po pierwszej sekundzie (rozbieg TCP) daje uczciwszy wynik
    elapsed = max(0.5, stop_flag - start)
    return ctr.bytes, elapsed


def measure_download(seconds: float, on_tick, stop: threading.Event, threads: int = 4) -> float:
    def worker(ctr, deadline, stop):
        while time.perf_counter() < deadline and not stop.is_set() and ctr.bytes < MAX_BYTES:
            try:
                req = urllib.request.Request(DOWN + str(25_000_000), headers={"User-Agent": UA})
                with _opener.open(req, timeout=8) as r:
                    while time.perf_counter() < deadline and not stop.is_set():
                        chunk = r.read(65536)
                        if not chunk:
                            break
                        ctr.add(len(chunk))
            except Exception:
                time.sleep(0.2)
    b, el = _run_parallel(worker, threads, seconds, on_tick, stop)
    return mbps(b, el)


def measure_upload(seconds: float, on_tick, stop: threading.Event, threads: int = 3) -> float:
    payload = bytes(2_000_000)

    def worker(ctr, deadline, stop):
        while time.perf_counter() < deadline and not stop.is_set() and ctr.bytes < MAX_BYTES:
            try:
                req = urllib.request.Request(UP, data=payload, method="POST",
                                             headers={"User-Agent": UA, "Content-Type": "application/octet-stream"})
                with _opener.open(req, timeout=10) as r:
                    r.read(1)
                ctr.add(len(payload))
            except Exception:
                time.sleep(0.2)
    b, el = _run_parallel(worker, threads, seconds, on_tick, stop)
    return mbps(b, el)


def run(on_phase: Callable[[str, float, Optional[float]], None], stop: Optional[threading.Event] = None) -> dict:
    """Pełny test. on_phase(nazwa, postęp 0-1, bieżąca prędkość Mb/s lub None)."""
    stop = stop or threading.Event()
    res: dict = {"time": int(time.time())}
    on_phase("ping", 0.0, None)
    res.update(measure_ping(12, lambda p: on_phase("ping", p, None)))
    if res["ping"] is None:
        res.update({"down": 0.0, "up": 0.0, "error": "Brak połączenia z serwerem testu."})
        return res
    if stop.is_set():
        return res
    on_phase("down", 0.0, 0.0)
    loaded: list[float] = []
    pinger_stop = threading.Event()

    def loaded_pinger():
        time.sleep(1.5)
        while not pinger_stop.is_set():
            v = _ping_once(3.0)
            if v is not None:
                loaded.append(v)
            time.sleep(0.4)
    threading.Thread(target=loaded_pinger, daemon=True).start()
    res["down"] = measure_download(8, lambda s, p: on_phase("down", p, s), stop)
    pinger_stop.set()
    res["loaded_ping"] = statistics.median(loaded) if loaded else None
    if stop.is_set():
        return res
    on_phase("up", 0.0, 0.0)
    res["up"] = measure_upload(6, lambda s, p: on_phase("up", p, s), stop)
    on_phase("done", 1.0, None)
    return res


# ----------------------------------------------------------------------------- kontekst, porady, raport
def connection_info() -> dict:
    """Co wiemy o łączu komputera: typ (kabel/Wi-Fi), szybkość karty, sygnał Wi-Fi, obciążenie. Tylko odczyt, bez wysyłania."""
    info: dict = {"type": "nieznane", "adapter": "", "link_mbps": None, "wifi_signal": None, "wifi_band": "",
                  "cpu": None, "ram": None, "os": ""}
    try:
        import platform
        import psutil
        info["os"] = f"{platform.system()} {platform.release()}"
        info["cpu"] = psutil.cpu_percent(interval=0.3)
        info["ram"] = psutil.virtual_memory().percent
    except Exception:
        pass
    try:
        from . import ps
        if ps.IS_WINDOWS:
            ok, data = ps.run_json("Get-NetAdapter | Where-Object {$_.Status -eq 'Up' -and -not $_.Virtual} | "
                                   "Select-Object Name,InterfaceDescription,LinkSpeed,PhysicalMediaType,NdisPhysicalMedium | ConvertTo-Json", 20)
            if ok and data:
                a = data[0]
                media = f"{a.get('PhysicalMediaType', '')} {a.get('Name', '')} {a.get('InterfaceDescription', '')}".lower()
                info["type"] = "Wi-Fi" if ("802.11" in media or "wi-fi" in media or "wireless" in media or "wlan" in media) else "kabel (Ethernet)"
                info["adapter"] = str(a.get("InterfaceDescription") or "")
                ls = str(a.get("LinkSpeed") or "")
                num = "".join(ch for ch in ls.split()[0] if ch.isdigit() or ch == ".") if ls else ""
                if num:
                    mult = 1000 if "Gb" in ls else (0.001 if "Kb" in ls else 1)
                    info["link_mbps"] = float(num) * mult
            if info["type"] == "Wi-Fi":
                rc, out = ps.run("netsh wlan show interfaces", 10)
                for line in out.splitlines():
                    k, _, v = line.partition(":")
                    k, v = k.strip().lower(), v.strip()
                    if k in ("signal", "sygnał") and v.endswith("%"):
                        info["wifi_signal"] = int(v[:-1] or 0)
                    if k in ("radio type", "typ radia"):
                        info["wifi_band"] = v
    except Exception:
        pass
    return info


def advice(res: dict, info: dict, context: Optional[dict] = None) -> list[dict]:
    """Lista porad: {'title','text','page'} - page to strona aplikacji, na którą można przeskoczyć (lub None)."""
    context = context or {}
    out: list[dict] = []
    ping, jit, loss = res.get("ping"), res.get("jitter", 0) or 0, res.get("loss", 0) or 0
    down, up, loaded = res.get("down", 0) or 0, res.get("up", 0) or 0, res.get("loaded_ping")
    wifi = (context.get("conn") or info.get("type") or "").lower().startswith("wi")
    link = info.get("link_mbps")

    def add(title, text, page=None):
        out.append({"title": title, "text": text, "page": page})

    if wifi:
        if (info.get("wifi_signal") or 100) < 60:
            add("Słaby sygnał Wi-Fi", f"Sygnał to tylko {info.get('wifi_signal')}%. Podejdź bliżej routera albo podłącz komputer kablem - "
                "to najpewniejszy sposób na niższy ping.")
        if ping and (ping > 40 or jit > 15):
            add("Wi-Fi zwiększa ping", "Wi-Fi zawsze dodaje opóźnienia i skoki. W grach najlepiej użyć kabla sieciowego. Jeśli się nie da: "
                "sieć 5 GHz zamiast 2,4 GHz i brak ścian między komputerem a routerem.")
    if link and down and link < 150 and down > link * 0.8:
        add("Karta sieciowa ogranicza prędkość", f"Karta pracuje na {link:.0f} Mb/s - to Twój sufit. Sprawdź kabel (powinien być kat. 5e lub lepszy) i port w routerze.")
    if ping and ping > 70:
        add("Wysoki ping", "Zrestartuj router (wyjmij zasilanie na 30 s). Jeśli się nie poprawi, zmień serwery DNS w „Szybszy Windows i internet”. "
            "Przy stałym pingu >70 ms zgłoś to dostawcy z raportem poniżej.", "system")
    if jit > 20:
        add("Niestabilne połączenie (jitter)", "Skoki opóźnienia psują grę i rozmowy. Zamknij programy, które pobierają w tle (aktualizacje, torrent, chmura).")
    if loss and loss > 1:
        add("Gubienie pakietów", "To zwykle wina kabla, gniazdka lub dostawcy. Wymień kabel i zrób test ponownie. Jeśli dalej gubi - zgłoś awarię z raportem.")
    if loaded is not None and ping is not None and loaded - ping > 100:
        add("Bufferbloat: łącze się „zapycha”", f"Pod obciążeniem ping rośnie z {ping:.0f} do {loaded:.0f} ms. W routerze włącz QoS / SQM (Smart Queue), "
            "a limit prędkości ustaw na ok. 90% wyniku testu.")
    if (info.get("cpu") or 0) > 85 or (info.get("ram") or 0) > 90:
        add("Komputer był mocno obciążony", "Podczas testu procesor lub pamięć były prawie pełne - wynik może być zaniżony. Zamknij programy i powtórz test.", "dashboard")
    if context.get("others") == "tak":
        add("Inni korzystali z internetu", "Gdy ktoś ogląda filmy lub pobiera, Twoje łącze jest dzielone. Powtórz test, gdy nikt inny nie korzysta.")
    if down and down < 20:
        add("Niska prędkość pobierania", "Sprawdź w umowie, jaką prędkość masz zapłaconą. Jeśli wynik jest wyraźnie niższy (poniżej ~70%), reklamuj usługę z raportem.")
    if not out:
        add("Wszystko w porządku", "Łącze wygląda zdrowo. Jeśli coś mimo to się tnie, problem jest raczej po stronie serwera gry niż Twojego internetu.")
    return out


def report_text(res: dict, info: dict, context: Optional[dict] = None, app_version: str = "") -> str:
    """Raport do wysłania dostawcy internetu: wszystkie parametry naraz, żeby nie trzeba było dopytywać o kabel i sprzęt."""
    context = context or {}
    f = lambda v, u="": "brak" if v is None else f"{v:.1f}{u}"
    g = grade(res)
    lines = [
        "RAPORT Z TESTU INTERNETU (Aderis Boost" + (f" {app_version}" if app_version else "") + ")",
        "Data: " + time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(res.get("time") or time.time())),
        "Serwer testu: speed.cloudflare.com (HTTPS)",
        "",
        "WYNIKI",
        f"  Pobieranie:                {f(res.get('down'), ' Mb/s')}",
        f"  Wysyłanie:                 {f(res.get('up'), ' Mb/s')}",
        f"  Ping (mediana):            {f(res.get('ping'), ' ms')}",
        f"  Jitter:                    {f(res.get('jitter'), ' ms')}",
        f"  Utrata pakietów:           {f(res.get('loss'), ' %')}",
        f"  Ping pod obciążeniem:      {f(res.get('loaded_ping'), ' ms')}",
        f"  Opóźnienie pod obciążeniem: {g.get('Opóźnienie pod obciążeniem', '-')}",
        "",
        "SPRZĘT I POŁĄCZENIE",
        f"  Typ połączenia (wykryty):  {info.get('type')}",
        f"  Typ połączenia (podany):   {context.get('conn') or 'nie podano'}",
        f"  Karta sieciowa:            {info.get('adapter') or 'brak danych'}",
        f"  Szybkość karty:            {f(info.get('link_mbps'), ' Mb/s') if info.get('link_mbps') else 'brak danych'}",
    ]
    if info.get("type") == "Wi-Fi":
        lines.append(f"  Sygnał Wi-Fi:              {info.get('wifi_signal') if info.get('wifi_signal') is not None else 'brak'} %  ({info.get('wifi_band') or '-'})")
    lines += [
        f"  System:                    {info.get('os') or '-'}",
        f"  Obciążenie CPU / RAM:      {f(info.get('cpu'), ' %')} / {f(info.get('ram'), ' %')}",
        f"  Inne urządzenia w sieci:   {context.get('others') or 'nie podano'}",
        f"  Router/modem przeżył restart: {context.get('restarted') or 'nie podano'}",
        "",
        "OCENA: " + "; ".join(f"{k}: {v}" for k, v in g.items()),
        "",
        "Raport nie zawiera nazwy komputera, kont ani adresu IP.",
    ]
    return "\n".join(lines)

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

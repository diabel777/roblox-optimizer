"""Akcje, które asystent AI może ZAPROPONOWAĆ. Biała lista: nic poza nią nie zostanie wykonane, a każda akcja
wymaga potwierdzenia użytkownika w oknie aplikacji. Model nie decyduje o tym, co robi przycisk - tylko wybiera z listy."""
from __future__ import annotations

from typing import Callable, Optional

from . import automation

PAGES = {"dashboard", "games", "diagnostics", "automation", "cleaner", "system", "speed", "fan", "controllers",
         "antivirus", "drivers", "backups", "downloads", "settings", "assistant"}
TASKS = {"ram", "dns", "clean", "tweaks", "defender", "scan", "app_opt", "game_boost"}

# id -> (etykieta, opis dla okna potwierdzenia)
CATALOG = {
    "open_page": ("Otwórz stronę", "Przejdę do wskazanej strony aplikacji. Nic nie zmieniam."),
    "run_speedtest": ("Zrób test internetu", "Uruchomię test prędkości (ok. 20 s, kilkadziesiąt MB danych)."),
    "optimize_now": ("Zwiększ FPS", "Zastosuję bezpieczne ustawienia Windows, zwolnię RAM, wyczyszczę DNS i dopinguję uruchomioną grę. Wszystko da się cofnąć w Kopiach zapasowych."),
    "clean_now": ("Wyczyść cache aplikacji", "Wyczyszczę pliki tymczasowe zaznaczonych aplikacji (uruchomione aplikacje pomijam)."),
    "free_ram": ("Zwolnij RAM", "Zmniejszę zajętość pamięci przez nieużywane programy. Niczego nie zamykam."),
    "flush_dns": ("Wyczyść DNS", "Wyczyszczę pamięć podręczną nazw stron (pomaga przy dziwnych problemach z połączeniem)."),
    "quick_scan": ("Szybkie skanowanie", "Uruchomię szybkie skanowanie antywirusem Windows."),
    "update_defender": ("Zaktualizuj definicje wirusów", "Pobiorę najnowsze definicje antywirusa Windows."),
    "set_roblox_preset": ("Ustawienia Robloxa", "Otworzę stronę Gry, gdzie sam wybierzesz i zatwierdzisz profil Robloxa."),
    "enable_automation": ("Włącz automatykę", "Włączę wskazaną automatyczną czynność (zawsze możesz ją wyłączyć na stronie „Działa samo”)."),
}

_TASK_FOR = {"clean_now": "clean", "free_ram": "ram", "flush_dns": "dns", "quick_scan": "scan", "update_defender": "defender"}


def validate(action: dict) -> Optional[dict]:
    """Czyści akcję od modelu: nieznane id/argumenty -> None. Zwraca {id,label,desc,args}."""
    if not isinstance(action, dict):
        return None
    aid = action.get("id")
    if aid not in CATALOG:
        return None
    args = action.get("args") if isinstance(action.get("args"), dict) else {}
    clean: dict = {}
    label, desc = CATALOG[aid]
    if aid == "open_page":
        page = str(args.get("page", ""))
        if page not in PAGES:
            return None
        clean["page"] = page
        label = f"Otwórz: {page}"
    elif aid == "enable_automation":
        task = str(args.get("task", ""))
        if task not in TASKS:
            return None
        clean["task"] = task
        label = f"Włącz: {automation.TASK_LABELS.get(task, task)}"
    elif aid == "set_roblox_preset":
        clean["preset"] = str(args.get("preset", ""))[:40]
    return {"id": aid, "label": label, "desc": desc, "args": clean}


def execute(action: dict, app, notify: Callable[[str, str], None]) -> None:
    """Wykonuje już zatwierdzoną akcję. Praca w tle idzie przez app.bg, wynik przez notify(tekst, rodzaj)."""
    a = validate(action)
    if not a:
        notify("Ta akcja nie jest dozwolona.", "err")
        return
    aid, args = a["id"], a["args"]
    if aid == "open_page":
        app.show_page(args["page"])
        return
    if aid == "set_roblox_preset":
        app.show_page("games")
        return
    if aid == "run_speedtest":
        app.show_page("speed")
        pg = app.page("speed")
        if pg and hasattr(pg, "start"):
            app.after(300, pg.start)
        return
    if aid == "enable_automation":
        cfg = automation.merged(app.settings.get("auto"))
        cfg[args["task"]]["enabled"] = True
        app.settings.set("auto", cfg)
        notify(f"Włączono: {automation.TASK_LABELS[args['task']]}.", "ok")
        return
    tasks = ["tweaks", "ram", "dns", "game_boost"] if aid == "optimize_now" else [_TASK_FOR[aid]]

    def work():
        from . import cleaner
        running = cleaner.running_processes()
        return [(t, *automation.run_task(t, app.settings, app.catalog, app.games, running)) for t in tasks]

    def done(res):
        good = [automation.TASK_LABELS[t] for t, ok, _m in res if ok]
        bad = [m for _t, ok, m in res if not ok]
        if good:
            notify("Gotowe: " + ", ".join(good) + ".", "ok")
        if bad:
            notify(bad[0][:160], "warn")

    app.bg.run(work, done, lambda e: notify(f"Nie udało się: {e}", "err"))

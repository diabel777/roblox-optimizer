"""Profile realistycznej kierownicy do Forza Horizon 4 / 5.

Forza nie ma pliku konfiguracyjnego, który można bezpiecznie podmienić z zewnątrz (a ingerencja w grę mogłaby
zadziałać jak cheat), dlatego aplikacja daje GOTOWĄ ŚCIĄGĘ wartości: co ustawić w sterowniku kierownicy i co w menu gry.
Nic nie jest modyfikowane w grze ani w sterowniku - to wyłącznie dane do wpisania, które można skopiować do notatnika."""
from __future__ import annotations

from typing import Any

GAMES = {"fh5": "Forza Horizon 5", "fh4": "Forza Horizon 4"}

STYLES = {
    "real": ("Realistyczny", "Ciężka, komunikatywna kierownica: czujesz utratę przyczepności, nie szarpie i nie klipuje."),
    "stable": ("Stabilny / komfortowy", "Lżejsze siły i większy margines - dobry na początek i na długie sesje."),
    "drift": ("Drift / szybki kontrapunkt", "Szybsza reakcja i mocniejszy self-aligning, żeby czuć moment łapania kontry."),
}

# sprzęt: nazwa, zakres obrotu fizycznego, uwaga o sterowniku, dodatkowa korekta siły (mnożnik)
BRANDS: dict[str, dict[str, Any]] = {
    "g29": {"name": "Logitech G29 / G920 / G923", "range": 900, "driver": "Logitech G HUB",
            "notes": ["W G HUB: Operating range 900°, Centering spring wyłączony, „Allow game to adjust settings” włączone.",
                      "Siła ogólna w G HUB (Overall strength) ustaw 100% - skalowanie robisz w grze, nie w dwóch miejscach.",
                      "Wyłącz „Enable Logitech Gaming Software profile” dla gry, jeśli masz stary profil z innej gry."],
            "ffb_mult": 1.0},
    "t300": {"name": "Thrustmaster T150 / T248 / T300 / TX", "range": 900, "driver": "Thrustmaster Control Panel",
             "notes": ["W panelu: Rotation 900°, „Overall strength of all forces” 100%, „Constant” i „Periodic” 100%, „Spring” i „Damper” 0%.",
                       "Wyłącz „Auto-center by the game” tylko jeśli kierownica sama szarpie na postoju.",
                       "T150/T248 mają ograniczony zakres sił - nie schodź poniżej 80% w panelu, tylko tłum w grze."],
             "ffb_mult": 1.0},
    "fanatec": {"name": "Fanatec CSL DD / DD Pro / Podium", "range": 900, "driver": "Fanatec Control Panel",
                "notes": ["Silnik direct drive jest bardzo mocny - zacznij od 60-70% w Fanatec Control Panel (FFS/SEN: 900°).",
                          "Wyłącz „Soft stop” zbyt twardy, ustaw „Natural Damper” nisko, żeby kierownica nie była gumowa.",
                          "Przy DD zmniejsz FFB w grze, jeśli czujesz klipowanie (nagłe „płaskie” siły w zakrętach)."],
                "ffb_mult": 0.75},
    "moza": {"name": "Moza R5 / R9 / R12", "range": 900, "driver": "Moza Pit House",
             "notes": ["W Pit House: Steering angle 900°, Game FFB strength 100%, „Maximum torque limit” 80-100%.",
                       "Wyłącz wszystkie dodatkowe filtry (Speed damping, Natural inertia) i dopiero wtedy dostrajaj w grze."],
             "ffb_mult": 0.85},
    "other": {"name": "Inna kierownica / pad z kierownicą", "range": 900, "driver": "sterownik producenta",
              "notes": ["W sterowniku ustaw zakres obrotu 900° i siłę ogólną na maksimum, a skalowanie rób w grze.",
                        "Jeśli kierownica ma tryb „Xbox / PC (DirectInput)”, wybierz tryb PC - Forza działa lepiej z natywnym wejściem."],
              "ffb_mult": 1.0},
}

# bazowe wartości w grze (skala 0-100); nazwy opcji mogą się różnić po aktualizacjach gry
_BASE = {
    "real":   {"ffb_scale": 75, "vibration": 45, "sat": 80, "mech_trail": 70, "deadzone_in": 0, "deadzone_out": 100,
               "linearity": 50, "sensitivity": 50, "road_feel": 55},
    "stable": {"ffb_scale": 60, "vibration": 30, "sat": 60, "mech_trail": 55, "deadzone_in": 3, "deadzone_out": 100,
               "linearity": 45, "sensitivity": 45, "road_feel": 40},
    "drift":  {"ffb_scale": 85, "vibration": 50, "sat": 100, "mech_trail": 80, "deadzone_in": 0, "deadzone_out": 100,
               "linearity": 55, "sensitivity": 60, "road_feel": 60},
}

LABELS = {
    "ffb_scale": ("Force Feedback Scale (siła FFB)", "Ogólna siła sił zwrotnych. Za dużo = klipowanie."),
    "vibration": ("Vibration Scale (wibracje)", "Faktura nawierzchni. Wysokie wartości zagłuszają informacje o przyczepności."),
    "sat": ("Self-aligning torque", "Siła, z jaką koła wracają do środka - klucz do wyczucia poślizgu."),
    "mech_trail": ("Mechanical trail", "Ciężar kierownicy zależny od prędkości; wyższy = bardziej „samochodowy” opór."),
    "deadzone_in": ("Steering Axis Deadzone - wewnętrzna", "Martwa strefa przy środku. Kierownica z luzem: 2-5, bez luzu: 0."),
    "deadzone_out": ("Steering Axis Deadzone - zewnętrzna", "Zostaw 100, żeby wykorzystać pełny zakres obrotu."),
    "linearity": ("Steering Linearity", "50 = 1:1 jak w prawdziwym aucie. Niżej: zwinniejsze środkowe pozycje."),
    "sensitivity": ("Steering Sensitivity", "Czułość reakcji kół. Przy pełnym zakresie 900° zwykle 45-55."),
    "road_feel": ("Road feel / Tyre feel (jeśli dostępne)", "Ile informacji o drodze trafia do kierownicy."),
}
# FH4 nie ma części opcji z FH5 - pokazujemy tylko te, które istnieją
FH4_MISSING = {"sat", "mech_trail", "road_feel"}


def profile(brand: str, game: str, style: str) -> dict:
    """Zwraca {'driver': [...], 'game': [(nazwa, wartość, opis)], 'notes': [...]} - czyste dane do wyświetlenia."""
    b = BRANDS.get(brand) or BRANDS["other"]
    g = game if game in GAMES else "fh5"
    s = style if style in STYLES else "real"
    base = dict(_BASE[s])
    mult = b["ffb_mult"]
    base["ffb_scale"] = max(20, min(100, round(base["ffb_scale"] * mult)))
    rows = []
    for key, val in base.items():
        if g == "fh4" and key in FH4_MISSING:
            continue
        name, desc = LABELS[key]
        rows.append((name, val, desc))
    driver = [("Zakres obrotu", f"{b['range']}°"), ("Program", b["driver"])]
    notes = list(b["notes"])
    notes.append("Zacznij od tych wartości, jedź 2-3 minuty po asfalcie i zmieniaj jedną rzecz naraz (najpierw siła FFB, potem wibracje).")
    if g == "fh4":
        notes.append("Forza Horizon 4 ma mniej opcji FFB niż FH5 - pominięto ustawienia, których w niej nie ma.")
    else:
        notes.append("W FH5 po zmianie ustawień zrestartuj wyścig, żeby zadziałały wszystkie suwaki.")
    return {"brand": b["name"], "game": GAMES[g], "style": STYLES[s][0], "driver": driver, "game_rows": rows, "notes": notes}


def to_text(p: dict) -> str:
    lines = [f"{p['game']} - {p['brand']} - styl: {p['style']}", "", "Sterownik kierownicy:"]
    lines += [f"  {k}: {v}" for k, v in p["driver"]]
    lines += ["", "Ustawienia w grze:"]
    lines += [f"  {n}: {v}" for n, v, _ in p["game_rows"]]
    lines += ["", "Wskazówki:"] + [f"  - {n}" for n in p["notes"]]
    return "\n".join(lines) + "\n"

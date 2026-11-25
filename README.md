# Aderis Boost v4

Optymalizator Roblox / Roblox Studio + czyszczenie Discorda, Opery, przeglądarek, launcherów i Windowsa.
Instaluje się i **aktualizuje sam, jak Discord**: jeden `Setup.exe`, potem nowe wersje wchodzą w tle.

## Jak to działa (po co ta przebudowa)

W v3.3 instalator ściągał surowy exe, a aktualizacja nadpisywała działający plik przez `.bat` po 3 sekundach
(zawodziło, gdy plik był jeszcze zablokowany), bez żadnej weryfikacji pobranego pliku. Teraz:

```
%LOCALAPPDATA%\ProUltimateOptimizer\
  ProUltimateOptimizer.exe     launcher (skróty wskazują na niego; uruchamia najnowszą dobrą wersję)
  app-4.0.0\ app-4.1.0\        kolejne wersje OBOK siebie - działająca nigdy nie jest nadpisywana
  Backups\ config\ logs\ settings.json     Twoje dane - aktualizacje ich nie ruszają
```

* **Instalator** (`ProUltimateOptimizer-Setup.exe`) – ładny kreator z paskiem postępu, bez UAC, skróty (Pulpit/Menu Start),
  wpis w *Ustawienia → Aplikacje* (z odinstalowaniem), naprawa przy ponownym uruchomieniu.
* **Aktualizacje w tle** – aplikacja sprawdza co N godzin (ustawienie), pobiera nową wersję do `app-X.Y.Z`,
  a ta uruchamia się przy następnym starcie (albo przyciskiem „Uruchom ponownie”).
* **Wycofanie** – jeśli nowa wersja wywali się zaraz po starcie, launcher oznacza ją `.bad` i odpala poprzednią.
* **Migracja z v3.3** – instalator sprząta stare pliki i zostawia Twoje kopie zapasowe (`Backups`).

## Bezpieczeństwo

| Zagrożenie | Zabezpieczenie |
|---|---|
| Podmieniona aktualizacja (włamanie na GitHuba, MITM) | manifest podpisany **Ed25519**; klucz publiczny jest w aplikacji, prywatny tylko u Ciebie |
| Uszkodzona / podmieniona paczka | SHA-256 z podpisanego manifestu; niezgodność = odrzucenie, nic się nie instaluje |
| Przekierowanie na obcy serwer | tylko HTTPS i lista hostów GitHuba – sprawdzana po każdym przekierowaniu |
| Złośliwe zip (zip-slip, symlinki, zip-bomba) | `safe_extract` z limitami |
| Cofnięcie do starej, dziurawej wersji | wersja z manifestu musi być **nowsza** niż obecna |
| Nadmierne uprawnienia | aplikacja i instalator działają **bez admina**; UAC tylko na żądanie dla wybranych funkcji |
| Przypadkowe skasowanie plików | czyszczenie ma ochronę ścieżek (nie rusza dysków, profilu, symlinków), pomija uruchomione aplikacje, pokazuje rozmiar przed usunięciem |
| Zmiany systemowe bez powrotu | tweaki Windows zapamiętują poprzednie wartości i da się je cofnąć; przed zmianą powstaje kopia |

Własny kod Ed25519 (`ed25519.py`) został porównany z biblioteką `cryptography` na losowych danych – zgodność 1:1.
**Czego to NIE załatwia:** SmartScreen/antywirus. Niepodpisany exe może dostać ostrzeżenie „nieznany wydawca”
(exe mają pełne metadane i bez UPX, co pomaga, ale pełne rozwiązanie to płatny certyfikat Code Signing).

## Pierwsze wydanie – krok po kroku

Wymagania: Windows, Python 3.11+ (z tkinter, domyślnie jest w instalatorze z python.org).

1. `.\build.ps1 -Notes "Pierwsze wydanie v4"` – robi testy, **tworzy klucze** (jednorazowo), buduje 3 exe, paczkę i podpis → folder `release\`.
   Skopiuj `keys\release_private.key` w bezpieczne miejsce (menedżer haseł). **Nigdy** nie wrzucaj go na GitHub (`keys/` jest w `.gitignore`).
   Zgubisz klucz = zainstalowane aplikacje nie przyjmą kolejnych aktualizacji.
2. Na GitHubie utwórz **Release** z tagiem `v4.0.0` i wgraj do niego: `ProUltimateOptimizer-4.0.0.zip` oraz `ProUltimateOptimizer-Setup.exe`.
3. **Dopiero potem** wrzuć `release\version.json` do głównego katalogu repo (branch `main`, zastępuje stary). To on „ogłasza” aktualizację.
   Kolejność ma znaczenie: dopóki `version.json` jest w starym formacie, instalator i aplikacja v4 (słusznie) go odrzucają.
4. Dziel się linkiem do `Setup.exe` z Release’a.

**Użytkownicy ze starym v3.3** zaktualizują się sami: stary mechanizm pobierze `Setup.exe` (pole `download_url` w manifeście)
i uruchomi go – instalator zrobi resztę. To jedyny moment bez weryfikacji podpisu (tak działa v3.3); od v4 podpis jest zawsze sprawdzany.
Mogą zostać nieszkodliwe śmieci po v3.3 (`RobloxStudioOptimizer.exe` w AppData), jeśli były zablokowane.

### Kolejne wersje (3 kroki)
1. Zmień `VERSION` w `src/pro_optimizer/version.py` (np. `4.0.1`).
2. `.\build.ps1 -Notes "co nowego" -Tag v4.0.1`
3. Release `v4.0.1` z `…-4.0.1.zip` (+ ewentualnie nowy Setup) → potem `version.json` do `main`.

**Albo automatycznie:** dodaj sekret repo `POU_SIGNING_KEY` (zawartość klucza prywatnego) i wypchnij tag `git tag v4.0.1 && git push --tags`
– workflow `.github/workflows/release.yml` zbuduje wszystko, utworzy Release i na końcu opublikuje `version.json`.

## Personalizacja (bez przebudowy)

Pliki JSON w `%LOCALAPPDATA%\ProUltimateOptimizer\config\` (przycisk **Ustawienia → Utwórz pliki do edycji**) nadpisują domyślne po restarcie:

| Plik | Co zmieniasz |
|---|---|
| `theme.json` | kolory, czcionki, zaokrąglenia, rozmiar okna |
| `apps.user.json` | własne aplikacje do czyszczenia (dodają się do 29 wbudowanych; `"disabled": true` ukrywa wbudowaną) |
| `presets.user.json` | własne profile Roblox (flagi FFlag) |

W kodzie: nowe strony w `src/pro_optimizer/ui/pages/` (dopisz w `app.py → page_defs`), logika w `cleaner.py`, `roblox.py`, `winsys.py`.

## Uwaga o flagach Roblox
Roblox wpuszcza tylko część flag (allowlista). Nieznane są ignorowane, a po aktualizacji Robloxa folder wersji się zmienia –
dlatego aplikacja sama **przywraca Twój profil po aktualizacji Robloxa** (można wyłączyć). Profil „eksperymentalny” jest tak opisany celowo.

## Struktura
```
src/pro_optimizer/   aplikacja + rdzeń (updater, security, install, shell, cleaner, roblox, winsys)
installer/           Setup (kreator)         launcher/   launcher + rollback + odinstalowanie
config/              domyślne katalogi/motyw  tools/      release.py (klucze, paczka, podpis), ikona, metadane
specs/               PyInstaller              tests/      testy (33) + smoke-testy GUI (xvfb)
```
Testy: `python -m pytest tests/test_core.py tests/test_install.py`

## Nowości w 4.1

- **Optymalizacja gier** - lista gier (Roblox Player, Studio, CS2, Fortnite, Valorant, GTA V, FiveM…), każda z własnymi ustawieniami:
  wysoka wydajność GPU, pełny ekran bez optymalizacji, stały priorytet CPU, doping po uruchomieniu. Własną grę dodasz przyciskiem „+ Dodaj .exe”.
  Dla Robloxa dodatkowo profile FastFlag i limit FPS. Katalog gier: `config/games.json` (+ `games.user.json` w folderze konfiguracji).
- **Analiza i naprawa** - skanuje komputer i gry (dysk, RAM, odświeżanie monitora, plan zasilania, temperatury, antywirus, sterowniki…)
  i naprawia problemy jednym kliknięciem.
- **Automatyzacja** - samo zwalnianie RAM (próg), czyszczenie DNS i cache, pilnowanie optymalizacji, aktualizacja definicji, doping gier.
- **Wentylator i GPU** - inteligentna krzywa obrotów dla kart NVIDIA (NVML, wymaga admina), tryb ręczny, odczyty na żywo.
- **Antywirus** - panel Microsoft Defendera: skanowanie, definicje, zagrożenia + audyt autostartu.
- **Sterowniki i BIOS** - sterowniki z Windows Update, linki producentów GPU, aktualizacja programów (winget), informacje o BIOS i strona producenta płyty.
- Aktualizacje są zawsze automatyczne (sprawdzanie co 30 minut) - bez przełączników.

Ograniczenia (celowe): BIOS nie jest wgrywany z Windowsa (ryzyko unieruchomienia płyty), antywirus to Defender (własny silnik AV byłby nierealny),
wentylatorami steruje się tylko w kartach NVIDIA (wentylatory CPU/obudowy nie mają publicznego API).

## Budowanie wydania jednym kliknięciem

Dwuklik na `ZBUDUJ.bat` (albo `ZBUDUJ.bat "opis zmian"` w cmd). Skrypt sam znajdzie Pythona, zbuduje wszystko i otworzy folder `release`.
Klucz podpisu jest kopiowany do `%USERPROFILE%\POU-keys` - poza projektem, więc skasowanie folderu projektu go nie usuwa.
Skrypt nigdy nie generuje nowego klucza sam (nowy klucz = zainstalowane aplikacje odrzucą aktualizacje).

## Nowości w 4.7.2

- Naprawiony przycisk **„Zwiększ FPS"** na panelu głównym (kończył się błędem po pierwszym kroku).
- Skróty i launcher są sprawdzane co 10 minut, także gdy aplikacja działa w tle; szczegółowy log skrótów do diagnostyki.
- Automatyczne skanowanie nie zgłasza błędu, gdy Defender już skanuje.

## Nowości w 4.7.1

- **Motyw zmienia się od razu**, bez restartu aplikacji.
- **Pobrane** - nowa zakładka: paczki aktualizacji i zapisane raporty, z otwieraniem i usuwaniem.
- **Test internetu**: usuwanie pojedynczych wyników i całej historii; raporty zapisują się do zakładki Pobrane.

## Nowości w 4.7

- **Logo wszędzie** - ikona .exe, paska zadań i skrótów to teraz Twoje logo (wcześniej budowanie nadpisywało je piorunem).
- **Test internetu**: pytania o kabel/Wi-Fi, porady „co możesz zrobić" z przejściem do odpowiedniej strony, raport dla dostawcy (zapis / kopiowanie).
- **Pady**: alerty baterii (spadek o N%, niski poziom, naładowany) także z zegara, szacunek czasu pracy i ładowania, widoczny status automatycznych spustów.
- **Działa samo**: RAM wg progu, co X minut albo oba; automatyczne szybkie skanowanie antywirusem.
- **Ochrona**: ocena bezpieczeństwa 0-100 z listą rzeczy do poprawy; czytelne komunikaty błędów.
- **Motywy** zapisują się także przy własnym theme.json.

## Nowości w 4.6

- **Test internetu** - ping, jitter, utrata pakietów, pobieranie, wysyłanie i opóźnienie pod obciążeniem, z oceną dla gier/wideo/streamingu.
- **Praca w tle** - zamknięcie okna chowa aplikację przy zegarze; opcjonalny autostart z Windows. Ponowne otwarcie skrótu pokazuje okno.
- **Motywy kolorów** i przełącznik animacji w Ustawieniach.
- **Usuń całkowicie** - cofa zmiany w Windows i w plikach gier, potem kasuje aplikację razem z danymi, skrótami i autostartem.
- Pady: podgląd koloru na żywo, poziom baterii, animacje świecenia, logo Aderis Boost.

## Nowości w 4.5
- Nowa nazwa: Aderis Boost. Pady: poziom baterii i stan ładowania, poprawiony test wibracji (nowszy firmware DualSense), lepsze rozpoznanie Bluetooth. Usunięto instalację DS4Windows i podgląd pliku FastFlag.

## Nowości w 4.4
- Samonaprawa: launcher (kopia zapasowa), skróty i wpis w Aplikacjach odtwarzają się same; aplikacja nie zostaje już w trybie administratora po restarcie.
- Pady: pilnowanie koloru, automatyczna siła spustów zależnie od gry, instalacja DS4Windows (pad jako Xbox).
- Windows i sieć: „Dopasuj do mojego komputera”, ping, szybki DNS, strojenie TCP. Ochrona: dodatkowe tarcze Windows.
- Optymalizacja aplikacji w tle podczas gry, ponad 60 gier (m.in. Motor Town), czyszczenie Opery nie wylogowuje komunikatorów.
- Podpisana lista plików aplikacji (wykrywanie podmiany plików).

## Nowości w 4.3
- **Pady i kierownice**: pad PS4/PS5 (kolor paska, jasność, test wibracji, spusty adaptacyjne DualSense, głośność głośnika/słuchawek/mikrofonu, dioda mikrofonu) przez oficjalny kanał HID oraz gotowe profile kierownicy (Logitech, Thrustmaster, Fanatec, Moza) do Forza Horizon 4/5.

## Nowości w 4.2

- Kopie zapasowe: „Zabezpiecz wszystko" albo wybrane części (Roblox, optymalizacje Windows, gry, ustawienia programu), z przywracaniem wybranych części.
- 6 nowych optymalizacji FPS (każda z cofaniem): pełny ekran bez optymalizacji, brak ograniczania mocy CPU, priorytet pierwszego planu,
  mysz bez przyspieszania, blokada aplikacji w tle, brak animacji okien.
- Udostępnianie profilu: zapis/odczyt ustawień do pliku `.pouprofile`. Nic nie idzie przez sieć; import jest walidowany
  (lista dozwolonych pól, twarde zakresy liczb, limit rozmiaru) i wymaga zatwierdzenia listy zmian.
- Zabezpieczenia czyszczenia: wpisy własne użytkownika mają ostrzejsze reguły, zablokowane foldery z danymi logowania/certyfikatami,
  kontrola linków/junctionów całego łańcucha folderów tuż przed kasowaniem. Pliki konfiguracji są ograniczone rozmiarem i walidowane.
- Usunięto przycisk „Dodaj .exe" i stronę Logi (błędy nadal zapisują się do pliku w folderze `logs`).

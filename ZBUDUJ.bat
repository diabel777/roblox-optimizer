@echo off
rem Buduje komplet wydania jednym klikiem. Uzycie: dwuklik na ZBUDUJ.bat
rem (opcjonalnie: ZBUDUJ.bat "opis zmian")
setlocal
cd /d "%~dp0"
title Budowanie PRO Ultimate Optimizer

set "STORE=%USERPROFILE%\POU-keys"

rem --- 1. Klucz podpisu: trzymany POZA projektem, zeby nie zginal przy kasowaniu folderu ---
if not exist "%STORE%\release_private.key" (
  if exist "keys\release_private.key" (
    echo Zapisuje klucz podpisu w bezpiecznym miejscu: %STORE%
    mkdir "%STORE%" 2>nul
    copy /y "keys\release_private.key" "%STORE%\release_private.key" >nul
    if not exist "%STORE%\release_private.key" (
      echo.
      echo NIE UDALO SIE zapisac klucza w %STORE% - zrob kopie folderu "keys" na pendrive!
      pause
    )
  )
)
if not exist "%STORE%\release_private.key" (
  echo.
  echo BRAK KLUCZA PODPISU.
  echo Wstaw swoj folder "keys" obok tego pliku ^(ZBUDUJ.bat^) i uruchom ponownie.
  echo Klucz zostanie zapamietany w: %STORE%
  echo Nie generuje nowego klucza, bo zainstalowane aplikacje odrzucilyby aktualizacje.
  echo.
  pause
  exit /b 1
)
mkdir keys 2>nul
copy /y "%STORE%\release_private.key" "keys\release_private.key" >nul
echo Klucz podpisu: OK ^(zapamietany w %STORE%^)

rem --- 2. Python ---
set "PYEXE="
for %%P in ("%LOCALAPPDATA%\Programs\Python\Python313\python.exe" "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" "%LOCALAPPDATA%\Programs\Python\Python311\python.exe" "%ProgramFiles%\Python313\python.exe" "%ProgramFiles%\Python312\python.exe") do (
  if not defined PYEXE if exist %%P set "PYEXE=%%~P"
)
if not exist ".venv\Scripts\python.exe" (
  if defined PYEXE (
    "%PYEXE%" -m venv .venv
  ) else (
    py -3 -m venv .venv
  )
  if errorlevel 1 (
    echo.
    echo Nie znaleziono Pythona 3.11+. Zainstaluj go z python.org ^(zaznacz "Add to PATH"^) i uruchom ponownie.
    pause
    exit /b 1
  )
)

rem --- 3. Budowanie ---
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0build.ps1" -Notes "%~1"
if errorlevel 1 (
  echo.
  echo BLAD budowania - zrob zrzut tego okna i wyslij.
  pause
  exit /b 1
)

echo.
echo ==============================================================
echo  GOTOWE. W otwartym folderze sa 3 pliki:
echo    ProUltimateOptimizer-Setup.exe
echo    ProUltimateOptimizer-X.Y.Z.zip
echo    version.json
echo  Wyslij mi je i wgraj Setup.exe + zip do wydania na GitHubie.
echo ==============================================================
start "" "%~dp0release"
pause

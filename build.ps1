<#
  Buduje komplet wydania:  .\build.ps1
  Wymaga: Python 3.11+ (z tkinter) w PATH. Wynik: folder .\release\
      ProUltimateOptimizer-Setup.exe        <- to dajesz użytkownikom
      ProUltimateOptimizer-<wersja>.zip     <- paczka aktualizacji
      version.json                          <- podpisany manifest (ogłasza aktualizację)
  Wersję zmieniasz w src\pro_optimizer\version.py (VERSION) przed budowaniem.
  Opcje: -Notes "co nowego" (pokaże się w instalatorze)   -Tag v4.0.1
#>
param([string]$Notes = "", [string]$Tag = "")
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

function Run($exe, $argList) { & $exe @argList; if ($LASTEXITCODE -ne 0) { throw "Błąd: $exe $argList" } }

if (-not $Tag) {
    $m = Select-String -Path src\pro_optimizer\version.py -Pattern 'VERSION\s*=\s*"([^"]+)"'
    if ($m) { $Tag = "v" + $m.Matches[0].Groups[1].Value }
}
if (-not (Test-Path .venv)) { Run python @("-m", "venv", ".venv") }
$py = ".\.venv\Scripts\python.exe"
Run $py @("-m", "pip", "install", "--quiet", "--upgrade", "pip")
Run $py @("-m", "pip", "install", "--quiet", "-r", "requirements-dev.txt")

Write-Host "==> Testy" -ForegroundColor Cyan
Run $py @("-m", "pytest", "-q", "tests/test_core.py", "tests/test_install.py")

Write-Host "==> Ikona, metadane, klucze" -ForegroundColor Cyan
Run $py @("tools/make_icon.py")
Run $py @("tools/make_version_info.py")
if (-not (Test-Path keys\release_private.key) -and -not $env:POU_SIGNING_KEY) {
    if ($env:POU_ALLOW_KEYGEN -eq "1") { Run $py @("tools/release.py", "keygen") }
    else { throw "Brak klucza podpisu (keys\release_private.key). Nie generuje nowego, bo zainstalowane aplikacje odrzucilyby aktualizacje. Uzyj ZBUDUJ.bat albo wstaw swoj folder keys." }
}

Write-Host "==> Budowanie (aplikacja, launcher, instalator)" -ForegroundColor Cyan
Remove-Item -Recurse -Force dist, build -ErrorAction SilentlyContinue
Run $py @("-m", "PyInstaller", "--noconfirm", "--clean", "specs/app.spec")
Run $py @("-m", "PyInstaller", "--noconfirm", "--clean", "specs/launcher.spec")
Run $py @("-m", "PyInstaller", "--noconfirm", "--clean", "specs/setup.spec")

Write-Host "==> Paczka + podpis" -ForegroundColor Cyan
$pkgArgs = @("tools/release.py", "package", "--dist", "dist/ProUltimateOptimizerApp", "--out", "release", "--notes=$Notes")
if ($Tag) { $pkgArgs += @("--tag=$Tag") }
Run $py $pkgArgs
Copy-Item dist\ProUltimateOptimizer-Setup.exe release\ -Force
Write-Host "`nGOTOWE -> .\release\" -ForegroundColor Green

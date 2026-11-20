"""Generuje pliki „Właściwości > Szczegóły” (VERSIONINFO) dla exe. Pliki z pełnymi metadanymi
(nazwa produktu, wydawca, wersja) rzadziej wzbudzają podejrzenia Windows Defendera/SmartScreen.
Uruchamia to build.ps1 przed PyInstallerem."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from pro_optimizer.version import APP_NAME, VERSION, parse_version   # noqa: E402

TEMPLATE = """VSVersionInfo(
  ffi=FixedFileInfo(filevers={tup}, prodvers={tup}, mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('040904B0', [
      StringStruct('CompanyName', 'Diabeł'),
      StringStruct('FileDescription', '{desc}'),
      StringStruct('FileVersion', '{ver}'),
      StringStruct('InternalName', '{name}'),
      StringStruct('LegalCopyright', '© 2026 Diabeł'),
      StringStruct('OriginalFilename', '{name}.exe'),
      StringStruct('ProductName', '{prod}'),
      StringStruct('ProductVersion', '{ver}')])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
"""

TARGETS = {"app": ("ProUltimateOptimizerApp", f"{APP_NAME}"),
           "launcher": ("ProUltimateOptimizer", f"{APP_NAME} (launcher)"),
           "setup": ("ProUltimateOptimizer-Setup", f"{APP_NAME} – instalator")}


def main() -> None:
    out = ROOT / "specs" / "version_info"
    out.mkdir(parents=True, exist_ok=True)
    tup = parse_version(VERSION)[:4]
    for key, (name, desc) in TARGETS.items():
        (out / f"{key}.txt").write_text(
            TEMPLATE.format(tup=tup, ver=VERSION, name=name, desc=desc, prod=APP_NAME), encoding="utf-8")
    print("Zapisano pliki VERSIONINFO w", out)


if __name__ == "__main__":
    main()

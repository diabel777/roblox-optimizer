"""Narzędzie wydawcy: klucze, paczka aktualizacji, podpisany manifest.

    python tools/release.py keygen                 jednorazowo: tworzy parę kluczy Ed25519
    python tools/release.py package --dist dist/ProUltimateOptimizerApp [--notes "..."] [--out release]
    python tools/release.py verify release/version.json

Klucz PRYWATNY (keys/release_private.key lub zmienna POU_SIGNING_KEY w CI) podpisuje manifest.
Klucz PUBLICZNY trafia do src/pro_optimizer/update_key.py i jest wkompilowany w aplikację -
dzięki temu nikt, kto nie ma Twojego klucza prywatnego (nawet z dostępem do repo na GitHubie),
nie podrzuci użytkownikom fałszywej aktualizacji.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from pro_optimizer import ed25519, security                         # noqa: E402
from pro_optimizer.version import APP_EXE, SETUP_EXE, VERSION      # noqa: E402

REPO = "diabel777/roblox-optimizer"
KEY_FILE = ROOT / "keys" / "release_private.key"
PUB_FILE = ROOT / "src" / "pro_optimizer" / "update_key.py"


def die(msg: str) -> None:
    print(f"BŁĄD: {msg}", file=sys.stderr)
    sys.exit(1)


def embedded_public_key() -> str:
    m = re.search(r'PUBLIC_KEY_HEX\s*=\s*"([0-9a-fA-F]*)"', PUB_FILE.read_text(encoding="utf-8"))
    return m.group(1).lower() if m else ""


def load_secret() -> bytes:
    raw = os.environ.get("POU_SIGNING_KEY", "").strip()
    if not raw:
        if not KEY_FILE.exists():
            die(f"Brak klucza podpisu. Uruchom najpierw:  python tools/release.py keygen\n(szukano: {KEY_FILE})")
        raw = KEY_FILE.read_text(encoding="utf-8").strip()
    if not re.fullmatch(r"[0-9a-fA-F]{64}", raw):
        die("Klucz prywatny ma zły format (oczekiwane 64 znaki hex).")
    return bytes.fromhex(raw)


# --------------------------------------------------------------------------- keygen
def cmd_keygen(a) -> None:
    if KEY_FILE.exists() and not a.force:
        die(f"Klucz już istnieje ({KEY_FILE}).\nZmiana klucza sprawi, że JUŻ ZAINSTALOWANE aplikacje przestaną "
            "przyjmować aktualizacje!\nJeśli naprawdę tego chcesz, dodaj --force.")
    sk = os.urandom(32)
    pk = ed25519.public_key(sk).hex()
    KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
    KEY_FILE.write_text(sk.hex() + "\n", encoding="utf-8")
    try:
        os.chmod(KEY_FILE, 0o600)
    except OSError:
        pass
    src = PUB_FILE.read_text(encoding="utf-8")
    PUB_FILE.write_text(re.sub(r'PUBLIC_KEY_HEX\s*=\s*"[0-9a-fA-F]*"', f'PUBLIC_KEY_HEX = "{pk}"', src), encoding="utf-8")
    print(f"Klucz prywatny: {KEY_FILE}   <-- ZRÓB KOPIĘ ZAPASOWĄ (np. menedżer haseł). Nie wrzucaj na GitHub!")
    print(f"Klucz publiczny wpisany do: {PUB_FILE.relative_to(ROOT)}")
    print("Dla GitHub Actions dodaj sekret POU_SIGNING_KEY o wartości z pliku klucza prywatnego.")


# --------------------------------------------------------------------------- package
def cmd_package(a) -> None:
    dist = Path(a.dist).resolve()
    if not (dist / APP_EXE).exists():
        die(f"W {dist} nie ma {APP_EXE}. Najpierw zbuduj aplikację (build.ps1).")
    sk = load_secret()
    pk = ed25519.public_key(sk).hex()
    if embedded_public_key() != pk:
        die("Klucz publiczny wkompilowany w aplikację (update_key.py) NIE pasuje do klucza podpisu.\n"
            "Użytkownicy odrzuciliby tę aktualizację. Zbuduj aplikację ponownie po 'keygen'.")

    from pro_optimizer import integrity
    (dist / integrity.FILE).write_text(json.dumps(integrity.build(dist, sk), indent=1) + "\n", encoding="utf-8")
    chk = integrity.verify(dist, pk)
    if not chk["ok"]:
        die(f"Autotest integralności nie przeszedł: {chk['reason']}")
    print(f"Integralność: {chk['checked']} plików podpisanych")

    out = Path(a.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    ver = a.version or VERSION
    zip_path = out / f"ProUltimateOptimizer-{ver}.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for f in sorted(dist.rglob("*")):
            if f.is_file():
                z.write(f, f.relative_to(dist).as_posix())               # exe aplikacji leży w korzeniu paczki
    sha = hashlib.sha256(zip_path.read_bytes()).hexdigest()
    size = zip_path.stat().st_size
    tag = a.tag or f"v{ver}"
    manifest = {
        "version": ver,
        "notes": a.notes or "",
        "package": {"url": f"https://github.com/{REPO}/releases/download/{tag}/{zip_path.name}",
                    "sha256": sha, "size": size},
        # Tylko dla starych klientów v3.x: pobiorą Setup i sami się zmigrują. (Stary mechanizm nie weryfikuje
        # podpisu - dlatego to jednorazowy most, a v4 już zawsze sprawdza podpis.)
        "download_url": f"https://github.com/{REPO}/releases/latest/download/{SETUP_EXE}",
    }
    signed = security.sign_manifest(manifest, sk)
    mp = out / "version.json"
    mp.write_text(json.dumps(signed, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    security.verify_manifest(mp.read_bytes(), pk)                         # autotest: podpis musi się zweryfikować
    print(f"Paczka:   {zip_path}  ({size / 1048576:.1f} MB)\nSHA-256:  {sha}\nManifest: {mp}  (podpis OK)")
    print(f"\nDalej:\n  1) GitHub Release z tagiem {tag}: wgraj {zip_path.name} oraz {SETUP_EXE}\n"
          f"  2) DOPIERO POTEM wrzuć version.json do głównego katalogu repo (branch main) - to on ogłasza aktualizację")


# --------------------------------------------------------------------------- verify
def cmd_verify(a) -> None:
    pk = embedded_public_key()
    if not pk:
        die("update_key.py nie zawiera klucza publicznego (uruchom keygen).")
    try:
        m = security.verify_manifest(Path(a.manifest).read_bytes(), pk)
    except Exception as e:                                              # noqa: BLE001
        die(str(e))
    print(f"Podpis poprawny. Wersja {m['version']}, paczka {m['package']['url']}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    k = sub.add_parser("keygen"); k.add_argument("--force", action="store_true"); k.set_defaults(fn=cmd_keygen)
    p = sub.add_parser("package")
    p.add_argument("--dist", required=True); p.add_argument("--out", default="release")
    p.add_argument("--notes", default=""); p.add_argument("--version"); p.add_argument("--tag")
    p.set_defaults(fn=cmd_package)
    v = sub.add_parser("verify"); v.add_argument("manifest"); v.set_defaults(fn=cmd_verify)
    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()

"""Smoke-test kreatora Setup (Linux + Xvfb):  xvfb-run -a python tests/ui_installer_smoke.py OUT_DIR
Lokalny serwer z podpisanym pakietem; robi zrzuty ekranów kolejnych ekranów i sprawdza wynik instalacji."""
import hashlib, io, json, os, socketserver, subprocess, sys, tempfile, threading, time, zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src")); sys.path.insert(0, str(ROOT / "installer")); sys.path.insert(0, str(ROOT / "tests"))
out = Path(sys.argv[1] if len(sys.argv) > 1 else tempfile.mkdtemp()); out.mkdir(parents=True, exist_ok=True)
tmp = Path(tempfile.mkdtemp())
os.environ.update(LOCALAPPDATA=str(tmp / "L"), APPDATA=str(tmp / "R"), PRO_OPT_HOME=str(tmp / "L" / "ProUltimateOptimizer"))

from test_core import _H
from pro_optimizer import ed25519, security, updater, install, paths
from pro_optimizer.version import APP_EXE
import installer as setup_mod

sk = os.urandom(32); pk = ed25519.public_key(sk).hex()
srv = socketserver.TCPServer(("127.0.0.1", 0), _H); threading.Thread(target=srv.serve_forever, daemon=True).start()
base = f"http://127.0.0.1:{srv.server_address[1]}"
buf = io.BytesIO()
with zipfile.ZipFile(buf, "w") as z:
    z.writestr(APP_EXE, "MZ"); z.writestr("_internal/big.bin", os.urandom(6 * 1024 * 1024))
pkg = buf.getvalue(); _H.files["/p.zip"] = pkg
_H.files["/version.json"] = json.dumps(security.sign_manifest({"version": "4.0.0", "notes": "Nowy wygląd i instalator", "package": {
    "url": base + "/p.zip", "sha256": hashlib.sha256(pkg).hexdigest(), "size": len(pkg)}}, sk)).encode()
policy = security.FetchPolicy(allowed_hosts=frozenset({"127.0.0.1"}), require_https=False)
Real = updater.Updater
class Patched(Real):
    def __init__(self, current_version="0", root=None, **kw):
        super().__init__(current_version, root, policy, pk, base + "/version.json")
updater.Updater = Patched; setup_mod.Updater = Patched
(tmp / "launcher.exe").write_bytes(b"L"); (tmp / "icon.ico").write_bytes(b"I")
install.find_payload = lambda name: tmp / ("launcher.exe" if name.endswith("exe") else "icon.ico")
setup_mod.launch_app = lambda: print("launch_app() wywołane")

def shot(name):
    subprocess.run(["import", "-window", "root", str(out / f"setup_{name}.png")], check=True)

def on_ready(app):
    def pump(sec):
        end = time.time() + sec
        while time.time() < end:
            app.update(); time.sleep(0.03)
    def script():
        pump(1.5); shot("1_welcome")
        app.v_launch.set(False); app.start(); pump(0.35); shot("2_progress")
        t0 = time.time()
        while not install.is_installed() and time.time() - t0 < 20: pump(0.2)
        pump(1.0); shot("3_done")
        r = paths.install_root()
        print("installed:", install.is_installed(), sorted(p.name for p in r.iterdir()))
        # błąd: zepsuty podpis
        _H.files["/version.json"] = _H.files["/version.json"].replace(b"4.0.0", b"9.9.9")
        app.welcome(); pump(0.8); app.start(); pump(2.5); shot("4_error")
        print("SETUP UI SMOKE DONE"); app.destroy()
    app.after(200, script)

setup_mod.run_gui(install.InstallOptions(True, True, False), on_ready=on_ready)

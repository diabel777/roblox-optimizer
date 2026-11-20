"""Testy instalatora: instalacja, naprawa, migracja z v3.x, odinstalowanie (lokalny serwer, bez Windowsa)."""
import hashlib, io, json, os, socketserver, sys, threading, time, unittest, zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_core import Env, _H                                   # noqa: E402
from pro_optimizer import ed25519, install, paths, security, updater   # noqa: E402
from pro_optimizer.security import FetchPolicy, SecurityError   # noqa: E402
from pro_optimizer.version import APP_EXE, LAUNCHER_EXE        # noqa: E402


class TestInstall(Env):
    def setUp(self):
        super().setUp()
        self.sk = os.urandom(32); self.pk = ed25519.public_key(self.sk).hex()
        self.srv = socketserver.TCPServer(("127.0.0.1", 0), _H)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.srv.server_address[1]}"
        self.policy = FetchPolicy(allowed_hosts=frozenset({"127.0.0.1"}), require_https=False)
        self.launcher_src = self.mk("payload/launcher.exe", 50)
        self.icon_src = self.mk("payload/icon.ico", 20)

    def tearDown(self):
        self.srv.shutdown(); self.srv.server_close(); super().tearDown()

    def publish(self, version):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr(APP_EXE, "MZ-" + version); z.writestr("_internal/x.dll", "dll")
        pkg = buf.getvalue()
        _H.files["/pkg.zip"] = pkg
        m = security.sign_manifest({"version": version, "notes": "n", "package": {
            "url": self.base + "/pkg.zip", "sha256": hashlib.sha256(pkg).hexdigest(), "size": len(pkg)}}, self.sk)
        _H.files["/version.json"] = json.dumps(m).encode()

    def up(self):
        return updater.Updater("0", paths.install_root(), self.policy, self.pk, self.base + "/version.json")

    def do_install(self, **kw):
        return install.install(install.InstallOptions(), updater=self.up(), launcher_src=self.launcher_src,
                               icon_src=self.icon_src, **kw)

    def test_fresh_install_layout_and_progress(self):
        self.publish("4.0.0"); seen = []
        r = self.do_install(progress=lambda st, f, t: seen.append((st, f)))
        root = paths.install_root()
        self.assertEqual(r.version, "4.0.0")
        self.assertTrue((root / LAUNCHER_EXE).exists())
        self.assertTrue((root / "app.ico").exists())
        self.assertTrue((root / "app-4.0.0" / APP_EXE).exists())
        self.assertTrue(install.is_installed())
        fr = [f for _, f in seen]
        self.assertEqual(fr, sorted(fr))                         # postęp nigdy nie cofa się
        self.assertEqual(seen[-1], ("done", 1.0))
        self.assertIn("download", {s for s, _ in seen})

    def test_reinstall_is_repair_and_keeps_user_data(self):
        self.publish("4.0.0"); self.do_install()
        root = paths.install_root()
        (root / "app-4.0.0" / APP_EXE).unlink()                   # uszkodzona instalacja
        (root / "Backups" / "moja.bak").write_text("dane")
        self.do_install()
        self.assertTrue((root / "app-4.0.0" / APP_EXE).exists())
        self.assertEqual((root / "Backups" / "moja.bak").read_text(), "dane")

    def test_upgrade_installs_side_by_side(self):
        self.publish("4.0.0"); self.do_install()
        self.publish("4.1.0"); self.do_install()
        root = paths.install_root()
        self.assertTrue((root / "app-4.0.0" / APP_EXE).exists())  # poprzednia wersja zostaje do rollbacku
        self.assertTrue((root / "app-4.1.0" / APP_EXE).exists())

    def test_migrates_from_v3(self):
        root = paths.install_root()
        for n in install.LEGACY_FILES:
            (root / n).write_text("stare")
        (root / "Backups" / "Manual_Studio.json.bak").write_text("{}")
        self.publish("4.0.0"); self.do_install()
        for n in install.LEGACY_FILES:
            self.assertFalse((root / n).exists(), n)
        self.assertTrue((root / "Backups" / "Manual_Studio.json.bak").exists())

    def test_replace_file_over_locked_launcher(self):
        dest = self.mk("Local/x/launcher.exe", 10)
        orig = os.replace; calls = {"n": 0}
        def flaky(a, b):                                          # pierwszy os.replace(tmp,dest) "zablokowany"
            calls["n"] += 1
            if calls["n"] == 1:
                raise PermissionError("in use")
            return orig(a, b)
        os.replace = flaky
        try:
            install.replace_file(self.launcher_src, dest)
        finally:
            os.replace = orig
        self.assertEqual(dest.read_bytes(), b"x" * 50)
        self.assertTrue(dest.with_name("launcher.exe.old").exists())

    def test_bad_signature_aborts_before_touching_install(self):
        self.publish("4.0.0")
        m = json.loads(_H.files["/version.json"]); m["version"] = "9.9.9"
        _H.files["/version.json"] = json.dumps(m).encode()
        with self.assertRaises(SecurityError):
            self.do_install()
        self.assertFalse((paths.install_root() / LAUNCHER_EXE).exists())

    def test_uninstall_keeps_or_removes_data(self):
        self.publish("4.0.0"); self.do_install()
        root = paths.install_root()
        (root / "Backups" / "b.bak").write_text("x"); (root / "settings.json").write_text("{}")
        install.uninstall(remove_data=False)
        self.assertFalse(list(root.glob("app-*")))
        deadline = time.time() + 10                              # Windows: launcher kasuje się z opóźnieniem (osobny cmd)
        while (root / LAUNCHER_EXE).exists() and time.time() < deadline:
            time.sleep(0.25)
        self.assertFalse((root / LAUNCHER_EXE).exists())
        self.assertTrue((root / "Backups" / "b.bak").exists())    # dane zostały
        self.assertTrue((root / "settings.json").exists())
        install.uninstall(remove_data=True)
        deadline = time.time() + 10
        while root.exists() and time.time() < deadline:
            time.sleep(0.25)
        self.assertFalse(root.exists())

    def test_deferred_delete_cmdline_has_no_escaped_quotes(self):
        # regresja: list2cmdline zamieniał " na \" i cmd.exe nic nie kasował (wykryte na prawdziwym Windowsie)
        a = self.mk("Local/ProUltimateOptimizer/ProUltimateOptimizer.exe", 5)
        d = self.tmp / "Local" / "ProUltimateOptimizer" / "app-4.0.0"; d.mkdir(parents=True)
        cmd = install.deferred_delete_cmdline([a, d])
        self.assertTrue(cmd.startswith('cmd.exe /d /s /c "ping -n 3 127.0.0.1 >nul & '))
        self.assertNotIn('\\"', cmd)
        self.assertIn(f'del /f /q "{a}"', cmd)
        self.assertIn(f'rmdir /s /q "{d}"', cmd)
        self.assertTrue(cmd.endswith('"'))


    def test_uninstall_refuses_foreign_directory(self):
        os.environ.pop("PRO_OPT_HOME")
        with self.assertRaises(RuntimeError):
            install.uninstall(root=Path("/tmp") / "Documents")


if __name__ == "__main__":
    unittest.main()

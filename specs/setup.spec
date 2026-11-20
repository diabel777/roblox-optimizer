# -*- mode: python ; coding: utf-8 -*-
# Instalator: jeden plik exe. W środku siedzi launcher (payload) - dlatego launcher.spec budujemy PRZED tym.
import os
from PyInstaller.utils.hooks import collect_data_files
ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))
LAUNCHER = os.path.join(ROOT, "dist", "ProUltimateOptimizer.exe")
if not os.path.exists(LAUNCHER):
    raise SystemExit("Najpierw zbuduj launcher:  pyinstaller specs/launcher.spec")

a = Analysis(
    [os.path.join(ROOT, "installer", "installer.py")],
    pathex=[os.path.join(ROOT, "src")],
    binaries=[(LAUNCHER, "payload")],
    datas=[(os.path.join(ROOT, "config"), "config"),
           (os.path.join(ROOT, "assets", "icon.ico"), "payload")] + collect_data_files("customtkinter"),
    hiddenimports=[],
    excludes=["unittest", "pydoc", "psutil", "matplotlib", "numpy"],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, a.binaries, a.datas, [],
    name="ProUltimateOptimizer-Setup",
    console=False,
    upx=False,
    icon=os.path.join(ROOT, "assets", "icon.ico"),
    version=os.path.join(ROOT, "specs", "version_info", "setup.txt"),
    uac_admin=False,                # instalacja per-użytkownik - bez monitu UAC
)

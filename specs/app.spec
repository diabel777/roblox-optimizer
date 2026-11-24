# -*- mode: python ; coding: utf-8 -*-
# Aplikacja (onedir - szybki start, bez rozpakowywania do TEMP, mniej fałszywych alarmów AV niż onefile).
import os
from PyInstaller.utils.hooks import collect_data_files
ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))

a = Analysis(
    [os.path.join(ROOT, "src", "run_app.py")],
    pathex=[os.path.join(ROOT, "src")],
    datas=[(os.path.join(ROOT, "config"), "config"),
           (os.path.join(ROOT, "assets"), "assets")] + collect_data_files("customtkinter"),
    hiddenimports=["hid", "pystray", "pystray._win32"],
    excludes=["unittest", "pydoc", "test", "matplotlib", "numpy"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="ProUltimateOptimizerApp",
    console=False,
    upx=False,                      # UPX zwiększa liczbę fałszywych alarmów antywirusa - wyłączony celowo
    icon=os.path.join(ROOT, "assets", "icon.ico"),
    version=os.path.join(ROOT, "specs", "version_info", "app.txt"),
    uac_admin=False,                # zwykłe uprawnienia; admin tylko na żądanie (przycisk w aplikacji)
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="ProUltimateOptimizerApp")

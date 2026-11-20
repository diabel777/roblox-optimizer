# -*- mode: python ; coding: utf-8 -*-
# Launcher: maleńki, tylko biblioteka standardowa. Ląduje jako ProUltimateOptimizer.exe w katalogu instalacji.
import os
ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))

a = Analysis(
    [os.path.join(ROOT, "launcher", "launcher.py")],
    pathex=[os.path.join(ROOT, "src")],
    hiddenimports=["pro_optimizer.install", "pro_optimizer.shell", "pro_optimizer.updater", "pro_optimizer.paths"],
    excludes=["tkinter", "customtkinter", "PIL", "psutil", "unittest", "pydoc"],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, a.binaries, a.datas, [],
    name="ProUltimateOptimizer",
    console=False,
    upx=False,
    icon=os.path.join(ROOT, "assets", "icon.ico"),
    version=os.path.join(ROOT, "specs", "version_info", "launcher.txt"),
    uac_admin=False,
)

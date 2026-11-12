# -*- mode: python ; coding: utf-8 -*-
# Derleme: .venv\Scripts\python.exe -m PyInstaller --noconfirm --clean Xyron_Voice_Changer.spec
from PyInstaller.utils.hooks import collect_all

datas = [("assets/icon.ico", "assets"), ("assets/icon.png", "assets")]
binaries = []
hiddenimports = []
# sounddevice tek modüldür; PortAudio DLL'leri _sounddevice_data paketinde gelir.
for pkg in ("customtkinter", "pedalboard", "_sounddevice_data"):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["pytest", "matplotlib", "scipy", "pandas", "IPython"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="Xyron Voice Changer",
    debug=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    icon="assets/icon.ico",
)

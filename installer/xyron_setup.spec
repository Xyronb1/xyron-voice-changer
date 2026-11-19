# -*- mode: python ; coding: utf-8 -*-
# Kurulum sihirbazı. Önce tools/build_release.py klasör sürümünü build/payload.zip olarak hazırlar.
# Derleme: ..\.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean xyron_setup.spec

a = Analysis(
    ["xyron_setup.py"],
    pathex=[],
    binaries=[],
    datas=[("build/payload.zip", "."), ("../assets/icon.ico", ".")],
    hiddenimports=[],
    hookspath=[],
    runtime_hooks=[],
    excludes=["numpy", "PIL", "customtkinter", "pedalboard", "sounddevice", "pytest",
              "unittest", "pydoc"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="Xyron-Voice-Changer-Setup",
    debug=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    icon="../assets/icon.ico",
)

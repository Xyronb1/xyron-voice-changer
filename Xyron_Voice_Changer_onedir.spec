# -*- mode: python ; coding: utf-8 -*-
# Klasör sürümü (onedir): Temp'e açılmaz, hızlı başlar, antivirüslere daha az takılır.
# Kurulum sihirbazı (installer/) bu klasörü paketler.
# Derleme: .venv\Scripts\python.exe -m PyInstaller --noconfirm --clean Xyron_Voice_Changer_onedir.spec
from PyInstaller.utils.hooks import collect_all

datas = [("assets/icon.ico", "assets"), ("assets/icon.png", "assets")]
binaries = []
hiddenimports = []
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
    excludes=["pytest", "matplotlib", "scipy", "pandas", "IPython", "unittest", "pydoc",
              "lib2to3", "xmlrpc"],
    noarchive=False,
)
pyz = PYZ(a.pure)

splash = Splash(
    "assets/splash.png",
    binaries=a.binaries,
    datas=a.datas,
    text_pos=(40, 236),
    text_size=10,
    text_color="#a3a8c7",
    text_default="Loading...",
    always_on_top=True,
)

exe = EXE(
    pyz,
    a.scripts,
    splash,
    [],
    exclude_binaries=True,
    name="Xyron Voice Changer",
    debug=False,
    strip=False,
    upx=False,
    console=False,
    icon="assets/icon.ico",
)
coll = COLLECT(exe, splash.binaries, a.binaries, a.datas, strip=False, upx=False,
               name="Xyron Voice Changer")

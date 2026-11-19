"""Xyron Voice Changer kurulum sihirbazı (yönetici izni gerektirmez).

Klasör sürümünü (onedir) %LOCALAPPDATA%\\Programs\\Xyron Voice Changer altına kurar, Başlat
menüsü / masaüstü kısayolu oluşturur ve Windows "Uygulamalar" listesine kaldırma kaydı ekler.
Kurulu program her açılışta kendini Temp'e açmadığı için tek dosyalık EXE'den çok daha hızlı başlar.

Kullanım:
  Xyron-Voice-Changer-Setup.exe                    sihirbazı açar
  Xyron-Voice-Changer-Setup.exe --silent           sorusuz kurar
  python xyron_setup.py --payload app.zip --target D:\\test --silent --no-shortcuts --no-register
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

APP_NAME = "Xyron Voice Changer"
APP_EXE = "Xyron Voice Changer.exe"
PUBLISHER = "Xyron"
VERSION = "1.3.0"
UNINSTALL_KEY = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\XyronVoiceChanger"
MUTEX_NAME = "Local\\Xyron.VoiceChanger.SingleInstance"
# Yarıda kalan bir kurulumun geçici klasörü de "bizim" sayılsın diye ilk yazılan işaret dosyası.
STAGING_MARKER = ".xyron-setup-in-progress"
EXIT_OK, EXIT_ERROR, EXIT_USAGE = 0, 1, 2

UNINSTALL_PS1 = r"""# Xyron Voice Changer kaldırıcı (kurulum sihirbazı tarafından oluşturuldu)
$ErrorActionPreference = 'SilentlyContinue'
Add-Type -AssemblyName System.Windows.Forms
$appDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$running = Get-Process -Name 'Xyron Voice Changer' -ErrorAction SilentlyContinue |
  Where-Object { $_.Path -and $_.Path.StartsWith($appDir) }
if ($running) {
  [System.Windows.Forms.MessageBox]::Show('Please close Xyron Voice Changer first, then try again.',
    'Xyron Voice Changer', 'OK', 'Warning') | Out-Null
  exit 1
}
$quiet = $args -contains '/quiet'
if (-not $quiet) {
  $answer = [System.Windows.Forms.MessageBox]::Show(
    "Remove Xyron Voice Changer from this computer?`n`nYour settings and saved profiles in %APPDATA%\Xyron_Voice_Changer are kept.",
    'Uninstall Xyron Voice Changer', 'YesNo', 'Question')
  if ($answer -ne 'Yes') { exit 2 }
}
$shell = New-Object -ComObject WScript.Shell
foreach ($lnk in @(
    (Join-Path $shell.SpecialFolders('Programs') 'Xyron Voice Changer.lnk'),
    (Join-Path $shell.SpecialFolders('Desktop') 'Xyron Voice Changer.lnk'))) {
  if (Test-Path -LiteralPath $lnk) { Remove-Item -LiteralPath $lnk -Force }
}
Remove-Item -Path 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\XyronVoiceChanger' -Recurse -Force
Set-Location $env:TEMP
Remove-Item -LiteralPath $appDir -Recurse -Force
if (Test-Path -LiteralPath $appDir) {
  # Bir dosya hâlâ kilitliyse klasörü birkaç saniye sonra arka planda sil.
  Start-Process -WindowStyle Hidden -FilePath 'cmd.exe' -ArgumentList "/c timeout /t 3 /nobreak >nul & rmdir /s /q `"$appDir`""
}
if (-not $quiet) {
  [System.Windows.Forms.MessageBox]::Show('Xyron Voice Changer was removed.', 'Xyron Voice Changer') | Out-Null
}
exit 0
"""


@dataclass
class Options:
    target: Path
    desktop_shortcut: bool = True
    start_menu: bool = True
    register: bool = True
    launch: bool = False


class SetupError(Exception):
    """Kullanıcıya gösterilecek, anlaşılır kurulum hatası."""


def default_target() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(base) / "Programs" / APP_NAME


def bundled_payload() -> Path:
    """EXE içine gömülü payload.zip (PyInstaller) ya da betiğin yanındaki dosya."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base / "payload.zip"


def app_is_running() -> bool:
    """Uygulamanın tek kopya kilidi alınmışsa çalışıyordur (dosyalar kilitli olur)."""
    if sys.platform != "win32":
        return False
    import ctypes
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenMutexW.restype = ctypes.c_void_p
    kernel32.OpenMutexW.argtypes = (ctypes.c_uint32, ctypes.c_bool, ctypes.c_wchar_p)
    synchronize = 0x00100000
    handle = kernel32.OpenMutexW(synchronize, False, MUTEX_NAME)
    if handle:
        kernel32.CloseHandle.argtypes = (ctypes.c_void_p,)
        kernel32.CloseHandle(handle)
        return True
    return False


def validate_payload(payload: Path) -> list[zipfile.ZipInfo]:
    """Arşivi açar, içinde uygulama EXE'si olduğunu ve zararlı yol olmadığını doğrular."""
    if not payload.is_file():
        raise SetupError(f"Installer data is missing: {payload}")
    try:
        with zipfile.ZipFile(payload) as zf:
            members = zf.infolist()
    except zipfile.BadZipFile as exc:
        raise SetupError(f"Installer data is damaged ({exc}). Please download the setup again.") from exc
    names = {m.filename.replace("\\", "/") for m in members}
    if APP_EXE not in names:
        raise SetupError("Installer data does not contain the application.")
    for m in members:
        parts = Path(m.filename.replace("\\", "/")).parts
        if m.filename.startswith(("/", "\\")) or ".." in parts or (parts and ":" in parts[0]):
            raise SetupError(f"Unsafe path in installer data: {m.filename}")
    return members


def install_files(payload: Path, target: Path, progress: Callable[[float, str], None]) -> None:
    """Dosyaları önce yan klasöre açar, sonra eski sürümle tek hamlede yer değiştirir.

    Yarıda kesilirse eski kurulum bozulmaz.
    """
    members = validate_payload(payload)
    check_target_is_safe(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = target.with_name(target.name + ".new")
    backup = target.with_name(target.name + ".old")
    for leftover in (staging, backup):  # önceki yarım kurulumdan kalanlar (sadece bizimkiler)
        if leftover.exists() and is_our_install(leftover):
            shutil.rmtree(leftover, ignore_errors=True)
        elif leftover.exists():
            raise SetupError(f"Please remove or rename this folder first: {leftover}")
    total = sum(m.file_size for m in members) or 1
    done = 0
    try:
        staging.mkdir(parents=True)
        (staging / STAGING_MARKER).write_text("xyron-voice-changer setup", encoding="utf-8")
        with zipfile.ZipFile(payload) as zf:
            for m in members:
                zf.extract(m, staging)
                done += m.file_size
                progress(0.05 + 0.85 * done / total, f"Copying {Path(m.filename).name}")
        (staging / "uninstall.ps1").write_text(UNINSTALL_PS1, encoding="utf-8-sig")
        (staging / STAGING_MARKER).unlink()
        if target.exists():
            try:
                target.replace(backup)
            except OSError as exc:
                raise SetupError("The old version is still in use. Close Xyron Voice Changer "
                                 "and run the setup again.") from exc
        staging.replace(target)
    except (OSError, SetupError) as exc:
        shutil.rmtree(staging, ignore_errors=True)
        if backup.exists() and not target.exists():
            backup.replace(target)
        if isinstance(exc, SetupError):
            raise
        raise SetupError(f"Could not copy the files: {exc}") from exc
    shutil.rmtree(backup, ignore_errors=True)


def is_our_install(folder: Path) -> bool:
    """Klasör bizim kurulumumuz mu (veya boş mu)? Başka hiçbir klasör silinmez/taşınmaz."""
    try:
        entries = list(folder.iterdir())
    except OSError:
        return False
    return (not entries or (folder / APP_EXE).is_file() or (folder / "uninstall.ps1").is_file()
            or (folder / STAGING_MARKER).is_file())


def check_target_is_safe(target: Path) -> None:
    if not target.is_absolute() or len(target.parts) < 2 or target.parent == target:
        raise SetupError("Please choose a folder inside a drive, for example C:\\Apps\\Xyron Voice Changer.")
    if target.exists() and not target.is_dir():
        raise SetupError(f"A file with this name already exists: {target}")
    if target.exists() and not is_our_install(target):
        raise SetupError(f"The folder is not empty and does not contain Xyron Voice Changer:\n{target}\n\n"
                         "Choose an empty folder or a new folder name.")


def run_powershell(script: str, env_extra: dict[str, str]) -> None:
    """Küçük bir PowerShell betiği çalıştırır; yollar ortam değişkeniyle geçer (tırnak sorunu yok)."""
    env = {**os.environ, **env_extra}
    creation = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
             "-Command", script],
            env=env, capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=60, creationflags=creation)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise SetupError(f"Could not run PowerShell: {exc}") from exc
    if result.returncode != 0:
        raise SetupError(f"PowerShell step failed: {result.stderr.strip()[:300]}")


SHORTCUT_PS = r"""
$s = New-Object -ComObject WScript.Shell
$folder = $s.SpecialFolders($env:XVC_FOLDER)
$lnk = $s.CreateShortcut((Join-Path $folder 'Xyron Voice Changer.lnk'))
$lnk.TargetPath = $env:XVC_EXE
$lnk.WorkingDirectory = $env:XVC_DIR
$lnk.IconLocation = "$env:XVC_EXE,0"
$lnk.Description = 'Real-time voice changer'
$lnk.Save()
"""


def create_shortcut(target: Path, folder: str) -> None:
    run_powershell(SHORTCUT_PS, {"XVC_FOLDER": folder, "XVC_EXE": str(target / APP_EXE),
                                 "XVC_DIR": str(target)})


def folder_size_kb(path: Path) -> int:
    total = 0
    for f in path.rglob("*"):
        try:
            if f.is_file():
                total += f.stat().st_size
        except OSError:  # kilitli/kaybolan dosya boyut tahminini bozmasın
            continue
    return total // 1024


def register_uninstaller(target: Path) -> None:
    import winreg
    uninstall = (f'powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden '
                 f'-File "{target / "uninstall.ps1"}"')
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY) as key:
        values = {
            "DisplayName": APP_NAME, "DisplayVersion": VERSION, "Publisher": PUBLISHER,
            "DisplayIcon": f"{target / APP_EXE},0", "InstallLocation": str(target),
            "UninstallString": uninstall, "QuietUninstallString": uninstall + " /quiet",
            "URLInfoAbout": "https://xyronb1.github.io/xyron-voice-changer/",
        }
        for name, value in values.items():
            winreg.SetValueEx(key, name, 0, winreg.REG_SZ, value)
        winreg.SetValueEx(key, "NoModify", 0, winreg.REG_DWORD, 1)
        winreg.SetValueEx(key, "NoRepair", 0, winreg.REG_DWORD, 1)
        winreg.SetValueEx(key, "EstimatedSize", 0, winreg.REG_DWORD, folder_size_kb(target))


def launch(target: Path) -> None:
    subprocess.Popen([str(target / APP_EXE)], cwd=str(target), close_fds=True)


def perform_install(payload: Path, opts: Options, progress: Callable[[float, str], None]) -> None:
    if app_is_running():
        raise SetupError("Xyron Voice Changer is running. Close it and click Install again.")
    progress(0.02, "Preparing")
    install_files(payload, opts.target, progress)
    if opts.start_menu:
        progress(0.92, "Creating Start menu shortcut")
        create_shortcut(opts.target, "Programs")
    if opts.desktop_shortcut:
        progress(0.95, "Creating desktop shortcut")
        create_shortcut(opts.target, "Desktop")
    if opts.register:
        progress(0.98, "Registering in Windows")
        try:
            register_uninstaller(opts.target)
        except OSError as exc:
            raise SetupError(f"Could not add the uninstall entry: {exc}") from exc
    progress(1.0, "Done")
    if opts.launch:
        launch(opts.target)


# ------------------------------------------------------------------------- arayüz
def run_gui(payload: Path, target: Path) -> int:
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk

    bg, card, text, muted, accent = "#0d0e18", "#151726", "#eef0ff", "#a3a8c7", "#7c5cff"
    root = tk.Tk()
    root.title(f"{APP_NAME} {VERSION} Setup")
    root.configure(bg=bg)
    root.resizable(False, False)
    root.geometry("560x380")
    try:
        icon = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent)) / "icon.ico"
        root.iconbitmap(str(icon))
    except tk.TclError:
        pass

    style = ttk.Style(root)
    style.theme_use("clam")
    style.configure("X.Horizontal.TProgressbar", troughcolor=card, background=accent,
                    bordercolor=card, lightcolor=accent, darkcolor=accent)

    tk.Label(root, text="XYRON", font=("Segoe UI", 26, "bold"), fg=text, bg=bg).place(x=32, y=24)
    tk.Label(root, text="VOICE CHANGER  ·  SETUP", font=("Segoe UI Semibold", 10), fg="#9b82ff",
             bg=bg).place(x=35, y=72)
    tk.Label(root, text=f"Version {VERSION}. No administrator rights needed.\n"
             "The app is installed for your Windows account and starts fast every time.",
             font=("Segoe UI", 10), fg=muted, bg=bg, justify="left").place(x=32, y=104)

    target_var = tk.StringVar(value=str(target))
    tk.Label(root, text="Install to", font=("Segoe UI Semibold", 10), fg=text, bg=bg).place(x=32, y=160)
    tk.Entry(root, textvariable=target_var, font=("Segoe UI", 10), bg=card, fg=text,
             insertbackground=text, relief="flat", width=52).place(x=32, y=184, height=28)

    def browse() -> None:
        chosen = filedialog.askdirectory(initialdir=target_var.get(), title="Choose a folder")
        if chosen:
            target_var.set(str(Path(chosen) / APP_NAME))

    tk.Button(root, text="Change…", command=browse, font=("Segoe UI", 9), bg=card, fg=text,
              activebackground="#202442", activeforeground=text, relief="flat").place(x=462, y=184, height=28, width=66)

    desktop_var, launch_var = tk.BooleanVar(value=True), tk.BooleanVar(value=True)
    for i, (label, var) in enumerate((("Create a desktop shortcut", desktop_var),
                                      ("Launch Xyron Voice Changer when setup finishes", launch_var))):
        tk.Checkbutton(root, text=label, variable=var, font=("Segoe UI", 10), fg=text, bg=bg,
                       selectcolor=card, activebackground=bg, activeforeground=text).place(x=28, y=224 + i * 26)

    bar = ttk.Progressbar(root, style="X.Horizontal.TProgressbar", length=496, maximum=1.0)
    bar.place(x=32, y=290)
    status = tk.Label(root, text="Ready to install.", font=("Segoe UI", 9), fg=muted, bg=bg, anchor="w")
    status.place(x=32, y=304, width=496)
    result: dict[str, object] = {}

    def set_progress(value: float, message: str) -> None:
        root.after(0, lambda: (bar.configure(value=value), status.configure(text=message)))

    def worker(opts: Options) -> None:
        try:
            perform_install(payload, opts, set_progress)
            result["ok"] = True
        except SetupError as exc:
            result["error"] = str(exc)
        except Exception as exc:  # beklenmeyen hata: sihirbaz çökmesin, mesaj göstersin
            result["error"] = f"{type(exc).__name__}: {exc}"
        root.after(0, finish)

    def finish() -> None:
        if result.get("ok"):
            status.configure(text="Installed successfully.")
            install_btn.configure(text="Close", state="normal", command=root.destroy)
            messagebox.showinfo(APP_NAME, "Xyron Voice Changer is installed.\n\n"
                                "You can start it from the Start menu any time.")
        else:
            status.configure(text="Setup did not finish.")
            install_btn.configure(state="normal", text="Install")
            messagebox.showerror(APP_NAME, str(result.get("error")))
        result.clear()

    def start() -> None:
        path = Path(target_var.get().strip())
        if not path.is_absolute():
            messagebox.showerror(APP_NAME, "Please choose a full folder path, for example C:\\Apps.")
            return
        install_btn.configure(state="disabled", text="Installing…")
        opts = Options(target=path, desktop_shortcut=desktop_var.get(), launch=launch_var.get())
        threading.Thread(target=worker, args=(opts,), daemon=True).start()

    install_btn = tk.Button(root, text="Install", command=start, font=("Segoe UI Semibold", 11),
                            bg=accent, fg="white", activebackground="#8a6dff", activeforeground="white",
                            relief="flat")
    install_btn.place(x=408, y=330, width=120, height=34)
    tk.Button(root, text="Cancel", command=root.destroy, font=("Segoe UI", 10), bg=card, fg=text,
              activebackground="#202442", activeforeground=text, relief="flat").place(x=318, y=330, width=80, height=34)
    root.mainloop()
    return EXIT_OK


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="xyron-setup", description=f"{APP_NAME} {VERSION} setup")
    parser.add_argument("--silent", action="store_true", help="Install without any window")
    parser.add_argument("--target", type=Path, default=None, help="Installation folder")
    parser.add_argument("--payload", type=Path, default=None, help="Application zip (for testing)")
    parser.add_argument("--no-shortcuts", action="store_true", help="Do not create shortcuts")
    parser.add_argument("--no-register", action="store_true", help="Do not add an uninstall entry")
    parser.add_argument("--launch", action="store_true", help="Start the app after a silent install")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    payload = args.payload or bundled_payload()
    target = args.target or default_target()
    if not args.silent:
        return run_gui(payload, target)
    opts = Options(target=target, desktop_shortcut=not args.no_shortcuts,
                   start_menu=not args.no_shortcuts, register=not args.no_register,
                   launch=args.launch)
    try:
        perform_install(payload, opts, lambda _v, _m: None)
    except SetupError as exc:
        if sys.stderr:
            print(f"Setup failed: {exc}", file=sys.stderr)
        return EXIT_ERROR
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())

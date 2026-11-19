"""Bütün sürüm dosyalarını üretir: kurulum sihirbazı, tek dosya EXE, taşınabilir zip, SHA256SUMS.

Kullanım (proje kökünden):
  .venv\\Scripts\\python.exe tools\\build_release.py            hepsini derle
  .venv\\Scripts\\python.exe tools\\build_release.py --skip-onefile
Çıktı: release\\
"""

from __future__ import annotations

import argparse
import hashlib
import shutil
import subprocess
import sys
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RELEASE = ROOT / "release"
APP = "Xyron Voice Changer"


def run_pyinstaller(spec: Path, distpath: Path, workpath: Path) -> None:
    cmd = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
           "--distpath", str(distpath), "--workpath", str(workpath), spec.name]
    print(f"> PyInstaller {spec.name}", flush=True)
    started = time.monotonic()
    result = subprocess.run(cmd, cwd=spec.parent, capture_output=True, text=True,
                            encoding="utf-8", errors="replace", timeout=1200)
    if result.returncode != 0:
        print(result.stdout[-3000:], result.stderr[-3000:], sep="\n", file=sys.stderr)
        raise SystemExit(f"PyInstaller failed for {spec.name} (exit {result.returncode})")
    print(f"  ok in {time.monotonic() - started:.0f} s", flush=True)


def zip_folder(folder: Path, dest: Path, *, with_root: bool) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for f in sorted(folder.rglob("*")):
            if f.is_file():
                rel = f.relative_to(folder.parent if with_root else folder)
                zf.write(f, rel.as_posix())


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--skip-onefile", action="store_true", help="Do not build the single-file EXE")
    parser.add_argument("--vbcable", type=Path, default=None,
                        help="Unmodified VB-CABLE pack zip to copy into release/ (optional)")
    args = parser.parse_args(argv)
    if args.vbcable and not args.vbcable.is_file():  # derlemeye başlamadan önce yakala
        print(f"VB-CABLE pack not found: {args.vbcable}", file=sys.stderr)
        return 2

    build = ROOT / "build"
    RELEASE.mkdir(exist_ok=True)

    onedir_dist = ROOT / "dist_onedir"
    run_pyinstaller(ROOT / "Xyron_Voice_Changer_onedir.spec", onedir_dist, build / "onedir")
    app_dir = onedir_dist / APP
    if not (app_dir / f"{APP}.exe").is_file():
        raise SystemExit(f"Folder build is missing {APP}.exe")

    zip_folder(app_dir, RELEASE / "Xyron-Voice-Changer-win64-portable.zip", with_root=True)
    payload = ROOT / "installer" / "build" / "payload.zip"
    zip_folder(app_dir, payload, with_root=False)
    run_pyinstaller(ROOT / "installer" / "xyron_setup.spec", ROOT / "installer" / "dist",
                    ROOT / "installer" / "build" / "work")
    shutil.copy2(ROOT / "installer" / "dist" / "Xyron-Voice-Changer-Setup.exe",
                 RELEASE / "Xyron-Voice-Changer-Setup.exe")

    if not args.skip_onefile:
        run_pyinstaller(ROOT / "Xyron_Voice_Changer.spec", ROOT / "dist", build / "onefile")
        shutil.copy2(ROOT / "dist" / f"{APP}.exe", RELEASE / "Xyron-Voice-Changer-win64.exe")

    if args.vbcable:
        shutil.copy2(args.vbcable, RELEASE / "VBCABLE_Driver_Pack.zip")

    assets = sorted(p for p in RELEASE.iterdir() if p.is_file() and p.name != "SHA256SUMS.txt")
    lines = [f"{sha256(p)}  {p.name}" for p in assets]
    (RELEASE / "SHA256SUMS.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    for p in assets:
        print(f"  {p.name:<42} {p.stat().st_size / 1e6:6.1f} MB")
    return 0


if __name__ == "__main__":
    sys.exit(main())

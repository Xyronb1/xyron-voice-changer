"""Kurulum sihirbazının dosya işlemleri (kısayol ve kayıt defteri adımları hariç)."""

import sys
import zipfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "installer"))
import xyron_setup as setup  # noqa: E402

from xyrox_voice import __version__  # noqa: E402


def make_payload(path: Path, files: dict[str, str]) -> Path:
    with zipfile.ZipFile(path, "w") as zf:
        for name, content in files.items():
            zf.writestr(name, content)
    return path


@pytest.fixture
def payload(tmp_path):
    return make_payload(tmp_path / "app.zip", {setup.APP_EXE: "exe-v2", "_internal/lib.dll": "dll"})


def silent(payload: Path, target: Path) -> int:
    return setup.main(["--silent", "--payload", str(payload), "--target", str(target),
                       "--no-shortcuts", "--no-register"])


def test_installer_version_matches_app():
    assert setup.VERSION == __version__


def test_fresh_install(payload, tmp_path):
    target = tmp_path / "Programs" / setup.APP_NAME
    assert silent(payload, target) == 0
    assert (target / setup.APP_EXE).read_text() == "exe-v2"
    assert (target / "_internal" / "lib.dll").is_file()
    assert "Remove-Item" in (target / "uninstall.ps1").read_text(encoding="utf-8-sig")
    assert not target.with_name(target.name + ".new").exists()


def test_upgrade_replaces_old_files(payload, tmp_path):
    target = tmp_path / setup.APP_NAME
    target.mkdir()
    (target / setup.APP_EXE).write_text("exe-v1")
    (target / "stale.dll").write_text("old")
    assert silent(payload, target) == 0
    assert (target / setup.APP_EXE).read_text() == "exe-v2"
    assert not (target / "stale.dll").exists()
    assert not target.with_name(target.name + ".old").exists()


def test_refuses_unrelated_non_empty_folder(payload, tmp_path):
    target = tmp_path / "Documents"
    target.mkdir()
    (target / "thesis.docx").write_text("important")
    assert silent(payload, target) == 1
    assert (target / "thesis.docx").read_text() == "important"
    assert not (target / setup.APP_EXE).exists()


def test_failed_copy_keeps_previous_version(payload, tmp_path, monkeypatch):
    target = tmp_path / setup.APP_NAME
    target.mkdir()
    (target / setup.APP_EXE).write_text("exe-v1")

    def broken_extract(self, member, path=None, pwd=None):
        raise OSError("disk full")

    monkeypatch.setattr(zipfile.ZipFile, "extract", broken_extract)
    assert silent(payload, target) == 1
    assert (target / setup.APP_EXE).read_text() == "exe-v1"
    assert not target.with_name(target.name + ".new").exists()


def test_half_finished_previous_setup_does_not_block(payload, tmp_path):
    target = tmp_path / setup.APP_NAME
    staging = target.with_name(target.name + ".new")
    (staging / "_internal").mkdir(parents=True)
    (staging / setup.STAGING_MARKER).write_text("x")
    (staging / "_internal" / "partial.dll").write_text("half")
    assert silent(payload, target) == 0
    assert (target / setup.APP_EXE).is_file()
    assert not staging.exists()
    assert not (target / setup.STAGING_MARKER).exists()


@pytest.mark.parametrize("bad_name", ["../evil.exe", "/abs.exe", "C:/evil.exe"])
def test_rejects_unsafe_paths(tmp_path, bad_name):
    zp = make_payload(tmp_path / "bad.zip", {setup.APP_EXE: "x", bad_name: "y"})
    with pytest.raises(setup.SetupError):
        setup.validate_payload(zp)


def test_rejects_payload_without_app(tmp_path):
    zp = make_payload(tmp_path / "empty.zip", {"readme.txt": "x"})
    with pytest.raises(setup.SetupError):
        setup.validate_payload(zp)


def test_rejects_damaged_payload(tmp_path):
    bad = tmp_path / "broken.zip"
    bad.write_bytes(b"not a zip")
    with pytest.raises(setup.SetupError):
        setup.validate_payload(bad)


def test_refuses_drive_root(payload, tmp_path):
    with pytest.raises(setup.SetupError):
        setup.check_target_is_safe(Path(tmp_path.anchor))

"""İngilizce destek: sistem dili algılama, CLI çevirisi, ayar klasörü taşıma."""

import ast
import json
import re
from pathlib import Path

import pytest

import main
from xyrox_voice import APP_NAME, i18n
from xyrox_voice.config import DATA_DIR_NAME, LEGACY_DATA_DIR_NAME, app_data_dir

TURKISH_CHARS = re.compile(r"[çğıöşüÇĞİÖŞÜ]")


@pytest.fixture(autouse=True)
def restore_language():
    yield
    i18n.set_language("tr")


def test_app_name():
    assert APP_NAME == "Xyron Voice Changer"


def test_en_dictionary_has_no_duplicate_keys():
    tree = ast.parse(Path(i18n.__file__).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.AnnAssign) and getattr(node.target, "id", "") == "EN":
            keys = [k.value for k in node.value.keys]
            dupes = {k for k in keys if keys.count(k) > 1}
            assert not dupes, f"Tekrarlanan anahtarlar: {dupes}"
            return
    pytest.fail("EN sözlüğü bulunamadı")


def test_english_translations_contain_no_turkish_letters():
    bad = {k: v for k, v in i18n.EN.items() if TURKISH_CHARS.search(v)}
    assert not bad


def test_resolve_language_prefers_saved_value():
    assert i18n.resolve_language("en") == "en"
    assert i18n.resolve_language("tr") == "tr"
    assert i18n.resolve_language("") in i18n.LANGUAGES
    assert i18n.resolve_language("xx") == i18n.detect_system_language()


@pytest.mark.parametrize(("lang_env", "expected"), [
    ("tr_TR.UTF-8", "tr"), ("Turkish_Turkey", "tr"), ("de_DE.UTF-8", "en"), ("en_US", "en"),
])
def test_detect_system_language_from_env(monkeypatch, lang_env, expected):
    monkeypatch.setattr(i18n.sys, "platform", "linux")
    monkeypatch.delenv("LC_ALL", raising=False)
    monkeypatch.delenv("LC_MESSAGES", raising=False)
    monkeypatch.setenv("LANG", lang_env)
    assert i18n.detect_system_language() == expected


def test_detect_system_language_returns_supported_code():
    assert i18n.detect_system_language() in i18n.LANGUAGES


def test_cli_help_in_english(capsys):
    with pytest.raises(SystemExit) as exc:
        main.main(["--lang", "en", "--help"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "List the built-in and saved voice presets" in out
    assert "INPUT OUTPUT" in out
    assert not TURKISH_CHARS.search(out)


def test_cli_help_in_turkish(capsys):
    with pytest.raises(SystemExit):
        main.main(["--lang", "tr", "--help"])
    assert "Hazır profilleri listele" in capsys.readouterr().out


def test_cli_list_presets_in_english(capsys):
    assert main.main(["--lang", "en", "--list-presets"]) == 0
    out = capsys.readouterr().out
    assert "Natural Female" in out and "Female" in out
    assert not TURKISH_CHARS.search(out)


def test_cli_uses_saved_language(isolated_appdata, capsys):
    folder = isolated_appdata / DATA_DIR_NAME
    folder.mkdir()
    (folder / "settings.json").write_text(json.dumps({"language": "en"}), encoding="utf-8")
    assert main.main(["--list-presets"]) == 0
    assert "Studio Male" in capsys.readouterr().out


def test_cli_errors_in_english(tmp_path, capsys):
    assert main.main(["--lang", "en", "--render", str(tmp_path / "x.wav"),
                      str(tmp_path / "o.wav")]) == 2
    assert "Input file not found" in capsys.readouterr().err


def test_cli_version(capsys):
    with pytest.raises(SystemExit):
        main.main(["--version"])
    assert APP_NAME in capsys.readouterr().out


def test_app_data_dir_migrates_legacy_folder(isolated_appdata):
    legacy = isolated_appdata / LEGACY_DATA_DIR_NAME
    legacy.mkdir()
    (legacy / "presets.json").write_text('{"version": 1, "presets": []}', encoding="utf-8")
    folder = app_data_dir()
    assert folder.name == DATA_DIR_NAME
    assert (folder / "presets.json").is_file()
    assert (legacy / "presets.json").is_file()  # eski klasör silinmez


def test_app_data_dir_failed_migration_leaves_no_partial_folder(isolated_appdata, monkeypatch):
    from xyrox_voice import config
    legacy = isolated_appdata / LEGACY_DATA_DIR_NAME
    legacy.mkdir()

    def broken_copy(src, dst):
        Path(dst).mkdir()
        raise OSError("disk full")

    monkeypatch.setattr(config.shutil, "copytree", broken_copy)
    assert app_data_dir() == legacy
    assert sorted(p.name for p in isolated_appdata.iterdir()) == [LEGACY_DATA_DIR_NAME]


def test_cli_invalid_lang_reports_usage_error(capsys):
    with pytest.raises(SystemExit) as exc:
        main.main(["--lang", "de", "--list-presets"])
    assert exc.value.code == 2
    assert "xyron-voice" in capsys.readouterr().err


def test_app_data_dir_fresh_install(isolated_appdata):
    folder = app_data_dir()
    assert folder == isolated_appdata / DATA_DIR_NAME
    assert not folder.exists()  # klasörü kaydederken oluşturulur

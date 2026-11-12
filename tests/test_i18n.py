import ast
import string
from pathlib import Path

import pytest

from xyrox_voice import i18n, ui
from xyrox_voice.params import PARAM_SPECS, format_param
from xyrox_voice.presets import BUILTIN_PRESETS, CATEGORIES
from xyrox_voice.processor import QUALITY_MODES

UI_SOURCE = Path(ui.__file__)


@pytest.fixture(autouse=True)
def restore_language():
    yield
    i18n.set_language("tr")


def literal_ui_strings() -> set[str]:
    """ui.py içinde _("...") ile sarılmış tüm sabit metinler."""
    tree = ast.parse(UI_SOURCE.read_text(encoding="utf-8"))
    found = set()
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "_"
                and node.args and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)):
            found.add(node.args[0].value)
    return found


def dynamic_strings() -> set[str]:
    """Değişken üzerinden çevrilen metinler (AST ile görülemez)."""
    texts = {ui.ALL_CATEGORY, *CATEGORIES, *ui.HOTKEY_NAMES.values(), *ui.HEALTH_LABELS.values()}
    texts |= {title for title, _names, _opened in ui.SECTIONS}
    texts |= {label for label, _n, _h in QUALITY_MODES.values()}
    texts |= {spec[3] for spec in PARAM_SPECS.values()}
    for preset in BUILTIN_PRESETS.values():
        texts |= {preset.name, preset.desc}
    return texts


def fields(text: str) -> set[str]:
    return {name for _lit, name, _spec, _conv in string.Formatter().parse(text) if name}


def test_ui_has_many_translatable_strings():
    assert len(literal_ui_strings()) > 60


def test_every_string_has_english_translation():
    missing = sorted((literal_ui_strings() | dynamic_strings()) - set(i18n.EN))
    assert not missing, f"İngilizce çevirisi eksik: {missing}"


def test_placeholders_match_in_translations():
    for source, translated in i18n.EN.items():
        assert fields(source) == fields(translated), source


def test_no_empty_translations():
    assert all(value.strip() for value in i18n.EN.values())


def test_tr_switches_language_and_falls_back():
    assert i18n.tr("BAŞLAT") == "BAŞLAT"
    assert i18n.set_language("en") == "en"
    assert i18n.tr("BAŞLAT") == "START"
    assert i18n.tr("çevirisi olmayan metin") == "çevirisi olmayan metin"
    assert i18n.set_language("xx") == "tr"
    assert i18n.get_language() == "tr"


def test_format_param_follows_language():
    assert format_param("bitcrush", 0) == "Kapalı"
    i18n.set_language("en")
    assert format_param("bitcrush", 0) == "Off"
    assert format_param("gate_db", -90) == "Off"
    assert format_param("pitch", 3) == "+3.0 st"


def test_sections_cover_every_parameter_once():
    in_sections = [name for _t, names, _o in ui.SECTIONS for name in names]
    assert sorted(in_sections + ["pitch", "formant"]) == sorted(PARAM_SPECS)

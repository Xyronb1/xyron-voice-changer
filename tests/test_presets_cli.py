import json
import wave

import numpy as np
import pytest

import main
from conftest import harmonic_voice
from xyrox_voice.config import AppConfig
from xyrox_voice.params import PARAM_SPECS, VoiceParams
from xyrox_voice.presets import BUILTIN_PRESETS, CATEGORIES, PresetStore, slugify


def test_builtin_presets_are_valid():
    assert len(BUILTIN_PRESETS) >= 30
    for p in BUILTIN_PRESETS.values():
        assert p.category in CATEGORIES
        for name, (lo, hi, *_rest) in PARAM_SPECS.items():
            assert lo <= getattr(p.params, name) <= hi, (p.key, name)
    cats = {p.category for p in BUILTIN_PRESETS.values()}
    assert {"Kadın", "Erkek", "Karakter", "Efekt"} <= cats


def test_female_presets_change_voice_not_just_pitch():
    """Kadın sesleri: kadın perdesi + formant + temel ton birlikte (sadece inceltme değil)."""
    for key in ("f_natural", "f_young", "f_mature", "f_velvet", "f_announcer"):
        p = BUILTIN_PRESETS[key].params
        assert p.pitch >= 8.0, key
        assert p.formant >= 2.5, key
        assert p.h1 >= 4.0, key
        assert p.bass >= 0.0, key  # alt gövdeyi kesmek sesi cılızlaştırıyordu


def test_static_deep_voice_combines_static_and_deepening():
    p = BUILTIN_PRESETS["c_static_deep"].params
    assert p.pitch < 0 and p.formant < 0
    assert p.bitcrush >= 1 and p.drive > 0
    assert BUILTIN_PRESETS["c_static_deep"].category == "Karakter"


def test_params_from_dict_clamps_and_ignores_garbage():
    p = VoiceParams.from_dict({"pitch": 99, "formant": "abc", "bilinmeyen": 1, "reverb": -5})
    assert p.pitch == 12.0
    assert p.formant == 0.0
    assert p.reverb == 0.0


def test_slugify_handles_turkish():
    assert slugify("Şeytan Çığlığı") == "seytan_cigligi"
    assert slugify("!!!") == "profil"


def test_preset_store_roundtrip(tmp_path):
    path = tmp_path / "presets.json"
    store = PresetStore(path)
    preset = store.add("Benim Sesim", VoiceParams(pitch=3.5))
    assert preset.key == "u_benim_sesim"
    again = PresetStore(path)
    assert again.get("u_benim_sesim").params.pitch == 3.5
    assert again.delete("u_benim_sesim")
    assert PresetStore(path).get("u_benim_sesim") is None


def test_preset_store_survives_corrupt_file(tmp_path):
    path = tmp_path / "presets.json"
    path.write_text("{bozuk json", encoding="utf-8")
    store = PresetStore(path)
    assert store.load_error
    assert store.get("f_natural") is not None


def test_config_roundtrip_and_corrupt(tmp_path):
    path = tmp_path / "settings.json"
    cfg = AppConfig(mic="Mikrofon (USB)", monitor_on=True, params={"pitch": 2.0})
    cfg.save(path)
    loaded = AppConfig.load(path)
    assert loaded.mic == "Mikrofon (USB)" and loaded.monitor_on and loaded.params["pitch"] == 2.0
    path.write_text("[1,2,3]", encoding="utf-8")
    assert AppConfig.load(path) == AppConfig()


def test_cli_list_presets(capsys):
    assert main.main(["--list-presets"]) == 0
    assert "f_natural" in capsys.readouterr().out


def test_cli_render_errors(tmp_path, capsys):
    assert main.main(["--render", str(tmp_path / "yok.wav"), str(tmp_path / "o.wav")]) == 2
    src = tmp_path / "in.wav"
    _write_wav(src, harmonic_voice(120.0, 0.5))
    assert main.main(["--render", str(src), str(tmp_path / "o.wav"), "--preset", "yok"]) == 2


def test_cli_render_roundtrip(tmp_path):
    src, dst = tmp_path / "in.wav", tmp_path / "out.wav"
    _write_wav(src, harmonic_voice(120.0, 0.8))
    assert main.main(["--render", str(src), str(dst), "--preset", "f_natural"]) == 0
    with wave.open(str(dst)) as w:
        assert w.getframerate() == 48000
        assert w.getnframes() >= int(0.8 * 48000)


def _write_wav(path, audio):
    data = (np.clip(audio, -1, 1) * 32767).astype("<i2").tobytes()
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(48000)
        w.writeframes(data)


def test_json_presets_file_format(tmp_path):
    store = PresetStore(tmp_path / "p.json")
    store.add("Deneme", VoiceParams())
    raw = json.loads((tmp_path / "p.json").read_text(encoding="utf-8"))
    assert raw["version"] == 1 and raw["presets"][0]["name"] == "Deneme"

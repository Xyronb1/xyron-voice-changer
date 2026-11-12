import numpy as np
import pytest

from conftest import SR, run_blocks
from xyrox_voice.effects import OUTPUT_CEILING_DB, EffectChain, PeakLimiter
from xyrox_voice.params import VoiceParams
from xyrox_voice.presets import BUILTIN_PRESETS
from xyrox_voice.processor import CEILING_MAX, VoiceProcessor, soft_ceiling


@pytest.mark.parametrize("block", [1, 37, 480, 2048])
def test_limiter_never_exceeds_ceiling(block):
    rng = np.random.default_rng(block)
    x = (rng.normal(0, 0.6, SR) * np.repeat(rng.uniform(0.1, 4, SR // 480 + 1), 480)[:SR])
    lim = PeakLimiter(SR)
    y = run_blocks(lim.process, x.astype(np.float32), block)
    assert np.max(np.abs(y)) <= 10 ** (OUTPUT_CEILING_DB / 20) + 1e-6


def test_limiter_is_transparent_below_ceiling():
    x = (0.3 * np.sin(2 * np.pi * 440 * np.arange(SR) / SR)).astype(np.float32)
    lim = PeakLimiter(SR)
    y = run_blocks(lim.process, x)
    d = lim.latency_samples
    np.testing.assert_allclose(y[d:], x[:-d], atol=1e-6)


def test_soft_ceiling_bounds_and_passthrough():
    x = np.array([0.0, 0.5, -0.89, 1.5, -40.0], dtype=np.float32)
    y = soft_ceiling(x)
    assert np.max(np.abs(y)) <= CEILING_MAX
    np.testing.assert_allclose(y[:3], x[:3])


def test_chain_updates_in_place_when_structure_same():
    chain = EffectChain(SR)
    p = VoiceParams(reverb=0.3)
    chain.update(p)
    board_before = chain._board
    chain.update(p.with_value("reverb", 0.6))
    assert chain._board is board_before
    chain.update(p.with_value("drive", 10.0))
    assert chain._board is not board_before


@pytest.mark.parametrize("key", list(BUILTIN_PRESETS))
def test_every_preset_processes_cleanly(key, voice120):
    proc = VoiceProcessor(SR)
    proc.set_params(BUILTIN_PRESETS[key].params)
    y = run_blocks(proc.process, voice120)
    assert np.all(np.isfinite(y))
    assert np.max(np.abs(y)) <= 10 ** (OUTPUT_CEILING_DB / 20) + 1e-6
    assert np.sqrt(np.mean(y[SR // 2:] ** 2)) > 1e-3  # sessizleşmemeli


def test_bypass_and_mute_have_no_clicks(voice120):
    proc = VoiceProcessor(SR)
    proc.set_params(VoiceParams(pitch=7.0))
    out = []
    for i in range(0, voice120.size, 480):
        if i == 480 * 40:
            proc.bypass = True
        if i == 480 * 80:
            proc.muted = True
        out.append(proc.process(voice120[i:i + 480]))
    y = np.concatenate(out)
    jumps = np.abs(np.diff(y))
    assert jumps.max() < 0.25
    assert np.max(np.abs(y[480 * 81:])) == 0.0


def test_quality_switch_changes_latency():
    proc = VoiceProcessor(SR, "studio")
    assert proc.latency_ms == pytest.approx(2048 / SR * 1000)
    proc.set_quality("low_latency")
    assert proc.latency_ms == pytest.approx(1024 / SR * 1000)
    proc.set_quality("bilinmeyen")
    assert proc.quality == "low_latency"
    proc.set_quality("max")
    assert proc.latency_ms == pytest.approx(4096 / SR * 1000)

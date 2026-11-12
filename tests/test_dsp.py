import numpy as np
import pytest

from conftest import SR, estimate_f0, harmonic_voice, run_blocks
from xyrox_voice.dsp import EngineParams, VoiceEngine, cepstral_log_envelope


@pytest.mark.parametrize("n_fft,hop", [(4096, 512), (2048, 256), (2048, 512), (1024, 256)])
def test_neutral_settings_pass_audio_unchanged(voice120, n_fft, hop):
    eng = VoiceEngine(SR, n_fft=n_fft, hop=hop)
    y = run_blocks(eng.process, voice120)
    lat = eng.latency_samples
    assert y.size == voice120.size
    np.testing.assert_allclose(y[lat + 4096:], voice120[4096:voice120.size - lat], atol=1e-5)


@pytest.mark.parametrize("semitones", [-7.0, -3.0, 4.0, 7.0, 12.0])
def test_pitch_shift_hits_target_frequency(voice120, semitones):
    eng = VoiceEngine(SR)
    eng.set_params(EngineParams(pitch=semitones))
    y = run_blocks(eng.process, voice120)
    expected = 120.0 * 2 ** (semitones / 12)
    assert estimate_f0(y) == pytest.approx(expected, rel=0.02)


def test_formant_shift_moves_envelope_without_changing_pitch(voice120):
    """Formant +4 st: perde aynı kalmalı, zarf tepesi (700 Hz) yukarı kaymalı."""
    eng = VoiceEngine(SR)
    eng.set_params(EngineParams(formant=4.0))
    y = run_blocks(eng.process, voice120)
    assert estimate_f0(y) == pytest.approx(120.0, rel=0.02)

    def envelope_peak(sig):
        frame = sig[SR // 2:SR // 2 + 2048] * np.hanning(2048)
        mag = np.abs(np.fft.rfft(frame))
        lifter = 0.5 + 0.5 * np.cos(np.pi * np.arange(73) / 73)
        env = cepstral_log_envelope(mag, 73, lifter)
        freqs = np.fft.rfftfreq(2048, 1 / SR)
        band = (freqs > 300) & (freqs < 3000)
        return freqs[band][np.argmax(env[band])]

    assert envelope_peak(y) > envelope_peak(voice120) * 1.12


def test_output_independent_of_block_size(voice120):
    p = EngineParams(pitch=5.0, formant=2.0)
    outs = []
    for block in (64, 480, 1000):
        eng = VoiceEngine(SR, seed=1)
        eng.set_params(p)
        outs.append(run_blocks(eng.process, voice120, block))
    np.testing.assert_allclose(outs[0], outs[1], atol=1e-6)
    np.testing.assert_allclose(outs[0], outs[2], atol=1e-6)


@pytest.mark.parametrize("signal", ["silence", "loud_noise", "dc"])
def test_extreme_inputs_produce_finite_output(signal):
    rng = np.random.default_rng(0)
    x = {"silence": np.zeros(SR, np.float32),
         "loud_noise": rng.uniform(-1, 1, SR).astype(np.float32),
         "dc": np.full(SR, 0.9, np.float32)}[signal]
    eng = VoiceEngine(SR, seed=0)
    eng.set_params(EngineParams(pitch=-8, formant=5, denoise=1.0, robot=0.5, whisper=0.5,
                                breath=1.0, vibrato=1.0, deess=1.0, layer_mix=1.0, h1=12.0))
    y = run_blocks(eng.process, x)
    assert np.all(np.isfinite(y))
    assert np.max(np.abs(y)) < 20.0


def test_robot_uses_fixed_pitch(voice120):
    eng = VoiceEngine(SR)
    eng.set_params(EngineParams(robot=1.0, robot_hz=150.0))
    y = run_blocks(eng.process, voice120)
    assert estimate_f0(y) == pytest.approx(150.0, rel=0.02)


def test_denoise_reduces_steady_noise():
    rng = np.random.default_rng(3)
    noise = rng.normal(0, 0.02, SR * 3).astype(np.float32)
    eng = VoiceEngine(SR)
    eng.set_params(EngineParams(denoise=0.8))
    y = run_blocks(eng.process, noise)
    tail_in = np.sqrt(np.mean(noise[-SR:] ** 2))
    tail_out = np.sqrt(np.mean(y[-SR:] ** 2))
    assert 20 * np.log10(tail_out / tail_in) < -12.0


def test_pitch_tracker_finds_fundamental(voice120):
    eng = VoiceEngine(SR)
    eng.set_params(EngineParams(pitch=5.0))
    run_blocks(eng.process, voice120)
    assert np.exp(eng._f0_log) == pytest.approx(120.0, rel=0.03)


def test_h1_boost_strengthens_fundamental_only(voice120):
    """Temel ton +9 dB: çıkışta temel harmonik güçlenir, üst harmonikler aynı kalır."""
    def harmonic_levels(h1):
        eng = VoiceEngine(SR)
        eng.set_params(EngineParams(pitch=7.0, h1=h1))
        y = run_blocks(eng.process, voice120)[SR // 2:SR // 2 + SR // 2]
        spec = np.abs(np.fft.rfft(y * np.hanning(y.size)))
        freqs = np.fft.rfftfreq(y.size, 1 / SR)
        f0 = 120.0 * 2 ** (7 / 12)
        return [spec[np.abs(freqs - f0 * k) < 8].max() for k in (1, 4)]

    base, boosted = harmonic_levels(0.0), harmonic_levels(9.0)
    assert 20 * np.log10(boosted[0] / base[0]) == pytest.approx(9.0, abs=2.0)
    assert abs(20 * np.log10(boosted[1] / base[1])) < 1.0


def test_formant_shift_is_smaller_at_low_frequencies():
    eng = VoiceEngine(SR)
    assert eng.formant_weight[0] == pytest.approx(0.7)
    assert eng.formant_weight[-1] == pytest.approx(1.0)
    assert np.all(np.diff(eng.formant_weight) >= 0)


def test_invalid_configuration_rejected():
    with pytest.raises(ValueError):
        VoiceEngine(SR, n_fft=1000)
    with pytest.raises(ValueError):
        VoiceEngine(SR, n_fft=2048, hop=1024)


def test_harmonic_voice_helper_sanity():
    assert estimate_f0(harmonic_voice(200.0)) == pytest.approx(200.0, rel=0.01)

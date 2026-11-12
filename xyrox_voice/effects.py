"""Pedalboard tabanlı son işlem zinciri (EQ, karakter efektleri, dinamik, limiter).

Zincirin yapısı (hangi efektlerin açık olduğu) değişmedikçe efektler yeniden
yaratılmaz, sadece değerleri güncellenir: slider sürüklerken yankı kuyruğu kesilmez.
"""

from __future__ import annotations

import threading
from typing import Callable

import numpy as np
from pedalboard import (Bitcrush, Chorus, Compressor, Delay, Distortion, Gain, HighpassFilter,
                        HighShelfFilter, LowpassFilter, LowShelfFilter, NoiseGate,
                        Pedalboard, PeakFilter, Phaser, Reverb)

from .params import VoiceParams

OUTPUT_CEILING_DB = -1.0
OUTPUT_BASE_DB = 4.0  # tepeleri lookahead limiter tuttuğu için güvenle eklenen taban kazanç


def _comp_settings(amount: float) -> tuple[float, float, float]:
    """Kompresör miktarından (eşik, oran, makeup) üretir."""
    threshold = -12.0 - 18.0 * amount
    ratio = 1.5 + 4.5 * amount
    makeup = -threshold * (1.0 - 1.0 / ratio) * 0.45
    return threshold, ratio, makeup


def _output_gain(p: VoiceParams) -> float:
    makeup = _comp_settings(p.comp)[2] if p.comp > 0.005 else 0.0
    return OUTPUT_BASE_DB + p.volume + makeup


Stage = tuple[str, Callable[[VoiceParams], bool], Callable[[VoiceParams], object],
              Callable[[object, VoiceParams], None]]


def _set(**attrs: Callable[[VoiceParams], float]) -> Callable[[object, VoiceParams], None]:
    def updater(plugin: object, p: VoiceParams) -> None:
        for name, fn in attrs.items():
            setattr(plugin, name, float(fn(p)))
    return updater


STAGES: list[Stage] = [
    ("gate", lambda p: p.gate_db > -89.5,
     lambda p: NoiseGate(threshold_db=p.gate_db, ratio=8.0, attack_ms=2.0, release_ms=180.0),
     _set(threshold_db=lambda p: p.gate_db)),
    ("hpf", lambda p: True,
     lambda p: HighpassFilter(cutoff_frequency_hz=p.hpf),
     _set(cutoff_frequency_hz=lambda p: p.hpf)),
    ("lpf", lambda p: p.lpf < 19900.0,
     lambda p: LowpassFilter(cutoff_frequency_hz=p.lpf),
     _set(cutoff_frequency_hz=lambda p: p.lpf)),
    ("bass", lambda p: abs(p.bass) > 0.05,
     lambda p: LowShelfFilter(cutoff_frequency_hz=160.0, gain_db=p.bass, q=0.7),
     _set(gain_db=lambda p: p.bass)),
    ("body", lambda p: abs(p.body) > 0.05,
     lambda p: PeakFilter(cutoff_frequency_hz=350.0, gain_db=p.body, q=0.9),
     _set(gain_db=lambda p: p.body)),
    ("presence", lambda p: abs(p.presence) > 0.05,
     lambda p: PeakFilter(cutoff_frequency_hz=3200.0, gain_db=p.presence, q=0.8),
     _set(gain_db=lambda p: p.presence)),
    ("air", lambda p: abs(p.air) > 0.05,
     lambda p: HighShelfFilter(cutoff_frequency_hz=9000.0, gain_db=p.air, q=0.7),
     _set(gain_db=lambda p: p.air)),
    ("drive", lambda p: p.drive > 0.05,
     lambda p: Distortion(drive_db=p.drive),
     _set(drive_db=lambda p: p.drive)),
    ("drive_trim", lambda p: p.drive > 0.05,
     lambda p: Gain(gain_db=-0.55 * p.drive),
     _set(gain_db=lambda p: -0.55 * p.drive)),
    ("bitcrush", lambda p: p.bitcrush >= 1.0,
     lambda p: Bitcrush(bit_depth=p.bitcrush),
     _set(bit_depth=lambda p: p.bitcrush)),
    ("chorus", lambda p: p.chorus > 0.005,
     lambda p: Chorus(rate_hz=1.1, depth=0.35, centre_delay_ms=8.0, feedback=0.1, mix=p.chorus),
     _set(mix=lambda p: p.chorus)),
    ("phaser", lambda p: p.phaser > 0.005,
     lambda p: Phaser(rate_hz=0.7, depth=0.6, centre_frequency_hz=1200.0, feedback=0.3,
                      mix=p.phaser),
     _set(mix=lambda p: p.phaser)),
    ("comp", lambda p: p.comp > 0.005,
     lambda p: Compressor(threshold_db=_comp_settings(p.comp)[0], ratio=_comp_settings(p.comp)[1],
                          attack_ms=4.0, release_ms=90.0),
     _set(threshold_db=lambda p: _comp_settings(p.comp)[0],
          ratio=lambda p: _comp_settings(p.comp)[1])),
    ("delay", lambda p: p.delay > 0.005,
     lambda p: Delay(delay_seconds=p.delay_time, feedback=p.delay_feedback, mix=0.6 * p.delay),
     _set(delay_seconds=lambda p: p.delay_time, feedback=lambda p: p.delay_feedback,
          mix=lambda p: 0.6 * p.delay)),
    ("reverb", lambda p: p.reverb > 0.005,
     lambda p: Reverb(room_size=p.room, damping=0.45, wet_level=0.5 * p.reverb,
                      dry_level=1.0 - 0.35 * p.reverb, width=1.0),
     _set(room_size=lambda p: p.room, wet_level=lambda p: 0.5 * p.reverb,
          dry_level=lambda p: 1.0 - 0.35 * p.reverb)),
    ("output", lambda p: True,
     lambda p: Gain(gain_db=_output_gain(p)),
     _set(gain_db=_output_gain)),
]


class PeakLimiter:
    """Lookahead tepe limiter'ı: çıkış örnekleri tavanı asla aşmaz (sert kırpma yok).

    Kazanç, tepeden `lookahead` örnek önce inmeye başlar (min filtresi + hareketli ortalama;
    ortalamadaki her terim tepe anının gereken kazancından küçük olduğu için aşım imkânsız),
    sonra ~release_ms içinde yumuşakça geri döner.
    """

    DECIMATE = 32

    def __init__(self, sample_rate: int, ceiling_db: float = OUTPUT_CEILING_DB,
                 lookahead: int = 64, release_ms: float = 80.0) -> None:
        self.ceiling = float(10.0 ** (ceiling_db / 20.0))
        self.lookahead = int(lookahead)
        self.release = 1.0 - np.exp(-self.DECIMATE / (sample_rate * release_ms / 1000.0))
        self.reset()

    def reset(self) -> None:
        self._req_hist = np.ones(2 * self.lookahead, dtype=np.float64)
        self._x_hist = np.zeros(self.lookahead, dtype=np.float32)
        self._state = 1.0
        self._remainder = np.zeros(0, dtype=np.float64)

    @property
    def latency_samples(self) -> int:
        return self.lookahead

    def process(self, x: np.ndarray) -> np.ndarray:
        x = np.asarray(x, dtype=np.float32).reshape(-1)
        n = x.size
        if n == 0:
            return x.copy()
        L = self.lookahead
        req = np.minimum(1.0, self.ceiling / np.maximum(np.abs(x), 1e-9))
        req_all = np.concatenate((self._req_hist, req))
        mins = np.lib.stride_tricks.sliding_window_view(req_all, L + 1).min(axis=1)
        csum = np.concatenate(([0.0], np.cumsum(mins)))
        g_fast = (csum[L + 1:L + 1 + n] - csum[1:1 + n]) / L
        g_fast = np.minimum(g_fast, 1.0)

        # Release: seyreltilmiş zarf üzerinde tek kutuplu geri dönüş (Python döngüsü küçük kalır).
        # `pending` = önceki bloktan gruba girmemiş (zaten çalınmış) örnekler + yeni örnekler.
        carried = self._remainder.size
        pending = np.concatenate((self._remainder, g_fast))
        n_dec = pending.size // self.DECIMATE
        start_state = self._state
        if n_dec:
            dec = pending[:n_dec * self.DECIMATE].reshape(n_dec, self.DECIMATE).min(axis=1)
            states = np.empty(n_dec + 1)
            states[0] = state = start_state
            for i, v in enumerate(dec):
                state = v if v < state else state + (v - state) * self.release
                states[i + 1] = state
            self._state = state
            # Grup içinde bir önceki durumdan yenisine doğrusal geçiş (basamak/zipper yok).
            frac = (np.arange(self.DECIMATE) + 1.0) / self.DECIMATE
            env = (states[:-1, None] + (states[1:] - states[:-1])[:, None] * frac).reshape(-1)
        else:
            env = np.zeros(0)
        tail = np.full(pending.size - env.size, self._state)
        g_slow = np.concatenate((env, tail))[carried:]
        self._remainder = pending[n_dec * self.DECIMATE:]
        gain = np.minimum(g_slow, g_fast)

        x_all = np.concatenate((self._x_hist, x))
        out = (x_all[:n] * gain).astype(np.float32)
        self._req_hist = req_all[-2 * L:]
        self._x_hist = x_all[-L:]
        return out


class EffectChain:
    """Thread-safe efekt zinciri: UI iş parçacığı günceller, ses iş parçacığı işler."""

    def __init__(self, sample_rate: int) -> None:
        self.sample_rate = int(sample_rate)
        self._lock = threading.Lock()
        self._signature: tuple[str, ...] = ()
        self._plugins: dict[str, object] = {}
        self._board = Pedalboard([])
        self.limiter = PeakLimiter(self.sample_rate)
        self.update(VoiceParams())

    @staticmethod
    def signature_for(p: VoiceParams) -> tuple[str, ...]:
        return tuple(name for name, enabled, _, _ in STAGES if enabled(p))

    def update(self, p: VoiceParams) -> None:
        signature = self.signature_for(p)
        with self._lock:
            if signature == self._signature:
                for name, _, _, updater in STAGES:
                    if name in self._plugins:
                        updater(self._plugins[name], p)
                return
            plugins: dict[str, object] = {}
            for name, enabled, factory, _ in STAGES:
                if enabled(p):
                    plugins[name] = factory(p)
            self._plugins = plugins
            self._board = Pedalboard(list(plugins.values()))
            self._signature = signature

    def process(self, mono: np.ndarray) -> np.ndarray:
        x = np.asarray(mono, dtype=np.float32).reshape(1, -1)
        with self._lock:
            y = self._board(x, self.sample_rate, reset=False)
            return self.limiter.process(np.asarray(y, dtype=np.float32).reshape(-1))

    def reset(self) -> None:
        with self._lock:
            self._board.reset()
            self.limiter.reset()

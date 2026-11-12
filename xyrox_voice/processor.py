"""Motor + efekt zinciri + ölçümler: tek bir blok işleyici."""

from __future__ import annotations

import threading
import time

import numpy as np

from .dsp import VoiceEngine
from .effects import EffectChain
from .params import VoiceParams

QUALITY_MODES: dict[str, tuple[str, int, int]] = {
    # anahtar: (etiket, n_fft, hop)
    "max": ("Maksimum Netlik", 4096, 512),
    "studio": ("Stüdyo Kalite", 2048, 256),
    "balanced": ("Dengeli", 2048, 512),
    "low_latency": ("Düşük Gecikme", 1024, 256),
}
DEFAULT_QUALITY = "studio"

CEILING_KNEE = 0.9
CEILING_MAX = 0.98


def soft_ceiling(x: np.ndarray) -> np.ndarray:
    """Diz noktasının üstünü tanh ile yumuşakça sıkıştırır; çıkış asla 0.98'i geçmez.

    Sert kırpmanın (clipping) yarattığı cızırtı yerine fark edilmeyen bir doygunluk verir.
    """
    out = np.asarray(x, dtype=np.float32).copy()
    mag = np.abs(out)
    over = mag > CEILING_KNEE
    if np.any(over):
        span = CEILING_MAX - CEILING_KNEE
        squashed = CEILING_KNEE + span * np.tanh((mag[over] - CEILING_KNEE) / span)
        out[over] = np.sign(out[over]) * squashed
    return out


class VoiceProcessor:
    """Ses iş parçacığından çağrılır; UI iş parçacığı parametreleri günceller."""

    def __init__(self, sample_rate: int = 48000, quality: str = DEFAULT_QUALITY) -> None:
        self.sample_rate = int(sample_rate)
        self._lock = threading.Lock()
        self.params = VoiceParams()
        self.quality = quality if quality in QUALITY_MODES else DEFAULT_QUALITY
        self.engine = self._make_engine(self.quality)
        self.chain = EffectChain(self.sample_rate)
        self.bypass = False
        self.muted = False
        self._wet = 1.0
        self._mute_gain = 1.0
        self.in_level = 0.0
        self.out_level = 0.0
        self.cpu_load = 0.0
        self.set_params(self.params)

    def _make_engine(self, quality: str) -> VoiceEngine:
        _, n_fft, hop = QUALITY_MODES[quality]
        return VoiceEngine(self.sample_rate, n_fft=n_fft, hop=hop)

    # ---------------------------------------------------------------- kontrol
    def set_params(self, params: VoiceParams) -> None:
        self.params = params
        self.engine.set_params(params.engine_params())
        self.chain.update(params)

    def set_quality(self, quality: str) -> None:
        if quality not in QUALITY_MODES or quality == self.quality:
            return
        engine = self._make_engine(quality)
        engine.set_params(self.params.engine_params())
        with self._lock:
            self.engine = engine
            self.quality = quality

    def learn_noise(self) -> None:
        """Gürültü profilini sıfırdan öğrenmeye başlat (birkaç saniye sessiz kal)."""
        with self._lock:
            self.engine.relearn_noise()

    def warmup(self) -> None:
        """İlk FFT/efekt çağrıları yavaştır; akış başlamadan bir tur çalıştırıp sıfırla."""
        noise = np.random.default_rng(0).normal(0, 0.01, 4096).astype(np.float32)
        for i in range(0, noise.size, 512):
            self.process(noise[i:i + 512])
        self.reset()
        self.in_level = self.out_level = 0.0

    def reset(self) -> None:
        with self._lock:
            self.engine.reset()
            self.chain.reset()
            self._wet = 0.0 if self.bypass else 1.0

    @property
    def latency_ms(self) -> float:
        return self.engine.latency_samples / self.sample_rate * 1000.0

    # ---------------------------------------------------------------- işleme
    def process(self, mono: np.ndarray) -> np.ndarray:
        start = time.perf_counter()
        dry = np.asarray(mono, dtype=np.float32).reshape(-1)
        with self._lock:
            wet = self.chain.process(self.engine.process(dry))
        # Bypass geçişi tek blok boyunca çapraz geçişle (tıkırtısız A/B).
        target = 0.0 if self.bypass else 1.0
        if self._wet == target:
            out = wet if target == 1.0 else dry.copy()
        else:
            ramp = np.linspace(self._wet, target, dry.size, dtype=np.float32)
            out = wet * ramp + dry * (1.0 - ramp)
            self._wet = target
        mute_target = 0.0 if self.muted else 1.0
        if self._mute_gain != mute_target:
            out = out * np.linspace(self._mute_gain, mute_target, out.size, dtype=np.float32)
            self._mute_gain = mute_target
        elif mute_target == 0.0:
            out = np.zeros_like(out)
        out = soft_ceiling(out)

        self.in_level = max(float(np.max(np.abs(dry))) if dry.size else 0.0, self.in_level * 0.85)
        self.out_level = max(float(np.max(np.abs(out))) if out.size else 0.0, self.out_level * 0.85)
        elapsed = time.perf_counter() - start
        budget = max(dry.size, 1) / self.sample_rate
        self.cpu_load = 0.9 * self.cpu_load + 0.1 * (elapsed / budget)
        return out

    def spectrum_bands(self, n_bands: int = 48) -> np.ndarray:
        """Son çıkış spektrumunu logaritmik bantlara (0..1) indirger; UI için."""
        spec = self.engine.last_spectrum
        if self.bypass or spec.size == 0:
            return np.zeros(n_bands, dtype=np.float32)
        freqs = np.arange(spec.size) * (self.sample_rate / self.engine.n_fft)
        edges = np.geomspace(60.0, min(16000.0, self.sample_rate / 2 - 1), n_bands + 1)
        idx = np.searchsorted(freqs, edges)
        bands = np.empty(n_bands, dtype=np.float32)
        for i in range(n_bands):
            lo, hi = idx[i], max(idx[i + 1], idx[i] + 1)
            bands[i] = float(spec[lo:hi].max()) if lo < spec.size else 0.0
        db = 20.0 * np.log10(bands / (self.engine.n_fft * 0.25) + 1e-9)
        return np.clip((db + 75.0) / 70.0, 0.0, 1.0)

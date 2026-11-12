"""Ses dosyasını offline işler (wav/flac/mp3 -> wav). Test ve 'dosyayı dönüştür' için."""

from __future__ import annotations

from pathlib import Path

import numpy as np
from pedalboard.io import AudioFile

from .params import VoiceParams
from .processor import VoiceProcessor

RENDER_RATE = 48000
BLOCK = 480


def load_mono(path: Path, sample_rate: int = RENDER_RATE) -> np.ndarray:
    with AudioFile(str(path)).resampled_to(sample_rate) as f:
        audio = f.read(f.frames)
    return audio.mean(axis=0).astype(np.float32) if audio.ndim == 2 else audio.astype(np.float32)


def process_array(audio: np.ndarray, params: VoiceParams, quality: str = "studio",
                  sample_rate: int = RENDER_RATE) -> np.ndarray:
    """Diziyi gerçek zamanlı yolla aynı işleyiciden geçirir; gecikmeyi telafi eder."""
    proc = VoiceProcessor(sample_rate, quality)
    proc.set_params(params)
    latency = proc.engine.latency_samples
    tail = int(sample_rate * (0.6 + 1.5 * params.reverb + 2.0 * params.delay))
    padded = np.concatenate((audio.astype(np.float32), np.zeros(latency + tail, np.float32)))
    out = np.empty_like(padded)
    for i in range(0, padded.size, BLOCK):
        out[i:i + BLOCK] = proc.process(padded[i:i + BLOCK])
    return out[latency:]


def render_file(src: Path, dst: Path, params: VoiceParams, quality: str = "studio") -> float:
    """Dosyayı işler ve 24-bit WAV yazar. Süreyi (sn) döndürür."""
    audio = load_mono(src)
    out = process_array(audio, params, quality)
    dst.parent.mkdir(parents=True, exist_ok=True)
    with AudioFile(str(dst), "w", RENDER_RATE, 1, bit_depth=24) as f:
        f.write(out.reshape(1, -1))
    return audio.size / RENDER_RATE

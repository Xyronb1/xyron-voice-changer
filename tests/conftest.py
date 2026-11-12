import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

SR = 48000


def harmonic_voice(f0: float, seconds: float = 1.5, sr: int = SR) -> np.ndarray:
    """Formant benzeri zarflı (700/1200 Hz) sentetik sesli harf."""
    t = np.arange(int(sr * seconds)) / sr
    sig = np.zeros_like(t)
    for h in range(1, 60):
        f = f0 * h
        if f > sr / 2 - 500:
            break
        amp = np.exp(-((f - 700) / 300) ** 2) + 0.6 * np.exp(-((f - 1200) / 400) ** 2) + 0.05
        sig += amp * np.sin(2 * np.pi * f * t)
    return (0.3 * sig / np.max(np.abs(sig))).astype(np.float32)


def estimate_f0(x: np.ndarray, sr: int = SR) -> float:
    x = x[sr // 2:sr // 2 + 8192].astype(np.float64)
    x = x - x.mean()
    ac = np.fft.irfft(np.abs(np.fft.rfft(x, 2 * x.size)) ** 2)[:x.size]
    lo, hi = sr // 600, sr // 50
    seg = ac[lo:hi]
    thr = 0.85 * seg.max()
    for i in range(1, seg.size - 1):
        if seg[i] >= thr and seg[i] >= seg[i - 1] and seg[i] >= seg[i + 1]:
            return sr / (lo + i)
    return sr / (lo + int(np.argmax(seg)))


def run_blocks(fn, x: np.ndarray, block: int = 480) -> np.ndarray:
    return np.concatenate([fn(x[i:i + block]) for i in range(0, x.size, block)])


@pytest.fixture
def voice120() -> np.ndarray:
    return harmonic_voice(120.0)


@pytest.fixture(autouse=True)
def isolated_appdata(tmp_path, monkeypatch):
    """Testler kullanıcının gerçek %APPDATA% ayarlarını okumasın ve değiştirmesin."""
    appdata = tmp_path / "appdata"
    appdata.mkdir()
    monkeypatch.setenv("APPDATA", str(appdata))
    return appdata

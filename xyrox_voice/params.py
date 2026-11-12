"""Tüm ses parametreleri: tek kaynak, sınırlar ve slider tanımları burada."""

from __future__ import annotations

from dataclasses import asdict, dataclass, fields, replace
from typing import Any

from .dsp import EngineParams
from .i18n import tr


@dataclass(frozen=True)
class VoiceParams:
    # --- Ses kimliği (spektral motor)
    pitch: float = 0.0
    formant: float = 0.0
    denoise: float = 0.35
    gate_db: float = -70.0
    robot: float = 0.0
    robot_hz: float = 110.0
    whisper: float = 0.0
    breath: float = 0.0
    vibrato: float = 0.0
    vibrato_rate: float = 5.5
    deess: float = 0.25
    layer_pitch: float = -12.0
    layer_mix: float = 0.0
    h1: float = 0.0
    # --- Ton / EQ
    hpf: float = 80.0
    lpf: float = 20000.0
    bass: float = 0.0
    body: float = 0.0
    presence: float = 0.0
    air: float = 0.0
    # --- Karakter efektleri
    drive: float = 0.0
    bitcrush: float = 0.0
    chorus: float = 0.0
    phaser: float = 0.0
    delay: float = 0.0
    delay_time: float = 0.25
    delay_feedback: float = 0.3
    reverb: float = 0.0
    room: float = 0.4
    # --- Dinamik / çıkış
    comp: float = 0.45
    volume: float = 0.0

    def engine_params(self) -> EngineParams:
        return EngineParams(
            pitch=self.pitch, formant=self.formant, denoise=self.denoise,
            robot=self.robot, robot_hz=self.robot_hz, whisper=self.whisper,
            breath=self.breath, vibrato=self.vibrato, vibrato_rate=self.vibrato_rate,
            deess=self.deess, layer_pitch=self.layer_pitch, layer_mix=self.layer_mix,
            h1=self.h1,
        )

    def to_dict(self) -> dict[str, float]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "VoiceParams":
        """Bilinmeyen anahtarları atar, değerleri sınırlara kırpar (bozuk JSON'a dayanıklı)."""
        base = cls()
        if not data:
            return base
        values: dict[str, float] = {}
        for f in fields(cls):
            if f.name not in data:
                continue
            try:
                values[f.name] = clamp_param(f.name, float(data[f.name]))
            except (TypeError, ValueError):
                continue
        return replace(base, **values)

    def with_value(self, name: str, value: float) -> "VoiceParams":
        return replace(self, **{name: clamp_param(name, float(value))})


# ad: (min, max, adım, etiket, birim)
PARAM_SPECS: dict[str, tuple[float, float, float, str, str]] = {
    "pitch": (-12.0, 12.0, 0.1, "Perde", "st"),
    "formant": (-12.0, 12.0, 0.1, "Formant (gırtlak tınısı)", "st"),
    "denoise": (0.0, 1.0, 0.01, "Gürültü Engelleme", "%"),
    "gate_db": (-90.0, -20.0, 1.0, "Sessizlik Kapısı", "dB"),
    "robot": (0.0, 1.0, 0.01, "Robot", "%"),
    "robot_hz": (50.0, 300.0, 1.0, "Robot Perdesi", "Hz"),
    "whisper": (0.0, 1.0, 0.01, "Fısıltı", "%"),
    "breath": (0.0, 1.0, 0.01, "Nefes / Hava", "%"),
    "vibrato": (0.0, 1.5, 0.01, "Vibrato", "st"),
    "vibrato_rate": (1.0, 12.0, 0.1, "Vibrato Hızı", "Hz"),
    "deess": (0.0, 1.0, 0.01, "De-esser (sert S)", "%"),
    "layer_pitch": (-24.0, 24.0, 1.0, "Katman Perdesi", "st"),
    "layer_mix": (0.0, 1.0, 0.01, "Katman (harmonizer)", "%"),
    "h1": (0.0, 12.0, 0.1, "Temel Ton (yumuşaklık)", "dB"),
    "hpf": (20.0, 1000.0, 1.0, "Alçak Kesici", "Hz"),
    "lpf": (1000.0, 20000.0, 10.0, "Tiz Kesici", "Hz"),
    "bass": (-12.0, 12.0, 0.1, "Bas", "dB"),
    "body": (-12.0, 12.0, 0.1, "Gövde", "dB"),
    "presence": (-12.0, 12.0, 0.1, "Netlik", "dB"),
    "air": (-12.0, 12.0, 0.1, "Parlaklık", "dB"),
    "drive": (0.0, 30.0, 0.1, "Distorsiyon", "dB"),
    "bitcrush": (0.0, 16.0, 1.0, "Bitcrush (0=kapalı)", "bit"),
    "chorus": (0.0, 1.0, 0.01, "Chorus", "%"),
    "phaser": (0.0, 1.0, 0.01, "Phaser", "%"),
    "delay": (0.0, 1.0, 0.01, "Eko", "%"),
    "delay_time": (0.02, 1.0, 0.01, "Eko Süresi", "sn"),
    "delay_feedback": (0.0, 0.9, 0.01, "Eko Tekrarı", "%"),
    "reverb": (0.0, 1.0, 0.01, "Yankı (oda)", "%"),
    "room": (0.0, 1.0, 0.01, "Oda Boyutu", "%"),
    "comp": (0.0, 1.0, 0.01, "Kompresör", "%"),
    "volume": (-24.0, 12.0, 0.1, "Çıkış Seviyesi", "dB"),
}


def clamp_param(name: str, value: float) -> float:
    spec = PARAM_SPECS.get(name)
    if spec is None:
        return value
    lo, hi = spec[0], spec[1]
    return min(hi, max(lo, value))


def format_param(name: str, value: float) -> str:
    """Slider değerini birimiyle, arayüz dilinde yazar."""
    unit = PARAM_SPECS[name][4]
    if unit == "%":
        return f"{value * 100:.0f}%"
    if unit == "st":
        return f"{value:+.1f} st"
    if unit == "dB":
        if name == "gate_db":
            return tr("Kapalı") if value <= -89.5 else f"{value:.0f} dB"
        return f"{value:+.1f} dB"
    if unit == "Hz":
        return f"{value / 1000:.1f} kHz" if value >= 1000 else f"{value:.0f} Hz"
    if unit == "bit":
        return tr("Kapalı") if value < 1 else f"{value:.0f} bit"
    if unit == "sn":
        return f"{value * 1000:.0f} ms"
    return f"{value:.2f}"

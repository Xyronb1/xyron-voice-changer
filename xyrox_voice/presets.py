"""Hazır ses profilleri ve kullanıcı profillerinin saklanması."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .i18n import tr
from .params import VoiceParams

CATEGORIES = ("Kadın", "Erkek", "Karakter", "Efekt", "Benim")
CATEGORY_COLORS = {
    "Kadın": "#FF6FB5",
    "Erkek": "#4FA3FF",
    "Karakter": "#B57BFF",
    "Efekt": "#2EE6A8",
    "Benim": "#FFC857",
}


@dataclass(frozen=True)
class Preset:
    key: str
    name: str
    category: str
    icon: str
    desc: str
    params: VoiceParams = field(default_factory=VoiceParams)
    builtin: bool = True


def _p(**kw: float) -> VoiceParams:
    return VoiceParams.from_dict(kw)


# Değerler erkek konuşma sesi (~100-140 Hz) baz alınarak ayarlandı.
# Kadın sesi kullanan biri Erkek kategorisindeki "Kadından Erkeğe" profilini kullanabilir.
_BUILTIN: list[Preset] = [
    # ------------------------------------------------------------- Kadın
    Preset("f_natural", "Doğal Kadın", "Kadın", "🌸",
           "Gerçekçi günlük kadın sesi: perde, tını ve temel ton birlikte değişir",
           _p(pitch=10.0, formant=3.2, h1=7.0, denoise=0.3, breath=0.03, deess=0.3, hpf=100,
              presence=2.5, comp=0.45)),
    Preset("f_young", "Genç Kız", "Kadın", "🎀",
           "Enerjik, parlak ve tatlı genç kız tonu",
           _p(pitch=11.5, formant=3.8, h1=6.0, denoise=0.3, breath=0.03, deess=0.3, hpf=120,
              presence=3.0, air=1.0, comp=0.45)),
    Preset("f_mature", "Olgun Kadın", "Kadın", "👠",
           "Tok, zarif ve güven veren olgun kadın sesi",
           _p(pitch=8.5, formant=2.6, h1=8.0, denoise=0.3, breath=0.03, deess=0.3, hpf=90,
              body=1.0, presence=2.0, comp=0.5)),
    Preset("f_velvet", "Kadife Kadın", "Kadın", "🍷",
           "Hafif buğulu, nefesli ve yumuşak kadın tonu",
           _p(pitch=8.5, formant=2.8, h1=9.0, denoise=0.3, breath=0.18, deess=0.35, hpf=90,
              body=1.0, presence=1.0, air=1.0, comp=0.55, reverb=0.05, room=0.3)),
    Preset("f_anime", "Anime Kızı", "Kadın", "🎌",
           "Çok parlak, sevimli anime karakter sesi",
           _p(pitch=12.0, formant=5.0, h1=4.0, denoise=0.3, breath=0.03, deess=0.35, hpf=150,
              presence=3.0, air=2.0, comp=0.5)),
    Preset("f_announcer", "Spiker Kadın", "Kadın", "🎙️",
           "Yayın kalitesinde, kompresörlü net kadın spiker",
           _p(pitch=9.5, formant=3.0, h1=6.0, denoise=0.35, deess=0.4, hpf=110,
              presence=3.5, air=1.0, comp=0.75)),
    Preset("f_whisper", "Fısıltı (ASMR)", "Kadın", "🤫",
           "Yakın mikrofon hissi veren yumuşak kadın fısıltısı",
           _p(pitch=8.0, formant=3.0, denoise=0.4, whisper=0.85, breath=0.2, deess=0.5,
              hpf=150, presence=2.0, air=2.0, comp=0.6, reverb=0.05, room=0.2, volume=3.0)),
    Preset("f_girl", "Küçük Kız", "Kadın", "🧸",
           "Çocuksu, ince ve masum kız çocuğu sesi",
           _p(pitch=12.0, formant=6.0, h1=3.0, denoise=0.3, deess=0.35, hpf=180,
              presence=2.5, air=1.5, comp=0.45)),
    # ------------------------------------------------------------- Erkek
    Preset("m_clean", "Stüdyo Erkek", "Erkek", "🎧",
           "Kendi sesin, ama stüdyo kalitesinde: gürültüsüz, net, dolgun",
           _p(denoise=0.55, deess=0.35, hpf=75, bass=1.5, body=-1.0, presence=2.0,
              air=1.5, comp=0.6)),
    Preset("m_deep", "Kalın Erkek", "Erkek", "🗿",
           "Tok, güçlü ve dolgun bariton erkek sesi",
           _p(pitch=-3.0, formant=-1.5, denoise=0.5, deess=0.2, hpf=60, bass=3.0,
              body=1.5, presence=1.0, air=0.5, comp=0.6)),
    Preset("m_bass", "Derin Bas", "Erkek", "🐻",
           "Çok kalın, yerden gelen derin bas ses",
           _p(pitch=-5.0, formant=-2.6, denoise=0.5, deess=0.15, hpf=45, bass=4.5,
              body=1.0, presence=1.5, comp=0.65)),
    Preset("m_radio", "Radyo DJ", "Erkek", "📻",
           "Gece FM programcısı: yakın, sıcak ve kompresörlü",
           _p(pitch=-1.5, formant=-0.8, denoise=0.55, deess=0.4, hpf=60, bass=4.0,
              body=0.5, presence=3.0, air=2.0, comp=0.85)),
    Preset("m_trailer", "Fragman Sesi", "Erkek", "🎬",
           "Sinema fragmanı anlatıcısı gibi devasa ve sinematik",
           _p(pitch=-6.0, formant=-3.0, denoise=0.55, deess=0.2, hpf=40, bass=5.0,
              presence=2.0, comp=0.75, reverb=0.16, room=0.75)),
    Preset("m_young", "Genç Erkek", "Erkek", "🧢",
           "Daha genç, enerjik delikanlı sesi",
           _p(pitch=2.5, formant=1.0, denoise=0.5, deess=0.35, hpf=90, presence=1.5,
              air=1.0, comp=0.5)),
    Preset("m_old", "Yaşlı Adam", "Erkek", "👴",
           "Titrek, nefesli ve yorgun yaşlı adam sesi",
           _p(pitch=-1.5, formant=-0.8, denoise=0.5, breath=0.18, vibrato=0.28,
              vibrato_rate=6.0, deess=0.3, hpf=110, lpf=7500, presence=-1.0, comp=0.5)),
    Preset("m_from_female", "Kadından Erkeğe", "Erkek", "🔁",
           "Kadın sesini inandırıcı bir erkek sesine çevirir",
           _p(pitch=-6.5, formant=-2.6, denoise=0.5, deess=0.3, hpf=60, bass=3.0,
              body=1.0, presence=1.0, comp=0.6)),
    # ------------------------------------------------------------- Karakter
    Preset("c_robot", "Robot", "Karakter", "🤖",
           "Klasik metalik, tek perdeli robot",
           _p(robot=1.0, robot_hz=105, denoise=0.6, hpf=120, presence=3.0, phaser=0.2,
              comp=0.6)),
    Preset("c_ai", "Yapay Zekâ", "Karakter", "💠",
           "Sakin ve kusursuz yapay zekâ asistanı",
           _p(pitch=3.0, formant=1.5, robot=0.35, robot_hz=190, denoise=0.6, deess=0.5,
              hpf=130, presence=2.0, air=3.0, chorus=0.25, comp=0.6, reverb=0.1, room=0.35)),
    Preset("c_cyborg", "Siborg", "Karakter", "🦾",
           "Yarı insan yarı makine, sert ve dijital",
           _p(pitch=-2.0, formant=-1.0, robot=0.55, robot_hz=85, denoise=0.6, hpf=90,
              bitcrush=11, chorus=0.3, presence=2.0, comp=0.65)),
    Preset("c_demon", "Şeytan", "Karakter", "😈",
           "Alt oktav katmanlı, boğuk ve korkutucu iblis",
           _p(pitch=-6.0, formant=-3.5, layer_pitch=-12, layer_mix=0.55, denoise=0.6,
              hpf=40, bass=4.0, drive=7.0, reverb=0.25, room=0.6, comp=0.7)),
    Preset("c_giant", "Dev", "Karakter", "🏔️",
           "Mağarada yaşayan devasa yaratık",
           _p(pitch=-8.0, formant=-4.5, denoise=0.6, hpf=35, bass=4.0, body=2.0,
              reverb=0.32, room=0.85, comp=0.65)),
    Preset("c_monster", "Canavar", "Karakter", "👹",
           "Hırıltılı, vahşi ork/canavar sesi",
           _p(pitch=-5.0, formant=-1.0, layer_pitch=-7, layer_mix=0.35, denoise=0.6,
              hpf=50, drive=12.0, bass=3.0, presence=2.0, comp=0.7, reverb=0.1)),
    Preset("c_dark_lord", "Karanlık Lord", "Karakter", "🌑",
           "Maskeli, metalik ve otoriter kötü karakter",
           _p(pitch=-4.0, formant=-2.0, denoise=0.6, hpf=60, lpf=4800, bass=3.0,
              drive=4.0, chorus=0.15, comp=0.75, reverb=0.12, room=0.45)),
    Preset("c_alien", "Uzaylı", "Karakter", "👽",
           "Uyumsuz formantlı, dalgalanan uzaylı sesi",
           _p(pitch=3.0, formant=-2.5, layer_pitch=7, layer_mix=0.3, robot=0.2,
              robot_hz=160, denoise=0.6, phaser=0.5, chorus=0.25, comp=0.5)),
    Preset("c_ghost", "Hayalet", "Karakter", "👻",
           "Fısıltılı, uzak ve ürpertici hayalet",
           _p(pitch=2.0, formant=0.5, whisper=0.6, denoise=0.6, hpf=160, phaser=0.35,
              delay=0.3, delay_time=0.32, delay_feedback=0.35, reverb=0.5, room=0.9,
              comp=0.5)),
    Preset("c_chipmunk", "Sincap", "Karakter", "🐿️",
           "Helyum çekmiş gibi komik sincap sesi",
           _p(pitch=10.0, formant=10.0, denoise=0.55, deess=0.5, hpf=200, comp=0.5)),
    Preset("c_child", "Çocuk", "Karakter", "🧒",
           "Okul çağındaki küçük çocuk sesi",
           _p(pitch=8.0, formant=4.5, denoise=0.55, deess=0.5, hpf=180, bass=-3.0,
              presence=2.0, comp=0.5)),
    Preset("c_hacker", "Anonim Hacker", "Karakter", "🕶️",
           "Kimliği gizlenmiş, dijital bozulmalı anonim ses",
           _p(pitch=-4.0, formant=-2.0, robot=0.3, robot_hz=95, denoise=0.6, hpf=180,
              lpf=5000, bitcrush=10, chorus=0.3, comp=0.7)),
    Preset("c_static_deep", "Karıncalı Kalın Ses", "Karakter", "📺",
           "Kimlik gizleyen röportajlardaki gibi: cızırtılı ve kalın",
           _p(pitch=-5.0, formant=-2.5, whisper=0.18, denoise=0.5, hpf=70, lpf=6500, bass=3.0,
              presence=2.0, drive=8.0, bitcrush=8, comp=0.7)),
    # ------------------------------------------------------------- Efekt
    Preset("e_phone", "Telefon", "Efekt", "☎️",
           "Eski hat telefon görüşmesi",
           _p(denoise=0.5, hpf=400, lpf=3400, drive=5.0, presence=4.0, comp=0.7)),
    Preset("e_radio", "Telsiz", "Efekt", "📡",
           "Taktik askeri telsiz, cızırtılı ve sıkışık",
           _p(denoise=0.5, gate_db=-50, hpf=500, lpf=3000, drive=12.0, bitcrush=9,
              presence=5.0, comp=0.8)),
    Preset("e_megaphone", "Megafon", "Efekt", "📢",
           "Sokak megafonu, sert ve yüksek",
           _p(denoise=0.5, hpf=600, lpf=4200, drive=14.0, presence=6.0, comp=0.8)),
    Preset("e_cave", "Mağara", "Efekt", "🕳️",
           "Taş duvarlardan dönen yankı",
           _p(denoise=0.5, delay=0.35, delay_time=0.28, delay_feedback=0.35, reverb=0.45,
              room=0.9, comp=0.5)),
    Preset("e_hall", "Konser Salonu", "Efekt", "🏛️",
           "Büyük salonda konuşma, geniş ve görkemli",
           _p(denoise=0.5, reverb=0.4, room=0.8, presence=1.0, comp=0.5)),
    Preset("e_underwater", "Su Altı", "Efekt", "🌊",
           "Suyun altından gelen boğuk ses",
           _p(denoise=0.5, lpf=900, chorus=0.6, phaser=0.4, bass=3.0, comp=0.5)),
    Preset("e_choir", "Koro", "Efekt", "🎶",
           "Arkada oktav katmanlı kalabalık koro",
           _p(denoise=0.5, layer_pitch=12, layer_mix=0.35, chorus=0.6, reverb=0.3,
              room=0.7, comp=0.55)),
    Preset("e_old_radio", "Eski Radyo", "Efekt", "📼",
           "1940'lar radyo yayını",
           _p(denoise=0.5, hpf=300, lpf=4500, bitcrush=10, drive=6.0, presence=3.0,
              comp=0.7)),
]

BUILTIN_PRESETS: dict[str, Preset] = {p.key: p for p in _BUILTIN}
DEFAULT_PRESET_KEY = "m_clean"


def slugify(name: str) -> str:
    table = str.maketrans("çğıöşüÇĞİÖŞÜ", "cgiosuCGIOSU")
    slug = re.sub(r"[^a-z0-9]+", "_", name.translate(table).lower()).strip("_")
    return slug or "profil"


class PresetStore:
    """Kullanıcı profillerini JSON dosyasında tutar; hazır profillerle birleştirir."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.user: dict[str, Preset] = {}
        self.load_error: str | None = None
        self.load()

    def load(self) -> None:
        self.user = {}
        self.load_error = None
        if not self.path.exists():
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            for item in raw.get("presets", []):
                preset = self._from_json(item)
                if preset:
                    self.user[preset.key] = preset
        except (OSError, ValueError, AttributeError) as exc:
            self.load_error = tr("Kullanıcı profilleri okunamadı: {error}").format(error=exc)

    @staticmethod
    def _from_json(item: Any) -> Preset | None:
        if not isinstance(item, dict) or not item.get("name"):
            return None
        name = str(item["name"])[:40]
        key = "u_" + slugify(str(item.get("key", name)).removeprefix("u_"))
        return Preset(key=key, name=name, category="Benim", icon=str(item.get("icon", "⭐"))[:2],
                      desc=str(item.get("desc", "Kendi kaydettiğin profil"))[:80],
                      params=VoiceParams.from_dict(item.get("params")), builtin=False)

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = {"version": 1, "presets": [
            {"key": p.key, "name": p.name, "icon": p.icon, "desc": p.desc,
             "params": p.params.to_dict()} for p in self.user.values()]}
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.path)  # yarım yazılmış dosya kalmasın

    def add(self, name: str, params: VoiceParams, desc: str = "") -> Preset:
        name = name.strip()[:40] or "Profilim"
        preset = Preset(key="u_" + slugify(name), name=name, category="Benim", icon="⭐",
                        desc=desc or "Kendi kaydettiğin profil", params=params, builtin=False)
        self.user[preset.key] = preset
        self.save()
        return preset

    def delete(self, key: str) -> bool:
        if key in self.user:
            del self.user[key]
            self.save()
            return True
        return False

    def all(self) -> dict[str, Preset]:
        merged = dict(BUILTIN_PRESETS)
        merged.update(self.user)
        return merged

    def get(self, key: str) -> Preset | None:
        return self.all().get(key)

"""Uygulama ayarları (%APPDATA%\\Xyron_Voice_Changer\\settings.json)."""

from __future__ import annotations

import json
import os
import shutil
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any

DATA_DIR_NAME = "Xyron_Voice_Changer"
LEGACY_DATA_DIR_NAME = "XYROX_Voice_Studio"  # 1.1.0 ve öncesi


def app_data_dir() -> Path:
    """Ayar klasörü. Eski sürümün klasörü varsa ilk çağrıda yenisine kopyalanır."""
    base = Path(os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming"))
    current, legacy = base / DATA_DIR_NAME, base / LEGACY_DATA_DIR_NAME
    if not current.exists() and legacy.is_dir():
        # Önce geçici klasöre kopyala, bitince tek hamlede yeniden adlandır: yarıda kesilirse
        # yarım bir klasör kalmaz ve bir sonraki açılışta taşıma tekrar denenir.
        staging = base / (DATA_DIR_NAME + ".migrating")
        try:
            shutil.rmtree(staging, ignore_errors=True)
            shutil.copytree(legacy, staging)
            staging.replace(current)
        except OSError:
            shutil.rmtree(staging, ignore_errors=True)
            return legacy  # kopyalanamazsa ayarlar kaybolmasın, eski klasörle devam et
    return current


@dataclass
class AppConfig:
    hostapi: str = ""
    mic: str = ""
    cable: str = ""
    monitor: str = ""
    monitor_on: bool = False
    quality: str = "studio"
    preset: str = "m_clean"
    params: dict[str, float] = field(default_factory=dict)
    hotkey_enabled: bool = True
    language: str = ""  # boş = sistem dilini kullan (i18n.resolve_language)

    @classmethod
    def load(cls, path: Path) -> "AppConfig":
        try:
            raw: Any = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return cls()
        if not isinstance(raw, dict):
            return cls()
        cfg = cls()
        for f in fields(cls):
            if f.name in raw:
                value = raw[f.name]
                default = getattr(cfg, f.name)
                if isinstance(default, bool):
                    value = bool(value)
                elif isinstance(default, str):
                    value = str(value)
                elif isinstance(default, dict) and not isinstance(value, dict):
                    continue
                setattr(cfg, f.name, value)
        return cfg

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)

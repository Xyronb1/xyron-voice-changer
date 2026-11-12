"""Ses aygıtları, halka tampon ve gerçek zamanlı yönlendirme (mikrofon -> kablo + kulaklık)."""

from __future__ import annotations

import math
import threading
import time
from dataclasses import dataclass
from typing import Callable

import numpy as np

try:
    import sounddevice as sd
except (ImportError, OSError) as exc:  # PortAudio DLL eksikse uygulama yine açılsın
    sd = None
    SOUNDDEVICE_ERROR: str | None = str(exc)
else:
    SOUNDDEVICE_ERROR = None

from .i18n import tr
from .processor import VoiceProcessor

SAMPLE_RATE = 48000
HOSTAPI_PREFERENCE = ("Windows WASAPI", "MME", "Windows DirectSound")
CABLE_HINTS = ("cable in", "cable input", "vb-audio virtual cable")


# ===================================================================== tampon
class RingBuffer:
    """Thread-safe mono halka tampon. Dolarsa en eski veriyi atar."""

    def __init__(self, capacity: int) -> None:
        self.capacity = int(capacity)
        self._buf = np.zeros(self.capacity, dtype=np.float32)
        self._read = 0
        self._count = 0
        self._lock = threading.Lock()
        self.dropped = 0

    @property
    def available(self) -> int:
        return self._count

    def clear(self) -> None:
        with self._lock:
            self._read = 0
            self._count = 0

    def write(self, data: np.ndarray) -> None:
        data = np.asarray(data, dtype=np.float32).reshape(-1)
        if data.size >= self.capacity:
            data = data[-self.capacity:]
        with self._lock:
            overflow = self._count + data.size - self.capacity
            if overflow > 0:
                self._read = (self._read + overflow) % self.capacity
                self._count -= overflow
                self.dropped += overflow
            start = (self._read + self._count) % self.capacity
            first = min(data.size, self.capacity - start)
            self._buf[start:start + first] = data[:first]
            if first < data.size:
                self._buf[:data.size - first] = data[first:]
            self._count += data.size

    def read(self, n: int) -> np.ndarray:
        """En fazla n örnek okur (mevcut kadar)."""
        with self._lock:
            n = min(int(n), self._count)
            out = np.empty(n, dtype=np.float32)
            first = min(n, self.capacity - self._read)
            out[:first] = self._buf[self._read:self._read + first]
            if first < n:
                out[first:] = self._buf[:n - first]
            self._read = (self._read + n) % self.capacity
            self._count -= n
            return out

    def discard(self, n: int) -> None:
        with self._lock:
            n = min(int(n), self._count)
            self._read = (self._read + n) % self.capacity
            self._count -= n


class AdaptiveReader:
    """Çıkış tarafı okuyucu: doluluğu hedefte tutmak için okuma hızını ±%0.5 ayarlar.

    İki farklı ses kartının saati hiçbir zaman birebir aynı değildir; bu mikro-resampling
    dakikalar içinde biriken kaymayı çıtırtı olmadan emer. Boşalırsa yumuşakça susar,
    tekrar dolunca yumuşakça başlar.
    """

    FADE = 64

    def __init__(self, ring: RingBuffer, target: int = 768) -> None:
        self.ring = ring
        self.initial_target = int(target)
        self.target = int(target)
        self.max_target = 6144
        self._playing = False
        self._fill = float(target)
        self._acc = 0.0
        self._last = 0.0
        self.underruns = 0

    def reset(self, full: bool = False) -> None:
        if full:
            self.target = self.initial_target
            self.underruns = 0
        self._playing = False
        self._fill = float(self.target)
        self._acc = 0.0
        self._last = 0.0

    def read(self, n: int) -> np.ndarray:
        # MME gibi büyük bloklu sistemlerde (callback başına ~4400 örnek) hedef en az 2 blok olmalı.
        if self.target < 2 * n:
            self.target = min(2 * n, 32768)
            self.max_target = max(self.max_target, 3 * n)
        avail = self.ring.available
        if not self._playing:
            if avail < self.target:
                return np.zeros(n, dtype=np.float32)
            self._playing = True
            self._fill = float(avail)
            fade_in = True
        else:
            fade_in = False

        # Uzun bir takılmadan sonra birikmiş fazlalığı at (gecikme büyümesin).
        if avail > 4 * self.target + n:
            self.ring.discard(avail - self.target)
            avail = self.ring.available

        self._fill = 0.97 * self._fill + 0.03 * avail
        error = (self._fill - self.target) / max(self.target, 1)
        rate = 1.0 + max(-0.005, min(0.005, 0.004 * error))
        self._acc += n * rate
        need = int(self._acc)

        if avail < need:
            self.underruns += 1
            data = self.ring.read(avail)
            out = np.zeros(n, dtype=np.float32)
            m = min(data.size, n)
            if m:
                out[:m] = data[:m]
                fade = min(self.FADE, m)
                out[m - fade:m] *= np.linspace(1.0, 0.0, fade, dtype=np.float32)
            self._playing = False
            self._acc = 0.0
            # Sık boşalıyorsa hedefi büyüt: biraz gecikme, sıfır kesinti.
            self.target = min(self.max_target, int(self.target * 1.25) + 64)
            return out

        self._acc -= need
        data = self.ring.read(need)
        if need == n:
            out = data
        elif need < 2:
            out = np.full(n, data[-1] if data.size else self._last, dtype=np.float32)
        else:
            pos = np.linspace(0.0, need - 1, n)
            out = np.interp(pos, np.arange(need), data).astype(np.float32)
        if fade_in:
            fade = min(self.FADE, n)
            out[:fade] *= np.linspace(0.0, 1.0, fade, dtype=np.float32)
        if out.size:
            self._last = float(out[-1])
        return out


# ===================================================================== aygıtlar
@dataclass(frozen=True)
class Device:
    index: int
    name: str
    hostapi: str
    in_channels: int
    out_channels: int
    default_rate: float


def list_hostapis() -> list[str]:
    if sd is None:
        return []
    names = [h["name"] for h in sd.query_hostapis()]
    ordered = [n for n in HOSTAPI_PREFERENCE if n in names]
    return ordered or names


def list_devices(hostapi: str) -> tuple[list[Device], list[Device]]:
    """(girişler, çıkışlar) döndürür; sadece seçili host API'ye ait aygıtlar."""
    if sd is None:
        return [], []
    hostapis = sd.query_hostapis()
    inputs: list[Device] = []
    outputs: list[Device] = []
    for i, d in enumerate(sd.query_devices()):
        api = hostapis[d["hostapi"]]["name"]
        if api != hostapi:
            continue
        dev = Device(i, d["name"], api, d["max_input_channels"], d["max_output_channels"],
                     d["default_samplerate"])
        if dev.in_channels > 0:
            inputs.append(dev)
        if dev.out_channels > 0:
            outputs.append(dev)
    return inputs, outputs


def is_cable(name: str) -> bool:
    low = name.lower()
    return any(h in low for h in CABLE_HINTS)


def default_devices(hostapi: str) -> tuple[Device | None, Device | None, Device | None]:
    """Önerilen (mikrofon, sanal kablo, kulaklık) üçlüsü."""
    if sd is None:
        return None, None, None
    inputs, outputs = list_devices(hostapi)
    api_info = next((h for h in sd.query_hostapis() if h["name"] == hostapi), None)
    def_in = api_info["default_input_device"] if api_info else -1
    def_out = api_info["default_output_device"] if api_info else -1

    mic = next((d for d in inputs if d.index == def_in and "cable" not in d.name.lower()), None)
    mic = mic or next((d for d in inputs if "cable" not in d.name.lower()), None)
    cable = next((d for d in outputs if "cable in" in d.name.lower()), None)
    cable = cable or next((d for d in outputs if is_cable(d.name)), None)
    phones = next((d for d in outputs if d.index == def_out and not is_cable(d.name)), None)
    phones = phones or next((d for d in outputs if not is_cable(d.name)), None)
    return mic, cable, phones


def find_device(name: str | None, devices: list[Device]) -> Device | None:
    if not name:
        return None
    return next((d for d in devices if d.name == name), None)


# ===================================================================== yönlendirici
class AudioRouter:
    """Mikrofonu okur, işleyiciden geçirir, sanal kabloya ve (isteğe bağlı) kulaklığa yollar."""

    CHUNK = 256

    def __init__(self, processor: VoiceProcessor,
                 on_error: Callable[[str], None] | None = None) -> None:
        if sd is None:
            raise RuntimeError(
                tr("Ses kütüphanesi yüklenemedi: {error}").format(error=SOUNDDEVICE_ERROR))
        self.processor = processor
        self.on_error = on_error
        self.sample_rate = SAMPLE_RATE
        self._in_ring = RingBuffer(SAMPLE_RATE * 2)
        self._cable_ring = RingBuffer(SAMPLE_RATE)
        self._monitor_ring = RingBuffer(SAMPLE_RATE)
        self._cable_reader = AdaptiveReader(self._cable_ring)
        self._monitor_reader = AdaptiveReader(self._monitor_ring)
        self._event = threading.Event()
        self._worker: threading.Thread | None = None
        self._running = False
        self._streams: list = []
        self._monitor_stream = None
        self.monitor_enabled = False
        self.xruns = 0
        self._started_at = time.monotonic()
        self._health_base: tuple[int, int] | None = None
        self._capture_left = 0
        self._capture_parts: list[np.ndarray] = []
        self._captured: np.ndarray | None = None
        self.config: tuple[Device, Device | None, Device | None] | None = None

    # --------------------------------------------------------------- yardımcı
    def _extra(self, dev: Device):
        if dev.hostapi == "Windows WASAPI":
            return sd.WasapiSettings(auto_convert=True)
        return None

    @property
    def running(self) -> bool:
        return self._running

    def streams_alive(self) -> bool:
        if not self._running:
            return True
        try:
            alive = all(s.active for s in self._streams)
            if self._monitor_stream is not None:
                alive = alive and self._monitor_stream.active
            return alive
        except Exception:  # aygıt söküldüyse PortAudio istisna fırlatabilir
            return False

    @property
    def total_latency_ms(self) -> float:
        io = 0.0
        for s in self._streams + ([self._monitor_stream] if self._monitor_stream else []):
            try:
                lat = s.latency
                io = max(io, sum(lat) if isinstance(lat, tuple) else lat)
            except Exception:
                pass
        buffered = self._cable_reader.target / self.sample_rate
        return self.processor.latency_ms + (io + buffered) * 1000.0

    # --------------------------------------------------------------- callback
    def _input_cb(self, indata, frames, time_info, status) -> None:
        if status:
            self.xruns += 1
        mono = indata[:, 0] if indata.shape[1] == 1 else indata.mean(axis=1)
        self._in_ring.write(mono)
        self._event.set()

    def _make_output_cb(self, reader: AdaptiveReader):
        def callback(outdata, frames, time_info, status) -> None:
            if status:
                self.xruns += 1
            data = reader.read(frames)
            outdata[:] = data[:, None]
        return callback

    def _worker_loop(self) -> None:
        while self._running:
            self._event.wait(0.05)
            self._event.clear()
            while self._running and self._in_ring.available >= self.CHUNK:
                block = self._in_ring.read(min(self._in_ring.available, 4 * self.CHUNK))
                try:
                    out = self.processor.process(block)
                except Exception as exc:  # işleme hatası sesi kesmesin, bildir ve sessizlik ver
                    out = np.zeros_like(block)
                    if self.on_error:
                        self.on_error(tr("İşleme hatası: {error}").format(error=exc))
                if self._capture_left > 0:
                    self._capture_parts.append(out.copy())
                    self._capture_left -= out.size
                    if self._capture_left <= 0:
                        self._captured = np.concatenate(self._capture_parts)
                        self._capture_parts = []
                if self.config is not None and self.config[1] is not None:
                    self._cable_ring.write(out)
                if self.monitor_enabled:
                    self._monitor_ring.write(out)

    # --------------------------------------------------------------- yaşam döngüsü
    def start(self, mic: Device, cable: Device | None, monitor: Device | None,
              monitor_enabled: bool) -> None:
        self.stop()
        if cable is None and not (monitor_enabled and monitor is not None):
            raise ValueError(tr("En az bir çıkış seç: sanal kablo veya kulaklık."))
        self.config = (mic, cable, monitor)
        for ring in (self._in_ring, self._cable_ring, self._monitor_ring):
            ring.clear()
        self._cable_reader.reset(full=True)
        self._monitor_reader.reset(full=True)
        self.processor.warmup()
        self.xruns = 0
        self._started_at = time.monotonic()
        self._health_base: tuple[int, int] | None = None
        self.monitor_enabled = monitor_enabled and monitor is not None

        try:
            in_stream = sd.InputStream(
                device=mic.index, samplerate=self.sample_rate, channels=min(mic.in_channels, 2),
                dtype="float32", blocksize=0, latency="low", callback=self._input_cb,
                extra_settings=self._extra(mic))
            self._streams = [in_stream]
            if cable is not None:
                self._streams.append(sd.OutputStream(
                    device=cable.index, samplerate=self.sample_rate,
                    channels=min(cable.out_channels, 2), dtype="float32", blocksize=0,
                    latency="low", callback=self._make_output_cb(self._cable_reader),
                    extra_settings=self._extra(cable)))
            self._running = True
            self._worker = threading.Thread(target=self._worker_loop, name="xyrox-dsp",
                                            daemon=True)
            self._worker.start()
            for s in self._streams:
                s.start()
            if self.monitor_enabled and monitor is not None:
                self._open_monitor(monitor)
        except Exception:
            self.stop()
            raise

    def _open_monitor(self, monitor: Device) -> None:
        self._monitor_ring.clear()
        self._monitor_reader.reset()
        stream = sd.OutputStream(
            device=monitor.index, samplerate=self.sample_rate,
            channels=min(monitor.out_channels, 2), dtype="float32", blocksize=0, latency="low",
            callback=self._make_output_cb(self._monitor_reader),
            extra_settings=self._extra(monitor))
        stream.start()
        self._monitor_stream = stream

    def _close_monitor(self) -> None:
        if self._monitor_stream is not None:
            try:
                self._monitor_stream.stop()
                self._monitor_stream.close()
            except Exception:
                pass
            self._monitor_stream = None

    def set_monitor(self, enabled: bool) -> None:
        """Akışı durdurmadan kendini dinlemeyi aç/kapat."""
        self.monitor_enabled = False
        self._close_monitor()
        if enabled and self._running and self.config and self.config[2] is not None:
            self._open_monitor(self.config[2])
            self.monitor_enabled = True

    # --------------------------------------------------------------- test kaydı
    def start_capture(self, seconds: float) -> None:
        """İşlenmiş (karşı tarafa giden) sesi `seconds` saniye boyunca kaydetmeye başlar."""
        self._captured = None
        self._capture_parts = []
        self._capture_left = int(seconds * self.sample_rate)

    def take_capture(self) -> np.ndarray | None:
        """Kayıt bittiyse sesi döndürür (bir kez); bitmediyse None."""
        audio, self._captured = self._captured, None
        return audio

    def play_clip(self, audio: np.ndarray, device: Device) -> None:
        """Kaydı seçilen kulaklıktan çalar (canlı akıştan bağımsız, beklemeden döner)."""
        clip = np.asarray(audio, dtype=np.float32).reshape(-1)
        if device.out_channels >= 2:
            clip = np.column_stack((clip, clip))
        sd.play(clip, self.sample_rate, device=device.index, extra_settings=self._extra(device))

    def stop(self) -> None:
        self._capture_left = 0
        try:
            sd.stop()  # varsa çalan test kaydını da durdur
        except Exception:
            pass
        self._running = False
        self._event.set()
        if self._worker is not None:
            self._worker.join(timeout=1.0)
            self._worker = None
        for s in self._streams:
            try:
                s.stop()
                s.close()
            except Exception:
                pass
        self._streams = []
        self._close_monitor()
        self.monitor_enabled = False

    def health(self) -> str:
        """'iyi' | 'orta' | 'kötü' — UI'deki tampon sağlığı rozeti için.

        Açılışın ilk 2 saniyesindeki (aygıtlar senkronlanırken) boşalmalar sayılmaz.
        """
        u = self._cable_reader.underruns + self._monitor_reader.underruns
        if time.monotonic() - self._started_at < 2.0:
            return "iyi"
        if self._health_base is None:
            self._health_base = (u, self.xruns)
        problems = (u - self._health_base[0]) + (self.xruns - self._health_base[1])
        if problems == 0:
            return "iyi"
        return "orta" if problems < 20 else "kötü"


def db_to_meter(level: float) -> float:
    """Doğrusal tepe seviyesini 0..1 gösterge değerine çevirir (-60..0 dB)."""
    if level <= 1e-6:
        return 0.0
    return max(0.0, min(1.0, (20.0 * math.log10(level) + 60.0) / 60.0))

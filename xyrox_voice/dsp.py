"""Spektral ses motoru (STFT).

Tek bir STFT çerçevesi içinde sırayla:
  1. Spektral gürültü azaltma (minimum takipli gürültü tabanı + yumuşatılmış kazanç)
  2. Perde kaydırma: Laroche-Dolson tepe bölgesi kaydırma (faz kilitli, az "phasiness")
  3. Formant düzeltme: cepstral zarf ile perde ve formant birbirinden bağımsız
  4. Karakter katmanları: robot (sabit perdeli vocoder), fısıltı, nefes, harmonizer katmanı
  5. De-esser (sert "s/ş" bastırma)
Girdi/çıktı mono float32'dir; `process` her çağrıda girdiyle aynı uzunlukta çıktı verir.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

TWO_PI = 2.0 * math.pi
SPEECH_RATIO = 5.0  # yumuşatılmış güç, minimumun ~7 dB üstündeyse o bin'de konuşma var say


@dataclass(frozen=True)
class EngineParams:
    """Spektral motorun parametreleri (hepsi gerçek zamanlı değiştirilebilir)."""

    pitch: float = 0.0          # yarım ton (semitone)
    formant: float = 0.0        # yarım ton; 0 = formant korunur
    denoise: float = 0.0        # 0..1 gürültü azaltma gücü
    robot: float = 0.0          # 0..1 robot karışımı
    robot_hz: float = 110.0     # robot sesinin sabit perdesi
    whisper: float = 0.0        # 0..1 fısıltı karışımı
    breath: float = 0.0         # 0..1 tiz bantta nefes/hava
    vibrato: float = 0.0        # vibrato derinliği (yarım ton)
    vibrato_rate: float = 5.5   # Hz
    deess: float = 0.0          # 0..1 de-esser gücü
    layer_pitch: float = -12.0  # harmonizer katmanının perdesi (ana sese göre, yarım ton)
    layer_mix: float = 0.0      # 0..1 harmonizer katmanı seviyesi
    h1: float = 0.0             # dB; temel harmoniği (H1) güçlendirir: yumuşak, kadınsı ton


def periodic_hann(n: int) -> np.ndarray:
    """STFT için periyodik Hann penceresi (COLA koşulunu tam sağlar)."""
    return (0.5 - 0.5 * np.cos(TWO_PI * np.arange(n) / n)).astype(np.float64)


def cepstral_log_envelope(mag: np.ndarray, n_coef: int, lifter: np.ndarray) -> np.ndarray:
    """Genlik spektrumunun yumuşak spektral zarfını (doğal log) döndürür."""
    log_mag = np.log(mag + 1e-9)
    cep = np.fft.irfft(log_mag)
    cep[:n_coef] *= lifter
    cep[n_coef:cep.size - n_coef + 1] = 0.0
    cep[cep.size - n_coef + 1:] *= lifter[1:][::-1]
    return np.fft.rfft(cep).real


class _PeakShifter:
    """Laroche-Dolson tepe bölgesi kaydırmalı perde değiştirici (kendi faz durumuyla)."""

    def __init__(self, n_fft: int, hop: int) -> None:
        self.n_fft = n_fft
        self.hop = hop
        self.n_bins = n_fft // 2 + 1
        self.bins = np.arange(self.n_bins)
        self.src_pos = self.bins.astype(np.float64)
        self.prev_out_phase = np.zeros(self.n_bins)
        self.active = False

    def reset(self) -> None:
        self.prev_out_phase.fill(0.0)
        self.active = False

    def shift(self, spec: np.ndarray, mag: np.ndarray, phase: np.ndarray,
              true_bin: np.ndarray, ratio: float, transient: bool = False) -> np.ndarray:
        n_bins = self.n_bins
        if not self.active:
            # Kaydırmaya yeni başlanıyorsa çıkış fazını girişle hizala (tıkırtı olmasın).
            self.prev_out_phase = phase.copy()
            self.active = True

        peak_floor = mag.max() * 10.0 ** (-70.0 / 20.0)
        inner = mag[1:-1]
        is_peak = (inner > mag[:-2]) & (inner >= mag[2:]) & (inner > peak_floor)
        peaks = np.flatnonzero(is_peak) + 1
        if peaks.size == 0:
            self.prev_out_phase = phase.copy()
            self.src_pos = self.bins / ratio
            return np.zeros(n_bins, dtype=np.complex128)

        if peaks.size > 1:
            bounds = (peaks[:-1] + peaks[1:]) // 2 + 1
            region = np.searchsorted(bounds, self.bins, side="right")
        else:
            region = np.zeros(n_bins, dtype=np.int64)

        peak_true = true_bin[peaks]
        # Tam bin kaydırma. Kesirli (iki bin'e paylaştırmalı) kaydırma denendi; ölçümde
        # harmonik temizliğini artırmadı, o yüzden sade olan tutuldu.
        shift = np.rint(peak_true * (ratio - 1.0)).astype(np.int64)
        target = np.clip(peaks + shift, 0, n_bins - 1)
        target_phase = (self.prev_out_phase[target]
                        + TWO_PI * peak_true * ratio * self.hop / self.n_fft)
        if transient:
            # Patlamalı harflerde girişin dikey faz yapısını aynen koru: sert ve net kalır.
            rotation = np.zeros(peaks.size)
        else:
            rotation = target_phase - phase[peaks]

        region_shift = shift[region]
        dest = self.bins + region_shift
        values = spec * np.exp(1j * rotation[region])
        ok = (dest >= 0) & (dest < n_bins)
        dest_ok = dest[ok]
        real = np.bincount(dest_ok, weights=values.real[ok], minlength=n_bins)
        imag = np.bincount(dest_ok, weights=values.imag[ok], minlength=n_bins)
        out = real + 1j * imag

        # Her çıkış bin'inin kaynakta nereden geldiği: formant düzeltmesi zarfın tam olarak
        # nereye taşındığını buradan bilir (boş kalan bin'lerde yaklaşık değer: k / oran).
        count = np.bincount(dest_ok, minlength=n_bins)
        filled = count > 0
        self.src_pos = self.bins / ratio
        self.src_pos[filled] = (self.bins[filled]
                                - np.bincount(dest_ok, weights=region_shift[ok],
                                              minlength=n_bins)[filled] / count[filled])
        self.prev_out_phase = np.angle(out)
        return out


class VoiceEngine:
    """Gerçek zamanlı spektral ses motoru (mono)."""

    def __init__(self, sample_rate: int = 48000, n_fft: int = 2048, hop: int | None = None,
                 seed: int | None = None) -> None:
        if n_fft < 256 or n_fft & (n_fft - 1):
            raise ValueError("n_fft 256 veya daha büyük bir 2'nin kuvveti olmalı")
        self.sample_rate = int(sample_rate)
        self.n_fft = int(n_fft)
        self.hop = int(hop) if hop else self.n_fft // 4
        if self.n_fft % self.hop or self.n_fft // self.hop < 4:
            raise ValueError("hop, n_fft'nin en fazla 1/4'ü olmalı ve onu tam bölmeli")
        self.n_bins = self.n_fft // 2 + 1
        self.frames_per_sec = self.sample_rate / self.hop

        self.window = periodic_hann(self.n_fft)
        # Hann analiz + Hann sentez: üst üste binen pencerelerin kareleri toplamı sabittir.
        self.ola_norm = 1.0 / (np.sum(self.window ** 2) / self.hop)
        self.bins = np.arange(self.n_bins)
        self.bin_hz = self.sample_rate / self.n_fft
        self.expected_advance = TWO_PI * self.bins * self.hop / self.n_fft

        # Cepstral zarf: varsayılan ~1.5 ms quefrency. İnce (yüksek perdeli) konuşanda harmonikler
        # zarfa sızmasın diye kısalır. Kalın seste uzatmak denendi: ölçümde netliği düşürdü.
        self._cep_default = max(16, int(self.sample_rate / 650.0))
        self._cep_min = max(16, self.sample_rate // 1000)
        self._cep_max = self._cep_default
        self._set_lifter(self._cep_default)

        # Perde takibi: güç spektrumunun otokorelasyonu, pencere etkisi bölünerek giderilir.
        win_ac = np.fft.irfft(np.abs(np.fft.rfft(self.window)) ** 2)
        self._lag_lo = max(2, self.sample_rate // 450)
        self._lag_hi = min(self.sample_rate // 60, int(0.45 * self.n_fft))
        self._win_ac = np.maximum(win_ac[self._lag_lo:self._lag_hi] / win_ac[0], 0.05)

        freqs = self.bins * self.bin_hz
        # Formant kaydırma ağırlığı: 0 Hz'de %70, 1.5 kHz ve üstünde %100.
        self.formant_weight = 0.7 + 0.3 * np.clip(freqs / 1500.0, 0.0, 1.0)
        self.breath_weight = np.clip((freqs - 1500.0) / 3500.0, 0.0, 1.0)
        self.sib_band = (freqs >= 4500.0) & (freqs <= 11000.0)
        self.sib_taper = np.clip((freqs - 3500.0) / 1000.0, 0.0, 1.0)

        self.params = EngineParams()
        self._rng = np.random.default_rng(seed)
        self._robot_table: np.ndarray | None = None
        self._robot_table_hz = 0
        self.main_shifter = _PeakShifter(self.n_fft, self.hop)
        self.layer_shifter = _PeakShifter(self.n_fft, self.hop)
        self.reset()

    # ------------------------------------------------------------------ durum
    def reset(self) -> None:
        """Tüm iç tamponları ve faz durumlarını sıfırlar."""
        self._in_frame = np.zeros(self.n_fft)
        self._ola = np.zeros(self.n_fft)
        self._pending = np.zeros(0, dtype=np.float32)
        # Gecikmeyi sabit tutmak için çıkış kuyruğu bir hop sessizlikle başlar.
        self._out_queue = np.zeros(self.hop, dtype=np.float32)
        self._prev_in_phase = np.zeros(self.n_bins)
        self._prev_energy = 0.0
        self._noise_psd: np.ndarray | None = None
        self._smooth_psd: np.ndarray | None = None
        self._min_psd: np.ndarray | None = None
        self._clean_psd: np.ndarray | None = None
        self._nr_gain = np.ones(self.n_bins)
        self._nr_frames = 0
        self._deess_gain = 1.0
        self._sample_clock = 0
        self._vib_phase = 0.0
        self._log_ratio = 0.0
        self._log_formant = 0.0
        self._f0_log: float | None = None
        self._f0_jumps = 0
        self._voiced = False
        self._h1_amount = 0.0
        self.main_shifter.reset()
        self.layer_shifter.reset()
        self.last_spectrum = np.zeros(self.n_bins, dtype=np.float32)

    def relearn_noise(self) -> None:
        """Gürültü tabanı tahminini sıfırla; ilk ~0.6 sn hızlı öğrenme yeniden başlar."""
        self._noise_psd = None
        self._smooth_psd = None
        self._min_psd = None
        self._clean_psd = None
        self._nr_frames = 0

    @property
    def latency_samples(self) -> int:
        return self.n_fft

    def set_params(self, params: EngineParams) -> None:
        """Parametreleri atomik olarak değiştirir (ses iş parçacığı bir sonraki çerçevede görür)."""
        self.params = params

    # ------------------------------------------------------------------ akış
    def process(self, block: np.ndarray) -> np.ndarray:
        """Mono bloğu işler; aynı uzunlukta çıktı döner (sabit gecikme: n_fft örnek)."""
        block = np.asarray(block, dtype=np.float32).reshape(-1)
        if block.size == 0:
            return block.copy()
        pending = np.concatenate((self._pending, block))
        n_hops = pending.size // self.hop
        if n_hops:
            produced = np.empty(n_hops * self.hop, dtype=np.float32)
            for i in range(n_hops):
                chunk = pending[i * self.hop:(i + 1) * self.hop]
                produced[i * self.hop:(i + 1) * self.hop] = self._process_hop(chunk)
            self._out_queue = np.concatenate((self._out_queue, produced))
            pending = pending[n_hops * self.hop:]
        self._pending = pending
        out = self._out_queue[:block.size]
        self._out_queue = self._out_queue[block.size:]
        return out

    def _process_hop(self, chunk: np.ndarray) -> np.ndarray:
        hop = self.hop
        self._in_frame[:-hop] = self._in_frame[hop:]
        self._in_frame[-hop:] = chunk
        spec_out = self._process_frame(self._in_frame)
        if spec_out is not None:
            self._ola += np.fft.irfft(spec_out, n=self.n_fft) * self.window * self.ola_norm
        out = self._ola[:hop].astype(np.float32)
        self._ola[:-hop] = self._ola[hop:]
        self._ola[-hop:] = 0.0
        self._sample_clock += hop
        return out

    # ------------------------------------------------------------------ çerçeve
    def _process_frame(self, frame: np.ndarray) -> np.ndarray | None:
        """Çerçeveyi işler, çıkış spektrumunu döner (tam sessizlikte None)."""
        p = self.params
        spec = np.fft.rfft(frame * self.window)
        mag = np.abs(spec)
        phase = np.angle(spec)

        if mag.max() < 1e-7:  # tam sessizlik: hesap yapma, durumları sessizce ilerlet
            self._prev_in_phase = phase
            self.main_shifter.reset()
            self.layer_shifter.reset()
            self._advance_lfo()
            self.last_spectrum *= 0.8
            return None

        if p.denoise > 0.001:
            spec, mag = self._denoise(spec, mag, p.denoise)
        elif self._noise_psd is not None:
            self.relearn_noise()  # tekrar açılınca eski durumla değil sıfırdan başlasın

        # Bin'lerin gerçek frekansı (faz farkından), perde kaydırıcılar için.
        dphi = phase - self._prev_in_phase - self.expected_advance
        dphi = (dphi + math.pi) % TWO_PI - math.pi
        true_bin = self.bins + dphi * (self.n_fft / (TWO_PI * self.hop))
        self._prev_in_phase = phase

        energy = float(np.dot(mag, mag))
        transient = energy > 4.0 * self._prev_energy and energy > 1e-6
        self._prev_energy = 0.6 * energy + 0.4 * self._prev_energy

        neutral = (abs(p.pitch) < 1e-3 and abs(p.formant) < 1e-3 and p.robot < 1e-3
                   and p.layer_mix < 1e-3 and p.vibrato < 1e-3 and p.h1 < 0.05 and abs(self._log_ratio) < 1e-4 and abs(self._log_formant) < 1e-4)
        if neutral:
            self._voiced = False
        else:
            self._track_f0(mag)

        ratio, formant = self._frame_ratios(p)
        log_env = None
        need_env = abs(math.log(formant)) > 1e-4 or abs(math.log(ratio)) > 1e-4 or p.robot > 0.001
        if need_env:
            log_env = cepstral_log_envelope(mag, self.n_cep, self.lifter)

        if abs(ratio - 1.0) > 1e-4:
            out = self.main_shifter.shift(spec, mag, phase, true_bin, ratio, transient)
            src_pos = self.main_shifter.src_pos
        else:
            self.main_shifter.reset()
            out = spec.copy()
            src_pos = self.bins

        if log_env is not None and abs(formant / ratio - 1.0) > 1e-4:
            out *= self._formant_gain(log_env, src_pos, formant)

        # Temel harmonik (H1) güçlendirme: kadın sesinde H1, üst harmoniklere göre belirgin
        # biçimde güçlüdür; perdesi yükseltilmiş erkek sesinde zayıf kalır ("incelmiş" hissi).
        h1_on = p.h1 > 0.05 and self._voiced and self._f0_log is not None
        self._h1_amount += ((1.0 if h1_on else 0.0) - self._h1_amount) * 0.3
        if self._h1_amount > 0.01 and self._f0_log is not None:
            center = math.exp(self._f0_log) * ratio / self.bin_hz
            width = max(1.5, 0.22 * center)
            bump = np.exp(-0.5 * ((self.bins - center) / width) ** 2)
            out *= 1.0 + (10.0 ** (p.h1 / 20.0) - 1.0) * self._h1_amount * bump

        if p.layer_mix > 0.001:
            layer_ratio = ratio * 2.0 ** (p.layer_pitch / 12.0)
            layer = self.layer_shifter.shift(spec, mag, phase, true_bin, layer_ratio, transient)
            if abs(formant / layer_ratio - 1.0) > 1e-4:  # katman da formantı korusun
                if log_env is None:
                    log_env = cepstral_log_envelope(mag, self.n_cep, self.lifter)
                layer *= self._formant_gain(log_env, self.layer_shifter.src_pos, formant)
            out = out + p.layer_mix * layer
        else:
            self.layer_shifter.reset()

        if p.robot > 0.001 and log_env is not None:
            out = self._robotize(out, log_env, formant, p)
        if p.whisper > 0.001:
            out = self._mix_noise_phase(out, p.whisper, None)
        if p.breath > 0.001:
            noisy = np.abs(out) * self.breath_weight * np.exp(
                1j * self._rng.uniform(-math.pi, math.pi, self.n_bins))
            out = out + (0.6 * p.breath) * noisy
        if p.deess > 0.001:
            out = self._deess(out, p.deess)

        self.last_spectrum = np.abs(out).astype(np.float32)
        return out

    # ------------------------------------------------------------------ parçalar
    def _advance_lfo(self) -> None:
        self._vib_phase = (self._vib_phase
                           + TWO_PI * self.params.vibrato_rate / self.frames_per_sec) % TWO_PI

    def _frame_ratios(self, p: EngineParams) -> tuple[float, float]:
        """Yumuşatılmış perde ve formant oranlarını döndürür (vibrato dahil)."""
        target_r = p.pitch / 12.0 * math.log(2.0)
        target_f = p.formant / 12.0 * math.log(2.0)
        # ~25 ms'lik yumuşatma: slider sürüklerken veya preset değişiminde zıplama olmaz.
        alpha = 1.0 - math.exp(-1.0 / (0.025 * self.frames_per_sec))
        self._log_ratio += (target_r - self._log_ratio) * alpha
        self._log_formant += (target_f - self._log_formant) * alpha
        self._advance_lfo()
        vib = p.vibrato / 12.0 * math.log(2.0) * math.sin(self._vib_phase)
        return math.exp(self._log_ratio + vib), math.exp(self._log_formant)

    def _set_lifter(self, n_cep: int) -> None:
        self.n_cep = n_cep
        self.lifter = 0.5 + 0.5 * np.cos(math.pi * np.arange(n_cep) / n_cep)

    def _track_f0(self, mag: np.ndarray) -> None:
        """Çerçevenin temel frekansını bulur (H1 güçlendirme ve zarf ayrıntısı bunu kullanır)."""
        ac = np.fft.irfft(mag * mag)
        self._voiced = False
        if ac[0] <= 1e-12:
            return
        seg = ac[self._lag_lo:self._lag_hi] / (ac[0] * self._win_ac)
        best = int(np.argmax(seg))
        peak = float(seg[best])
        if peak < 0.45:
            return
        # Oktav hatasına karşı: en güçlü tepeye yakın güçteki İLK tepe seçilir.
        inner = seg[1:-1]
        strong = np.flatnonzero((inner >= 0.85 * peak) & (inner >= seg[:-2]) & (inner >= seg[2:]))
        if strong.size:
            best = int(strong[0]) + 1
        delta = 0.0
        if 0 < best < seg.size - 1:
            a, b, c = seg[best - 1], seg[best], seg[best + 1]
            denom = a - 2.0 * b + c
            if abs(denom) > 1e-12:
                delta = max(-0.5, min(0.5, 0.5 * (a - c) / denom))
        log_f0 = math.log(self.sample_rate / (self._lag_lo + best + delta))

        if self._f0_log is None:
            self._f0_log = log_f0
        elif abs(log_f0 - self._f0_log) < 0.25 or self._f0_jumps >= 2:
            self._f0_log += 0.5 * (log_f0 - self._f0_log)
            self._f0_jumps = 0
        else:  # tek çerçevelik sıçrama büyük ihtimalle ölçüm hatası: yok say
            self._f0_jumps += 1
            return
        self._voiced = True

        period = self.sample_rate / math.exp(self._f0_log)
        n_cep = int(max(self._cep_min, min(self._cep_max, 0.42 * period)))
        if abs(n_cep - self.n_cep) >= 2:
            self._set_lifter(n_cep)

    def _formant_gain(self, log_env: np.ndarray, src_pos: np.ndarray,
                      formant: float) -> np.ndarray:
        """Kaydırılmış zarfı hedef formant zarfına çeviren kazanç (log alanında, sınırlı).

        `src_pos`: her çıkış bin'inin kaynak spektrumda geldiği konum.
        """
        # Ses yolu tek oranla büyüyüp küçülmez: alt formant (F1) üsttekilerden daha az kayar.
        # Tek oran, büyük kaydırmada sesi kadın/erkek yerine "oyuncak/çocuk" gibi yapar.
        target = np.interp(self.bins / formant ** self.formant_weight, self.bins, log_env)
        moved = np.interp(src_pos, self.bins, log_env)
        log_gain = np.clip(target - moved, -2.76, 1.38)  # -24 dB .. +12 dB
        return np.exp(log_gain)

    def _denoise(self, spec: np.ndarray, mag: np.ndarray,
                 strength: float) -> tuple[np.ndarray, np.ndarray]:
        """MCRA: minimum takibi 'bu bin'de konuşma var mı' kararını verir, gürültü tahmini
        ise konuşmasız bin'lerin özyinelemeli ortalamasıdır (minimumun aşağı sapması olmaz)."""
        psd = mag * mag
        if self._noise_psd is None or self._smooth_psd is None or self._min_psd is None:
            self._noise_psd = psd.copy()
            self._smooth_psd = psd.copy()
            self._min_psd = psd.copy()
            self._nr_gain = np.ones(self.n_bins)
        self._smooth_psd = 0.8 * self._smooth_psd + 0.2 * psd
        # İlk ~0.6 sn hızlı öğrenme, sonra minimum saniyede ~3 dB yavaş yükselir.
        learning = self._nr_frames < 0.6 * self.frames_per_sec
        rise_db = 30.0 if learning else 3.0
        grow = 10.0 ** (rise_db / 10.0 / self.frames_per_sec)
        self._min_psd = np.minimum(self._min_psd * grow, self._smooth_psd)
        speech_absent = self._smooth_psd < SPEECH_RATIO * self._min_psd
        update = 0.85 if learning else 0.95
        self._noise_psd = np.where(speech_absent,
                                   update * self._noise_psd + (1.0 - update) * psd,
                                   self._noise_psd)
        self._nr_frames += 1

        # Decision-directed Wiener (Ephraim-Malah): önsel SNR bir önceki temiz çerçeveden
        # türetilir; gürültüdeki rastgele tepeler kazancı açamaz (müzikal gürültü olmaz).
        noise = self._noise_psd + 1e-12
        snr_post = psd / noise
        if self._clean_psd is None:
            self._clean_psd = np.maximum(psd - noise, 0.0)
        snr_prio = 0.98 * self._clean_psd / noise + 0.02 * np.maximum(snr_post - 1.0, 0.0)
        snr_prio *= 1.5 / (1.0 + 1.5 * strength)  # düşük güçte konuşmayı korur, yüksekte agresif
        floor = 10.0 ** (-(6.0 + 22.0 * strength) / 20.0)
        gain = np.maximum(snr_prio / (1.0 + snr_prio), floor)
        self._clean_psd = gain * gain * psd
        self._nr_gain = gain
        smoothed = np.convolve(gain, (0.25, 0.5, 0.25), mode="same")
        smoothed[0], smoothed[-1] = gain[0], gain[-1]
        return spec * smoothed, mag * smoothed

    def _robot_excitation_table(self, hz: float) -> np.ndarray:
        """1 saniyelik, tam periyodik, Schroeder fazlı harmonik dizi (düşük tepe/RMS oranı).

        Düz darbe dizisi aynı tınıyı verir ama dalga şekli çok sivridir ve limiter'ı aşar.
        """
        f0 = int(round(max(40.0, min(hz, 600.0))))
        if self._robot_table is not None and self._robot_table_hz == f0:
            return self._robot_table
        length = self.sample_rate
        spectrum = np.zeros(length // 2 + 1, dtype=np.complex128)
        harmonics = np.arange(1, (length // 2) // f0 + 1)
        phases = math.pi * harmonics * harmonics / harmonics.size
        spectrum[harmonics * f0] = np.exp(1j * phases)
        table = np.fft.irfft(spectrum, n=length)
        table /= np.sqrt(np.mean(table ** 2)) + 1e-12
        self._robot_table, self._robot_table_hz = table, f0
        return table

    def _robotize(self, out: np.ndarray, log_env: np.ndarray, formant: float,
                  p: EngineParams) -> np.ndarray:
        """Sabit perdeli harmonik diziyi sesin (formantlı) zarfıyla şekillendirir."""
        table = self._robot_excitation_table(p.robot_hz)
        start = (self._sample_clock - (self.n_fft - self.hop)) % table.size
        idx = (start + np.arange(self.n_fft)) % table.size
        excitation = np.fft.rfft(table[idx] * self.window)
        env = np.exp(np.interp(self.bins / formant, self.bins, log_env))
        robot = excitation * env
        e_out = float(np.sum(np.abs(out) ** 2))
        e_rob = float(np.sum(np.abs(robot) ** 2)) + 1e-12
        robot *= math.sqrt(e_out / e_rob)
        return (1.0 - p.robot) * out + p.robot * robot

    def _mix_noise_phase(self, out: np.ndarray, amount: float,
                         weight: np.ndarray | None) -> np.ndarray:
        mag = np.abs(out) if weight is None else np.abs(out) * weight
        noisy = mag * np.exp(1j * self._rng.uniform(-math.pi, math.pi, self.n_bins))
        return (1.0 - amount) * out + amount * noisy

    def _deess(self, out: np.ndarray, amount: float) -> np.ndarray:
        power = np.abs(out) ** 2
        total = float(power.sum()) + 1e-12
        ratio = float(power[self.sib_band].sum()) / total
        threshold = 0.45 - 0.3 * amount
        target = 1.0 if ratio <= threshold else (threshold / ratio) ** (0.5 + amount)
        coef = 0.5 if target < self._deess_gain else 0.08
        self._deess_gain += (target - self._deess_gain) * coef
        if self._deess_gain > 0.999:
            return out
        gain = 1.0 - (1.0 - self._deess_gain) * self.sib_taper
        return out * gain

import numpy as np

from xyrox_voice.audio_io import AdaptiveReader, RingBuffer, db_to_meter


def test_ring_buffer_wraps_and_preserves_order():
    rb = RingBuffer(10)
    rb.write(np.arange(7))
    np.testing.assert_array_equal(rb.read(5), np.arange(5))
    rb.write(np.arange(7, 14))  # sona taşıp başa sarar
    np.testing.assert_array_equal(rb.read(100), np.arange(5, 14))
    assert rb.available == 0


def test_ring_buffer_drops_oldest_on_overflow():
    rb = RingBuffer(5)
    rb.write(np.arange(8))
    assert rb.available == 5
    np.testing.assert_array_equal(rb.read(5), np.arange(3, 8))
    assert rb.dropped == 0  # tek seferde kapasiteden büyük yazımda kırpılır
    rb.write(np.arange(4))
    rb.write(np.arange(4))
    assert rb.dropped == 3


def test_adaptive_reader_waits_for_prefill_then_plays():
    rb = RingBuffer(48000)
    reader = AdaptiveReader(rb, target=1000)
    rb.write(np.ones(500, np.float32))
    assert not reader.read(256).any()
    rb.write(np.ones(600, np.float32))
    out = reader.read(256)
    assert out[0] == 0.0 and out[-1] == 1.0  # yumuşak başlangıç (fade-in)


def test_adaptive_reader_absorbs_clock_drift():
    """Üretici %0.3 hızlı: doluluk sınırsız büyümemeli, kesinti olmamalı."""
    rb = RingBuffer(48000)
    reader = AdaptiveReader(rb, target=1024)
    produced, carry = 0.0, 0.0
    fills = []
    for _ in range(4000):
        carry += 480 * 1.003
        n = int(carry)
        carry -= n
        rb.write(np.full(n, 0.5, np.float32))
        produced += n
        reader.read(480)
        fills.append(rb.available)
    assert reader.underruns == 0
    assert max(fills[-500:]) < 3 * 1024


def test_adaptive_reader_underrun_fades_out():
    rb = RingBuffer(48000)
    reader = AdaptiveReader(rb, target=512)
    rb.write(np.ones(1024, np.float32))
    reader.read(480)
    out = reader.read(1024)  # elde ~544 örnek var: boşalma
    assert reader.underruns == 1
    assert out[-1] == 0.0
    assert reader.target > 512  # hedef büyüdü


def test_adaptive_reader_handles_large_device_blocks():
    """MME benzeri 4410 örneklik bloklarda hedef otomatik büyür, sürekli boşalma olmaz."""
    rb = RingBuffer(48000)
    reader = AdaptiveReader(rb, target=768)
    for _ in range(200):
        rb.write(np.full(4410, 0.5, np.float32))
        reader.read(4410)
    assert reader.target >= 2 * 4410
    assert reader.underruns <= 1


def test_config_language_field_roundtrip(tmp_path):
    from xyrox_voice.config import AppConfig
    path = tmp_path / "s.json"
    AppConfig(language="en").save(path)
    assert AppConfig.load(path).language == "en"
    assert AppConfig().language == ""  # boş = ilk açılışta sistem dili


def test_db_to_meter_range():
    assert db_to_meter(0.0) == 0.0
    assert db_to_meter(1.0) == 1.0
    assert 0.45 < db_to_meter(10 ** (-30 / 20)) < 0.55

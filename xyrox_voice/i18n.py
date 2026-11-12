"""Çok dilli arayüz. Kaynak dil Türkçe'dir; metnin kendisi çeviri anahtarıdır.

Yeni dil eklemek için: LANGUAGES'e kodu ekle ve TRANSLATIONS'a o kodla bir sözlük koy.
Çevirisi olmayan metin Türkçe gösterilir (uygulama asla çökmez).
"""

from __future__ import annotations

import locale
import os
import sys

LANGUAGES: dict[str, str] = {"tr": "Türkçe", "en": "English"}
DEFAULT_LANGUAGE = "tr"
FALLBACK_SYSTEM_LANGUAGE = "en"  # sistem dili desteklenmiyorsa (global kullanıcılar)
_LANG_TURKISH = 0x1F  # Windows LANGID birincil dil kodu

_current = DEFAULT_LANGUAGE

EN: dict[str, str] = {
    # ------------------------------------------------------------ komut satırı (CLI)
    "Gerçek zamanlı, formant kontrollü ses değiştirici":
        "Real-time, formant-aware voice changer",
    "Hazır profilleri listele": "List the built-in and saved voice presets",
    "Ses aygıtlarını listele": "List audio devices, grouped by audio system",
    "Ses dosyasını işleyip WAV olarak kaydet":
        "Process an audio file and save the result as a 24-bit WAV",
    "GİRDİ": "INPUT",
    "ÇIKTI": "OUTPUT",
    "Profil anahtarı (varsayılan m_clean)": "Preset key (default: m_clean)",
    "Perdeyi geçersiz kıl (yarım ton)": "Override the pitch (semitones)",
    "Formantı geçersiz kıl (yarım ton)": "Override the formant (semitones)",
    "Arayüz ve çıktı dili (varsayılan: kayıtlı ayar, yoksa sistem dili)":
        "Interface and output language (default: saved setting, else system language)",
    "Hata olursa tam iz göster": "Show the full traceback on errors",
    "Ses kütüphanesi yüklenemedi: {error}": "Audio library failed to load: {error}",
    "<- önerilen mikrofon": "<- suggested microphone",
    "<- sanal kablo": "<- virtual cable",
    "<- kulaklık": "<- headphones",
    "Girdi dosyası bulunamadı: {path}": "Input file not found: {path}",
    "Bilinmeyen profil: {key} (--list-presets ile bak)":
        "Unknown preset: {key} (see --list-presets)",
    "Tamam: {seconds} sn ses '{name}' ile işlendi -> {dst}":
        "Done: processed {seconds} s of audio with '{name}' -> {dst}",
    "Hata: {error}": "Error: {error}",
    "Uygulama başlatılamadı:\n\n{error}": "The application could not start:\n\n{error}",
    # ------------------------------------------------------------ çekirdek mesajlar
    "En az bir çıkış seç: sanal kablo veya kulaklık.":
        "Select at least one output: virtual cable or headphones.",
    "İşleme hatası: {error}": "Processing error: {error}",
    "Kullanıcı profilleri okunamadı: {error}": "Could not read user profiles: {error}",
    "Kendi kaydettiğin profil": "A profile you saved",
    # ------------------------------------------------------------ genel arayüz
    "BAŞLAT": "START",
    "DURDUR": "STOP",
    "Aktif": "Active",
    "Kapalı": "Off",
    "kendini duyuyorsun": "you hear yourself",
    "sadece karşı taraf duyar": "only the other side hears it",
    "GECİKME": "LATENCY",
    "TAMPON": "BUFFER",
    "İyi": "Good",
    "Orta": "Fair",
    "Kötü": "Poor",
    "GİRİŞ": "INPUT",
    "ÇIKIŞ": "OUTPUT",
    "Kendimi duy (kulaklık)": "Hear myself (headphones)",
    "Ham ses (A/B karşılaştır)": "Raw voice (A/B compare)",
    "Mikrofonu sustur": "Mute microphone",
    "🎙  5 sn kaydet ve dinle": "🎙  Record 5 s and listen",
    "🎚  Oda gürültüsünü öğren": "🎚  Learn room noise",
    "📁  Ses dosyası dönüştür": "📁  Convert audio file",
    "SES AYGITLARI": "AUDIO DEVICES",
    "Ses sistemi": "Audio system",
    "Mikrofon": "Microphone",
    "Sanal mikrofon (Discord/oyun buradan duyar)": "Virtual microphone (Discord/games listen here)",
    "Kulaklık (kendini duymak için)": "Headphones (to hear yourself)",
    "Motor kalitesi": "Engine quality",
    "↻  Aygıtları yenile": "↻  Refresh devices",
    "⚠  VB-Cable bulunamadı: Kur": "⚠  VB-Cable not found: Install",
    "KISAYOLLAR (her yerde çalışır)": "HOTKEYS (work everywhere)",
    "Ham ses": "Raw voice",
    "Sustur": "Mute",
    "Aç/Kapat": "On/Off",
    "↺ Sıfırla": "↺ Reset",
    "🗑 Sil": "🗑 Delete",
    "★ Profili kaydet": "★ Save profile",
    "🔍  Ses ara…": "🔍  Search voices…",
    "SES KİMLİĞİ": "VOICE IDENTITY",
    "Noktayı sürükle • çift tık = doğal ses": "Drag the dot • double-click = natural voice",
    "Kadın / Çocuk": "Female / Child",
    "Dev / Kalın": "Giant / Deep",
    "Uzaylı": "Alien",
    "Tuhaf": "Odd",
    "formant →": "formant →",
    "perde": "pitch",
    "NETLİK & TEMİZLİK": "CLARITY & CLEANUP",
    "KARAKTER": "CHARACTER",
    "EFEKTLER": "EFFECTS",
    "ÇIKIŞ & DİNAMİK": "OUTPUT & DYNAMICS",
    "özelleştirildi": "customized",
    # ------------------------------------------------------------ bildirimler
    "Kısayol alınamadı (başka program kullanıyor): {keys}":
        "Hotkey unavailable (used by another program): {keys}",
    "Ses sistemi yüklenemedi: {error}": "Audio system failed to load: {error}",
    "Bu filtrede ses yok. 'Benim' sekmesi için önce bir profil kaydet.":
        "No voices match this filter. Save a profile first to fill the 'Mine' tab.",
    "Profil varsayılan ayarlarına döndü.": "Profile restored to its defaults.",
    "Profili kaydet": "Save profile",
    "Profil adı (aynı ad varsa üzerine yazılır):":
        "Profile name (an existing name is overwritten):",
    "{name} tabanlı özel profil": "Custom profile based on {name}",
    "Kaydedilemedi": "Could not save",
    "Profil dosyası yazılamadı:\n{error}": "Could not write the profile file:\n{error}",
    "'{name}' kaydedildi (Benim sekmesi).": "'{name}' saved (Mine tab).",
    "Profili sil": "Delete profile",
    "'{name}' silinsin mi?": "Delete '{name}'?",
    "Silinemedi": "Could not delete",
    "Profil silindi.": "Profile deleted.",
    "Aygıt listesi yenilendi.": "Device list refreshed.",
    "Motor: {label} (motor gecikmesi ≈ {ms} ms)": "Engine: {label} (engine latency ≈ {ms} ms)",
    "Ses sistemi yok": "No audio system",
    "Mikrofon yok": "No microphone",
    "Lütfen bir mikrofon seç.": "Please select a microphone.",
    "Çıkış yok": "No output",
    "Sanal mikrofon (VB-Cable) veya kulaklık seç.\n"
    "Sesi Discord/oyuna vermek için VB-Cable gerekir.":
        "Select a virtual microphone (VB-Cable) or headphones.\n"
        "VB-Cable is required to send your voice to Discord/games.",
    "Ses başlatılamadı": "Could not start audio",
    "{error}\n\nÖneriler:\n• Mikrofonu başka bir program 'özel modda' kullanıyor "
    "olabilir.\n• 'Ses sistemi' menüsünden MME veya DirectSound'u dene.\n"
    "• Aygıtları yenile ve tekrar dene.":
        "{error}\n\nSuggestions:\n• Another program may be using the microphone in "
        "'exclusive mode'.\n• Try MME or DirectSound in the 'Audio system' menu.\n"
        "• Refresh the devices and try again.",
    "Kulaklık açılamadı": "Could not open headphones",
    "Ham ses: karşı taraf gerçek sesini duyuyor.": "Raw voice: the other side hears your real voice.",
    "Ses değiştirici yeniden devrede.": "Voice changer is active again.",
    "Mikrofon susturuldu.": "Microphone muted.",
    "Mikrofon açık.": "Microphone on.",
    "2-3 saniye sessiz kal: oda gürültüsü öğreniliyor…":
        "Stay silent for 2-3 seconds: learning the room noise…",
    "Önce BAŞLAT'a bas, sonra kaydet.": "Press START first, then record.",
    "Kaydı dinlemek için bir kulaklık seç.": "Select headphones to listen to the recording.",
    "Şimdi konuş: {seconds} saniye kaydediliyor…": "Speak now: recording {seconds} seconds…",
    "Kayıt çalınamadı: {error}": "Could not play the recording: {error}",
    "Kayıt çalınıyor: karşı taraf seni böyle duyuyor.":
        "Playing the recording: this is how others hear you.",
    "Kurulum dosyası bulunamadı.\nResmi siteden indir: https://vb-audio.com/Cable/":
        "Installer not found.\nDownload it from the official site: https://vb-audio.com/Cable/",
    "VB-Cable kurulumu": "VB-Cable setup",
    "Sanal ses kablosu sürücüsü kurulacak (yönetici izni ister).\n"
    "Açılan pencerede 'Install Driver'a bas, sonra bilgisayarı "
    "yeniden başlat.\n\nDevam edilsin mi?":
        "The virtual audio cable driver will be installed (needs administrator rights).\n"
        "Click 'Install Driver' in the window that opens, then restart the "
        "computer.\n\nContinue?",
    "Kurulum başlatılamadı (izin verilmedi olabilir).":
        "Could not start the installer (permission may have been denied).",
    "Dönüştürülecek ses dosyası": "Audio file to convert",
    "Ses dosyaları": "Audio files",
    "Tüm dosyalar": "All files",
    "Kaydet": "Save",
    "Dönüştürülüyor…": "Converting…",
    "{seconds} sn ses kaydedildi: {path}": "{seconds} s of audio saved: {path}",
    "Dönüştürme başarısız: {error}": "Conversion failed: {error}",
    "Ses aygıtı bağlantısı koptu. Aygıtları yenileyip tekrar başlat.":
        "Audio device disconnected. Refresh the devices and start again.",
    "Aygıt bağlantısı koptu, yeniden bağlanılıyor ({n}/3)…":
        "Device disconnected, reconnecting ({n}/3)…",
    # ------------------------------------------------------------ kalite modları
    "Maksimum Netlik": "Maximum Clarity",
    "Stüdyo Kalite": "Studio Quality",
    "Dengeli": "Balanced",
    "Düşük Gecikme": "Low Latency",
    # ------------------------------------------------------------ parametreler
    "Perde": "Pitch",
    "Formant (gırtlak tınısı)": "Formant (throat timbre)",
    "Gürültü Engelleme": "Noise Suppression",
    "Sessizlik Kapısı": "Noise Gate",
    "Robot": "Robot",
    "Robot Perdesi": "Robot Pitch",
    "Fısıltı": "Whisper",
    "Nefes / Hava": "Breath / Air",
    "Vibrato": "Vibrato",
    "Vibrato Hızı": "Vibrato Rate",
    "De-esser (sert S)": "De-esser (harsh S)",
    "Katman Perdesi": "Layer Pitch",
    "Katman (harmonizer)": "Layer (harmonizer)",
    "Temel Ton (yumuşaklık)": "Fundamental (softness)",
    "Alçak Kesici": "Low Cut",
    "Tiz Kesici": "High Cut",
    "Bas": "Bass",
    "Gövde": "Body",
    "Netlik": "Clarity",
    "Parlaklık": "Brightness",
    "Distorsiyon": "Distortion",
    "Bitcrush (0=kapalı)": "Bitcrush (0=off)",
    "Chorus": "Chorus",
    "Phaser": "Phaser",
    "Eko": "Echo",
    "Eko Süresi": "Echo Time",
    "Eko Tekrarı": "Echo Feedback",
    "Yankı (oda)": "Reverb (room)",
    "Oda Boyutu": "Room Size",
    "Kompresör": "Compressor",
    "Çıkış Seviyesi": "Output Level",
    # ------------------------------------------------------------ kategoriler
    "Tümü": "All",
    "Kadın": "Female",
    "Erkek": "Male",
    "Karakter": "Character",
    "Efekt": "Effect",
    "Benim": "Mine",
    # ------------------------------------------------------------ hazır sesler
    "Doğal Kadın": "Natural Female",
    "Gerçekçi günlük kadın sesi: perde, tını ve temel ton birlikte değişir":
        "Realistic everyday female voice: pitch, timbre and fundamental change together",
    "Genç Kız": "Young Woman",
    "Enerjik, parlak ve tatlı genç kız tonu": "Energetic, bright and sweet young woman",
    "Olgun Kadın": "Mature Female",
    "Tok, zarif ve güven veren olgun kadın sesi": "Full, elegant and confident mature woman",
    "Kadife Kadın": "Velvet Female",
    "Hafif buğulu, nefesli ve yumuşak kadın tonu": "Slightly husky, breathy and soft female tone",
    "Anime Kızı": "Anime Girl",
    "Çok parlak, sevimli anime karakter sesi": "Very bright, cute anime character voice",
    "Spiker Kadın": "Female Announcer",
    "Yayın kalitesinde, kompresörlü net kadın spiker":
        "Broadcast-quality, compressed and clear female announcer",
    "Fısıltı (ASMR)": "Whisper (ASMR)",
    "Yakın mikrofon hissi veren yumuşak kadın fısıltısı":
        "Soft female whisper with a close-mic feel",
    "Küçük Kız": "Little Girl",
    "Çocuksu, ince ve masum kız çocuğu sesi": "Childlike, thin and innocent little girl voice",
    "Stüdyo Erkek": "Studio Male",
    "Kendi sesin, ama stüdyo kalitesinde: gürültüsüz, net, dolgun":
        "Your own voice in studio quality: noise-free, clear, full",
    "Kalın Erkek": "Deep Male",
    "Tok, güçlü ve dolgun bariton erkek sesi": "Full, strong baritone male voice",
    "Derin Bas": "Deep Bass",
    "Çok kalın, yerden gelen derin bas ses": "Very deep, rumbling bass voice",
    "Radyo DJ": "Radio DJ",
    "Gece FM programcısı: yakın, sıcak ve kompresörlü": "Late-night FM host: close, warm, compressed",
    "Fragman Sesi": "Trailer Voice",
    "Sinema fragmanı anlatıcısı gibi devasa ve sinematik":
        "Huge and cinematic, like a movie trailer narrator",
    "Genç Erkek": "Young Male",
    "Daha genç, enerjik delikanlı sesi": "A younger, energetic lad",
    "Yaşlı Adam": "Old Man",
    "Titrek, nefesli ve yorgun yaşlı adam sesi": "Shaky, breathy and tired old man",
    "Kadından Erkeğe": "Female to Male",
    "Kadın sesini inandırıcı bir erkek sesine çevirir":
        "Turns a female voice into a convincing male voice",
    "Klasik metalik, tek perdeli robot": "Classic metallic, single-pitch robot",
    "Yapay Zekâ": "AI Assistant",
    "Sakin ve kusursuz yapay zekâ asistanı": "Calm and flawless AI assistant",
    "Siborg": "Cyborg",
    "Yarı insan yarı makine, sert ve dijital": "Half human, half machine: harsh and digital",
    "Şeytan": "Demon",
    "Alt oktav katmanlı, boğuk ve korkutucu iblis":
        "Layered an octave down: muffled and frightening demon",
    "Dev": "Giant",
    "Mağarada yaşayan devasa yaratık": "A huge creature living in a cave",
    "Canavar": "Monster",
    "Hırıltılı, vahşi ork/canavar sesi": "Growling, savage orc/monster voice",
    "Karanlık Lord": "Dark Lord",
    "Maskeli, metalik ve otoriter kötü karakter": "Masked, metallic and commanding villain",
    "Uyumsuz formantlı, dalgalanan uzaylı sesi": "Wavering alien voice with mismatched formants",
    "Hayalet": "Ghost",
    "Fısıltılı, uzak ve ürpertici hayalet": "Whispery, distant and eerie ghost",
    "Sincap": "Chipmunk",
    "Helyum çekmiş gibi komik sincap sesi": "Funny helium-like chipmunk voice",
    "Çocuk": "Child",
    "Okul çağındaki küçük çocuk sesi": "A school-age child's voice",
    "Anonim Hacker": "Anonymous Hacker",
    "Kimliği gizlenmiş, dijital bozulmalı anonim ses":
        "Identity-masked anonymous voice with digital distortion",
    "Karıncalı Kalın Ses": "Static Deep Voice",
    "Kimlik gizleyen röportajlardaki gibi: cızırtılı ve kalın":
        "Like an identity-protected interview: staticky and deep",
    "Telefon": "Telephone",
    "Eski hat telefon görüşmesi": "An old landline phone call",
    "Telsiz": "Walkie-Talkie",
    "Taktik askeri telsiz, cızırtılı ve sıkışık": "Tactical military radio: crackly and squeezed",
    "Megafon": "Megaphone",
    "Sokak megafonu, sert ve yüksek": "Street megaphone: harsh and loud",
    "Mağara": "Cave",
    "Taş duvarlardan dönen yankı": "Echo bouncing off stone walls",
    "Konser Salonu": "Concert Hall",
    "Büyük salonda konuşma, geniş ve görkemli": "Speaking in a large hall: wide and grand",
    "Su Altı": "Underwater",
    "Suyun altından gelen boğuk ses": "A muffled voice from under the water",
    "Koro": "Choir",
    "Arkada oktav katmanlı kalabalık koro": "A crowded choir with an octave layer behind",
    "Eski Radyo": "Old Radio",
    "1940'lar radyo yayını": "A 1940s radio broadcast",
}

TRANSLATIONS: dict[str, dict[str, str]] = {"en": EN}


def set_language(code: str) -> str:
    """Arayüz dilini ayarlar; bilinmeyen kodda varsayılana döner. Geçerli olan kodu döndürür."""
    global _current
    _current = code if code in LANGUAGES else DEFAULT_LANGUAGE
    return _current


def get_language() -> str:
    return _current


def detect_system_language() -> str:
    """İşletim sisteminin arayüz dilinden uygulama dilini seçer: Türkçe ise tr, değilse en."""
    if sys.platform == "win32":
        try:
            import ctypes
            langid = ctypes.windll.kernel32.GetUserDefaultUILanguage()
            return "tr" if (langid & 0x3FF) == _LANG_TURKISH else FALLBACK_SYSTEM_LANGUAGE
        except (AttributeError, OSError):
            pass
    candidates = [os.environ.get(var, "") for var in ("LC_ALL", "LC_MESSAGES", "LANG")]
    try:
        candidates.append(locale.getlocale()[0] or "")
    except (ValueError, locale.Error):
        pass
    for value in candidates:
        if value:
            return "tr" if value.lower().startswith(("tr", "turkish")) else FALLBACK_SYSTEM_LANGUAGE
    return FALLBACK_SYSTEM_LANGUAGE


def resolve_language(saved: str | None) -> str:
    """Kayıtlı dil geçerliyse onu, değilse (ilk açılış) sistem dilini döndürür."""
    return saved if saved in LANGUAGES else detect_system_language()


def tr(text: str) -> str:
    """Metni geçerli dile çevirir; çevirisi yoksa metnin kendisini (Türkçe) döndürür."""
    if _current == DEFAULT_LANGUAGE:
        return text
    return TRANSLATIONS.get(_current, {}).get(text, text)

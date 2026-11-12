"""Xyron Voice Changer giriş noktası.

Argümansız çalışırsa arayüzü açar. CLI örnekleri:
  python main.py --list-presets
  python main.py --list-devices
  python main.py --render girdi.wav cikti.wav --preset f_natural
  python main.py --render girdi.wav cikti.wav --pitch 5 --formant 2
  python main.py --lang en --help
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from xyrox_voice import APP_NAME, __version__
from xyrox_voice.i18n import LANGUAGES, resolve_language, set_language
from xyrox_voice.i18n import tr as _

EXIT_OK, EXIT_ERROR, EXIT_USAGE = 0, 1, 2
QUALITY_CHOICES = ("max", "studio", "balanced", "low_latency")


def init_language(argv: list[str] | None) -> str:
    """Dil sırası: --lang > kayıtlı ayar > sistem dili. Yardım metni bundan sonra kurulur."""
    # Ön ayrıştırıcı hata vermez; geçersiz --lang değerini asıl ayrıştırıcı düzgünce raporlar.
    pre = argparse.ArgumentParser(add_help=False)
    pre.add_argument("--lang")
    known, _rest = pre.parse_known_args(argv)
    if known.lang in LANGUAGES:
        return set_language(known.lang)
    try:
        from xyrox_voice.config import AppConfig, app_data_dir
        saved = AppConfig.load(app_data_dir() / "settings.json").language
    except Exception:  # ayar okunamasa da CLI çalışsın
        saved = ""
    return set_language(resolve_language(saved))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="xyron-voice",
        description=f"{APP_NAME} v{__version__}: "
                    + _("Gerçek zamanlı, formant kontrollü ses değiştirici"))
    parser.add_argument("--list-presets", action="store_true", help=_("Hazır profilleri listele"))
    parser.add_argument("--list-devices", action="store_true", help=_("Ses aygıtlarını listele"))
    parser.add_argument("--render", nargs=2, metavar=(_("GİRDİ"), _("ÇIKTI")),
                        help=_("Ses dosyasını işleyip WAV olarak kaydet"))
    parser.add_argument("--preset", default="m_clean",
                        help=_("Profil anahtarı (varsayılan m_clean)"))
    parser.add_argument("--pitch", type=float, help=_("Perdeyi geçersiz kıl (yarım ton)"))
    parser.add_argument("--formant", type=float, help=_("Formantı geçersiz kıl (yarım ton)"))
    parser.add_argument("--quality", default="studio", choices=QUALITY_CHOICES,
                        help=_("Motor kalitesi"))
    parser.add_argument("--lang", choices=tuple(LANGUAGES),
                        help=_("Arayüz ve çıktı dili (varsayılan: kayıtlı ayar, yoksa sistem dili)"))
    parser.add_argument("--version", action="version", version=f"{APP_NAME} {__version__}")
    parser.add_argument("--debug", action="store_true", help=_("Hata olursa tam iz göster"))
    return parser


def all_presets() -> dict:
    """Hazır profiller + kullanıcının arayüzde kaydettikleri."""
    from xyrox_voice.config import app_data_dir
    from xyrox_voice.presets import PresetStore
    return PresetStore(app_data_dir() / "presets.json").all()


def cmd_list_presets() -> int:
    for p in all_presets().values():
        print(f"{p.key:<16} {_(p.category):<9} {_(p.name):<20} pitch={p.params.pitch:+.1f} "
              f"formant={p.params.formant:+.1f}  {_(p.desc)}")
    return EXIT_OK


def cmd_list_devices() -> int:
    from xyrox_voice.audio_io import SOUNDDEVICE_ERROR, default_devices, list_devices, list_hostapis
    if SOUNDDEVICE_ERROR:
        print(_("Ses kütüphanesi yüklenemedi: {error}").format(error=SOUNDDEVICE_ERROR),
              file=sys.stderr)
        return EXIT_ERROR
    for api in list_hostapis():
        inputs, outputs = list_devices(api)
        mic, cable, phones = default_devices(api)
        print(f"== {api}")
        for d in inputs:
            tag = "  " + _("<- önerilen mikrofon") if d == mic else ""
            print(f"  IN  [{d.index:>2}] {d.name}{tag}")
        for d in outputs:
            tag = ("  " + _("<- sanal kablo") if d == cable
                   else "  " + _("<- kulaklık") if d == phones else "")
            print(f"  OUT [{d.index:>2}] {d.name}{tag}")
    return EXIT_OK


def cmd_render(args: argparse.Namespace) -> int:
    from xyrox_voice.render import render_file
    src, dst = Path(args.render[0]), Path(args.render[1])
    if not src.is_file():
        print(_("Girdi dosyası bulunamadı: {path}").format(path=src), file=sys.stderr)
        return EXIT_USAGE
    preset = all_presets().get(args.preset)
    if preset is None:
        print(_("Bilinmeyen profil: {key} (--list-presets ile bak)").format(key=args.preset),
              file=sys.stderr)
        return EXIT_USAGE
    params = preset.params
    if args.pitch is not None:
        params = params.with_value("pitch", args.pitch)
    if args.formant is not None:
        params = params.with_value("formant", args.formant)
    seconds = render_file(src, dst, params, args.quality)
    print(_("Tamam: {seconds} sn ses '{name}' ile işlendi -> {dst}").format(
        seconds=f"{seconds:.1f}", name=_(preset.name), dst=dst))
    return EXIT_OK


def safe_console() -> None:
    """Eski kod sayfalı konsolda/yönlendirmede (cp1252) Türkçe harf yüzünden çökmesin."""
    for stream in (sys.stdout, sys.stderr):
        if stream is not None and hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(errors="replace")
            except (OSError, ValueError):
                pass


def main(argv: list[str] | None = None) -> int:
    safe_console()
    init_language(argv)
    args = build_parser().parse_args(argv)
    try:
        if args.list_presets:
            return cmd_list_presets()
        if args.list_devices:
            return cmd_list_devices()
        if args.render:
            return cmd_render(args)
        from xyrox_voice.ui import run_app
        return run_app(args.lang)
    except KeyboardInterrupt:
        return EXIT_ERROR
    except Exception as exc:  # CLI'da ham stack trace yerine anlaşılır mesaj
        if args.debug:
            raise
        if sys.stderr is not None:
            print(_("Hata: {error}").format(error=exc), file=sys.stderr)
        else:  # pencereli EXE: konsol yok, hatayı pencereyle göster
            _show_error_dialog(f"{type(exc).__name__}: {exc}")
        return EXIT_ERROR


def _show_error_dialog(message: str) -> None:
    try:
        import tkinter
        from tkinter import messagebox
        root = tkinter.Tk()
        root.withdraw()
        messagebox.showerror(APP_NAME, _("Uygulama başlatılamadı:\n\n{error}").format(error=message))
        root.destroy()
    except Exception:
        pass


if __name__ == "__main__":
    sys.exit(main())

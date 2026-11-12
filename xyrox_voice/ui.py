"""Xyron Voice Changer arayüzü (customtkinter, koyu modern tema, çok dilli)."""

from __future__ import annotations

import ctypes
import queue
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox
from typing import Callable

import customtkinter as ctk

from . import APP_NAME, __version__
from .audio_io import (SOUNDDEVICE_ERROR, AudioRouter, Device, db_to_meter, default_devices,
                       find_device, is_cable, list_devices, list_hostapis)
from .config import AppConfig, app_data_dir
from .hotkeys import HOTKEYS, GlobalHotkeys
from .i18n import LANGUAGES, get_language, resolve_language, set_language
from .i18n import tr as _
from .params import PARAM_SPECS, VoiceParams, format_param
from .presets import (CATEGORIES, CATEGORY_COLORS, DEFAULT_PRESET_KEY, Preset, PresetStore)
from .processor import QUALITY_MODES, VoiceProcessor

# ------------------------------------------------------------------ tema
BG = "#0A0B10"
PANEL = "#11131B"
CARD = "#171A25"
CARD_HOVER = "#1E2232"
BORDER = "#262A3B"
TEXT = "#E9EBF3"
MUTED = "#8B91A8"
DIM = "#5A6078"
ACCENT = "#7C5CFF"
ACCENT_HOVER = "#6A4BEB"
CYAN = "#00D4FF"
GOOD = "#2EE6A8"
BAD = "#FF4D6D"
WARN = "#FFC857"
FONT = "Segoe UI"
EMOJI_FONT = "Segoe UI Emoji"
NO_DEVICE = "—"
ALL_CATEGORY = "Tümü"
TEST_SECONDS = 5.0

# (başlık, parametreler, açık mı) — başlıklar ekrana basılırken çevrilir.
SECTIONS: list[tuple[str, list[str], bool]] = [
    ("NETLİK & TEMİZLİK", ["denoise", "presence", "bass", "air", "body", "deess"], True),
    ("KARAKTER", ["h1", "breath", "whisper", "robot", "robot_hz", "vibrato", "vibrato_rate",
                  "layer_mix", "layer_pitch"], False),
    ("EFEKTLER", ["reverb", "room", "delay", "delay_time", "delay_feedback", "chorus", "phaser",
                  "drive", "bitcrush"], False),
    ("ÇIKIŞ & DİNAMİK", ["volume", "comp", "gate_db", "hpf", "lpf"], False),
]
HOTKEY_NAMES = {"bypass": "Ham ses", "mute": "Sustur", "power": "Aç/Kapat"}
HEALTH_LABELS = {"iyi": "İyi", "orta": "Orta", "kötü": "Kötü"}


def resource_dir() -> Path:
    """PyInstaller içindeyken paketlenmiş dosyaların, değilse projenin kökü."""
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))


def install_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


# ================================================================== bileşenler
class ParamSlider(ctk.CTkFrame):
    def __init__(self, master, name: str, on_change: Callable[[str, float], None],
                 fonts: dict[str, ctk.CTkFont]) -> None:
        super().__init__(master, fg_color="transparent")
        self.name = name
        self.on_change = on_change
        lo, hi, step, label, _unit = PARAM_SPECS[name]
        self.columnconfigure(0, weight=1)
        ctk.CTkLabel(self, text=_(label), font=fonts["small"], text_color=MUTED,
                     anchor="w").grid(row=0, column=0, sticky="w")
        self.value_lbl = ctk.CTkLabel(self, text="", font=fonts["small_bold"], text_color=TEXT,
                                      anchor="e")
        self.value_lbl.grid(row=0, column=1, sticky="e")
        steps = max(1, round((hi - lo) / step))
        self.slider = ctk.CTkSlider(self, from_=lo, to=hi, number_of_steps=steps, height=16,
                                    button_length=0, progress_color=ACCENT, fg_color=BORDER,
                                    button_color=TEXT, button_hover_color=CYAN,
                                    command=self._on_slide)
        self.slider.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(0, 6))

    def _on_slide(self, value: float) -> None:
        self.value_lbl.configure(text=format_param(self.name, value))
        self.on_change(self.name, value)

    def set(self, value: float) -> None:
        self.slider.set(value)
        self.value_lbl.configure(text=format_param(self.name, value))


class Section(ctk.CTkFrame):
    """Başlığına tıklanınca açılıp kapanan ayar bölümü."""

    def __init__(self, master, title: str, fonts: dict[str, ctk.CTkFont], opened: bool) -> None:
        super().__init__(master, fg_color=CARD, corner_radius=12)
        self.title = title
        self.opened = opened
        self.columnconfigure(0, weight=1)
        self.header = ctk.CTkButton(self, text="", anchor="w", fg_color="transparent",
                                    hover_color=CARD_HOVER, text_color=TEXT,
                                    font=fonts["section"], height=34, command=self.toggle)
        self.header.grid(row=0, column=0, sticky="ew", padx=4, pady=4)
        self.body = ctk.CTkFrame(self, fg_color="transparent")
        self.body.columnconfigure(0, weight=1)
        self._refresh()

    def _refresh(self) -> None:
        self.header.configure(text=("▾  " if self.opened else "▸  ") + self.title)
        if self.opened:
            self.body.grid(row=1, column=0, sticky="ew", padx=14, pady=(0, 10))
        else:
            self.body.grid_forget()

    def toggle(self) -> None:
        self.opened = not self.opened
        self._refresh()


class XYPad(ctk.CTkFrame):
    """X ekseni formant, Y ekseni perde. Noktayı sürükleyerek sesin kimliğini değiştir."""

    F_RANGE = 8.0
    P_RANGE = 12.0

    def __init__(self, master, on_move: Callable[[float, float], None]) -> None:
        super().__init__(master, fg_color=BG, corner_radius=12)
        self.on_move = on_move
        self.canvas = tk.Canvas(self, height=180, bg=BG, highlightthickness=0, cursor="hand2")
        self.canvas.pack(fill="both", expand=True, padx=6, pady=6)
        self.pitch = 0.0
        self.formant = 0.0
        self.canvas.bind("<Configure>", lambda e: self.redraw())
        self.canvas.bind("<B1-Motion>", self._drag)
        self.canvas.bind("<Button-1>", self._drag)
        self.canvas.bind("<Double-Button-1>", lambda e: self._emit(0.0, 0.0))

    def _geom(self) -> tuple[int, int, int]:
        return max(self.canvas.winfo_width(), 50), max(self.canvas.winfo_height(), 50), 14

    def redraw(self) -> None:
        c = self.canvas
        c.delete("all")
        w, h, pad = self._geom()
        for i in range(1, 8):
            x = pad + (w - 2 * pad) * i / 8
            y = pad + (h - 2 * pad) * i / 8
            c.create_line(x, pad, x, h - pad, fill="#161927")
            c.create_line(pad, y, w - pad, y, fill="#161927")
        c.create_line(w / 2, pad, w / 2, h - pad, fill=BORDER, width=1)
        c.create_line(pad, h / 2, w - pad, h / 2, fill=BORDER, width=1)
        c.create_rectangle(pad, pad, w - pad, h - pad, outline=BORDER)
        labels = [(w - pad - 4, pad + 4, "ne", _("Kadın / Çocuk")),
                  (pad + 4, h - pad - 4, "sw", _("Dev / Kalın")),
                  (pad + 4, pad + 4, "nw", _("Uzaylı")),
                  (w - pad - 4, h - pad - 4, "se", _("Tuhaf"))]
        for x, y, anchor, text in labels:
            c.create_text(x, y, text=text, anchor=anchor, fill=DIM, font=(FONT, 8))
        c.create_text(w / 2, h - 2, text=_("formant →"), anchor="s", fill=DIM, font=(FONT, 8))
        c.create_text(4, h / 2, text=_("perde"), anchor="w", fill=DIM, font=(FONT, 8), angle=90)
        x = pad + (self.formant + self.F_RANGE) / (2 * self.F_RANGE) * (w - 2 * pad)
        y = pad + (self.P_RANGE - self.pitch) / (2 * self.P_RANGE) * (h - 2 * pad)
        c.create_line(w / 2, h / 2, x, y, fill=ACCENT, width=2)
        c.create_oval(x - 14, y - 14, x + 14, y + 14, fill="", outline="#3A2E7A", width=6)
        c.create_oval(x - 8, y - 8, x + 8, y + 8, fill=CYAN, outline=TEXT, width=2)

    def _drag(self, event) -> None:
        w, h, pad = self._geom()
        fx = min(1.0, max(0.0, (event.x - pad) / (w - 2 * pad)))
        fy = min(1.0, max(0.0, (event.y - pad) / (h - 2 * pad)))
        formant = round((fx * 2 - 1) * self.F_RANGE, 1)
        pitch = round((1 - fy * 2) * self.P_RANGE, 1)
        self._emit(pitch, formant)

    def _emit(self, pitch: float, formant: float) -> None:
        self.set(pitch, formant)
        self.on_move(pitch, formant)

    def set(self, pitch: float, formant: float) -> None:
        self.pitch = max(-self.P_RANGE, min(self.P_RANGE, pitch))
        self.formant = max(-self.F_RANGE, min(self.F_RANGE, formant))
        self.redraw()


class Visualizer(ctk.CTkFrame):
    """Canlı çıkış spektrumu + giriş/çıkış seviye göstergeleri."""

    N_BANDS = 48

    def __init__(self, master) -> None:
        super().__init__(master, fg_color=PANEL, corner_radius=16, border_width=1,
                         border_color=BORDER)
        self.canvas = tk.Canvas(self, height=130, bg=PANEL, highlightthickness=0)
        self.canvas.pack(fill="both", expand=True, padx=14, pady=12)
        self.display = [0.0] * self.N_BANDS
        self.bars: list[int] = []
        self.meter_in = self.meter_out = 0
        self.canvas.bind("<Configure>", lambda e: self._layout())

    @staticmethod
    def _blend(a: str, b: str, t: float) -> str:
        ca = [int(a[i:i + 2], 16) for i in (1, 3, 5)]
        cb = [int(b[i:i + 2], 16) for i in (1, 3, 5)]
        return "#" + "".join(f"{int(x + (y - x) * t):02x}" for x, y in zip(ca, cb))

    def _layout(self) -> None:
        c = self.canvas
        c.delete("all")
        w, h = max(c.winfo_width(), 100), max(c.winfo_height(), 60)
        self.spec_h = h - 26
        gap = 3
        bw = (w - gap * (self.N_BANDS - 1)) / self.N_BANDS
        self.bars = []
        for i in range(self.N_BANDS):
            x0 = i * (bw + gap)
            color = self._blend(ACCENT, CYAN, i / (self.N_BANDS - 1))
            self.bars.append(c.create_rectangle(x0, self.spec_h, x0 + bw, self.spec_h,
                                                fill=color, width=0))
        y = h - 12
        label_w = 54
        half = (w - 2 * label_w - 14) / 2
        c.create_text(0, y, text=_("GİRİŞ"), anchor="w", fill=DIM, font=(FONT, 8, "bold"))
        c.create_rectangle(label_w, y - 3, label_w + half, y + 3, fill="#1B1F2D", width=0)
        self.meter_in = c.create_rectangle(label_w, y - 3, label_w, y + 3, fill=GOOD, width=0)
        x2 = label_w + half + 14
        c.create_text(x2, y, text=_("ÇIKIŞ"), anchor="w", fill=DIM, font=(FONT, 8, "bold"))
        c.create_rectangle(x2 + label_w, y - 3, w, y + 3, fill="#1B1F2D", width=0)
        self.meter_out = c.create_rectangle(x2 + label_w, y - 3, x2 + label_w, y + 3, fill=CYAN,
                                            width=0)
        self._meter_geom = (label_w, half, x2 + label_w, w - (x2 + label_w), y)

    def update_view(self, bands, level_in: float, level_out: float) -> None:
        if not self.bars:
            return
        c = self.canvas
        for i, bar in enumerate(self.bars):
            v = float(bands[i]) if i < len(bands) else 0.0
            self.display[i] = max(v, self.display[i] * 0.82)
            x0, _y0, x1, _y1 = c.coords(bar)
            top = self.spec_h - max(2.0, self.display[i] * (self.spec_h - 4))
            c.coords(bar, x0, top, x1, self.spec_h)
        x_in, w_in, x_out, w_out, y = self._meter_geom
        m_in, m_out = db_to_meter(level_in), db_to_meter(level_out)
        c.coords(self.meter_in, x_in, y - 3, x_in + w_in * m_in, y + 3)
        c.coords(self.meter_out, x_out, y - 3, x_out + w_out * m_out, y + 3)
        c.itemconfigure(self.meter_out, fill=BAD if level_out > 0.95 else CYAN)


class PresetCard(ctk.CTkFrame):
    def __init__(self, master, preset: Preset, on_click: Callable[[str], None],
                 fonts: dict[str, ctk.CTkFont]) -> None:
        super().__init__(master, fg_color=CARD, corner_radius=14, border_width=2,
                         border_color=CARD, width=210, height=112)
        self.grid_propagate(False)
        self.preset = preset
        self.selected = False
        color = CATEGORY_COLORS.get(preset.category, ACCENT)
        self.color = color
        self.columnconfigure(1, weight=1)
        icon = ctk.CTkLabel(self, text=preset.icon, font=fonts["emoji"], width=44)
        icon.grid(row=0, column=0, rowspan=2, padx=(12, 6), pady=(12, 0), sticky="n")
        name = ctk.CTkLabel(self, text=_(preset.name), font=fonts["card_title"], text_color=TEXT,
                            anchor="w")
        name.grid(row=0, column=1, sticky="ew", padx=(0, 10), pady=(12, 0))
        chip = ctk.CTkLabel(self, text=_(preset.category).upper(), font=fonts["chip"],
                            text_color=color, anchor="w")
        chip.grid(row=1, column=1, sticky="w")
        desc = ctk.CTkLabel(self, text=_(preset.desc), font=fonts["small"], text_color=MUTED,
                            anchor="w", justify="left", wraplength=180)
        desc.grid(row=2, column=0, columnspan=2, sticky="ew", padx=12, pady=(2, 10))
        for w in (self, icon, name, chip, desc):
            w.bind("<Button-1>", lambda e: on_click(preset.key))
            w.bind("<Enter>", lambda e: self._hover(True))
            w.bind("<Leave>", lambda e: self._hover(False))
            w.configure(cursor="hand2")

    def search_text(self) -> str:
        p = self.preset
        return " ".join((p.name, p.desc, p.category, _(p.name), _(p.desc),
                         _(p.category))).casefold()

    def _hover(self, inside: bool) -> None:
        if not self.selected:
            self.configure(fg_color=CARD_HOVER if inside else CARD)

    def set_selected(self, selected: bool) -> None:
        self.selected = selected
        self.configure(border_color=self.color if selected else CARD,
                       fg_color=CARD_HOVER if selected else CARD)


# ================================================================== ana pencere
class VoiceStudioApp(ctk.CTk):
    def __init__(self, language: str | None = None) -> None:
        super().__init__(fg_color=BG)
        self.title(f"{APP_NAME}  v{__version__}")
        self.geometry("1380x840")
        self.minsize(1180, 720)
        self._set_icon()

        self.fonts = {
            "logo": ctk.CTkFont(FONT, 22, "bold"),
            "logo_sub": ctk.CTkFont(FONT, 10, "bold"),
            "title": ctk.CTkFont(FONT, 24, "bold"),
            "section": ctk.CTkFont(FONT, 12, "bold"),
            "label": ctk.CTkFont(FONT, 12),
            "label_bold": ctk.CTkFont(FONT, 12, "bold"),
            "small": ctk.CTkFont(FONT, 11),
            "small_bold": ctk.CTkFont(FONT, 11, "bold"),
            "chip": ctk.CTkFont(FONT, 9, "bold"),
            "card_title": ctk.CTkFont(FONT, 14, "bold"),
            "emoji": ctk.CTkFont(EMOJI_FONT, 24),
            "power": ctk.CTkFont(FONT, 17, "bold"),
            "metric": ctk.CTkFont(FONT, 15, "bold"),
        }

        self.data_dir = app_data_dir()
        self.config_path = self.data_dir / "settings.json"
        self.cfg = AppConfig.load(self.config_path)
        # --lang verilmişse o, yoksa kayıtlı dil, ilk açılışta sistem dili
        set_language(resolve_language(language or self.cfg.language))
        self.store = PresetStore(self.data_dir / "presets.json")
        self.processor = VoiceProcessor(48000, self.cfg.quality)
        self.ui_events: queue.Queue[tuple[str, str]] = queue.Queue()
        self.router: AudioRouter | None = None
        if SOUNDDEVICE_ERROR is None:
            self.router = AudioRouter(self.processor,
                                      on_error=lambda m: self.ui_events.put(("error", m)))
        self.hotkeys = GlobalHotkeys()

        self.current_params = VoiceParams()
        self.active_key = ""
        self.modified = False
        self.category = ALL_CATEGORY
        self._restart_attempts = 0
        self._alive_ticks = 0
        self._tick = 0
        self._toast_job: str | None = None
        self._testing = False
        self.inputs: list[Device] = []
        self.outputs: list[Device] = []

        self.columnconfigure(1, weight=1)
        self.rowconfigure(0, weight=1)
        self._build_all()

        self.refresh_devices(initial=True)
        start_key = self.cfg.preset if self.store.get(self.cfg.preset) else DEFAULT_PRESET_KEY
        self.select_preset(start_key)
        if self.cfg.params and self.cfg.preset == start_key:
            saved = VoiceParams.from_dict(self.cfg.params)
            if saved != self.current_params:
                self._apply_params(saved, modified=True)

        if self.cfg.hotkey_enabled:
            self.hotkeys.start()
            if self.hotkeys.failed:
                self.toast(_("Kısayol alınamadı (başka program kullanıyor): {keys}").format(
                    keys=", ".join(self.hotkeys.failed)), WARN)
        if self.store.load_error:
            self.toast(self.store.load_error, WARN)
        if SOUNDDEVICE_ERROR:
            self.toast(_("Ses sistemi yüklenemedi: {error}").format(error=SOUNDDEVICE_ERROR), BAD)

        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.after(33, self._ui_loop)

    # ------------------------------------------------------------- kurulum
    def _set_icon(self) -> None:
        ico = resource_dir() / "assets" / "icon.ico"
        if ico.exists():
            # customtkinter kendi ikonunu ~200 ms sonra koyar; bizimki ondan sonra gelsin.
            self.after(250, lambda: self.iconbitmap(str(ico)))

    def _build_all(self) -> None:
        self.cards: dict[str, PresetCard] = {}
        self.sliders: dict[str, ParamSlider] = {}
        self._grid_cols = 0
        self._build_sidebar()
        self._build_center()
        self._build_right()

    def _rebuild_ui(self) -> None:
        """Dil değişince tüm arayüzü yeni dilde baştan kurar; ses akışı ve ayarlar korunur."""
        state = (self.mic_var.get(), self.cable_var.get(), self.monitor_dev_var.get(),
                 self.monitor_var.get(), self.bypass_var.get(), self.mute_var.get())
        params, modified, key = self.current_params, self.modified, self.active_key
        self.cfg.hostapi = self.hostapi_var.get()  # yeniden kurulumda aynı ses sistemi seçilsin
        if self._toast_job:
            self.after_cancel(self._toast_job)
            self._toast_job = None
        for child in self.winfo_children():
            child.destroy()
        self.category = ALL_CATEGORY
        self._build_all()
        self.refresh_devices(initial=True)
        for var, value, names in ((self.mic_var, state[0], [d.name for d in self.inputs]),
                                  (self.cable_var, state[1], [d.name for d in self.outputs]),
                                  (self.monitor_dev_var, state[2],
                                   [d.name for d in self.outputs])):
            if value in names or value == NO_DEVICE:
                var.set(value)
        self.monitor_var.set(state[3])
        self.bypass_var.set(state[4])
        self.mute_var.set(state[5])
        self.active_key = ""
        self.select_preset(key if self.store.get(key) else DEFAULT_PRESET_KEY)
        if modified:
            self._apply_params(params, modified=True)
        self._set_running_ui(bool(self.router and self.router.running))

    def _build_sidebar(self) -> None:
        f = self.fonts
        side = ctk.CTkScrollableFrame(self, width=270, fg_color=PANEL, corner_radius=0,
                                      scrollbar_button_color=PANEL,
                                      scrollbar_button_hover_color=BORDER)
        side.grid(row=0, column=0, sticky="nsw")
        side.columnconfigure(0, weight=1)

        logo = ctk.CTkFrame(side, fg_color="transparent")
        logo.grid(row=0, column=0, sticky="ew", padx=18, pady=(20, 16))
        ctk.CTkLabel(logo, text="XYRON", font=f["logo"], text_color=TEXT).pack(anchor="w")
        ctk.CTkLabel(logo, text="VOICE CHANGER", font=f["logo_sub"],
                     text_color=ACCENT).pack(anchor="w")

        self.power_btn = ctk.CTkButton(side, text="", height=58, corner_radius=29,
                                       font=f["power"], fg_color=ACCENT, hover_color=ACCENT_HOVER,
                                       text_color="#FFFFFF", command=self.toggle_power)
        self.power_btn.grid(row=1, column=0, sticky="ew", padx=18)
        self.status_lbl = ctk.CTkLabel(side, text="", font=f["small_bold"], text_color=MUTED)
        self.status_lbl.grid(row=2, column=0, sticky="w", padx=22, pady=(6, 12))

        tele = ctk.CTkFrame(side, fg_color=CARD, corner_radius=12)
        tele.grid(row=3, column=0, sticky="ew", padx=18)
        tele.columnconfigure((0, 1, 2), weight=1)
        self.tele_vals: dict[str, ctk.CTkLabel] = {}
        for col, (key, title) in enumerate((("lat", _("GECİKME")), ("cpu", "CPU"),
                                            ("buf", _("TAMPON")))):
            ctk.CTkLabel(tele, text=title, font=f["chip"], text_color=DIM).grid(
                row=0, column=col, pady=(10, 0))
            lbl = ctk.CTkLabel(tele, text="–", font=f["metric"], text_color=TEXT)
            lbl.grid(row=1, column=col, pady=(0, 10))
            self.tele_vals[key] = lbl

        toggles = ctk.CTkFrame(side, fg_color="transparent")
        toggles.grid(row=4, column=0, sticky="ew", padx=18, pady=(14, 4))
        toggles.columnconfigure(0, weight=1)
        self.monitor_var = ctk.BooleanVar(value=self.cfg.monitor_on)
        self.bypass_var = ctk.BooleanVar(value=self.processor.bypass)
        self.mute_var = ctk.BooleanVar(value=self.processor.muted)
        switches = ((_("Kendimi duy (kulaklık)"), self.monitor_var, self.on_monitor_toggle),
                    (_("Ham ses (A/B karşılaştır)"), self.bypass_var, self.on_bypass_toggle),
                    (_("Mikrofonu sustur"), self.mute_var, self.on_mute_toggle))
        for i, (text, var, cmd) in enumerate(switches):
            ctk.CTkSwitch(toggles, text=text, variable=var, command=cmd, font=f["label"],
                          text_color=TEXT, progress_color=ACCENT, button_color=TEXT,
                          button_hover_color=CYAN, fg_color=BORDER).grid(
                row=i, column=0, sticky="w", pady=4)

        tools = ((_("🎙  5 sn kaydet ve dinle"), self.record_test),
                 (_("🎚  Oda gürültüsünü öğren"), self.learn_noise),
                 (_("📁  Ses dosyası dönüştür"), self.convert_file))
        for i, (text, cmd) in enumerate(tools):
            ctk.CTkButton(side, text=text, height=36, corner_radius=10, fg_color=CARD,
                          hover_color=CARD_HOVER, text_color=TEXT, font=f["label"],
                          command=cmd).grid(row=5 + i, column=0, sticky="ew", padx=18,
                                            pady=(10 if i == 0 else 4, 4))

        dev = Section(side, _("SES AYGITLARI"), f, opened=True)
        dev.configure(fg_color="transparent")
        dev.grid(row=8, column=0, sticky="ew", padx=10, pady=(14, 0))
        body = dev.body
        self.hostapi_var = ctk.StringVar()
        self.mic_var = ctk.StringVar()
        self.cable_var = ctk.StringVar()
        self.monitor_dev_var = ctk.StringVar()
        self.quality_var = ctk.StringVar(value=_(QUALITY_MODES[self.processor.quality][0]))
        self.lang_var = ctk.StringVar(value=LANGUAGES[get_language()])
        menus = (("hostapi", _("Ses sistemi"), self.hostapi_var, self.on_hostapi_change),
                 ("mic", _("Mikrofon"), self.mic_var, self.on_device_change),
                 ("cable", _("Sanal mikrofon (Discord/oyun buradan duyar)"), self.cable_var,
                  self.on_device_change),
                 ("monitor", _("Kulaklık (kendini duymak için)"), self.monitor_dev_var,
                  self.on_device_change),
                 ("quality", _("Motor kalitesi"), self.quality_var, self.on_quality_change),
                 ("lang", "Dil / Language", self.lang_var, self.on_language_change))
        self.menus: dict[str, ctk.CTkOptionMenu] = {}
        for i, (key, label, var, cmd) in enumerate(menus):
            ctk.CTkLabel(body, text=label, font=f["small"], text_color=MUTED, anchor="w",
                         wraplength=220, justify="left").grid(row=2 * i, column=0, sticky="w",
                                                              pady=(6, 2))
            menu = ctk.CTkOptionMenu(body, variable=var, values=["…"], command=cmd, height=32,
                                     corner_radius=8, fg_color=CARD, button_color=BORDER,
                                     button_hover_color=ACCENT, dropdown_fg_color=CARD,
                                     dropdown_hover_color=ACCENT, text_color=TEXT,
                                     font=f["small"], dropdown_font=f["small"],
                                     dynamic_resizing=False)
            menu.grid(row=2 * i + 1, column=0, sticky="ew")
            self.menus[key] = menu
        self.menus["quality"].configure(values=[_(v[0]) for v in QUALITY_MODES.values()])
        self.menus["lang"].configure(values=list(LANGUAGES.values()))
        ctk.CTkButton(body, text=_("↻  Aygıtları yenile"), height=30, corner_radius=8,
                      fg_color="transparent", border_width=1, border_color=BORDER,
                      hover_color=CARD_HOVER, text_color=MUTED, font=f["small"],
                      command=self.refresh_devices).grid(row=20, column=0, sticky="ew",
                                                         pady=(10, 0))
        self.cable_warn = ctk.CTkButton(body, text=_("⚠  VB-Cable bulunamadı: Kur"), height=32,
                                        corner_radius=8, fg_color="#3A2A12", hover_color="#4A3618",
                                        text_color=WARN, font=f["small_bold"],
                                        command=self.install_cable)

        lines = [_("KISAYOLLAR (her yerde çalışır)")]
        lines += [f"{label}: {_(HOTKEY_NAMES[action])}" for action, (label, _vk) in HOTKEYS.items()]
        ctk.CTkLabel(side, text="\n".join(lines), font=f["small"], text_color=DIM,
                     justify="left", anchor="w").grid(row=9, column=0, sticky="w", padx=22,
                                                      pady=(16, 20))
        self._set_running_ui(bool(self.router and self.router.running))

    def _build_center(self) -> None:
        f = self.fonts
        center = ctk.CTkFrame(self, fg_color=BG)
        center.grid(row=0, column=1, sticky="nsew", padx=(20, 10), pady=18)
        center.columnconfigure(0, weight=1)
        center.rowconfigure(3, weight=1)

        head = ctk.CTkFrame(center, fg_color="transparent")
        head.grid(row=0, column=0, sticky="ew")
        head.columnconfigure(0, weight=1)
        self.head_title = ctk.CTkLabel(head, text="", font=f["title"], text_color=TEXT,
                                       anchor="w")
        self.head_title.grid(row=0, column=0, sticky="w")
        self.head_desc = ctk.CTkLabel(head, text="", font=f["label"], text_color=MUTED, anchor="w")
        self.head_desc.grid(row=1, column=0, sticky="w")
        actions = ctk.CTkFrame(head, fg_color="transparent")
        actions.grid(row=0, column=1, rowspan=2, sticky="e")
        btn = dict(height=34, corner_radius=10, font=f["small_bold"])
        self.reset_btn = ctk.CTkButton(actions, text=_("↺ Sıfırla"), width=90, fg_color=CARD,
                                       hover_color=CARD_HOVER, text_color=TEXT,
                                       command=self.reset_preset, **btn)
        self.reset_btn.pack(side="left", padx=4)
        self.delete_btn = ctk.CTkButton(actions, text=_("🗑 Sil"), width=70, fg_color=CARD,
                                        hover_color="#3A1A24", text_color=BAD,
                                        command=self.delete_preset, **btn)
        ctk.CTkButton(actions, text=_("★ Profili kaydet"), width=130, fg_color=ACCENT,
                      hover_color=ACCENT_HOVER, text_color="#FFFFFF",
                      command=self.save_preset, **btn).pack(side="right", padx=4)

        self.visualizer = Visualizer(center)
        self.visualizer.grid(row=1, column=0, sticky="ew", pady=(14, 14))

        bar = ctk.CTkFrame(center, fg_color="transparent")
        bar.grid(row=2, column=0, sticky="ew", pady=(0, 10))
        bar.columnconfigure(0, weight=1)
        # Kategori anahtarları Türkçe kalır (preset verisi); ekranda çevirisi gösterilir.
        self._category_by_label = {_(c): c for c in (ALL_CATEGORY, *CATEGORIES)}
        self.cat_btn = ctk.CTkSegmentedButton(
            bar, values=list(self._category_by_label), command=self.on_category,
            font=f["small_bold"], height=34, corner_radius=10, fg_color=PANEL,
            selected_color=ACCENT, selected_hover_color=ACCENT_HOVER, unselected_color=PANEL,
            unselected_hover_color=CARD_HOVER, text_color=TEXT)
        self.cat_btn.set(_(self.category))
        self.cat_btn.grid(row=0, column=0, sticky="w")
        # Not: customtkinter'da textvariable verilirse placeholder görünmez; KeyRelease ile okunur.
        self.search_entry = ctk.CTkEntry(bar, placeholder_text=_("🔍  Ses ara…"), width=220,
                                         height=34, corner_radius=10, fg_color=PANEL,
                                         border_color=BORDER, text_color=TEXT,
                                         placeholder_text_color=DIM, font=f["small"])
        self.search_entry.grid(row=0, column=1, sticky="e")
        self.search_entry.bind("<KeyRelease>", lambda e: self.layout_cards(force=True))

        self.cards_frame = ctk.CTkScrollableFrame(center, fg_color="transparent",
                                                  scrollbar_button_color=BORDER,
                                                  scrollbar_button_hover_color=ACCENT)
        self.cards_frame.grid(row=3, column=0, sticky="nsew")
        self.toast_lbl = ctk.CTkLabel(center, text="", font=f["small_bold"], text_color=TEXT,
                                      fg_color=CARD, corner_radius=10, height=34)
        self.cards_frame.bind("<Configure>", lambda e: self.layout_cards())
        self.build_cards()

    def _build_right(self) -> None:
        f = self.fonts
        right = ctk.CTkScrollableFrame(self, width=330, fg_color=PANEL, corner_radius=0,
                                       scrollbar_button_color=PANEL,
                                       scrollbar_button_hover_color=BORDER)
        right.grid(row=0, column=2, sticky="nse")
        right.columnconfigure(0, weight=1)

        ident = ctk.CTkFrame(right, fg_color=CARD, corner_radius=12)
        ident.grid(row=0, column=0, sticky="ew", padx=12, pady=(16, 8))
        ident.columnconfigure(0, weight=1)
        ctk.CTkLabel(ident, text=_("SES KİMLİĞİ"), font=f["section"], text_color=TEXT,
                     anchor="w").grid(row=0, column=0, sticky="w", padx=14, pady=(12, 0))
        ctk.CTkLabel(ident, text=_("Noktayı sürükle • çift tık = doğal ses"), font=f["small"],
                     text_color=DIM, anchor="w").grid(row=1, column=0, sticky="w", padx=14)
        self.xy = XYPad(ident, self.on_xy)
        self.xy.grid(row=2, column=0, sticky="ew", padx=10, pady=8)
        inner = ctk.CTkFrame(ident, fg_color="transparent")
        inner.grid(row=3, column=0, sticky="ew", padx=14, pady=(0, 8))
        inner.columnconfigure(0, weight=1)
        for i, name in enumerate(("pitch", "formant")):
            s = ParamSlider(inner, name, self.on_param, f)
            s.grid(row=i, column=0, sticky="ew")
            self.sliders[name] = s

        for row, (title, names, opened) in enumerate(SECTIONS, start=1):
            sec = Section(right, _(title), f, opened)
            sec.grid(row=row, column=0, sticky="ew", padx=12, pady=6)
            for i, name in enumerate(names):
                s = ParamSlider(sec.body, name, self.on_param, f)
                s.grid(row=i, column=0, sticky="ew")
                self.sliders[name] = s
        ctk.CTkLabel(right, text=f"{APP_NAME} v{__version__}", font=f["small"],
                     text_color=DIM).grid(row=len(SECTIONS) + 1, column=0, pady=(10, 20))

    # ------------------------------------------------------------- preset kartları
    def build_cards(self) -> None:
        for card in self.cards.values():
            card.destroy()
        self.cards = {key: PresetCard(self.cards_frame, p, self.select_preset, self.fonts)
                      for key, p in self.store.all().items()}
        for key, card in self.cards.items():
            card.set_selected(key == self.active_key)
        self.layout_cards(force=True)

    def _visible_presets(self) -> list[str]:
        query = self.search_entry.get().strip().casefold()
        keys = []
        for key, card in self.cards.items():
            if self.category != ALL_CATEGORY and card.preset.category != self.category:
                continue
            if query and query not in card.search_text():
                continue
            keys.append(key)
        return keys

    def layout_cards(self, force: bool = False) -> None:
        width = self.cards_frame.winfo_width()
        cols = max(2, min(5, (width - 10) // 224)) if width > 50 else 3
        if not force and cols == self._grid_cols:
            return
        self._grid_cols = cols
        for card in self.cards.values():
            card.grid_forget()
        for c in range(6):
            self.cards_frame.columnconfigure(c, weight=1 if c < cols else 0, uniform="card"
                                             if c < cols else "")
        visible = self._visible_presets()
        for i, key in enumerate(visible):
            self.cards[key].grid(row=i // cols, column=i % cols, padx=6, pady=6, sticky="ew")
        if not visible:
            self.toast(_("Bu filtrede ses yok. 'Benim' sekmesi için önce bir profil kaydet."),
                       MUTED)

    def on_category(self, label: str) -> None:
        self.category = self._category_by_label.get(label, ALL_CATEGORY)
        self.layout_cards(force=True)

    # ------------------------------------------------------------- parametreler
    def select_preset(self, key: str) -> None:
        preset = self.store.get(key)
        if preset is None:
            return
        if self.active_key in self.cards:
            self.cards[self.active_key].set_selected(False)
        self.active_key = key
        if key in self.cards:
            self.cards[key].set_selected(True)
        self._apply_params(preset.params, modified=False)
        if preset.builtin:
            self.delete_btn.pack_forget()
        else:
            self.delete_btn.pack(side="left", padx=4, before=self.reset_btn)

    def _apply_params(self, params: VoiceParams, modified: bool) -> None:
        self.current_params = params
        self.processor.set_params(params)
        for name, slider in self.sliders.items():
            slider.set(getattr(params, name))
        self.xy.set(params.pitch, params.formant)
        self.modified = modified
        self._refresh_header()

    def _refresh_header(self) -> None:
        preset = self.store.get(self.active_key)
        if preset is None:
            return
        suffix = "   • " + _("özelleştirildi") if self.modified else ""
        self.head_title.configure(text=f"{preset.icon}  {_(preset.name)}{suffix}")
        self.head_desc.configure(text=_(preset.desc))

    def _mark_modified(self) -> None:
        if not self.modified:
            self.modified = True
            self._refresh_header()

    def on_param(self, name: str, value: float) -> None:
        self.current_params = self.current_params.with_value(name, value)
        self.processor.set_params(self.current_params)
        if name in ("pitch", "formant"):
            self.xy.set(self.current_params.pitch, self.current_params.formant)
        self._mark_modified()

    def on_xy(self, pitch: float, formant: float) -> None:
        self.current_params = (self.current_params.with_value("pitch", pitch)
                               .with_value("formant", formant))
        self.processor.set_params(self.current_params)
        self.sliders["pitch"].set(self.current_params.pitch)
        self.sliders["formant"].set(self.current_params.formant)
        self._mark_modified()

    def reset_preset(self) -> None:
        self.select_preset(self.active_key)
        self.toast(_("Profil varsayılan ayarlarına döndü."))

    def save_preset(self) -> None:
        current = self.store.get(self.active_key)
        dialog = ctk.CTkInputDialog(title=_("Profili kaydet"),
                                    text=_("Profil adı (aynı ad varsa üzerine yazılır):"),
                                    button_fg_color=ACCENT, button_hover_color=ACCENT_HOVER)
        name = dialog.get_input()
        if not name or not name.strip():
            return
        desc = _("{name} tabanlı özel profil").format(name=_(current.name)) if current else ""
        try:
            preset = self.store.add(name, self.current_params, desc)
        except OSError as exc:
            messagebox.showerror(_("Kaydedilemedi"),
                                 _("Profil dosyası yazılamadı:\n{error}").format(error=exc))
            return
        self.build_cards()
        self.select_preset(preset.key)
        self.toast(_("'{name}' kaydedildi (Benim sekmesi).").format(name=preset.name), GOOD)

    def delete_preset(self) -> None:
        preset = self.store.get(self.active_key)
        if preset is None or preset.builtin:
            return
        if not messagebox.askyesno(_("Profili sil"),
                                   _("'{name}' silinsin mi?").format(name=preset.name)):
            return
        try:
            self.store.delete(preset.key)
        except OSError as exc:
            messagebox.showerror(_("Silinemedi"), str(exc))
            return
        self.active_key = ""
        self.build_cards()
        self.select_preset(DEFAULT_PRESET_KEY)
        self.toast(_("Profil silindi."))

    # ------------------------------------------------------------- aygıtlar
    def refresh_devices(self, initial: bool = False) -> None:
        if self.router is None:
            return
        apis = list_hostapis()
        self.menus["hostapi"].configure(values=apis or [NO_DEVICE])
        current = self.hostapi_var.get()
        api = current if current in apis else (
            self.cfg.hostapi if self.cfg.hostapi in apis else (apis[0] if apis else ""))
        self.hostapi_var.set(api)
        self._load_devices_for(api, use_config=True)
        if not initial:
            self.toast(_("Aygıt listesi yenilendi."))

    def _load_devices_for(self, api: str, use_config: bool) -> None:
        self.inputs, self.outputs = list_devices(api)
        mic_d, cable_d, phones_d = default_devices(api)
        mic = (find_device(self.cfg.mic, self.inputs) if use_config else None) or mic_d
        cable = (find_device(self.cfg.cable, self.outputs) if use_config else None) or cable_d
        phones = (find_device(self.cfg.monitor, self.outputs) if use_config else None) or phones_d
        in_names = [d.name for d in self.inputs] or [NO_DEVICE]
        out_names = [NO_DEVICE] + [d.name for d in self.outputs]
        self.menus["mic"].configure(values=in_names)
        self.menus["cable"].configure(values=out_names)
        self.menus["monitor"].configure(values=out_names)
        self.mic_var.set(mic.name if mic else NO_DEVICE)
        self.cable_var.set(cable.name if cable else NO_DEVICE)
        self.monitor_dev_var.set(phones.name if phones else NO_DEVICE)
        if any(is_cable(d.name) for d in self.outputs):
            self.cable_warn.grid_forget()
        else:
            self.cable_warn.grid(row=21, column=0, sticky="ew", pady=(8, 0))

    def _selected_devices(self) -> tuple[Device | None, Device | None, Device | None]:
        return (find_device(self.mic_var.get(), self.inputs),
                find_device(self.cable_var.get(), self.outputs),
                find_device(self.monitor_dev_var.get(), self.outputs))

    def on_hostapi_change(self, api: str) -> None:
        self._load_devices_for(api, use_config=False)
        self._restart_if_running()

    def on_device_change(self, _value: str) -> None:
        self._restart_if_running()

    def on_quality_change(self, label: str) -> None:
        key = next((k for k, v in QUALITY_MODES.items() if _(v[0]) == label), None)
        if key:
            self.processor.set_quality(key)
            self.toast(_("Motor: {label} (motor gecikmesi ≈ {ms} ms)").format(
                label=label, ms=round(self.processor.latency_ms)))

    def on_language_change(self, label: str) -> None:
        code = next((c for c, name in LANGUAGES.items() if name == label), None)
        if code is None or code == get_language():
            return
        set_language(code)
        self.cfg.language = code
        # Menü kendi geri çağrısı içindeyken yok edilmesin: yeniden kurulumu sıraya koy.
        self.after(50, self._rebuild_ui)

    def _restart_if_running(self) -> None:
        if self.router and self.router.running:
            self.start_audio()

    # ------------------------------------------------------------- ses akışı
    def toggle_power(self) -> None:
        if self.router is None:
            messagebox.showerror(_("Ses sistemi yok"),
                                 _("Ses sistemi yüklenemedi: {error}").format(
                                     error=SOUNDDEVICE_ERROR))
            return
        if self.router.running:
            self.stop_audio()
        else:
            self.start_audio()

    def start_audio(self) -> bool:
        assert self.router is not None
        mic, cable, phones = self._selected_devices()
        if mic is None:
            messagebox.showwarning(_("Mikrofon yok"), _("Lütfen bir mikrofon seç."))
            return False
        if cable is None and not (self.monitor_var.get() and phones):
            messagebox.showwarning(
                _("Çıkış yok"),
                _("Sanal mikrofon (VB-Cable) veya kulaklık seç.\n"
                  "Sesi Discord/oyuna vermek için VB-Cable gerekir."))
            return False
        try:
            self.router.start(mic, cable, phones, self.monitor_var.get())
        except Exception as exc:
            self._set_running_ui(False)
            messagebox.showerror(
                _("Ses başlatılamadı"),
                _("{error}\n\nÖneriler:\n• Mikrofonu başka bir program 'özel modda' kullanıyor "
                  "olabilir.\n• 'Ses sistemi' menüsünden MME veya DirectSound'u dene.\n"
                  "• Aygıtları yenile ve tekrar dene.").format(error=exc))
            return False
        self._restart_attempts = 0
        self._set_running_ui(True)
        return True

    def stop_audio(self) -> None:
        if self.router:
            self.router.stop()
        self._testing = False
        self._set_running_ui(False)

    def _set_running_ui(self, running: bool) -> None:
        if running:
            self.power_btn.configure(text="■   " + _("DURDUR"), fg_color=BAD,
                                     hover_color="#E04360")
            mode = _("kendini duyuyorsun") if self.router and self.router.monitor_enabled else \
                _("sadece karşı taraf duyar")
            self.status_lbl.configure(text="● " + _("Aktif") + f" — {mode}", text_color=GOOD)
        else:
            self.power_btn.configure(text="▶   " + _("BAŞLAT"), fg_color=ACCENT,
                                     hover_color=ACCENT_HOVER)
            self.status_lbl.configure(text="● " + _("Kapalı"), text_color=MUTED)

    def on_monitor_toggle(self) -> None:
        if self.router and self.router.running:
            try:
                self.router.set_monitor(self.monitor_var.get())
            except Exception as exc:
                self.monitor_var.set(False)
                messagebox.showerror(_("Kulaklık açılamadı"), str(exc))
            self._set_running_ui(True)

    def on_bypass_toggle(self) -> None:
        self.processor.bypass = self.bypass_var.get()
        self.toast(_("Ham ses: karşı taraf gerçek sesini duyuyor.") if self.processor.bypass
                   else _("Ses değiştirici yeniden devrede."),
                   WARN if self.processor.bypass else GOOD)

    def on_mute_toggle(self) -> None:
        self.processor.muted = self.mute_var.get()
        self.toast(_("Mikrofon susturuldu.") if self.processor.muted else _("Mikrofon açık."),
                   WARN if self.processor.muted else GOOD)

    def learn_noise(self) -> None:
        if self.current_params.denoise < 0.05:
            self.sliders["denoise"].set(0.5)
            self.on_param("denoise", 0.5)
        self.processor.learn_noise()
        self.toast(_("2-3 saniye sessiz kal: oda gürültüsü öğreniliyor…"), CYAN, 3500)

    def record_test(self) -> None:
        """Değiştirilmiş sesi kısa süre kaydedip kulaklıktan çalar (karşı tarafın duyduğu)."""
        if not (self.router and self.router.running):
            self.toast(_("Önce BAŞLAT'a bas, sonra kaydet."), WARN)
            return
        if self._selected_devices()[2] is None:
            self.toast(_("Kaydı dinlemek için bir kulaklık seç."), WARN)
            return
        if self._testing:
            return
        self._testing = True
        self.router.start_capture(TEST_SECONDS)
        self.toast(_("Şimdi konuş: {seconds} saniye kaydediliyor…").format(
            seconds=round(TEST_SECONDS)), CYAN, int(TEST_SECONDS * 1000))

    def _poll_test_recording(self) -> None:
        if not self._testing or self.router is None:
            return
        audio = self.router.take_capture()
        if audio is None:
            return
        self._testing = False
        phones = self._selected_devices()[2]
        try:
            if phones is None:
                raise RuntimeError(_("Kaydı dinlemek için bir kulaklık seç."))
            self.router.play_clip(audio, phones)
        except Exception as exc:
            self.toast(_("Kayıt çalınamadı: {error}").format(error=exc), BAD, 6000)
            return
        self.toast(_("Kayıt çalınıyor: karşı taraf seni böyle duyuyor."), GOOD,
                   int(TEST_SECONDS * 1000))

    def install_cable(self) -> None:
        # Geliştirme klasöründe yanında, "Voice Changer" paketinde ../1_Gerekenler içinde durur.
        candidates = [install_dir() / "VBCable",
                      install_dir().parent / "1_Gerekenler" / "VBCable"]
        setup = next((c / "VBCABLE_Setup_x64.exe" for c in candidates
                      if (c / "VBCABLE_Setup_x64.exe").exists()), None)
        if setup is None:
            messagebox.showinfo("VB-Cable", _("Kurulum dosyası bulunamadı.\n"
                                              "Resmi siteden indir: https://vb-audio.com/Cable/"))
            return
        if not messagebox.askyesno(
                _("VB-Cable kurulumu"),
                _("Sanal ses kablosu sürücüsü kurulacak (yönetici izni ister).\n"
                  "Açılan pencerede 'Install Driver'a bas, sonra bilgisayarı "
                  "yeniden başlat.\n\nDevam edilsin mi?")):
            return
        result = ctypes.windll.shell32.ShellExecuteW(None, "runas", str(setup), None,
                                                     str(setup.parent), 1)
        if result <= 32:
            messagebox.showerror("VB-Cable",
                                 _("Kurulum başlatılamadı (izin verilmedi olabilir)."))

    # ------------------------------------------------------------- dosya dönüştürme
    def convert_file(self) -> None:
        src = filedialog.askopenfilename(
            title=_("Dönüştürülecek ses dosyası"),
            filetypes=[(_("Ses dosyaları"), "*.wav *.mp3 *.flac *.ogg *.m4a *.aiff"),
                       (_("Tüm dosyalar"), "*.*")])
        if not src:
            return
        preset = self.store.get(self.active_key)
        suggested = f"{Path(src).stem}_{preset.key if preset else 'xyrox'}.wav"
        dst = filedialog.asksaveasfilename(title=_("Kaydet"), defaultextension=".wav",
                                           initialfile=suggested,
                                           initialdir=str(Path(src).parent),
                                           filetypes=[("WAV", "*.wav")])
        if not dst:
            return
        params, quality = self.current_params, self.processor.quality
        self.toast(_("Dönüştürülüyor…"), CYAN, 60000)
        done_text = _("{seconds} sn ses kaydedildi: {path}")
        fail_text = _("Dönüştürme başarısız: {error}")

        def work() -> None:
            from .render import render_file
            try:
                seconds = render_file(Path(src), Path(dst), params, quality)
                self.ui_events.put(("done", done_text.format(seconds=f"{seconds:.1f}", path=dst)))
            except Exception as exc:
                self.ui_events.put(("error", fail_text.format(error=exc)))

        threading.Thread(target=work, name="xyrox-render", daemon=True).start()

    # ------------------------------------------------------------- bildirim / döngü
    def toast(self, message: str, color: str = TEXT, ms: int = 2600) -> None:
        self.toast_lbl.configure(text=f"   {message}   ", text_color=color)
        self.toast_lbl.place(relx=0.5, rely=1.0, anchor="s", y=-6)
        self.toast_lbl.lift()
        if self._toast_job:
            self.after_cancel(self._toast_job)
        self._toast_job = self.after(ms, self._hide_toast)

    def _hide_toast(self) -> None:
        self._toast_job = None
        self.toast_lbl.place_forget()

    def _handle_hotkey(self, action: str) -> None:
        if action == "bypass":
            self.bypass_var.set(not self.bypass_var.get())
            self.on_bypass_toggle()
        elif action == "mute":
            self.mute_var.set(not self.mute_var.get())
            self.on_mute_toggle()
        elif action == "power":
            self.toggle_power()

    def _ui_loop(self) -> None:
        self._tick += 1
        running = bool(self.router and self.router.running)
        if running:
            self.visualizer.update_view(self.processor.spectrum_bands(Visualizer.N_BANDS),
                                        self.processor.in_level, self.processor.out_level)
        elif self._tick % 3 == 0:
            self.visualizer.update_view([0.0] * Visualizer.N_BANDS, 0.0, 0.0)

        while True:
            try:
                kind, msg = self.ui_events.get_nowait()
            except queue.Empty:
                break
            if kind == "done":
                self.toast(msg, GOOD, 5000)
            else:
                self.toast(msg, BAD, 6000)
        while True:
            try:
                self._handle_hotkey(self.hotkeys.events.get_nowait())
            except queue.Empty:
                break

        self._poll_test_recording()
        if self._tick % 15 == 0:
            self._update_telemetry(running)
        if running and self._tick % 30 == 0:
            self._watchdog()
        self.after(33, self._ui_loop)

    def _update_telemetry(self, running: bool) -> None:
        if running and self.router:
            health = self.router.health()
            color = {"iyi": GOOD, "orta": WARN, "kötü": BAD}[health]
            self.tele_vals["buf"].configure(text=_(HEALTH_LABELS[health]), text_color=color)
            self.tele_vals["lat"].configure(text=f"{self.router.total_latency_ms:.0f} ms")
            self.tele_vals["cpu"].configure(text=f"{self.processor.cpu_load * 100:.0f}%")
        else:
            self.tele_vals["lat"].configure(text=f"~{self.processor.latency_ms:.0f} ms")
            self.tele_vals["cpu"].configure(text="–")
            self.tele_vals["buf"].configure(text="–", text_color=TEXT)

    def _watchdog(self) -> None:
        """Aygıt söküldüyse/akış öldüyse birkaç kez otomatik yeniden bağlanmayı dener."""
        if self.router is None:
            return
        if self.router.streams_alive():
            # 30 sn kesintisiz çalıştıysa sayaç sıfırlansın (saatler arayla kopmalar birikmesin).
            self._alive_ticks += 1
            if self._alive_ticks >= 30:
                self._restart_attempts = 0
            return
        self._alive_ticks = 0
        self._restart_attempts += 1
        if self._restart_attempts > 3:
            self.stop_audio()
            self.toast(_("Ses aygıtı bağlantısı koptu. Aygıtları yenileyip tekrar başlat."), BAD,
                       8000)
            return
        self.toast(_("Aygıt bağlantısı koptu, yeniden bağlanılıyor ({n}/3)…").format(
            n=self._restart_attempts), WARN)
        mic, cable, phones = self._selected_devices()
        try:
            if mic:
                self.router.start(mic, cable, phones, self.monitor_var.get())
        except Exception:
            pass  # bir sonraki turda yeniden denenir; 3 denemeden sonra kullanıcıya bildirilir

    def on_close(self) -> None:
        mic, cable, phones = self._selected_devices()
        self.cfg.hostapi = self.hostapi_var.get()
        self.cfg.mic = mic.name if mic else self.cfg.mic
        self.cfg.cable = cable.name if cable else self.cfg.cable
        self.cfg.monitor = phones.name if phones else self.cfg.monitor
        self.cfg.monitor_on = bool(self.monitor_var.get())
        self.cfg.quality = self.processor.quality
        self.cfg.language = get_language()
        self.cfg.preset = self.active_key
        self.cfg.params = self.current_params.to_dict() if self.modified else {}
        try:
            self.cfg.save(self.config_path)
        except OSError:
            pass  # ayar kaydedilemese de uygulama düzgün kapansın
        if self.router:
            self.router.stop()
        self.hotkeys.stop()
        self.destroy()


def run_app(language: str | None = None) -> int:
    if sys.platform == "win32":
        try:  # görev çubuğunda Python ikonu yerine uygulamanın kendi ikonu
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Xyron.VoiceChanger")
        except (AttributeError, OSError):
            pass
    ctk.set_appearance_mode("dark")
    app = VoiceStudioApp(language)
    app.mainloop()
    return 0

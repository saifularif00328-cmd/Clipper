from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Optional


@dataclass
class Word:
    text: str
    start: float
    end: float

    def to_dict(self):
        return asdict(self)


@dataclass
class Clip:
    id: int
    start: float
    end: float
    title: str = ""
    hook: str = ""
    thumb_text: str = ""
    caption: str = ""
    hashtags: list = field(default_factory=list)
    score: float = 0.0
    score_hook: float = 0.0
    score_flow: float = 0.0
    score_value: float = 0.0
    score_trend: float = 0.0
    reason: str = ""
    transcript_override: str = ""   # teks subtitle hasil sunting manual (timing disamakan otomatis)
    selected: bool = True

    @property
    def duration(self) -> float:
        return self.end - self.start

    def to_dict(self):
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> "Clip":
        keys = Clip.__dataclass_fields__.keys()
        return Clip(**{k: v for k, v in d.items() if k in keys})


@dataclass
class Style:
    """Semua pengaturan tampilan & render. Disimpan ke settings.json."""
    # layout
    layout: str = "face"            # face | center | blur
    out_width: int = 1080
    out_height: int = 1920
    fps: int = 30
    # subtitle
    sub_enabled: bool = True
    sub_font: str = "Poppins ExtraBold"
    sub_size: int = 84
    sub_anim: str = "pop"           # pop | karaoke | glow | keyword | emphasis | plain
    sub_fill: str = "#FFFFFF"
    sub_active: str = "#FFE600"
    sub_inner: str = "#000000"
    sub_outer: str = "#6A1BFF"
    sub_inner_w: int = 6
    sub_outer_w: int = 8
    sub_box: str = "#FF2D55"
    sub_glow: str = "#00E5FF"
    sub_uppercase: bool = True
    sub_max_words: int = 4
    sub_pos: list = field(default_factory=lambda: [1, 3])   # [kolom 0-2, baris 0-4]
    sub_dy: float = 0.0             # geser vertikal (fraksi tinggi layar)
    keywords: str = ""              # dipisah koma
    keyword_color: str = "#39FF14"
    # hook
    hook_enabled: bool = True
    hook_pos: list = field(default_factory=lambda: [1, 0])
    hook_style: str = "yellow"      # yellow | red | outline
    hook_size: int = 78
    hook_seconds: float = 3.0
    hook_voice: bool = False
    hook_voice_name: str = ""       # kosong = otomatis sesuai bahasa
    # logo
    logo_path: str = ""
    logo_pos: list = field(default_factory=lambda: [2, 0])  # [kolom 0-2, baris 0-2]
    logo_scale: float = 0.16
    logo_opacity: float = 0.9
    # branding teks
    badge_enabled: bool = False
    badge_text: str = "WATCH FULL VIDEO"
    badge_sub: str = ""             # nama channel
    badge_pos: list = field(default_factory=lambda: [0, 0])   # grid 3x5
    wm_enabled: bool = False
    wm_text: str = ""
    wm_pos: list = field(default_factory=lambda: [1, 2])
    wm_size: int = 60
    wm_opacity: float = 0.35
    # efek
    fx_punch: bool = True
    fx_shots: bool = False          # potongan shot: bergantian close-up & shot lebar
    fx_slowzoom: bool = True
    fx_progress: bool = True
    fx_fade: bool = True
    fx_grade: bool = True
    fx_vignette: bool = False
    # audio tambahan
    bgm_path: str = ""
    bgm_volume: float = 12.0        # % (musik latar)
    sfx_path: str = ""
    sfx_volume: float = 100.0       # % (efek suara hook, diputar di detik 0)
    voice_volume: float = 100.0     # % suara asli video
    encoder: str = "auto"           # auto | cpu | nvenc | qsv | amf | videotoolbox
    # audio / pemotongan
    cut_silence: bool = True
    silence_gap: float = 0.45
    remove_fillers: bool = True
    loudnorm: bool = True

    def to_dict(self):
        return asdict(self)

    def scaled(self, k: float) -> "Style":
        """Salinan dengan ukuran piksel diskalakan (untuk pratinjau resolusi rendah)."""
        d = self.to_dict()
        for f in ("sub_size", "hook_size", "sub_inner_w", "sub_outer_w", "wm_size"):
            d[f] = max(int(round(d[f] * k)), 1)
        d["out_width"], d["out_height"] = int(self.out_width * k) // 2 * 2, int(self.out_height * k) // 2 * 2
        return Style.from_dict(d)

    @staticmethod
    def from_dict(d: dict) -> "Style":
        s = Style()
        for k, v in (d or {}).items():
            if hasattr(s, k):
                setattr(s, k, v)
        return s

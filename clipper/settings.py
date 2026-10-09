from __future__ import annotations

import json
import os
from dataclasses import dataclass, field

from .models import Style
from .paths import data_dir


@dataclass
class Settings:
    api_key: str = ""
    gemini_model: str = "gemini-2.5-flash"
    whisper_model: str = "small"
    language: str = "auto"            # bahasa ucapan (auto/id/en/...)
    target_lang: str = ""             # kosong = tanpa terjemahan
    clip_count: int = 5
    min_sec: int = 30
    max_sec: int = 75
    output_dir: str = ""
    clip_prompt: str = ""             # instruksi kustom untuk pencarian klip
    use_gemini_polish: bool = True
    make_thumbnail: bool = True
    compile_clips: bool = False       # buat juga satu video kompilasi dari semua klip terpilih
    compile_transition: float = 0.4
    cookies_file: str = ""            # file cookies Netscape untuk YouTube
    cookies_browser: str = ""         # chrome | edge | firefox | brave ... (ambil cookies dari browser)
    proxy: str = ""
    last_source: str = ""
    style: Style = field(default_factory=Style)

    def api(self) -> str:
        return self.api_key or os.environ.get("GEMINI_API_KEY", "") or os.environ.get("GOOGLE_API_KEY", "")


def _path():
    return data_dir() / "settings.json"


def load() -> Settings:
    s = Settings()
    try:
        d = json.loads(_path().read_text(encoding="utf-8"))
    except Exception:
        return s
    for k, v in d.items():
        if k == "style":
            s.style = Style.from_dict(v)
        elif hasattr(s, k):
            setattr(s, k, v)
    return s


def save(s: Settings) -> None:
    d = {k: getattr(s, k) for k in s.__dataclass_fields__ if k != "style"}
    d["style"] = s.style.to_dict()
    _path().write_text(json.dumps(d, indent=2, ensure_ascii=False), encoding="utf-8")

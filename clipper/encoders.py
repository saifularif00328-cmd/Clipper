"""Deteksi & pemilihan encoder video (GPU bila tersedia, otomatis kembali ke CPU)."""
from __future__ import annotations

import subprocess
from functools import lru_cache
from typing import Dict, List

from . import paths

CHOICES = ["auto", "cpu", "nvenc", "qsv", "amf", "videotoolbox"]
CODEC = {"nvenc": "h264_nvenc", "qsv": "h264_qsv", "amf": "h264_amf", "videotoolbox": "h264_videotoolbox"}


@lru_cache(maxsize=1)
def available() -> Dict[str, bool]:
    """Uji-coba encode 0,2 detik untuk tiap encoder (daftar `-encoders` saja tidak menjamin perangkat ada)."""
    res = {}
    for key, codec in CODEC.items():
        try:
            p = subprocess.run(
                [paths.ffmpeg(), "-v", "error", "-f", "lavfi", "-i", "color=c=black:s=256x256:d=0.2:r=10",
                 "-c:v", codec, "-f", "null", "-"],
                capture_output=True, timeout=25, creationflags=paths.no_window_flags())
            res[key] = p.returncode == 0
        except Exception:
            res[key] = False
    return res


def resolve(choice: str) -> str:
    """'auto' -> encoder GPU pertama yang bekerja, jika tidak ada 'cpu'."""
    choice = (choice or "auto").lower()
    if choice == "cpu":
        return "cpu"
    if choice == "auto":
        av = available()
        return next((k for k in ("nvenc", "qsv", "amf", "videotoolbox") if av.get(k)), "cpu")
    return choice if choice in CODEC else "cpu"


def video_args(encoder: str, quick: bool = False) -> List[str]:
    """Argumen ffmpeg untuk encoder yang sudah di-resolve."""
    if encoder == "nvenc":
        return ["-c:v", "h264_nvenc", "-preset", "p1" if quick else "p5", "-rc", "vbr",
                "-cq", "32" if quick else "21", "-b:v", "0"]
    if encoder == "qsv":
        return ["-c:v", "h264_qsv", "-global_quality", "32" if quick else "22",
                "-preset", "veryfast" if quick else "medium"]
    if encoder == "amf":
        q = "32" if quick else "21"
        return ["-c:v", "h264_amf", "-quality", "speed" if quick else "quality", "-rc", "cqp",
                "-qp_i", q, "-qp_p", q]
    if encoder == "videotoolbox":
        return ["-c:v", "h264_videotoolbox", "-q:v", "40" if quick else "65"]
    return ["-c:v", "libx264", "-preset", "ultrafast" if quick else "medium", "-crf", "30" if quick else "18"]

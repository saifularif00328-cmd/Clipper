"""Lokasi file aplikasi (mode script maupun .exe hasil PyInstaller)."""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path


def app_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parent.parent


def asset(*parts: str) -> Path:
    return app_root().joinpath("assets", *parts)


def data_dir() -> Path:
    d = Path.home() / ".clipper"
    d.mkdir(parents=True, exist_ok=True)
    return d


def exe_name(name: str) -> str:
    return name + (".exe" if os.name == "nt" else "")


def find_binary(name: str) -> str:
    """Cari ffmpeg/ffprobe: folder bundel -> sebelah exe -> PATH."""
    candidates = [
        asset("ffmpeg", exe_name(name)),
        Path(sys.executable).parent / exe_name(name),
        Path(sys.executable).parent / "ffmpeg" / exe_name(name),
    ]
    for c in candidates:
        if c.exists():
            return str(c)
    found = shutil.which(name)
    if found:
        return found
    raise FileNotFoundError(
        f"{name} tidak ditemukan. Letakkan {exe_name(name)} di folder 'ffmpeg' "
        "di samping aplikasi atau pasang ke PATH."
    )


def ffmpeg() -> str:
    return find_binary("ffmpeg")


def ffprobe() -> str:
    return find_binary("ffprobe")


def no_window_flags() -> int:
    """Sembunyikan jendela konsol subprocess di Windows."""
    return getattr(__import__("subprocess"), "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0

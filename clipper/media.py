"""Helper ffmpeg/ffprobe dan pengunduh YouTube."""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Callable, Optional

from . import paths

LogFn = Callable[[str], None]


def run(cmd: list, log: Optional[LogFn] = None, cwd=None) -> subprocess.CompletedProcess:
    p = subprocess.run(
        cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
        cwd=cwd, creationflags=paths.no_window_flags(),
    )
    if p.returncode != 0:
        tail = "\n".join((p.stderr or "").strip().splitlines()[-12:])
        raise RuntimeError(f"Perintah gagal ({Path(cmd[0]).name}):\n{tail}")
    return p


def probe(path: str) -> dict:
    p = run([paths.ffprobe(), "-v", "error", "-print_format", "json", "-show_streams",
             "-show_format", str(path)])
    info = json.loads(p.stdout)
    v = next((s for s in info["streams"] if s["codec_type"] == "video"), None)
    a = next((s for s in info["streams"] if s["codec_type"] == "audio"), None)
    num, den = (v.get("r_frame_rate", "30/1").split("/") + ["1"])[:2] if v else ("30", "1")
    fps = float(num) / float(den or 1) if float(den or 1) else 30.0
    return {
        "width": int(v["width"]) if v else 0,
        "height": int(v["height"]) if v else 0,
        "fps": fps if 1 < fps < 121 else 30.0,
        "duration": float(info["format"].get("duration", 0)),
        "has_audio": a is not None,
    }


def is_url(s: str) -> bool:
    return bool(re.match(r"^https?://", s.strip(), re.I))


def download_video(url: str, out_dir: Path, log: LogFn = print, progress=None) -> Path:
    """Unduh video YouTube (maks 1080p, mp4) memakai yt-dlp."""
    import yt_dlp

    out_dir.mkdir(parents=True, exist_ok=True)

    def hook(d):
        if d.get("status") == "downloading" and progress:
            tot = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            if tot:
                progress(d.get("downloaded_bytes", 0) / tot)

    opts = {
        "format": "bv*[height<=1080]+ba/b[height<=1080]/b",
        "merge_output_format": "mp4",
        "outtmpl": str(out_dir / "%(title).80B [%(id)s].%(ext)s"),
        "restrictfilenames": False,
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "progress_hooks": [hook],
        "ffmpeg_location": str(Path(paths.ffmpeg()).parent),
        "windowsfilenames": True,
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)
        fn = Path(ydl.prepare_filename(info)).with_suffix(".mp4")
    if not fn.exists():
        cands = sorted(out_dir.glob(f"*{info.get('id', '')}*.mp4"))
        if not cands:
            raise RuntimeError("File hasil unduhan tidak ditemukan.")
        fn = cands[0]
    log(f"Video diunduh: {fn.name}")
    return fn

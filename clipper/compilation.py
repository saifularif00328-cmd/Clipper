"""Kompilasi: gabungkan beberapa klip hasil render menjadi satu video dengan crossfade."""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Callable, List, Optional

from . import encoders, paths
from .media import probe


def build_graph(durs: List[float], t: float, with_audio: bool) -> str:
    """Rantai xfade (video) + acrossfade (audio). Offset ke-k = jumlah durasi sebelumnya - k*t."""
    n = len(durs)
    parts: List[str] = []
    vl, al = "[0:v]", "[0:a]"
    acc = durs[0]
    for k in range(1, n):
        off = max(acc - t, 0.0)
        parts.append(f"{vl}[{k}:v]xfade=transition=fade:duration={t:.3f}:offset={off:.3f}[xv{k}]")
        vl = f"[xv{k}]"
        if with_audio:
            parts.append(f"{al}[{k}:a]acrossfade=d={t:.3f}:c1=tri:c2=tri[xa{k}]")
            al = f"[xa{k}]"
        acc = acc + durs[k] - t
    parts.append(f"{vl}format=yuv420p[vout]")
    if with_audio:
        parts.append(f"{al}anull[aout]")
    return ";\n".join(parts)


def compile_clips(clips: List[Path], out: Path, transition: float = 0.4, encoder: str = "auto",
                  log: Callable[[str], None] = print) -> Path:
    """Gabungkan `clips` (urutan diberikan) ke `out`. Satu klip -> disalin apa adanya."""
    if not clips:
        raise ValueError("Tidak ada klip untuk digabung.")
    if len(clips) == 1:
        out.write_bytes(Path(clips[0]).read_bytes())
        return out
    infos = [probe(str(c)) for c in clips]
    durs = [i["duration"] for i in infos]
    t = max(0.05, min(transition, min(durs) / 2.5))          # transisi tak boleh melebihi klip pendek
    with_audio = all(i["has_audio"] for i in infos)
    script = out.with_suffix(".filter.txt")
    script.write_text(build_graph(durs, t, with_audio), encoding="utf-8")
    enc = encoders.resolve(encoder)

    def run(e: str) -> subprocess.CompletedProcess:
        cmd = [paths.ffmpeg(), "-y"]
        for c in clips:
            cmd += ["-i", str(c)]
        cmd += ["-filter_complex_script", str(script), "-map", "[vout]"]
        if with_audio:
            cmd += ["-map", "[aout]", "-c:a", "aac", "-b:a", "192k"]
        cmd += encoders.video_args(e) + ["-pix_fmt", "yuv420p", "-movflags", "+faststart", str(out)]
        return subprocess.run(cmd, capture_output=True, text=True, errors="replace",
                              creationflags=paths.no_window_flags())

    p = run(enc)
    if p.returncode != 0 and enc != "cpu":
        log(f"  ! Encoder {enc} gagal untuk kompilasi, mengulang dengan CPU...")
        p = run("cpu")
    script.unlink(missing_ok=True)
    if p.returncode != 0:
        raise RuntimeError("Gagal membuat kompilasi:\n" + "\n".join(p.stderr.strip().splitlines()[-10:]))
    return out

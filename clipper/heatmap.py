"""Sinyal 'minat penonton': heatmap 'paling banyak diputar ulang' YouTube atau energi audio lokal."""
from __future__ import annotations

import wave
from pathlib import Path
from typing import List, Optional

import numpy as np

Heat = List[dict]   # [{"start": s, "end": e, "value": 0..1}]


def from_youtube(raw: Optional[list]) -> Heat:
    """Ubah field `heatmap` hasil yt-dlp menjadi format internal (nilai dinormalisasi 0..1)."""
    out = []
    for p in raw or []:
        try:
            out.append({"start": float(p["start_time"]), "end": float(p["end_time"]), "value": float(p["value"])})
        except (KeyError, TypeError, ValueError):
            continue
    if not out:
        return []
    hi = max(p["value"] for p in out) or 1.0
    for p in out:
        p["value"] = max(0.0, min(1.0, p["value"] / hi))
    return out


def from_audio(wav_path: Path, step: float = 2.0) -> Heat:
    """Energi RMS per jendela `step` detik dari WAV mono 16-bit, dinormalisasi 0..1."""
    try:
        with wave.open(str(wav_path), "rb") as w:
            sr, n = w.getframerate(), w.getnframes()
            raw = w.readframes(n)
    except Exception:
        return []
    x = np.frombuffer(raw, dtype=np.int16).astype(np.float32)
    if x.size == 0:
        return []
    win = max(int(sr * step), 1)
    out = []
    for i in range(0, x.size, win):
        seg = x[i:i + win]
        out.append({"start": i / sr, "end": min((i + win) / sr, x.size / sr),
                    "value": float(np.sqrt(np.mean(seg ** 2)))})
    # akar agar rentang dinamis tidak didominasi satu ledakan, lalu normalisasi
    vals = np.sqrt(np.array([p["value"] for p in out]))
    hi = float(vals.max()) or 1.0
    for p, v in zip(out, vals):
        p["value"] = float(v / hi)
    return out


def average(heat: Heat, start: float, end: float) -> float:
    """Rata-rata nilai heatmap pada [start, end], tertimbang panjang irisan."""
    tot, acc = 0.0, 0.0
    for p in heat:
        ov = min(end, p["end"]) - max(start, p["start"])
        if ov > 0:
            tot += ov
            acc += ov * p["value"]
    return acc / tot if tot else 0.0

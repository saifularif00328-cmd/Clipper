"""Transkripsi lokal dengan faster-whisper (timestamp per kata)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Callable, List, Tuple

from . import paths
from .media import run
from .models import Word


def extract_audio(video: Path, wav: Path) -> None:
    run([paths.ffmpeg(), "-y", "-i", str(video), "-vn", "-ac", "1", "-ar", "16000",
         "-c:a", "pcm_s16le", str(wav)])


def transcribe(video: Path, work: Path, model_name: str = "small", language: str = "auto",
               log: Callable[[str], None] = print, progress=None) -> Tuple[List[Word], str]:
    cache = work / "transcript.json"
    if cache.exists():
        d = json.loads(cache.read_text(encoding="utf-8"))
        if d.get("model") == model_name and d.get("req_lang") == language:
            log("Transkrip dimuat dari cache.")
            return [Word(**w) for w in d["words"]], d["language"]

    from faster_whisper import WhisperModel

    work.mkdir(parents=True, exist_ok=True)
    wav = work / "audio16k.wav"
    log("Mengekstrak audio...")
    extract_audio(video, wav)
    log(f"Memuat model Whisper '{model_name}' (unduhan pertama bisa beberapa menit)...")
    model = WhisperModel(model_name, device="cpu", compute_type="int8",
                         download_root=str(paths.data_dir() / "models"))
    segments, info = model.transcribe(
        str(wav), language=None if language == "auto" else language,
        word_timestamps=True, vad_filter=True, beam_size=5,
        vad_parameters={"min_silence_duration_ms": 300},
    )
    total = max(info.duration, 1.0)
    log(f"Bahasa terdeteksi: {info.language}. Mentranskrip...")
    words: List[Word] = []
    for seg in segments:
        for w in (seg.words or []):
            t = w.word.strip()
            if t:
                words.append(Word(t, float(w.start), float(w.end)))
        if progress:
            progress(min(seg.end / total, 1.0))
    cache.write_text(json.dumps({
        "model": model_name, "req_lang": language, "language": info.language,
        "words": [w.to_dict() for w in words]}, ensure_ascii=False), encoding="utf-8")
    return words, info.language

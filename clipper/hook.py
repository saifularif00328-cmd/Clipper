"""Voice-over opsional untuk hook (edge-tts, gratis & tanpa API key)."""
from __future__ import annotations

import asyncio
from pathlib import Path

from . import paths
from .media import probe

VOICES = {
    "id": "id-ID-ArdhiNeural", "en": "en-US-GuyNeural", "es": "es-ES-AlvaroNeural",
    "pt": "pt-BR-AntonioNeural", "fr": "fr-FR-HenriNeural", "de": "de-DE-ConradNeural",
    "ja": "ja-JP-KeitaNeural", "ko": "ko-KR-InJoonNeural", "zh": "zh-CN-YunxiNeural",
    "ar": "ar-SA-HamedNeural", "hi": "hi-IN-MadhurNeural", "ru": "ru-RU-DmitryNeural",
    "tr": "tr-TR-AhmetNeural", "th": "th-TH-NiwatNeural", "vi": "vi-VN-NamMinhNeural",
    "ms": "ms-MY-OsmanNeural", "it": "it-IT-DiegoNeural", "nl": "nl-NL-MaartenNeural",
}


def make_voice(text: str, lang: str, out: Path, voice: str = "") -> float:
    """Buat voice-over mp3, kembalikan durasi (detik)."""
    import edge_tts

    v = voice or VOICES.get(lang, VOICES["en"])

    async def go():
        await edge_tts.Communicate(text, v, rate="+8%", volume="+10%").save(str(out))

    asyncio.run(go())
    return probe(str(out))["duration"]

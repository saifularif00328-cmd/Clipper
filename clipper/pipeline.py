"""Orkestrasi: unduh -> transkrip -> pilih klip (cache) -> render + thumbnail."""
from __future__ import annotations

import json
import re
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, List, Optional

from . import ai, heatmap, library, media, paths
from .models import Clip, Word
from .settings import Settings
from .textproc import fmt_time

Log = Callable[[str], None]


class Cancelled(Exception):
    pass


def safe_name(s: str, n: int = 60) -> str:
    s = re.sub(r'[\\/:*?"<>|\x00-\x1f]+', "", s).strip(" .")
    return (s[:n].strip(" .")) or "video"


@dataclass
class Project:
    video: Path
    dir: Path
    lang: str
    words: List[Word]
    clips: List[Clip] = field(default_factory=list)

    @property
    def list_file(self) -> Path:
        return self.dir / "list_clip.json"

    def save(self, params: dict) -> None:
        self.list_file.write_text(json.dumps({
            "version": 1, "video": str(self.video), "language": self.lang, "params": params,
            "clips": [c.to_dict() for c in self.clips]}, ensure_ascii=False, indent=2), encoding="utf-8")


class Pipeline:
    def __init__(self, cfg: Settings, log: Log = print,
                 progress: Callable[[float, str], None] = lambda p, m: None):
        self.cfg, self.log, self.progress = cfg, log, progress
        self.cancel = threading.Event()

    def _check(self):
        if self.cancel.is_set():
            raise Cancelled()

    def _out_root(self, video: Path) -> Path:
        base = Path(self.cfg.output_dir) if self.cfg.output_dir else video.parent / "Clipper_output"
        # nama folder ASCII-aman: OpenCV di Windows sering gagal membuka path non-ASCII
        import hashlib
        import unicodedata
        ascii_name = unicodedata.normalize("NFKD", video.stem).encode("ascii", "ignore").decode()
        ascii_name = safe_name(ascii_name, 50)
        if ascii_name != video.stem or not ascii_name.strip():
            ascii_name = f"{ascii_name if ascii_name != 'video' else 'video'}-" + \
                hashlib.md5(video.stem.encode("utf-8")).hexdigest()[:6]
        d = base / ascii_name
        d.mkdir(parents=True, exist_ok=True)
        return d

    # ---------------------------------------------------------------- analisis
    def analyze(self, source: str, use_cache: bool = True) -> Project:
        cfg = self.cfg
        src = source.strip().strip('"')
        yt_info = {}
        if media.is_url(src):
            self.progress(0.0, "Mengunduh video...")
            dl_dir = (Path(cfg.output_dir) if cfg.output_dir else paths.data_dir()) / "downloads"
            yt_info: dict = {}
            video = media.download_video(src, dl_dir, self.log,
                                         lambda p: self.progress(0.1 * p, "Mengunduh video..."),
                                         cookies_file=cfg.cookies_file, cookies_browser=cfg.cookies_browser,
                                         proxy=cfg.proxy, info_out=yt_info)
        else:
            video = Path(src)
            if not video.exists():
                raise FileNotFoundError(f"File tidak ditemukan: {video}")
        self._check()
        pdir = self._out_root(video)
        from .transcribe import transcribe
        self.progress(0.1, "Transkripsi...")
        words, lang = transcribe(video, pdir, cfg.whisper_model, cfg.language, self.log,
                                 lambda p: self.progress(0.1 + 0.5 * p, "Transkripsi..."))
        if not words:
            raise RuntimeError("Tidak ada ucapan terdeteksi di video ini.")
        self._check()
        params = {"count": cfg.clip_count, "min": cfg.min_sec, "max": cfg.max_sec,
                  "model": cfg.gemini_model, "whisper": cfg.whisper_model, "prompt": cfg.clip_prompt.strip()}
        proj = Project(video, pdir, lang, words)
        heat = self._heat(pdir, yt_info)
        if use_cache and proj.list_file.exists():
            try:
                d = json.loads(proj.list_file.read_text(encoding="utf-8"))
                if d.get("params") == params:
                    proj.clips = [Clip.from_dict(c) for c in d["clips"]]
                    self.log("Daftar klip dimuat dari cache (list_clip.json) - hemat kuota Gemini.")
                    library.register_project(proj.list_file, video, len(proj.clips))
                    self.progress(1.0, "Selesai")
                    return proj
            except Exception:
                pass
        self.progress(0.65, "Memilih klip terbaik...")
        if cfg.api():
            self.log(f"Gemini ({cfg.gemini_model}) menganalisis transkrip...")
            g = ai.Gemini(cfg.api(), cfg.gemini_model)
            clips = ai.select_clips_ai(g, words, cfg.clip_count, cfg.min_sec, cfg.max_sec, lang, self.log,
                                       cfg.clip_prompt, heat, yt_info.get("channel", ""))
        else:
            self.log("API key Gemini kosong - memakai pemilihan lokal sederhana.")
            clips = ai.select_clips_local(words, cfg.clip_count, cfg.min_sec, cfg.max_sec, heat)
        clips = ai.enforce_complete(clips, words, cfg.max_sec)
        clips.sort(key=lambda c: c.start)
        for n, c in enumerate(clips, 1):
            c.id = n
        proj.clips = clips
        proj.save(params)
        library.register_project(proj.list_file, video, len(clips))
        self.log(f"{len(clips)} klip ditemukan.")
        self.progress(1.0, "Selesai")
        return proj

    def _heat(self, pdir: Path, yt_info: dict):
        """Heatmap minat: YouTube 'paling banyak diputar ulang' bila ada, jika tidak energi audio. Di-cache."""
        f = pdir / "heat.json"
        if f.exists():
            try:
                return json.loads(f.read_text(encoding="utf-8"))
            except Exception:
                pass
        heat = heatmap.from_youtube(yt_info.get("heatmap"))
        src = "YouTube"
        if not heat:
            heat, src = heatmap.from_audio(pdir / "audio16k.wav"), "energi audio"
        if heat:
            f.write_text(json.dumps(heat), encoding="utf-8")
            self.log(f"Heatmap minat penonton dipakai ({src}).")
        return heat

    @staticmethod
    def zip_results(proj: Project) -> Path:
        """Kemas semua hasil (mp4, thumbnail, caption) ke satu file ZIP."""
        import zipfile
        out = proj.dir / "clips.zip"
        with zipfile.ZipFile(out, "w", zipfile.ZIP_STORED) as z:
            for f in sorted((proj.dir / "clips").glob("*")):
                if f.suffix.lower() in (".mp4", ".jpg", ".txt"):
                    z.write(f, f.name)
        return out

    @staticmethod
    def load_cache(list_file: Path) -> Project:
        d = json.loads(Path(list_file).read_text(encoding="utf-8"))
        pdir = Path(list_file).parent
        t = json.loads((pdir / "transcript.json").read_text(encoding="utf-8"))
        proj = Project(Path(d["video"]), pdir, d.get("language", t.get("language", "en")),
                       [Word(**w) for w in t["words"]], [Clip.from_dict(c) for c in d["clips"]])
        return proj

    # ---------------------------------------------------------------- pratinjau cepat
    def preview(self, proj: Project, clip: Clip) -> Path:
        """Render cepat resolusi rendah (tanpa Gemini/voice/thumbnail) untuk dicek sebelum ekspor."""
        from .render import finish_render, prepare_clip
        st = self.cfg.style.scaled(360 / max(self.cfg.style.out_width, 1))
        st.loudnorm = False
        work = proj.dir / "work_preview"
        out_dir = proj.dir / "preview"
        out_dir.mkdir(exist_ok=True)
        prep = prepare_clip(proj.video, clip, proj.words, st, work, self.log)
        out = out_dir / f"preview_clip{clip.id:02d}.mp4"
        finish_render(proj.video, clip, prep, prep["rwords"], st, out, work, None, st.hook_seconds, clip.hook,
                      self.log, lambda p: self.progress(p, f"Pratinjau klip {clip.id}"), quick=True)
        return out

    # ---------------------------------------------------------------- render
    def render(self, proj: Project, clips: List[Clip]) -> List[Path]:
        from .hook import make_voice
        from .render import finish_render, prepare_clip
        from .thumbnail import make_thumbnails

        cfg, st = self.cfg, self.cfg.style
        gem = ai.Gemini(cfg.api(), cfg.gemini_model) if cfg.api() and (
            cfg.use_gemini_polish or cfg.target_lang) else None
        out_dir = proj.dir / "clips"
        out_dir.mkdir(exist_ok=True)
        work = proj.dir / "work"
        results = []
        total = len(clips)
        for n, clip in enumerate(clips):
            self._check()
            base = n / total

            def prog(p, msg=f"Merender klip {clip.id}/{total}"):
                self.progress(base + p / total, msg)

            self.log(f"Klip {clip.id}: {clip.title}")
            prep = prepare_clip(proj.video, clip, proj.words, st, work, self.log)
            rwords, c = prep["rwords"], clip
            if gem:
                try:
                    self.log("  Merapikan transkrip / menerjemahkan dengan Gemini...")
                    rwords, c = ai.polish_and_translate(gem, clip, rwords, proj.lang, cfg.target_lang,
                                                        cfg.use_gemini_polish)
                except Exception as e:
                    self.log(f"  ! Gemini gagal ({e}); memakai teks asli.")
            elif cfg.target_lang and cfg.target_lang != proj.lang:
                self.log("  ! Terjemahan butuh API key Gemini - dilewati.")
            hook_sec = st.hook_seconds
            voice = None
            if st.hook_enabled and st.hook_voice and c.hook:
                try:
                    vlang = cfg.target_lang or proj.lang
                    voice = work / f"clip{clip.id}_hook.mp3"
                    d = make_voice(c.hook, vlang, voice, st.hook_voice_name)
                    hook_sec = max(hook_sec, d + 0.6)
                except Exception as e:
                    self.log(f"  ! Voice-over gagal ({e}); lanjut tanpa suara.")
                    voice = None
            self._check()
            name = f"clip{clip.id:02d}_{safe_name(c.title or 'klip', 40)}"
            out = out_dir / f"{name}.mp4"
            r = finish_render(proj.video, c, prep, rwords, st, out, work, voice, hook_sec, c.hook,
                              self.log, prog)
            results.append(out)
            tags = " ".join(h if h.startswith("#") else f"#{h}" for h in c.hashtags)
            (out_dir / f"{name}.txt").write_text(
                f"{c.title}\n\n{c.caption}\n\n{tags}\n\nHook: {c.hook}\n"
                f"Waktu sumber: {fmt_time(clip.start)} - {fmt_time(clip.end)}\n", encoding="utf-8")
            if cfg.make_thumbnail:
                try:
                    thumbs = make_thumbnails(str(r["stage1"]), c.thumb_text or c.title, st, out_dir / name)
                    self.log(f"  Thumbnail: {', '.join(t.name for t in thumbs)}")
                except Exception as e:
                    self.log(f"  ! Thumbnail gagal: {e}")
            self.log(f"  Selesai: {out.name}")
            self.progress((n + 1) / total, f"Klip {clip.id} selesai")
        return results

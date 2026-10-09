"""Render satu klip: potong jeda -> face tracking -> crop 9:16 + efek -> subtitle/hook/logo."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Callable, List, Optional, Tuple

import cv2
import numpy as np

from . import paths
from .face_track import camera_path
from .media import probe, run
from .models import Clip, Style, Word
from .subtitles import build_ass
from .textproc import build_time_map, compute_keep_segments, is_filler, norm, remap_words, split_sentences

Log = Callable[[str], None]


# ------------------------------------------------------------------ tahap 1: potong
def cut_segments(src: Path, segs: List[Tuple[float, float]], out: Path, fps: int, has_audio: bool,
                 work: Path) -> None:
    base = max(0.0, segs[0][0] - 1.0)
    parts, cv, ca = [], [], []
    for k, (a, b) in enumerate(segs):
        a, b = a - base, b - base
        d = b - a
        parts.append(f"[0:v]trim=start={a:.3f}:end={b:.3f},setpts=PTS-STARTPTS,fps={fps}[v{k}]")
        cv.append(f"[v{k}]")
        if has_audio:
            fd = min(0.015, d / 4)
            parts.append(f"[0:a]atrim=start={a:.3f}:end={b:.3f},asetpts=PTS-STARTPTS,aresample=48000,"
                         f"afade=t=in:d={fd:.3f},afade=t=out:st={d - fd:.3f}:d={fd:.3f}[a{k}]")
            ca.append(f"[a{k}]")
    n = len(segs)
    inter = "".join(f"{v}{a}" for v, a in zip(cv, ca)) if has_audio else "".join(cv)
    parts.append(f"{inter}concat=n={n}:v=1:a={1 if has_audio else 0}[vc]" + ("[ac]" if has_audio else ""))
    parts.append("[vc]scale=-2:'min(1080,ih)':flags=bicubic,format=yuv420p[vo]")
    script = work / "cut_filter.txt"
    script.write_text(";\n".join(parts), encoding="utf-8")
    cmd = [paths.ffmpeg(), "-y", "-ss", f"{base:.3f}", "-i", str(src),
           "-filter_complex_script", str(script), "-map", "[vo]"]
    if has_audio:
        cmd += ["-map", "[ac]", "-c:a", "aac", "-b:a", "256k"]
    cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "12", "-pix_fmt", "yuv420p", str(out)]
    run(cmd)


# ------------------------------------------------------------------ efek zoom
def zoom_series(n: int, fps: float, words: List[Word], st: Style) -> np.ndarray:
    z = np.ones(n)
    t = np.arange(n) / fps
    if st.fx_slowzoom:
        z += 0.06 * (t / max(t[-1], 1e-3))
    if st.fx_shots and words:
        # potongan shot ala podcast: bergantian shot lebar <-> close-up (transisi cepat 0.18 dtk)
        sents = split_sentences(words, pause=0.5)
        level, last, tgt = 0, -9.0, np.zeros(n)
        switches = []
        for a, _ in sents:
            if words[a].start - last >= 3.2:
                switches.append(words[a].start)
                last = words[a].start
        for T in switches:
            level = 1 - level
            tgt = np.where(t >= T, float(level), tgt)
        sm = np.clip(np.convolve(tgt, np.ones(max(int(fps * 0.18), 1)) / max(int(fps * 0.18), 1), mode="same"), 0, 1)
        z += 0.5 * sm
    if st.fx_punch and words and not st.fx_shots:
        triggers, last = [], -9.0
        sents = split_sentences(words, pause=0.5)
        for a, _ in sents:
            if words[a].start - last >= 3.5:
                triggers.append(words[a].start)
                last = words[a].start
        for T in triggers:
            d = t - T
            attack = np.clip(d / 0.08, 0, 1)
            decay = np.exp(-np.maximum(d - 0.08, 0) / 0.55)
            z += np.where(d >= 0, 0.075 * attack * decay, 0)
    return z


# ------------------------------------------------------------------ transformasi frame
class Framer:
    def __init__(self, src_w: int, src_h: int, W: int, H: int, layout: str):
        self.sw, self.sh, self.W, self.H, self.layout = src_w, src_h, W, H, layout
        self.ar = W / H

    def _crop(self, frame, cx, cy, zoom):
        ch = self.sh / zoom
        cw = ch * self.ar
        if cw > self.sw:
            cw = self.sw / zoom if zoom > 1 else self.sw
            ch = cw / self.ar
        x0 = min(max(cx - cw / 2, 0), self.sw - cw)
        y0 = min(max(cy - ch / 2, 0), self.sh - ch)
        s = self.W / cw
        M = np.array([[s, 0, -x0 * s], [0, s, -y0 * s]], dtype=np.float32)
        return cv2.warpAffine(frame, M, (self.W, self.H), flags=cv2.INTER_CUBIC,
                              borderMode=cv2.BORDER_REPLICATE)

    def __call__(self, frame, cx, cy, zoom):
        if self.layout in ("face", "center"):
            return self._crop(frame, cx, cy, zoom)
        # blur: latar buram + video penuh lebar di tengah
        # latar = crop tengah diisi, diburamkan
        bgsrc = self._crop(frame, self.sw / 2, self.sh / 2, 1.0)
        bg = cv2.resize(bgsrc, (self.W // 8, self.H // 8), interpolation=cv2.INTER_AREA)
        bg = cv2.GaussianBlur(bg, (0, 0), 6)
        bg = cv2.resize(bg, (self.W, self.H), interpolation=cv2.INTER_LINEAR)
        bg = (bg * 0.55).astype(np.uint8)
        s = (self.W / self.sw) * zoom
        fw, fh = self.sw * s, self.sh * s
        tx = (self.W - fw) / 2
        ty = (self.H - fh) / 2
        M = np.array([[s, 0, tx], [0, s, ty]], dtype=np.float32)
        cv2.warpAffine(frame, M, (self.W, self.H), dst=bg, flags=cv2.INTER_CUBIC,
                       borderMode=cv2.BORDER_TRANSPARENT)
        return bg


# ------------------------------------------------------------------ ffmpeg helpers
def logo_xy(col: int, row: int) -> Tuple[str, str]:
    xs = ["W*0.04", "(W-w)/2", "W-w-W*0.04"]
    ys = ["H*0.07", "(H-h)/2", "H-h-H*0.07"]
    return xs[col], ys[row]


def build_final_cmd(stage1: Path, out: Path, st: Style, W: int, H: int, fps: float, duration: float,
                    has_audio: bool, ass_name: Optional[str], fontsdir: Optional[str],
                    voice: Optional[Path], hook_sec: float) -> list:
    cmd = [paths.ffmpeg(), "-y", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{W}x{H}",
           "-r", f"{fps:.4f}", "-i", "-", "-i", str(stage1)]
    idx = 2
    logo_idx = voice_idx = None
    if st.logo_path and Path(st.logo_path).exists():
        cmd += ["-loop", "1", "-i", st.logo_path]
        logo_idx, idx = idx, idx + 1
    if voice:
        cmd += ["-i", str(voice)]
        voice_idx, idx = idx, idx + 1

    vf = []
    if st.fx_grade:
        vf.append("eq=contrast=1.06:saturation=1.16:gamma=0.98,unsharp=5:5:0.5:5:5:0.0")
    if st.fx_vignette:
        vf.append("vignette=PI/6")
    if ass_name:
        vf.append(f"ass={ass_name}" + (f":fontsdir={fontsdir}" if fontsdir else ""))
    if st.fx_fade:
        vf.append("fade=t=in:d=0.25")
        vf.append(f"fade=t=out:st={max(duration - 0.35, 0):.3f}:d=0.35")
    chain = ",".join(vf) if vf else "null"
    graph = [f"[0:v]{chain}[v0]"]
    last = "v0"
    if logo_idx is not None:
        x, y = logo_xy(*st.logo_pos)
        graph.append(f"[{logo_idx}:v]format=rgba,scale={int(W * st.logo_scale)}:-1,"
                     f"colorchannelmixer=aa={st.logo_opacity:.2f}[lg]")
        graph.append(f"[v0][lg]overlay=x={x}:y={y}:shortest=1[v1]")
        last = "v1"
    amap = None
    if has_audio:
        a = "[1:a]"
        if voice_idx is not None:
            graph.append(f"{a}volume='if(lt(t,{hook_sec:.2f}),0.35,1)':eval=frame[bg]")
            graph.append(f"[{voice_idx}:a]adelay=120|120,volume=1.4[vo]")
            graph.append("[bg][vo]amix=inputs=2:duration=first:normalize=0[am]")
            a = "[am]"
        post = []
        if st.loudnorm:
            post.append("loudnorm=I=-16:TP=-1.5:LRA=11")
        if st.fx_fade:
            post.append("afade=t=in:d=0.2")
            post.append(f"afade=t=out:st={max(duration - 0.3, 0):.3f}:d=0.3")
        graph.append(f"{a}{','.join(post) if post else 'anull'}[aout]")
        amap = "[aout]"
    graph_text = ";".join(graph)
    cmd += ["-filter_complex", graph_text, "-map", f"[{last}]"]
    if amap:
        cmd += ["-map", amap, "-c:a", "aac", "-b:a", "192k"]
    cmd += ["-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p",
            "-movflags", "+faststart", "-t", f"{duration:.3f}", str(out)]
    return cmd


# ------------------------------------------------------------------ utama
def prepare_clip(src: Path, clip: Clip, words: List[Word], st: Style, work: Path,
                 log: Log = print) -> dict:
    """Tahap awal: tentukan segmen yang dipertahankan (jeda & filler dibuang) + remap kata."""
    work.mkdir(parents=True, exist_ok=True)
    info = probe(str(src))
    fps = float(st.fps)
    W, H = st.out_width, st.out_height

    if st.cut_silence or st.remove_fillers:
        gap = st.silence_gap if st.cut_silence else 1e9
        segs = compute_keep_segments(words, clip.start, clip.end, max_gap=gap,
                                     cut_fillers=st.remove_fillers)
    else:
        segs = [(clip.start, clip.end)]
    tmap, total = build_time_map(segs)
    saved = (clip.end - clip.start) - total
    log(f"  Klip {clip.id}: {total:.1f}s (jeda/filler dibuang {saved:.1f}s, {len(segs)} segmen)")
    rwords = remap_words(words, segs, cut_fillers=st.remove_fillers)
    return {"segs": segs, "rwords": rwords, "total": total, "info": info, "fps": fps, "W": W, "H": H}


def finish_render(src: Path, clip: Clip, prep: dict, rwords: List[Word], st: Style, out: Path,
                  work: Path, voice_file: Optional[Path], hook_seconds: float, hook_text: str,
                  log: Log = print, progress: Optional[Callable[[float], None]] = None) -> dict:
    info, segs, fps, W, H = prep["info"], prep["segs"], prep["fps"], prep["W"], prep["H"]
    stage1 = work / f"clip{clip.id}_cut.mp4"
    cut_segments(src, segs, stage1, int(fps), info["has_audio"], work)
    s1 = probe(str(stage1))
    duration = s1["duration"]
    sw, sh = s1["width"], s1["height"]

    framer = Framer(sw, sh, W, H, st.layout)
    n_est = int(duration * fps) + 2
    cx = np.full(n_est, sw / 2)
    cy = np.full(n_est, sh / 2)
    track_info = {}
    if st.layout == "face":
        log("  Melacak wajah pembicara...")
        crop_w = min(sw, sh * W / H)
        cx, cy, track_info = camera_path(str(stage1), crop_w,
                                         progress=(lambda p: progress(0.05 + 0.25 * p)) if progress else None)
        log(f"  Wajah: {track_info['faces']} terdeteksi, {track_info['found'] * 100:.0f}% frame "
            f"({track_info['backend']})")
    zoom = zoom_series(max(len(cx), n_est), fps, rwords, st)

    ass_name = fontsdir_rel = None
    if st.sub_enabled or (st.hook_enabled and hook_text) or st.fx_progress:
        text, fdir = build_ass(rwords, st, W, H, duration, hook_text if st.hook_enabled else "",
                               hook_seconds)
        ass_name = f"clip{clip.id}.ass"
        (work / ass_name).write_text(text, encoding="utf-8")
        if fdir:
            fd = work / "fonts"
            fd.mkdir(exist_ok=True)
            for f in Path(fdir).glob("*.[to]tf"):
                try:
                    if not (fd / f.name).exists():
                        shutil.copy2(f, fd / f.name)
                except OSError:
                    pass
            fontsdir_rel = "fonts"

    cmd = build_final_cmd(stage1, out, st, W, H, fps, duration, info["has_audio"], ass_name,
                          fontsdir_rel, voice_file, hook_seconds)
    log("  Merender video final...")
    errlog = work / f"clip{clip.id}_ffmpeg.log"
    cap = cv2.VideoCapture(str(stage1))
    n_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or n_est)
    with open(errlog, "w", encoding="utf-8", errors="replace") as ef:
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=ef, cwd=str(work),
                                creationflags=paths.no_window_flags())
        i = 0
        try:
            while True:
                ok, frame = cap.read()
                if not ok:
                    break
                k = min(i, len(cx) - 1)
                outf = framer(frame, cx[k], cy[k], zoom[min(i, len(zoom) - 1)])
                proc.stdin.write(outf.tobytes())
                i += 1
                if progress and i % 15 == 0:
                    progress(0.3 + 0.7 * min(i / max(n_frames, 1), 1.0))
            proc.stdin.close()
        except (BrokenPipeError, OSError):
            pass
        finally:
            cap.release()
        rc = proc.wait()
    if rc != 0:
        tail = "\n".join(errlog.read_text(errors="replace").splitlines()[-12:])
        raise RuntimeError(f"ffmpeg gagal merender klip {clip.id}:\n{tail}")
    return {"duration": duration, "track": track_info, "stage1": stage1}

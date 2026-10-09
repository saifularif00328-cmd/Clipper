"""Thumbnail otomatis: pilih frame terbaik (wajah jelas, tajam) + teks double stroke."""
from __future__ import annotations

from pathlib import Path
from typing import List, Tuple

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageEnhance, ImageFont

from . import paths
from .face_track import FaceDetector
from .models import Style


def best_frame(video: str, samples: int = 28):
    cap = cv2.VideoCapture(video)
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    if n <= 0:
        return None, None
    det = FaceDetector()
    best, best_score = None, -1e9
    for k in range(samples):
        idx = int(n * (0.04 + 0.86 * k / max(samples - 1, 1)))
        cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
        ok, fr = cap.read()
        if not ok:
            continue
        h, w = fr.shape[:2]
        gray = cv2.cvtColor(fr, cv2.COLOR_BGR2GRAY)
        sharp = min(cv2.Laplacian(gray, cv2.CV_64F).var() / 300.0, 1.5)
        bright = 1.0 - abs(gray.mean() - 125) / 125
        faces = det.detect(fr)
        score = sharp + 0.6 * bright
        box = None
        if faces:
            box = max(faces, key=lambda b: b[2] * b[3])
            area = box[2] * box[3] / (w * h)
            score += 2.0 + (1.0 if 0.02 < area < 0.3 else 0.0) + min(area * 8, 1.0)
            # tengah-tengah lebih baik
            score -= abs((box[0] + box[2] / 2) / w - 0.5) * 0.5
        if score > best_score:
            best, best_score = (fr, box), score
    cap.release()
    det.close()
    if best is None:
        return None, None
    return best


def _crop(img: Image.Image, box, aspect: float) -> Image.Image:
    w, h = img.size
    if w / h > aspect:
        cw, ch = h * aspect, h
    else:
        cw, ch = w, w / aspect
    cx = (box[0] + box[2] / 2) if box else w / 2
    cy = (box[1] + box[3] / 2) if box else h / 2
    x0 = min(max(cx - cw / 2, 0), w - cw)
    y0 = min(max(cy - ch / 2, 0), h - ch)
    return img.crop((int(x0), int(y0), int(x0 + cw), int(y0 + ch)))


def _gradient(size, top_alpha=0, bottom_alpha=190, start=0.45) -> Image.Image:
    w, h = size
    arr = np.zeros((h, w, 4), dtype=np.uint8)
    ys = np.linspace(0, 1, h)
    a = np.clip((ys - start) / (1 - start), 0, 1) * bottom_alpha
    arr[..., 3] = a[:, None]
    return Image.fromarray(arr, "RGBA")


def _fit_lines(draw, text: str, font_path: str, max_w: int, start: int, stroke: int, max_h: float):
    words = text.split()
    size = start
    while size > 24:
        f = ImageFont.truetype(font_path, size)
        lines, cur = [], []
        for wd in words:
            trial = " ".join(cur + [wd])
            if draw.textlength(trial, font=f) + stroke * 2 > max_w and cur:
                lines.append(" ".join(cur))
                cur = [wd]
            else:
                cur.append(wd)
        if cur:
            lines.append(" ".join(cur))
        if len(lines) <= 3 and len(lines) * size * 1.08 <= max_h and \
                all(draw.textlength(l, font=f) + stroke * 2 <= max_w for l in lines):
            return f, lines
        size -= 4
    return ImageFont.truetype(font_path, 24), [text]


def compose(frame_bgr, box, text: str, st: Style, size: Tuple[int, int]) -> Image.Image:
    W, H = size
    img = Image.fromarray(cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB))
    img = _crop(img, box, W / H).resize((W, H), Image.LANCZOS)
    img = ImageEnhance.Color(img).enhance(1.25)
    img = ImageEnhance.Contrast(img).enhance(1.12)
    img = ImageEnhance.Sharpness(img).enhance(1.4)
    img = img.convert("RGBA")
    img.alpha_composite(_gradient((W, H)))
    draw = ImageDraw.Draw(img)
    font_path = str(paths.asset("fonts", "Anton-Regular.ttf"))
    outer_w = max(8, W // 70)
    inner_w = max(4, W // 150)
    max_w = int(W * 0.9)
    max_h = H * (0.27 if H > W else 0.42)
    f, lines = _fit_lines(draw, text.upper(), font_path, max_w, int(H * (0.11 if H > W else 0.2)),
                          outer_w + inner_w, max_h)
    lh = f.size * 1.08
    y = H * (0.88 if H > W else 0.92) - lh * len(lines)
    for i, line in enumerate(lines):
        x = W / 2 - draw.textlength(line, font=f) / 2
        yy = y + i * lh
        col = st.sub_active if i == len(lines) - 1 else "#FFFFFF"
        draw.text((x, yy), line, font=f, fill=st.sub_outer, stroke_width=outer_w + inner_w,
                  stroke_fill=st.sub_outer)
        draw.text((x, yy), line, font=f, fill=col, stroke_width=inner_w, stroke_fill=st.sub_inner)
    return img.convert("RGB")


def make_thumbnails(video: str, text: str, st: Style, out_base: Path) -> List[Path]:
    fr, box = best_frame(video)
    if fr is None:
        return []
    outs = []
    for tag, size in (("vertical", (1080, 1920)), ("wide", (1280, 720))):
        p = out_base.with_name(f"{out_base.name}_thumb_{tag}.jpg")
        compose(fr, box, text, st, size).save(p, quality=93)
        outs.append(p)
    return outs

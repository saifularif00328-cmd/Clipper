"""Pelacak wajah pembicara aktif + stabilisasi posisi crop 9:16 (anti-jitter)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, List, Optional, Tuple

import cv2
import numpy as np

from . import paths


class FaceDetector:
    """MediaPipe face_detector.tflite; cadangan: Haar cascade bawaan OpenCV."""

    def __init__(self):
        self._mp = None
        self._haar = None
        try:
            import mediapipe as mp
            from mediapipe.tasks import python as mpp
            from mediapipe.tasks.python import vision

            buf = paths.asset("face_detector.tflite").read_bytes()
            opts = vision.FaceDetectorOptions(
                base_options=mpp.BaseOptions(model_asset_buffer=buf),
                min_detection_confidence=0.5)
            self._det = vision.FaceDetector.create_from_options(opts)
            self._mp = mp
        except Exception:
            self._mp = None
            try:
                haar = cv2.CascadeClassifier(
                    cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
                self._haar = haar if not haar.empty() else None
            except Exception:
                self._haar = None

    def close(self) -> None:
        det = getattr(self, "_det", None)
        if det is not None:
            try:
                det.close()
            except Exception:
                pass
            self._det = None
            self._mp = None

    @property
    def backend(self) -> str:
        return "mediapipe" if self._mp else ("haar" if self._haar else "none")

    def _detect_once(self, bgr: np.ndarray) -> List[Tuple[float, float, float, float]]:
        h, w = bgr.shape[:2]
        scale = 640.0 / max(w, h) if max(w, h) > 640 else 1.0
        small = cv2.resize(bgr, (int(w * scale), int(h * scale))) if scale != 1.0 else bgr
        if self._mp:
            rgb = cv2.cvtColor(small, cv2.COLOR_BGR2RGB)
            img = self._mp.Image(image_format=self._mp.ImageFormat.SRGB, data=np.ascontiguousarray(rgb))
            res = self._det.detect(img)
            boxes = [(d.bounding_box.origin_x, d.bounding_box.origin_y,
                      d.bounding_box.width, d.bounding_box.height) for d in res.detections]
        elif self._haar is not None:
            gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
            boxes = [tuple(b) for b in self._haar.detectMultiScale(gray, 1.15, 5, minSize=(40, 40))]
        else:
            boxes = []
        return [(x / scale, y / scale, bw / scale, bh / scale) for x, y, bw, bh in boxes]

    def detect(self, bgr: np.ndarray) -> List[Tuple[float, float, float, float]]:
        """Deteksi per-tile: model short-range hanya andal untuk wajah yang besar dalam frame,
        sedangkan di video 16:9 wajah biasanya kecil -> pindai potongan persegi lalu gabung (NMS)."""
        h, w = bgr.shape[:2]
        boxes = list(self._detect_once(bgr))
        side = min(w, h)
        tiles = []
        if w != h:
            step = max(side // 2, 1)
            xs = list(range(0, max(w - side, 0) + 1, step))
            ys = list(range(0, max(h - side, 0) + 1, step))
            if xs[-1] != max(w - side, 0):
                xs.append(max(w - side, 0))
            if ys[-1] != max(h - side, 0):
                ys.append(max(h - side, 0))
            tiles += [(x, y, side) for x in xs for y in ys]
        half = side // 2  # wajah lebih kecil lagi (shot lebar)
        tiles += [(x, y, half) for x in range(0, w - half + 1, max(half // 2, 1))
                  for y in range(0, h - half + 1, max(half // 2, 1))] if side >= 480 else []
        for x, y, sd in tiles:
            for bx, by, bw, bh in self._detect_once(np.ascontiguousarray(bgr[y:y + sd, x:x + sd])):
                boxes.append((bx + x, by + y, bw, bh))
        return _nms(boxes, 0.3)


def _nms(boxes, thr):
    boxes = sorted(boxes, key=lambda b: -b[2] * b[3])
    keep = []
    for b in boxes:
        ok = True
        for k in keep:
            ix = max(0.0, min(b[0] + b[2], k[0] + k[2]) - max(b[0], k[0]))
            iy = max(0.0, min(b[1] + b[3], k[1] + k[3]) - max(b[1], k[1]))
            inter = ix * iy
            if inter / (b[2] * b[3] + k[2] * k[3] - inter + 1e-9) > thr or \
                    inter / (min(b[2] * b[3], k[2] * k[3]) + 1e-9) > 0.6:
                ok = False
                break
        if ok:
            keep.append(b)
    return keep


@dataclass
class _Track:
    tid: int
    cx: float
    cy: float
    size: float
    last_t: float
    prev_patch: Optional[np.ndarray] = None


@dataclass
class Observation:
    t: float
    tid: int
    cx: float
    cy: float
    size: float
    motion: float


def _mouth_patch(gray: np.ndarray, box) -> Optional[np.ndarray]:
    x, y, w, h = box
    H, W = gray.shape
    y0, y1 = int(y + 0.55 * h), int(y + 1.05 * h)
    x0, x1 = int(x + 0.15 * w), int(x + 0.85 * w)
    x0, y0 = max(x0, 0), max(y0, 0)
    x1, y1 = min(x1, W), min(y1, H)
    if x1 - x0 < 4 or y1 - y0 < 4:
        return None
    return cv2.resize(gray[y0:y1, x0:x1], (24, 12), interpolation=cv2.INTER_AREA).astype(np.float32)


def collect_observations(video: str, sample_fps: float = 6.0,
                         progress: Optional[Callable[[float], None]] = None):
    cap = cv2.VideoCapture(str(video))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    W = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    H = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    step = max(1, round(fps / sample_fps))
    det = FaceDetector()
    tracks: List[_Track] = []
    obs: List[Observation] = []
    sample_times: List[float] = []
    next_id, i = 0, 0
    while True:
        ok = cap.grab()
        if not ok:
            break
        if i % step == 0:
            ok, frame = cap.retrieve()
            if not ok:
                break
            t = i / fps
            sample_times.append(t)
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            boxes = det.detect(frame)
            used = set()
            for box in sorted(boxes, key=lambda b: -b[2] * b[3]):
                x, y, bw, bh = box
                cx, cy = x + bw / 2, y + bh / 2
                best, bd = None, 0.18 * W + bw
                for tr in tracks:
                    if tr.tid in used or t - tr.last_t > 1.5:
                        continue
                    d = abs(tr.cx - cx) + abs(tr.cy - cy)
                    if d < bd:
                        best, bd = tr, d
                if best is None:
                    best = _Track(next_id, cx, cy, bw, t)
                    tracks.append(best)
                    next_id += 1
                used.add(best.tid)
                patch = _mouth_patch(gray, box)
                motion = 0.0
                if patch is not None and best.prev_patch is not None:
                    motion = float(np.abs(patch - best.prev_patch).mean())
                best.prev_patch = patch
                best.cx, best.cy, best.size, best.last_t = cx, cy, bw, t
                obs.append(Observation(t, best.tid, cx, cy, bw, motion))
            if progress and n:
                progress(min(i / n, 1.0))
        i += 1
    cap.release()
    backend = det.backend
    det.close()
    return obs, sample_times, (W, H, fps, i, backend)


def pick_speaker(obs: List[Observation], sample_times: List[float],
                 window: float = 0.8, switch_ratio: float = 1.6, min_dwell: float = 1.2):
    """Pilih pembicara aktif per sampel (histeresis agar tidak bolak-balik)."""
    by_t = {}
    for o in obs:
        by_t.setdefault(round(o.t, 4), []).append(o)
    tids = sorted({o.tid for o in obs})
    if not tids:
        return [None] * len(sample_times)
    # skor gerak mulut rata-rata dalam jendela
    scores = {tid: np.zeros(len(sample_times)) for tid in tids}
    for k, t in enumerate(sample_times):
        for o in by_t.get(round(t, 4), []):
            scores[o.tid][k] = o.motion
    ts = np.asarray(sample_times)
    smooth = {}
    for tid, arr in scores.items():
        sm = np.zeros_like(arr)
        for k, t in enumerate(ts):
            m = (ts >= t - window) & (ts <= t + window)
            sm[k] = arr[m].mean()
        smooth[tid] = sm
    # hitung total kehadiran -> awal pilih yang paling sering muncul / besar
    presence = {tid: sum(1 for o in obs if o.tid == tid) for tid in tids}
    head = ts <= ts[0] + 1.5
    cur = max(tids, key=lambda x: (round(float(smooth[x][head].mean()), 3), presence[x]))
    last_switch = -1e9
    chosen = []
    for k, t in enumerate(ts):
        here = {o.tid for o in by_t.get(round(float(t), 4), [])}
        if cur not in here and here:  # wajah aktif hilang
            cur = max(here, key=lambda x: smooth[x][k])
            last_switch = t
        elif len(here) > 1 and t - last_switch >= min_dwell:
            other = max((x for x in here if x != cur), key=lambda x: smooth[x][k], default=None)
            if other is not None and smooth[other][k] > smooth[cur][k] * switch_ratio + 0.4:
                cur, last_switch = other, t
        chosen.append(cur if cur in here else None)
    return chosen


def _median(a: np.ndarray, k: int) -> np.ndarray:
    k = max(1, k | 1)
    if k == 1 or len(a) < 3:
        return a
    pad = k // 2
    p = np.pad(a, pad, mode="edge")
    return np.array([np.median(p[i:i + k]) for i in range(len(a))])


def _gauss(a: np.ndarray, sigma: float) -> np.ndarray:
    if sigma < 0.5 or len(a) < 3:
        return a
    r = int(sigma * 3)
    x = np.arange(-r, r + 1)
    g = np.exp(-0.5 * (x / sigma) ** 2)
    g /= g.sum()
    return np.convolve(np.pad(a, r, mode="edge"), g, mode="valid")


def stabilize(target: np.ndarray, fps: float, span: float, deadband: float = 0.06) -> np.ndarray:
    """Deadband + pengikut halus + Gaussian zero-phase -> bebas getaran."""
    if len(target) == 0:
        return target
    db = deadband * span
    p = float(target[0])
    moving = False
    out = np.empty_like(target, dtype=np.float64)
    for i, t in enumerate(target):
        d = t - p
        if abs(d) > db:
            moving = True
        elif abs(d) < db * 0.25:
            moving = False
        if moving:
            alpha = 0.22 if abs(d) > 0.35 * span else 0.09
            p += d * alpha
        out[i] = p
    return _gauss(out, sigma=fps * 0.22)


def camera_path(video: str, crop_w: float, progress=None):
    """Kembalikan (cx[], cy[], info). cx/cy = pusat crop per frame di piksel sumber."""
    obs, times, (W, H, fps, nframes, backend) = collect_observations(video, progress=progress)
    n = max(nframes, 1)
    frame_t = np.arange(n) / fps
    info = {"backend": backend, "faces": len({o.tid for o in obs}), "W": W, "H": H, "fps": fps, "n": n}
    if not obs or not times:
        info["found"] = 0.0
        return np.full(n, W / 2), np.full(n, H / 2), info
    chosen = pick_speaker(obs, times)
    pos = {(round(o.t, 4), o.tid): o for o in obs}
    sx = np.full(len(times), np.nan)
    sy = np.full(len(times), np.nan)
    for k, (t, tid) in enumerate(zip(times, chosen)):
        o = pos.get((round(t, 4), tid)) if tid is not None else None
        if o:
            sx[k], sy[k] = o.cx, o.cy
    info["found"] = float(np.mean(~np.isnan(sx)))
    # isi kekosongan: tahan posisi terakhir, awal diisi mundur
    for arr in (sx, sy):
        valid = np.where(~np.isnan(arr))[0]
        if len(valid) == 0:
            arr[:] = W / 2 if arr is sx else H / 2
            continue
        arr[:valid[0]] = arr[valid[0]]
        for k in range(valid[0] + 1, len(arr)):
            if np.isnan(arr[k]):
                arr[k] = arr[k - 1]
    sample_fps = len(times) / max(times[-1], 1e-3) if len(times) > 1 else 6.0
    sx = _median(sx, int(round(sample_fps * 0.6)))
    sy = _median(sy, int(round(sample_fps * 0.6)))
    tx = np.interp(frame_t, times, sx)
    ty = np.interp(frame_t, times, sy)
    cx = stabilize(tx, fps, crop_w)
    cy = stabilize(ty, fps, H * 0.5, deadband=0.08)
    return cx, cy, info

"""Pemrosesan teks/transkrip: kalimat, filler, pemotongan jeda."""
from __future__ import annotations

import re
from typing import List, Tuple

from .models import Word

FILLERS = {
    # Indonesia
    "eee", "ee", "eeee", "aaa", "aa", "aaaa", "emm", "em", "eem", "mmm", "mm", "hmm", "hm",
    "ehm", "eh",
    # Inggris
    "uh", "um", "uhm", "umm", "er", "erm", "ah", "uhh",
}
SENT_END = re.compile(r"[.!?…]+[\"')\]]*$")
# kata yang membuat kalimat terasa menggantung bila menjadi kata terakhir
DANGLING = {
    "dan", "tapi", "tetapi", "karena", "yang", "dengan", "atau", "jadi", "kalau", "kalo", "jika",
    "untuk", "sama", "terus", "lalu", "kemudian", "sehingga", "supaya", "agar", "seperti", "di",
    "ke", "dari", "pada", "itu", "ini", "and", "but", "because", "so", "that", "which", "with",
    "or", "if", "to", "of", "the", "a", "an", "for", "in", "on", "at", "then",
}


def norm(t: str) -> str:
    return re.sub(r"[^\w']+", "", t.lower(), flags=re.UNICODE)


def is_filler(w: Word) -> bool:
    return norm(w.text) in FILLERS


def fmt_time(t: float) -> str:
    t = max(0.0, t)
    h, rem = divmod(int(t), 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def split_sentences(words: List[Word], pause: float = 0.9) -> List[Tuple[int, int]]:
    """Kembalikan list (idx_awal, idx_akhir_inklusif) per kalimat."""
    out, start = [], 0
    for i, w in enumerate(words):
        last = i == len(words) - 1
        gap = (words[i + 1].start - w.end) if not last else 0
        if last or SENT_END.search(w.text.strip()) or gap >= pause:
            out.append((start, i))
            start = i + 1
    return out


def sentence_is_complete(words: List[Word], idx_end: int) -> bool:
    """Heuristik: apakah kalimat berhenti dengan utuh (bukan menggantung)."""
    w = words[idx_end]
    txt = w.text.strip()
    if SENT_END.search(txt):
        return True
    if txt.endswith(","):
        return False
    if norm(txt) in DANGLING:
        return False
    nxt_gap = (words[idx_end + 1].start - w.end) if idx_end + 1 < len(words) else 9
    return nxt_gap >= 0.7


def words_in(words: List[Word], start: float, end: float) -> List[Word]:
    return [w for w in words if w.end > start and w.start < end]


def compute_keep_segments(
    words: List[Word], start: float, end: float, max_gap: float = 0.45,
    keep_gap: float = 0.14, cut_fillers: bool = True,
) -> List[Tuple[float, float]]:
    """Segmen sumber yang dipertahankan setelah jeda panjang & filler dibuang."""
    ws = words_in(words, start, end)
    if not ws:
        return [(start, end)]
    cuts: List[Tuple[float, float]] = []
    # jeda di awal/akhir
    if ws[0].start - start > keep_gap:
        cuts.append((start, ws[0].start - keep_gap / 2))
    prev = None
    for w in ws:
        if prev is not None:
            gap = w.start - prev.end
            if gap > max_gap:
                cuts.append((prev.end + keep_gap / 2, w.start - keep_gap / 2))
        if cut_fillers and is_filler(w):
            cuts.append((max(start, w.start - 0.02), min(end, w.end + 0.03)))
        prev = w
    if end - ws[-1].end > keep_gap:
        cuts.append((ws[-1].end + keep_gap, end))
    cuts = sorted((max(a, start), min(b, end)) for a, b in cuts if b > a)
    merged: List[List[float]] = []
    for a, b in cuts:
        if merged and a <= merged[-1][1] + 1e-3:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    keep, cur = [], start
    for a, b in merged:
        if a - cur > 0.12:
            keep.append((cur, a))
        cur = max(cur, b)
    if end - cur > 0.12:
        keep.append((cur, end))
    return keep or [(start, end)]


def build_time_map(segments: List[Tuple[float, float]]):
    """Fungsi pemetaan waktu sumber -> waktu keluaran, plus durasi total."""
    offsets, acc = [], 0.0
    for a, b in segments:
        offsets.append(acc)
        acc += b - a

    def tmap(t: float):
        for (a, b), off in zip(segments, offsets):
            if a - 1e-6 <= t <= b + 1e-6:
                return off + (t - a)
        return None

    return tmap, acc


def remap_words(words: List[Word], segments, cut_fillers: bool = True) -> List[Word]:
    tmap, _ = build_time_map(segments)
    out: List[Word] = []
    for w in words:
        if cut_fillers and is_filler(w):
            continue
        mid = (w.start + w.end) / 2
        seg = next(((a, b) for a, b in segments if a - 1e-6 <= mid <= b + 1e-6), None)
        if seg is None:
            continue
        s = tmap(max(w.start, seg[0]))
        e = tmap(min(w.end, seg[1]))
        if s is None or e is None:
            continue
        out.append(Word(w.text, s, max(e, s + 0.05)))
    return out


def clip_text(words: List[Word], start: float, end: float, cut_fillers: bool = True) -> str:
    """Teks klip untuk disunting: satu kalimat per baris, filler dibuang."""
    ws = [w for w in words_in(words, start, end) if not (cut_fillers and is_filler(w))]
    if not ws:
        return ""
    lines = []
    for a, b in split_sentences(ws):
        lines.append(" ".join(w.text for w in ws[a:b + 1]))
    return "\n".join(lines)

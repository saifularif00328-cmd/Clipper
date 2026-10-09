"""Generator subtitle ASS: double stroke ala CapCut + animasi per kata + hook + progress bar."""
from __future__ import annotations

import os
import re
import sys
from functools import lru_cache
from pathlib import Path
from typing import List, Optional, Tuple

from PIL import ImageFont

from . import paths
from .models import Style, Word
from .textproc import norm

WIN_ALIASES = {
    "arial black": "ariblk.ttf", "impact": "impact.ttf", "arial": "arial.ttf",
    "arial bold": "arialbd.ttf", "segoe ui black": "seguibl.ttf", "segoe ui": "segoeui.ttf",
    "segoe ui bold": "segoeuib.ttf", "verdana bold": "verdanab.ttf", "tahoma bold": "tahomabd.ttf",
    "comic sans ms": "comic.ttf", "bahnschrift": "bahnschrift.ttf",
}


def _font_dirs() -> List[Path]:
    dirs = [paths.asset("fonts")]
    if os.name == "nt":
        dirs.append(Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts")
        la = os.environ.get("LOCALAPPDATA")
        if la:
            dirs.append(Path(la) / "Microsoft/Windows/Fonts")
    else:
        dirs += [Path("/usr/share/fonts"), Path.home() / ".fonts", Path("/Library/Fonts")]
    return [d for d in dirs if d.exists()]


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def list_fonts() -> List[str]:
    """Nama font yang bisa dipilih di GUI (bundel + alias Windows yang ada)."""
    names = []
    for f in sorted(paths.asset("fonts").glob("*.ttf")):
        names.append(_resolve(f, f.stem)[1])
    if os.name == "nt":
        wf = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
        for n, fn in WIN_ALIASES.items():
            if (wf / fn).exists():
                names.append(n.title())
    return names or ["Poppins ExtraBold"]


@lru_cache(maxsize=64)
def find_font(name: str) -> Tuple[Optional[str], str]:
    """(path file, nama font untuk ASS)."""
    want = _slug(name)
    fn_alias = WIN_ALIASES.get(name.lower())
    for d in _font_dirs():
        if fn_alias and (d / fn_alias).exists():
            return _resolve(d / fn_alias, name)
        for f in d.rglob("*"):
            if f.suffix.lower() not in (".ttf", ".otf"):
                continue
            stem = _slug(f.stem)
            if want in (stem, stem.replace("regular", "")):
                return _resolve(f, name)
            if d == paths.asset("fonts") and _slug(_resolve(f, f.stem)[1]) == want:
                return _resolve(f, name)
    fallback = paths.asset("fonts", "Poppins-ExtraBold.ttf")
    if fallback.exists():
        return _resolve(fallback, "Poppins ExtraBold")
    return None, name


def _resolve(path: Path, fallback_name: str) -> Tuple[str, str]:
    try:
        fam, sty = ImageFont.truetype(str(path), 40).getname()
        full = fam if sty.lower() in ("regular", "normal") else f"{fam} {sty}"
        if sty.lower() == "bold":
            full = f"{fam} Bold"
        return str(path), full
    except Exception:
        return str(path), fallback_name


class Measurer:
    def __init__(self, font_name: str, size: int):
        path, self.ass_name = find_font(font_name)
        self.size = size
        self._f = None
        if path:
            try:
                # Fontsize ASS = tinggi baris (ascent+descent), bukan em -> konversi ke em
                probe_f = ImageFont.truetype(path, 100)
                asc, desc = probe_f.getmetrics()
                ratio = (asc + desc) / 100.0
                self._f = ImageFont.truetype(path, max(size / ratio, 4))
            except Exception:
                self._f = None
        self.fontsdir = str(Path(path).parent) if path else ""

    def width(self, text: str) -> float:
        if self._f:
            return float(self._f.getlength(text))
        return len(text) * self.size * 0.58

    @property
    def space(self) -> float:
        return self.width(" ") if self._f else self.size * 0.3


def ass_color(hexc: str, alpha: int = 0) -> str:
    h = hexc.lstrip("#")
    if len(h) != 6:
        h = "FFFFFF"
    r, g, b = h[0:2], h[2:4], h[4:6]
    return f"&H{alpha:02X}{b}{g}{r}".upper()


def _tc(sec: float) -> str:
    sec = max(sec, 0.0)
    cs = int(round(sec * 100))
    h, rem = divmod(cs, 360000)
    m, rem = divmod(rem, 6000)
    s, c = divmod(rem, 100)
    return f"{h}:{m:02d}:{s:02d}.{c:02d}"


def _clean(t: str) -> str:
    return re.sub(r"[{}\\]", "", t).replace("\n", " ")


def grid_xy(col: int, row: int, cols: int, rows: int, W: int, H: int) -> Tuple[float, float]:
    return (col + 0.5) / cols * W, (row + 0.5) / rows * H


STOP = {"yang", "dan", "di", "ke", "dari", "ini", "itu", "untuk", "dengan", "pada", "juga", "atau", "karena",
        "tapi", "kalau", "jadi", "aja", "saja", "udah", "sudah", "nggak", "gak", "ada", "akan", "bisa", "the",
        "and", "that", "this", "with", "have", "for", "you", "are", "was", "but", "not"}


def emphasis_index(texts: List[str]) -> int:
    """Kata yang ditekankan di satu baris: kata terpanjang yang bukan kata sambung."""
    best, best_len = -1, 3
    for i, t in enumerate(texts):
        n = norm(t)
        if n and n not in STOP and len(n) > best_len:
            best, best_len = i, len(n)
    return best


def chunk_words(words: List[Word], max_words: int, max_gap: float = 0.55) -> List[List[Word]]:
    lines, cur = [], []
    for i, w in enumerate(words):
        cur.append(w)
        nxt = words[i + 1] if i + 1 < len(words) else None
        end_sent = bool(re.search(r"[.!?…,;:]$", w.text))
        if (len(cur) >= max_words or nxt is None or (nxt.start - w.end) > max_gap
                or (end_sent and len(cur) >= 2)):
            lines.append(cur)
            cur = []
    return lines


def _wrap(texts: List[str], m: Measurer, max_w: float) -> List[List[int]]:
    """Bagi indeks kata ke baris (maks 2 baris) agar muat max_w."""
    widths = [m.width(t) for t in texts]
    total = sum(widths) + m.space * (len(texts) - 1)
    if total <= max_w or len(texts) < 2:
        return [list(range(len(texts)))]
    best, best_diff = 1, 1e18
    for k in range(1, len(texts)):
        a = sum(widths[:k]) + m.space * (k - 1)
        b = sum(widths[k:]) + m.space * (len(texts) - k - 1)
        d = abs(a - b)
        if d < best_diff:
            best, best_diff = k, d
    return [list(range(best)), list(range(best, len(texts)))]


def header(W: int, H: int, st: Style, ass_name: str) -> str:
    inner, outer = st.sub_inner_w, st.sub_inner_w + st.sub_outer_w
    def sty(name, fs, prim, outl, ow, bs=1, align=5, back="&H00000000"):
        return (f"Style: {name},{ass_name},{fs},{prim},&H000000FF,{outl},{back},"
                f"0,0,0,0,100,100,0,0,{bs},{ow},0,{align},10,10,10,1")
    s = [sty("Main", st.sub_size, ass_color(st.sub_fill), ass_color(st.sub_inner), inner),
         sty("Outer", st.sub_size, ass_color(st.sub_outer), ass_color(st.sub_outer), outer),
         sty("Box", st.sub_size, ass_color(st.sub_box), ass_color(st.sub_box), 16, bs=3),
         sty("Glow", st.sub_size, ass_color(st.sub_glow), ass_color(st.sub_glow), outer + 6),
         sty("Bar", 20, ass_color(st.sub_active), ass_color(st.sub_active), 0, align=7)]
    return (f"[Script Info]\nScriptType: v4.00+\nPlayResX: {W}\nPlayResY: {H}\nWrapStyle: 2\n"
            "ScaledBorderAndShadow: yes\nYCbCr Matrix: None\n\n[V4+ Styles]\n"
            "Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,"
            "Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,"
            "Alignment,MarginL,MarginR,MarginV,Encoding\n" + "\n".join(s) +
            "\n\n[Events]\nFormat: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text\n")


def _ev(layer, a, b, style, text) -> str:
    return f"Dialogue: {layer},{_tc(a)},{_tc(b)},{style},,0,0,0,,{text}\n"


def subtitle_events(words: List[Word], st: Style, W: int, H: int, m: Measurer) -> str:
    if not words:
        return ""
    kws = {norm(k) for k in st.keywords.split(",") if k.strip()}
    lines = chunk_words(words, st.sub_max_words)
    cx0, cy0 = grid_xy(st.sub_pos[0], st.sub_pos[1], 3, 5, W, H)
    cy0 += st.sub_dy * H
    EMPH = 1.25
    margin = W * 0.06
    max_w = W * 0.88
    out = []
    anim = st.sub_anim
    fill, act, kwc = ass_color(st.sub_fill), ass_color(st.sub_active), ass_color(st.keyword_color)
    for li, line in enumerate(lines):
        texts = [_clean(w.text.upper() if st.sub_uppercase else w.text) for w in line]
        emph = emphasis_index(texts) if anim == "emphasis" else -1
        rows = _wrap(texts, m, max_w)
        row_h = m.size * 1.18
        y_first = cy0 - (len(rows) - 1) * row_h / 2
        ls = line[0].start
        nxt = lines[li + 1][0].start if li + 1 < len(lines) else 1e9
        le = min(line[-1].end + 0.25, nxt - 0.01) if nxt < 1e9 else line[-1].end + 0.25
        le = max(le, line[-1].end)
        dur_ms = int((le - ls) * 1000)
        for r, idxs in enumerate(rows):
            wsum = sum(m.width(texts[i]) * (EMPH if i == emph else 1) for i in idxs) + m.space * (len(idxs) - 1)
            x = min(max(cx0 - wsum / 2, margin), W - margin - wsum)
            y = y_first + r * row_h
            for i in idxs:
                wd = m.width(texts[i]) * (EMPH if i == emph else 1)
                px = x + wd / 2
                x += wd + m.space
                w = line[i]
                is_kw = norm(w.text) in kws
                base = kwc if is_kw else fill
                ta = int((w.start - ls) * 1000)
                nxtw = line[i + 1].start if i + 1 < len(line) else w.end
                tb = int((max(w.end, min(nxtw, w.end + 0.35)) - ls) * 1000)
                tb = max(tb, ta + 120)
                pos = f"\\an5\\pos({px:.1f},{y:.1f})\\fad(70,40)"
                animate = anim in ("pop", "karaoke", "glow") or (anim == "keyword" and is_kw)
                scale_t = ""
                color_t = ""
                if animate:
                    if anim in ("pop", "keyword"):
                        scale_t = (f"\\t({ta},{ta + 80},\\fscx128\\fscy128)"
                                   f"\\t({ta + 80},{ta + 200},\\fscx110\\fscy110)"
                                   f"\\t({tb},{tb + 1},\\fscx100\\fscy100)")
                    if anim in ("pop", "glow") or (anim == "keyword" and is_kw):
                        a_col = kwc if is_kw else act
                        color_t = f"\\t({ta},{ta + 1},\\1c{a_col})\\t({tb},{tb + 1},\\1c{base})"
                sc0 = int(EMPH * 100) if i == emph else 100
                if i == emph:
                    base = kwc if is_kw else act
                body = f"{pos}\\fscx{sc0}\\fscy{sc0}"
                if animate and anim == "karaoke":
                    pass
                word = texts[i]
                if st.sub_outer_w > 0:
                    out.append(_ev(1, ls, le, "Outer", f"{{{body}{scale_t}}}{word}"))
                out.append(_ev(2, ls, le, "Main", f"{{{body}\\1c{base}{scale_t}{color_t}}}{word}"))
                a_abs, b_abs = ls + ta / 1000, ls + tb / 1000
                if anim == "karaoke":
                    out.append(_ev(0, a_abs, b_abs, "Box", f"{{{pos}\\fscx100\\fscy100}}{word}"))
                elif anim == "glow":
                    out.append(_ev(0, a_abs, b_abs, "Glow",
                                   f"{{{pos}\\blur14\\bord{st.sub_inner_w + st.sub_outer_w + 12}\\fscx100\\fscy100\\3a&H20&}}{word}"))
    return "".join(out)


HOOK_STYLES = {
    "yellow": dict(fill="#111111", box="#FFE600", outer="#111111"),
    "red": dict(fill="#FFFFFF", box="#E50914", outer="#7A0008"),
    "outline": dict(fill="#FFFFFF", box=None, outer="#FFE600"),
}


def hook_events(text: str, st: Style, W: int, H: int, m: Measurer, seconds: float) -> Tuple[str, str]:
    """(style_lines, event_lines) untuk hook/headline stop-scroll."""
    text = _clean(text).strip()
    if not text:
        return "", ""
    hs = HOOK_STYLES.get(st.hook_style, HOOK_STYLES["yellow"])
    size = st.hook_size
    hm = Measurer(st.sub_font, size)
    words = text.upper().split()
    max_w = W * 0.82
    lines, cur = [], []
    for wd in words:
        trial = " ".join(cur + [wd])
        if hm.width(trial) > max_w and cur:
            lines.append(" ".join(cur))
            cur = [wd]
        else:
            cur.append(wd)
    if cur:
        lines.append(" ".join(cur))
    x, y = grid_xy(st.hook_pos[0], st.hook_pos[1], 3, 5, W, H)
    wmax = max(hm.width(l) for l in lines)
    x = min(max(x, wmax / 2 + W * 0.06), W - wmax / 2 - W * 0.06)
    txt = "\\N".join(lines)
    box = hs["box"]
    styles = (
        f"Style: HookBox,{hm.ass_name},{size},{ass_color(box or hs['outer'])},&H000000FF,"
        f"{ass_color(box or hs['outer'])},&H00000000,0,0,0,0,100,100,0,0,3,26,0,5,10,10,10,1\n"
        f"Style: HookText,{hm.ass_name},{size},{ass_color(hs['fill'])},&H000000FF,"
        f"{ass_color(hs['outer'])},&H00000000,0,0,0,0,100,100,0,0,1,{4 if box else 14},0,5,10,10,10,1\n"
        f"Style: HookOuter,{hm.ass_name},{size},{ass_color(hs['outer'])},&H000000FF,"
        f"{ass_color(hs['outer'])},&H00000000,0,0,0,0,100,100,0,0,1,{20 if not box else 6},0,5,10,10,10,1\n")
    anim = "\\fscx70\\fscy70\\t(0,220,\\fscx108\\fscy108)\\t(220,340,\\fscx100\\fscy100)"
    pos = f"\\an5\\pos({x:.1f},{y:.1f})\\fad(120,250)"
    ev = ""
    if box:
        ev += _ev(5, 0, seconds, "HookBox", f"{{{pos}{anim}}}{txt}")
    else:
        ev += _ev(5, 0, seconds, "HookOuter", f"{{{pos}{anim}}}{txt}")
    ev += _ev(6, 0, seconds, "HookText", f"{{{pos}{anim}}}{txt}")
    return styles, ev


def overlay_events(st: Style, W: int, H: int, duration: float) -> Tuple[str, str]:
    """Badge 'WATCH FULL VIDEO + channel' dan watermark teks transparan. Return (styles, events)."""
    ev, styles = "", ""
    fnt = Measurer(st.sub_font, 30)
    styles += (f"Style: Plain,{fnt.ass_name},30,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,"
               "0,0,0,0,100,100,0,0,1,2,1,7,0,0,0,1\n")
    end = duration + 0.1
    if st.badge_enabled and (st.badge_text or st.badge_sub):
        t1, t2 = _clean(st.badge_text.upper()), _clean(st.badge_sub)
        m1, m2 = Measurer(st.sub_font, 26), Measurer(st.sub_font, 23)
        icon_w, icon_h, gap = 50, 36, 12
        tw = max(m1.width(t1), m2.width(t2) if t2 else 0)
        total = icon_w + gap + tw
        cx, cy = grid_xy(st.badge_pos[0], st.badge_pos[1], 3, 5, W, H)
        x0 = {0: W * 0.04, 1: cx - total / 2, 2: W * 0.96 - total}[st.badge_pos[0]]
        y0 = cy - icon_h / 2
        ev += _ev(3, 0, end, "Plain", f"{{\\an7\\pos({x0:.1f},{y0:.1f})\\1c&H1A1AE6&\\bord0\\shad0\\p1}}"
                  f"m 8 0 l {icon_w - 8} 0 {icon_w} 8 {icon_w} {icon_h - 8} {icon_w - 8} {icon_h} 8 {icon_h} 0 {icon_h - 8} 0 8")
        tx, ty = x0 + (icon_w - 16) / 2 + 4, y0 + icon_h / 2
        ev += _ev(4, 0, end, "Plain", f"{{\\an7\\pos({tx - 4:.1f},{ty - 9:.1f})\\1c&HFFFFFF&\\bord0\\shad0\\p1}}"
                  "m 0 0 l 18 9 0 18")
        txt = f"{{\\fs26\\b1}}{t1}"
        if t2:
            txt += f"\\N{{\\fs23\\b0\\1c&HD8D8D8&}}{t2}"
        ev += _ev(4, 0, end, "Plain", f"{{\\an4\\pos({x0 + icon_w + gap:.1f},{y0 + icon_h / 2 + (11 if t2 else 0):.1f})}}{txt}")
    if st.wm_enabled and st.wm_text.strip():
        x, y = grid_xy(st.wm_pos[0], st.wm_pos[1], 3, 5, W, H)
        a = int(round((1 - max(0.0, min(1.0, st.wm_opacity))) * 255))
        ev += _ev(2, 0, end, "Plain", f"{{\\an5\\pos({x:.1f},{y:.1f})\\fs{st.wm_size}\\b1\\bord0\\shad0"
                  f"\\1a&H{a:02X}&}}{_clean(st.wm_text)}")
    return styles, ev


def progress_bar(duration: float, W: int, H: int) -> str:
    ms = int(duration * 1000)
    return _ev(9, 0, duration + 0.1, "Bar",
               f"{{\\an7\\pos(0,{H - 14})\\fscx1\\fscy100\\t(0,{ms},\\fscx{W})\\p1}}m 0 0 l 1 0 1 14 0 14")


def build_ass(words: List[Word], st: Style, W: int, H: int, duration: float,
              hook_text: str = "", hook_seconds: float = 3.0) -> Tuple[str, str]:
    """Kembalikan (isi file .ass, fontsdir)."""
    m = Measurer(st.sub_font, st.sub_size)
    head = header(W, H, st, m.ass_name)
    hs, he = ("", "")
    if st.hook_enabled and hook_text:
        hs, he = hook_events(hook_text, st, W, H, m, hook_seconds)
    os_, oe = overlay_events(st, W, H, duration)
    hs += os_
    he += oe
    # sisipkan style hook/overlay sebelum [Events]
    head = head.replace("\n[Events]", hs + "\n[Events]", 1) if hs else head
    body = subtitle_events(words, st, W, H, m) if st.sub_enabled else ""
    bar = progress_bar(duration, W, H) if st.fx_progress else ""
    return head + he + body + bar, m.fontsdir

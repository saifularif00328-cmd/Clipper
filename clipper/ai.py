"""Gemini: pemilihan klip natural, perapian transkrip (SRT optimizer), terjemahan."""
from __future__ import annotations

import difflib
import json
import re
import time
from typing import Callable, Dict, List, Optional

from .models import Clip, Word
from .textproc import fmt_time, norm, sentence_is_complete, split_sentences

LANG_NAMES = {
    "id": "Indonesian", "en": "English", "es": "Spanish", "pt": "Portuguese", "fr": "French",
    "de": "German", "ja": "Japanese", "ko": "Korean", "zh": "Chinese", "ar": "Arabic",
    "hi": "Hindi", "ru": "Russian", "tr": "Turkish", "th": "Thai", "vi": "Vietnamese",
    "ms": "Malay", "it": "Italian", "nl": "Dutch",
}


def lang_name(code: str) -> str:
    return LANG_NAMES.get(code, code)


class Gemini:
    def __init__(self, api_key: str, model: str = "gemini-2.5-flash"):
        if not api_key:
            raise ValueError("API key Gemini belum diisi.")
        from google import genai
        self._types = __import__("google.genai.types", fromlist=["types"])
        self.client = genai.Client(api_key=api_key)
        self.model = model

    def json_call(self, prompt: str, retries: int = 3):
        last = None
        for i in range(retries):
            try:
                r = self.client.models.generate_content(
                    model=self.model, contents=prompt,
                    config=self._types.GenerateContentConfig(
                        response_mime_type="application/json", temperature=0.4))
                return parse_json(r.text)
            except Exception as e:  # jaringan / kuota / JSON rusak
                last = e
                time.sleep(2 * (i + 1))
        raise RuntimeError(f"Gemini gagal: {last}")


def parse_json(text: str):
    text = (text or "").strip()
    text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.M).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"(\{.*\}|\[.*\])", text, re.S)
        if not m:
            raise
        return json.loads(m.group(1))


# ---------------------------------------------------------------- pemilihan klip
def transcript_for_prompt(words: List[Word], sents) -> str:
    lines = []
    for n, (a, b) in enumerate(sents):
        txt = " ".join(w.text for w in words[a:b + 1])
        lines.append(f"[S{n} {fmt_time(words[a].start)}-{fmt_time(words[b].end)}] {txt}")
    return "\n".join(lines)


def select_clips_ai(g: Gemini, words: List[Word], count: int, min_s: int, max_s: int,
                    lang: str, log: Callable[[str], None] = print, user_prompt: str = "") -> List[Clip]:
    sents = split_sentences(words)
    extra = (f"\nINSTRUKSI KHUSUS DARI PENGGUNA (utamakan, selama aturan wajib tetap dipenuhi): "
             f"{user_prompt.strip()}\n") if user_prompt.strip() else ""
    prompt = f"""Kamu editor video pendek viral (TikTok/Reels/Shorts) yang sangat teliti.
Dari transkrip di bawah (bahasa: {lang_name(lang)}), pilih {count} momen TERBAIK untuk dijadikan klip.

ATURAN WAJIB (urutan prioritas):
1. NATURAL & TUNTAS: klip harus mulai di awal sebuah gagasan/cerita/pertanyaan dan BERAKHIR SETELAH
   gagasan itu selesai (kesimpulan, punchline, jawaban, atau klimaks emosional). DILARANG berhenti di
   tengah penjelasan, tengah cerita, atau kalimat yang menggantung (diakhiri 'dan', 'tapi', 'karena', dll).
   Jika sebuah topik butuh waktu lebih lama, perpanjang durasinya sampai tuntas (boleh melebihi maks sampai +25%).
2. Durasi ideal {min_s}-{max_s} detik.
3. Kalimat pertama harus langsung menarik perhatian (hook alami: pertanyaan, klaim berani, konflik, cerita).
4. Klip tidak boleh saling tumpang tindih. Pilih yang paling emosional, lucu, mengejutkan, atau bernilai/insightful.
5. Tentukan batas klip dengan NOMOR KALIMAT (S-index) dari transkrip, inklusif.

Untuk setiap klip berikan:
- start_sentence, end_sentence (integer)
- title: judul klip menarik (maks 70 karakter)
- hook: teks headline 'stop scroll' di awal video (maks 9 kata, memancing rasa penasaran, tanpa clickbait palsu)
- thumb_text: 2-4 kata untuk thumbnail, KAPITAL, impactful
- caption: caption sosial media 1-2 kalimat
- hashtags: 4-6 hashtag (tanpa spasi)
- score: 0-100 potensi viral keseluruhan
- hook_score, flow_score, value_score, trend_score: masing-masing 0-100 (kekuatan hook pembuka, alur/ketuntasan cerita,
  nilai/insight bagi penonton, kesesuaian tren & emosi)
- reason: 1 kalimat alasan
- complete: true bila klip berakhir tuntas (kamu yakin pembahasan selesai)

{extra}
Jawab HANYA JSON: {{"clips":[{{...}}]}}, bahasa teks = {lang_name(lang)}.

TRANSKRIP:
{transcript_for_prompt(words, sents)}"""
    data = g.json_call(prompt)
    raw = data["clips"] if isinstance(data, dict) else data
    clips: List[Clip] = []
    for i, c in enumerate(raw):
        try:
            a = max(0, min(int(c["start_sentence"]), len(sents) - 1))
            b = max(a, min(int(c["end_sentence"]), len(sents) - 1))
        except (KeyError, ValueError, TypeError):
            continue
        clips.append(Clip(
            id=i + 1, start=words[sents[a][0]].start, end=words[sents[b][1]].end,
            title=str(c.get("title", "")), hook=str(c.get("hook", "")),
            thumb_text=str(c.get("thumb_text", "")), caption=str(c.get("caption", "")),
            hashtags=[str(h) for h in c.get("hashtags", [])], score=float(c.get("score", 0) or 0),
            score_hook=float(c.get("hook_score", 0) or 0), score_flow=float(c.get("flow_score", 0) or 0),
            score_value=float(c.get("value_score", 0) or 0), score_trend=float(c.get("trend_score", 0) or 0),
            reason=str(c.get("reason", ""))))
    return clips


# ---------------------------------------------------------------- perapian & terjemahan
def realign(orig: List[Word], new_text: str) -> List[Word]:
    """Petakan teks baru ke timing kata asli (difflib), tanpa menggeser sinkronisasi."""
    new = new_text.split()
    if not orig:
        return []
    if not new:
        return []
    if len(new) == len(orig):
        return [Word(t, o.start, o.end) for t, o in zip(new, orig)]
    a = [norm(w.text) for w in orig]
    b = [norm(t) for t in new]
    sm = difflib.SequenceMatcher(a=a, b=b, autojunk=False)
    out: List[Word] = []
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == "equal":
            for k in range(i2 - i1):
                out.append(Word(new[j1 + k], orig[i1 + k].start, orig[i1 + k].end))
        elif op in ("replace", "insert"):
            if i2 > i1:
                t0, t1 = orig[i1].start, orig[i2 - 1].end
            else:  # insert: pinjam sedikit waktu dari kata sebelumnya
                ref = orig[max(i1 - 1, 0)]
                t0, t1 = ref.end, ref.end + 0.05 * (j2 - j1)
            n = j2 - j1
            step = (t1 - t0) / n
            for k in range(n):
                out.append(Word(new[j1 + k], t0 + k * step, t0 + (k + 1) * step))
    # pastikan monoton
    for k in range(1, len(out)):
        if out[k].start < out[k - 1].start:
            out[k].start = out[k - 1].start
        if out[k].end < out[k].start + 0.04:
            out[k].end = out[k].start + 0.04
    return out


def polish_and_translate(g: Gemini, clip: Clip, words: List[Word], src_lang: str,
                         target_lang: str, polish: bool) -> tuple[List[Word], Clip]:
    """Satu panggilan per klip: rapikan kalimat (buang filler/typo) + terjemahkan teks."""
    sents = split_sentences(words, pause=0.6)
    items = [{"id": n, "text": " ".join(w.text for w in words[a:b + 1])} for n, (a, b) in enumerate(sents)]
    do_tr = bool(target_lang) and target_lang != src_lang
    tasks = []
    if polish:
        tasks.append(f"Rapikan setiap kalimat ({lang_name(src_lang)}): buang kata gumaman/filler "
                     "('eee','aaa','emm','uh','um'), perbaiki salah ketik & tata bahasa ringan, "
                     "JANGAN mengubah makna, jangan meringkas, pertahankan gaya bicara.")
    if do_tr:
        tasks.append(f"Setelah itu TERJEMAHKAN hasilnya ke {lang_name(target_lang)} secara natural "
                     "(bukan kata per kata). Terjemahkan juga title, hook, thumb_text, caption, hashtags.")
    if not tasks:
        return words, clip
    prompt = (
        "Tugas:\n- " + "\n- ".join(tasks) +
        "\nPertahankan jumlah & urutan kalimat persis (id sama).\n"
        'Jawab HANYA JSON: {"sentences":[{"id":0,"text":"..."}],"title":"","hook":"",'
        '"thumb_text":"","caption":"","hashtags":[]}\n\nDATA:\n' +
        json.dumps({"sentences": items, "title": clip.title, "hook": clip.hook,
                    "thumb_text": clip.thumb_text, "caption": clip.caption,
                    "hashtags": clip.hashtags}, ensure_ascii=False))
    data = g.json_call(prompt)
    by_id: Dict[int, str] = {int(s["id"]): str(s["text"]) for s in data.get("sentences", []) if "id" in s}
    out: List[Word] = []
    for n, (a, b) in enumerate(sents):
        seg = words[a:b + 1]
        txt = by_id.get(n)
        out.extend(realign(seg, txt) if txt else seg)
    new_clip = Clip.from_dict(clip.to_dict())
    if do_tr:
        for k in ("title", "hook", "thumb_text", "caption"):
            if data.get(k):
                setattr(new_clip, k, str(data[k]))
        if data.get("hashtags"):
            new_clip.hashtags = [str(h) for h in data["hashtags"]]
    return out, new_clip


# ---------------------------------------------------------------- tanpa AI
def select_clips_local(words: List[Word], count: int, min_s: int, max_s: int) -> List[Clip]:
    """Cadangan tanpa API: jendela kalimat dengan kepadatan bicara & tanda seru/tanya tertinggi."""
    sents = split_sentences(words)
    if not sents:
        return []
    cands = []
    for i in range(len(sents)):
        j = i
        while j < len(sents):
            dur = words[sents[j][1]].end - words[sents[i][0]].start
            if dur >= min_s:
                break
            j += 1
        if j >= len(sents):
            break
        # perpanjang sampai kalimat berakhir tuntas
        from .textproc import sentence_is_complete
        while j < len(sents) - 1 and (not sentence_is_complete(words, sents[j][1])) \
                and words[sents[j + 1][1]].end - words[sents[i][0]].start <= max_s * 1.25:
            j += 1
        a, b = words[sents[i][0]].start, words[sents[j][1]].end
        seg = words[sents[i][0]:sents[j][1] + 1]
        dens = len(seg) / max(b - a, 1)
        punct = sum(w.text.endswith(("!", "?")) for w in seg)
        cands.append((dens + 0.4 * punct, i, j, a, b))
    cands.sort(reverse=True)
    chosen, clips = [], []
    for sc, i, j, a, b in cands:
        if any(not (b <= ca or a >= cb) for ca, cb in chosen):
            continue
        chosen.append((a, b))
        first = " ".join(w.text for w in words[sents[i][0]:sents[i][0] + 8])
        clips.append(Clip(id=len(clips) + 1, start=a, end=b, title=first, hook=first,
                          thumb_text=" ".join(first.split()[:3]).upper(), score=round(sc * 10, 1),
                          reason="Pemilihan lokal (tanpa AI)"))
        if len(clips) >= count:
            break
    clips.sort(key=lambda c: c.start)
    for n, c in enumerate(clips, 1):
        c.id = n
    return clips


def enforce_complete(clips: List[Clip], words: List[Word], max_s: int) -> List[Clip]:
    """Jaring pengaman: ujung klip digeser ke batas kalimat & diperpanjang jika menggantung."""
    from .textproc import sentence_is_complete
    sents = split_sentences(words)
    ends = [(words[b].end, b) for _, b in sents]
    starts = [words[a].start for a, _ in sents]
    for c in clips:
        # awal mundur ke awal kalimat, akhir MAJU ke ujung kalimat (pembahasan tidak terpotong)
        c.start = max((t for t in starts if t <= c.start + 0.05), default=starts[0])
        idx = next((k for k in range(len(ends)) if ends[k][0] >= c.end - 0.05), len(ends) - 1)
        limit = max_s * 1.25 + 20
        while idx < len(ends) - 1 and not sentence_is_complete(words, ends[idx][1]) \
                and ends[idx + 1][0] - c.start <= limit:
            idx += 1
        c.end = ends[idx][0]
    return clips

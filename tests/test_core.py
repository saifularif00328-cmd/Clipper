import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from clipper import ai, face_track, subtitles
from clipper.models import Clip, Style, Word
from clipper.textproc import (build_time_map, compute_keep_segments, is_filler, remap_words,
                              sentence_is_complete, split_sentences)


def mk(text, t0=0.0, dur=0.3, gap=0.05):
    out, t = [], t0
    for w in text.split():
        out.append(Word(w, t, t + dur))
        t += dur + gap
    return out


def test_filler_detection():
    assert is_filler(Word("eee", 0, 1)) and is_filler(Word("Um,", 0, 1))
    assert not is_filler(Word("anu", 0, 1))


def test_long_pause_is_cut():
    a = mk("halo semua", 0.0)
    b = mk("lanjut kita", 5.0)
    segs = compute_keep_segments(a + b, 0.0, b[-1].end, max_gap=0.45)
    assert len(segs) == 2
    tmap, total = build_time_map(segs)
    assert total < 2.5  # jeda 4 detik hilang
    rw = remap_words(a + b, segs)
    assert [w.text for w in rw] == ["halo", "semua", "lanjut", "kita"]
    assert all(rw[i].start <= rw[i + 1].start for i in range(3))


def test_filler_removed_from_timeline():
    ws = mk("halo eee dunia", 0.0)
    segs = compute_keep_segments(ws, 0.0, ws[-1].end, max_gap=5)
    rw = remap_words(ws, segs)
    assert [w.text for w in rw] == ["halo", "dunia"]
    assert len(segs) == 2


def test_sentences_and_completion():
    ws = mk("ini kalimat satu. ini kalimat dua karena", 0.0)
    s = split_sentences(ws)
    assert len(s) == 2
    assert sentence_is_complete(ws, s[0][1])
    assert not sentence_is_complete(ws, s[1][1])  # berakhir 'karena' -> menggantung


def test_enforce_complete_extends_dangling_end():
    ws = mk("kita mulai dari sini. lalu hasilnya sangat bagus sekali.", 0.0)
    c = Clip(1, ws[0].start, ws[3].end)
    c.end = ws[5].end  # berhenti di tengah kalimat 2
    out = ai.enforce_complete([c], ws, 60)
    assert abs(out[0].end - ws[-1].end) < 1e-6


def test_realign_keeps_timing():
    orig = mk("ini adalah eee tes yang bagus", 0.0)
    new = ai.realign(orig, "ini adalah tes yang bagus")
    assert [w.text for w in new][:3] == ["ini", "adalah", "tes"]
    assert new[2].start == orig[3].start
    tr = ai.realign(orig, "this is a good test")
    assert len(tr) == 5 and tr[0].start == orig[0].start
    assert all(tr[i].start <= tr[i + 1].start for i in range(4))


def test_stabilize_removes_jitter():
    rng = np.random.default_rng(0)
    target = 500 + rng.normal(0, 8, 300)  # wajah diam, deteksi bergetar
    out = face_track.stabilize(target, 30, 600)
    assert out.std() < 1.0
    step = np.r_[np.full(100, 300.0), np.full(200, 800.0)]  # ganti pembicara
    out = face_track.stabilize(step, 30, 600)
    assert abs(out[-1] - 800) < 12 and np.abs(np.diff(out)).max() < 40  # geser mulus


def test_speaker_selection_hysteresis():
    times = [i / 6 for i in range(60)]
    obs = []
    for t in times:
        m1 = 6.0 if t < 5 else 0.5
        m2 = 0.5 if t < 5 else 6.0
        obs.append(face_track.Observation(t, 0, 200, 300, 100, m1))
        obs.append(face_track.Observation(t, 1, 900, 300, 100, m2))
    chosen = face_track.pick_speaker(obs, times)
    assert chosen[3] == 0 and chosen[-1] == 1
    assert sum(1 for a, b in zip(chosen, chosen[1:]) if a != b) == 1


def test_ass_generation_all_modes():
    ws = mk("rahasia sukses konten kreator yang jarang diketahui orang", 0.0)
    for mode in ("pop", "karaoke", "glow", "keyword", "plain"):
        st = Style(sub_anim=mode, keywords="rahasia")
        text, _ = subtitles.build_ass(ws, st, 1080, 1920, 6.0, "Hook keren", 3.0)
        assert "[Events]" in text and "Dialogue:" in text and "HookText" in text
    assert subtitles.ass_color("#FF8000") == "&H0080FF&".replace("&H0080FF&", "&H000080FF")


def test_grid_positions():
    x, y = subtitles.grid_xy(1, 2, 3, 5, 1080, 1920)
    assert (x, y) == (540, 960)


class FakeGemini:
    """Pengganti Gemini untuk tes offline."""

    def __init__(self, payload):
        self.payload = payload
        self.prompts = []

    def json_call(self, prompt, retries=3):
        self.prompts.append(prompt)
        return self.payload


def test_select_clips_ai_uses_sentence_boundaries():
    ws = mk("kalimat satu selesai. kalimat dua juga selesai. kalimat tiga penutup akhir.", 0.0)
    g = FakeGemini({"clips": [{"start_sentence": 1, "end_sentence": 2, "title": "T", "hook": "H",
                               "thumb_text": "X", "caption": "C", "hashtags": ["a"], "score": 90}]})
    clips = ai.select_clips_ai(g, ws, 1, 5, 20, "id")
    assert len(clips) == 1
    assert clips[0].start == ws[3].start and clips[0].end == ws[-1].end
    assert "S0" in g.prompts[0] and "TUNTAS" in g.prompts[0]


def test_polish_and_translate_keeps_sync_and_translates_meta():
    ws = mk("halo eee dunia ini tes", 1.0)
    clip = Clip(1, 1.0, ws[-1].end, title="Judul", hook="Hook")
    g = FakeGemini({"sentences": [{"id": 0, "text": "Hello world this is a test"}],
                    "title": "Title", "hook": "Hook EN", "thumb_text": "", "caption": "", "hashtags": []})
    new_words, new_clip = ai.polish_and_translate(g, clip, ws, "id", "en", True)
    assert [w.text for w in new_words] == "Hello world this is a test".split()
    assert new_words[0].start == ws[0].start and new_words[-1].end <= ws[-1].end + 0.05
    assert new_clip.title == "Title" and new_clip.hook == "Hook EN"
    assert clip.title == "Judul"  # asli tidak berubah


def test_local_selector_ends_on_complete_sentence():
    text = ("ini kalimat pertama yang cukup panjang untuk tes. ini kalimat kedua yang juga panjang sekali. "
            "ini kalimat ketiga lagi. dan yang keempat menutup.")
    ws = mk(text, 0.0, dur=0.5, gap=0.1)
    clips = ai.select_clips_local(ws, 1, 3, 6)
    assert clips
    last = max(i for i, w in enumerate(ws) if w.end <= clips[0].end + 1e-6)
    assert sentence_is_complete(ws, last)


def test_analyze_writes_and_reuses_cache(tmp_path, monkeypatch):
    import clipper.transcribe as tr
    from clipper.pipeline import Pipeline, safe_name
    from clipper.settings import Settings

    ws = mk("ini kalimat pertama yang cukup panjang untuk tes. ini kalimat kedua yang juga panjang sekali. "
            "ini kalimat ketiga lagi.", 0.0, dur=0.5, gap=0.1)
    calls = []
    import json

    def fake_transcribe(video, work, *a, **k):
        calls.append(1)
        (work / "transcript.json").write_text(json.dumps(
            {"language": "id", "words": [w.to_dict() for w in ws]}), encoding="utf-8")
        return ws, "id"

    monkeypatch.setattr(tr, "transcribe", fake_transcribe)
    vid = tmp_path / "judul 日本語.mp4"
    vid.write_bytes(b"x")
    cfg = Settings(output_dir=str(tmp_path / "out"), min_sec=3, max_sec=8, clip_count=1)
    cfg.api_key = ""
    p1 = Pipeline(cfg).analyze(str(vid))
    assert p1.list_file.exists() and p1.clips and p1.dir.name.isascii()
    p2 = Pipeline(cfg).analyze(str(vid))          # kedua kali: dari cache list_clip.json
    assert [c.to_dict() for c in p2.clips] == [c.to_dict() for c in p1.clips]
    p3 = Pipeline.load_cache(p1.list_file)
    assert len(p3.words) == len(ws) and p3.clips[0].id == p1.clips[0].id and p3.lang == "id"
    assert safe_name('a/b:c*?"d') == "abcd"


def test_ytdlp_override_is_used(tmp_path, monkeypatch):
    import sys
    from clipper import media, paths
    monkeypatch.setattr(paths, "data_dir", lambda: tmp_path)
    pkg = tmp_path / "ytdlp_update" / "yt_dlp"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text("")
    (pkg / "version.py").write_text("__version__ = '2099.01.01'\n")
    monkeypatch.setattr(sys, "path", list(sys.path))
    assert media.ytdlp_version() == "2099.01.01"

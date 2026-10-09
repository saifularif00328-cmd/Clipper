"""Antarmuka desktop (customtkinter)."""
from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import colorchooser, filedialog, messagebox

import customtkinter as ctk

from . import __version__, settings as settings_mod
from .models import Clip, Style
from .pipeline import Cancelled, Pipeline, Project
from .subtitles import list_fonts
from .textproc import fmt_time

ANIMS = {"Pop Zoom (per kata)": "pop", "Karaoke Highlight Box": "karaoke", "Glow": "glow",
         "Highlight Kata Kunci": "keyword", "Polos": "plain"}
LAYOUTS = {"Face Tracking (ikuti pembicara)": "face", "Crop tengah": "center",
           "Fit + latar blur": "blur"}
HOOKS = {"Kotak kuning": "yellow", "Kotak merah": "red", "Outline tebal": "outline"}
RES = {"1080 x 1920 (Full HD)": (1080, 1920), "720 x 1280 (cepat)": (720, 1280)}
LANGS = {"Tanpa terjemahan": "", "Indonesia": "id", "English": "en", "Español": "es", "Português": "pt",
         "Français": "fr", "Deutsch": "de", "日本語": "ja", "한국어": "ko", "中文": "zh", "العربية": "ar",
         "हिन्दी": "hi", "Русский": "ru", "Türkçe": "tr", "ไทย": "th", "Tiếng Việt": "vi",
         "Melayu": "ms", "Italiano": "it", "Nederlands": "nl"}
SRC_LANGS = ["auto", "id", "en", "es", "pt", "fr", "de", "ja", "ko", "zh", "ar", "hi", "ru", "tr", "th", "vi", "ms"]
COLOR_FIELDS = [("Isi teks", "sub_fill"), ("Kata aktif", "sub_active"), ("Stroke dalam", "sub_inner"),
                ("Stroke luar", "sub_outer"), ("Kotak karaoke", "sub_box"), ("Glow", "sub_glow"),
                ("Kata kunci", "keyword_color")]


def inv(d, v, default=None):
    return next((k for k, x in d.items() if x == v), default or next(iter(d)))


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")
        self.title(f"Clipper {__version__} - AI Video Clipper")
        self.geometry("1240x860")
        self.minsize(1100, 760)
        self.cfg = settings_mod.load()
        self.st: Style = self.cfg.style
        self.proj: Project | None = None
        self.q: queue.Queue = queue.Queue()
        self.worker: threading.Thread | None = None
        self.pipe: Pipeline | None = None
        self.clip_rows: list = []
        self.grid_target = tk.StringVar(value="sub")
        self.color_btns = {}
        self.preview_bg = None
        self._build()
        self.after(100, self._poll)
        self.protocol("WM_DELETE_WINDOW", self._close)

    # ------------------------------------------------------------ util UI
    def _row(self, parent, label, widget_factory, r, c=0, span=1):
        ctk.CTkLabel(parent, text=label, anchor="w").grid(row=r, column=c, sticky="w", padx=(12, 6), pady=4)
        w = widget_factory(parent)
        w.grid(row=r, column=c + 1, columnspan=span, sticky="ew", padx=(0, 12), pady=4)
        return w

    def _build(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self.tabs = ctk.CTkTabview(self)
        self.tabs.grid(row=0, column=0, sticky="nsew", padx=10, pady=(10, 4))
        for t in ("1. Sumber & Analisis", "2. Klip", "3. Tampilan & Efek", "4. Render"):
            self.tabs.add(t)
        self._tab_source(self.tabs.tab("1. Sumber & Analisis"))
        self._tab_clips(self.tabs.tab("2. Klip"))
        self._tab_style(self.tabs.tab("3. Tampilan & Efek"))
        self._tab_render(self.tabs.tab("4. Render"))
        bottom = ctk.CTkFrame(self)
        bottom.grid(row=1, column=0, sticky="ew", padx=10, pady=(0, 10))
        bottom.grid_columnconfigure(0, weight=1)
        self.status = ctk.CTkLabel(bottom, text="Siap.", anchor="w")
        self.status.grid(row=0, column=0, sticky="ew", padx=10, pady=(6, 0))
        self.bar = ctk.CTkProgressBar(bottom)
        self.bar.set(0)
        self.bar.grid(row=1, column=0, sticky="ew", padx=10, pady=4)
        self.log = ctk.CTkTextbox(bottom, height=130)
        self.log.grid(row=2, column=0, sticky="ew", padx=10, pady=(0, 8))
        self.log.configure(state="disabled")

    # ------------------------------------------------------------ tab 1
    def _tab_source(self, tab):
        tab.grid_columnconfigure(1, weight=1)
        self.v_src = tk.StringVar(value=self.cfg.last_source)
        f = ctk.CTkFrame(tab, fg_color="transparent")
        f.grid(row=0, column=0, columnspan=3, sticky="ew")
        f.grid_columnconfigure(1, weight=1)
        self._row(f, "Link YouTube / file video", lambda p: ctk.CTkEntry(p, textvariable=self.v_src), 0)
        ctk.CTkButton(f, text="Pilih file...", width=110, command=self._pick_video).grid(row=0, column=2, padx=10)
        self.v_key = tk.StringVar(value=self.cfg.api_key)
        self._row(f, "API Key Gemini", lambda p: ctk.CTkEntry(p, textvariable=self.v_key, show="•"), 1)
        ctk.CTkLabel(f, text="gratis di aistudio.google.com/apikey", text_color="gray").grid(row=1, column=2)
        self.v_gmodel = tk.StringVar(value=self.cfg.gemini_model)
        self._row(f, "Model Gemini", lambda p: ctk.CTkComboBox(
            p, variable=self.v_gmodel, values=["gemini-2.5-flash", "gemini-2.5-pro", "gemini-2.0-flash"]), 2)
        self.v_wh = tk.StringVar(value=self.cfg.whisper_model)
        self._row(f, "Model transkripsi (lokal)", lambda p: ctk.CTkComboBox(
            p, variable=self.v_wh, values=["tiny", "base", "small", "medium", "large-v3"]), 3)
        self.v_lang = tk.StringVar(value=self.cfg.language)
        self._row(f, "Bahasa ucapan", lambda p: ctk.CTkComboBox(p, variable=self.v_lang, values=SRC_LANGS), 4)
        self.v_n = tk.StringVar(value=str(self.cfg.clip_count))
        self.v_min = tk.StringVar(value=str(self.cfg.min_sec))
        self.v_max = tk.StringVar(value=str(self.cfg.max_sec))
        self._row(f, "Jumlah klip", lambda p: ctk.CTkEntry(p, textvariable=self.v_n), 5)
        self._row(f, "Durasi min (detik)", lambda p: ctk.CTkEntry(p, textvariable=self.v_min), 6)
        self._row(f, "Durasi maks (detik)", lambda p: ctk.CTkEntry(p, textvariable=self.v_max), 7)
        ctk.CTkLabel(f, text="Durasi dapat diperpanjang otomatis agar pembahasan selesai tuntas.",
                     text_color="gray").grid(row=7, column=2, padx=10)
        self.v_out = tk.StringVar(value=self.cfg.output_dir)
        self._row(f, "Folder output", lambda p: ctk.CTkEntry(p, textvariable=self.v_out, placeholder_text=
                                                            "(default: di samping video)"), 8)
        ctk.CTkButton(f, text="Pilih...", width=110, command=self._pick_out).grid(row=8, column=2, padx=10)
        b = ctk.CTkFrame(tab, fg_color="transparent")
        b.grid(row=1, column=0, columnspan=3, sticky="w", pady=14, padx=12)
        self.btn_an = ctk.CTkButton(b, text="Analisis Video", height=40, command=self._analyze)
        self.btn_an.pack(side="left", padx=(0, 10))
        ctk.CTkButton(b, text="Muat list_clip.json (cache)", height=40, fg_color="#444",
                      command=self._load_cache).pack(side="left")

    # ------------------------------------------------------------ tab 2
    def _tab_clips(self, tab):
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_rowconfigure(1, weight=1)
        top = ctk.CTkFrame(tab, fg_color="transparent")
        top.grid(row=0, column=0, sticky="ew")
        ctk.CTkButton(top, text="Pilih semua", width=100, command=lambda: self._sel_all(True)).pack(side="left", padx=4)
        ctk.CTkButton(top, text="Kosongkan", width=100, fg_color="#444", command=lambda: self._sel_all(False)).pack(side="left")
        ctk.CTkButton(top, text="Simpan perubahan", width=140, fg_color="#444", command=self._save_clips).pack(side="left", padx=8)
        self.clip_info = ctk.CTkLabel(top, text="Belum ada klip. Jalankan analisis dulu.", text_color="gray")
        self.clip_info.pack(side="left", padx=10)
        self.clip_frame = ctk.CTkScrollableFrame(tab)
        self.clip_frame.grid(row=1, column=0, sticky="nsew", pady=6)
        self.clip_frame.grid_columnconfigure(2, weight=1)

    def _fill_clips(self):
        for w in self.clip_frame.winfo_children():
            w.destroy()
        self.clip_rows = []
        if not self.proj:
            return
        for r, c in enumerate(self.proj.clips):
            sel = tk.BooleanVar(value=c.selected)
            title, hook = tk.StringVar(value=c.title), tk.StringVar(value=c.hook)
            ctk.CTkCheckBox(self.clip_frame, text="", variable=sel, width=24).grid(row=r * 2, column=0, padx=4, pady=(8, 0))
            ctk.CTkLabel(self.clip_frame, text=f"#{c.id}  {fmt_time(c.start)}-{fmt_time(c.end)}  ({c.duration:.0f}s)  "
                         f"skor {c.score:.0f}", width=240, anchor="w").grid(row=r * 2, column=1, pady=(8, 0))
            ctk.CTkEntry(self.clip_frame, textvariable=title, placeholder_text="Judul").grid(
                row=r * 2, column=2, sticky="ew", padx=6, pady=(8, 0))
            ctk.CTkEntry(self.clip_frame, textvariable=hook, placeholder_text="Hook (teks stop-scroll)").grid(
                row=r * 2 + 1, column=2, sticky="ew", padx=6, pady=(2, 0))
            if c.reason:
                ctk.CTkLabel(self.clip_frame, text=c.reason, text_color="gray", anchor="w", wraplength=240,
                             justify="left").grid(row=r * 2 + 1, column=1, sticky="w")
            self.clip_rows.append((c, sel, title, hook))
        self.clip_info.configure(text=f"{len(self.proj.clips)} klip dari: {self.proj.video.name}")

    def _sync_clips(self):
        for c, sel, title, hook in self.clip_rows:
            c.selected, c.title, c.hook = sel.get(), title.get(), hook.get()

    def _sel_all(self, v):
        for _, sel, _, _ in self.clip_rows:
            sel.set(v)

    def _save_clips(self):
        if not self.proj:
            return
        self._sync_clips()
        self.proj.save({"count": self.cfg.clip_count, "min": self.cfg.min_sec, "max": self.cfg.max_sec,
                        "model": self.cfg.gemini_model, "whisper": self.cfg.whisper_model})
        self._log("list_clip.json disimpan.")

    # ------------------------------------------------------------ tab 3
    def _tab_style(self, tab):
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_rowconfigure(0, weight=1)
        left = ctk.CTkScrollableFrame(tab)
        left.grid(row=0, column=0, sticky="nsew")
        left.grid_columnconfigure(1, weight=1)
        s = self.st
        self.sv = {}

        def var(name, kind=tk.StringVar):
            v = kind(value=getattr(s, name))
            self.sv[name] = v
            return v

        r = 0
        ctk.CTkLabel(left, text="LAYOUT & SUBTITLE", font=ctk.CTkFont(weight="bold")).grid(row=r, column=0, columnspan=2, sticky="w", padx=12, pady=(6, 0)); r += 1
        self.v_layout = tk.StringVar(value=inv(LAYOUTS, s.layout))
        self._row(left, "Layout 9:16", lambda p: ctk.CTkOptionMenu(p, variable=self.v_layout, values=list(LAYOUTS)), r); r += 1
        ctk.CTkCheckBox(left, text="Subtitle aktif", variable=var("sub_enabled", tk.BooleanVar)).grid(row=r, column=0, columnspan=2, sticky="w", padx=12, pady=4); r += 1
        self.v_anim = tk.StringVar(value=inv(ANIMS, s.sub_anim))
        self._row(left, "Animasi", lambda p: ctk.CTkOptionMenu(p, variable=self.v_anim, values=list(ANIMS)), r); r += 1
        fonts = list_fonts()
        self._row(left, "Font", lambda p: ctk.CTkComboBox(p, variable=var("sub_font"), values=fonts), r); r += 1
        for label, name, lo, hi in (("Ukuran subtitle", "sub_size", 40, 140), ("Stroke dalam", "sub_inner_w", 0, 14),
                                    ("Stroke luar", "sub_outer_w", 0, 20), ("Kata per baris", "sub_max_words", 1, 8)):
            v = var(name, tk.IntVar)
            self._row(left, label, lambda p, v=v, lo=lo, hi=hi: ctk.CTkSlider(p, from_=lo, to=hi, number_of_steps=hi - lo, variable=v), r); r += 1
        ctk.CTkCheckBox(left, text="HURUF KAPITAL", variable=var("sub_uppercase", tk.BooleanVar)).grid(row=r, column=0, columnspan=2, sticky="w", padx=12, pady=4); r += 1
        self._row(left, "Kata kunci (koma)", lambda p: ctk.CTkEntry(p, textvariable=var("keywords")), r); r += 1
        cf = ctk.CTkFrame(left, fg_color="transparent")
        cf.grid(row=r, column=0, columnspan=2, sticky="w", padx=8, pady=4); r += 1
        for i, (label, name) in enumerate(COLOR_FIELDS):
            b = ctk.CTkButton(cf, text=label, width=104, height=28, text_color="white",
                              fg_color=getattr(s, name), command=lambda n=name: self._pick_color(n))
            b.grid(row=i // 4, column=i % 4, padx=3, pady=3)
            self.color_btns[name] = b
        ctk.CTkLabel(left, text="HOOK / HEADLINE AWAL", font=ctk.CTkFont(weight="bold")).grid(row=r, column=0, columnspan=2, sticky="w", padx=12, pady=(14, 0)); r += 1
        ctk.CTkCheckBox(left, text="Tampilkan hook di awal video", variable=var("hook_enabled", tk.BooleanVar)).grid(row=r, column=0, columnspan=2, sticky="w", padx=12, pady=4); r += 1
        self.v_hookstyle = tk.StringVar(value=inv(HOOKS, s.hook_style))
        self._row(left, "Gaya hook", lambda p: ctk.CTkOptionMenu(p, variable=self.v_hookstyle, values=list(HOOKS)), r); r += 1
        for label, name, lo, hi in (("Ukuran hook", "hook_size", 40, 140), ):
            v = var(name, tk.IntVar)
            self._row(left, label, lambda p, v=v, lo=lo, hi=hi: ctk.CTkSlider(p, from_=lo, to=hi, number_of_steps=hi - lo, variable=v), r); r += 1
        v = var("hook_seconds", tk.DoubleVar)
        self._row(left, "Durasi hook (detik)", lambda p: ctk.CTkSlider(p, from_=1.5, to=6, number_of_steps=9, variable=v), r); r += 1
        ctk.CTkCheckBox(left, text="Voice-over hook (suara AI, opsional)", variable=var("hook_voice", tk.BooleanVar)).grid(row=r, column=0, columnspan=2, sticky="w", padx=12, pady=4); r += 1
        ctk.CTkLabel(left, text="LOGO / WATERMARK & EFEK", font=ctk.CTkFont(weight="bold")).grid(row=r, column=0, columnspan=2, sticky="w", padx=12, pady=(14, 0)); r += 1
        lf = ctk.CTkFrame(left, fg_color="transparent")
        lf.grid(row=r, column=0, columnspan=2, sticky="ew", padx=8); r += 1
        lf.grid_columnconfigure(0, weight=1)
        ctk.CTkEntry(lf, textvariable=var("logo_path"), placeholder_text="(tanpa logo)").grid(row=0, column=0, sticky="ew", padx=4)
        ctk.CTkButton(lf, text="Pilih logo...", width=100, command=self._pick_logo).grid(row=0, column=1, padx=4)
        v = var("logo_scale", tk.DoubleVar)
        self._row(left, "Ukuran logo", lambda p: ctk.CTkSlider(p, from_=0.05, to=0.4, variable=v), r); r += 1
        v = var("logo_opacity", tk.DoubleVar)
        self._row(left, "Opasitas logo", lambda p: ctk.CTkSlider(p, from_=0.2, to=1.0, variable=v), r); r += 1
        for label, name in (("Zoom punch-in saat penekanan", "fx_punch"), ("Slow zoom (sinematik)", "fx_slowzoom"),
                            ("Progress bar", "fx_progress"), ("Fade in/out", "fx_fade"),
                            ("Color grade (kontras & saturasi)", "fx_grade"), ("Vignette", "fx_vignette")):
            ctk.CTkCheckBox(left, text=label, variable=var(name, tk.BooleanVar)).grid(row=r, column=0, columnspan=2, sticky="w", padx=12, pady=3); r += 1

        right = ctk.CTkFrame(tab)
        right.grid(row=0, column=1, sticky="ns", padx=(10, 0))
        ctk.CTkLabel(right, text="Pratinjau interaktif (klik sel untuk memindahkan)").pack(pady=(8, 2))
        seg = ctk.CTkSegmentedButton(right, values=["Subtitle", "Hook", "Logo"],
                                     command=lambda v: (self.grid_target.set({"Subtitle": "sub", "Hook": "hook", "Logo": "logo"}[v]), self._draw_preview()))
        seg.set("Subtitle")
        seg.pack(pady=4)
        self.cv = tk.Canvas(right, width=252, height=448, bg="#222", highlightthickness=0)
        self.cv.pack(padx=14, pady=6)
        self.cv.bind("<Button-1>", self._on_canvas)
        ctk.CTkLabel(right, text="Subtitle & hook: grid 3x5 | Logo: grid 3x3", text_color="gray").pack()
        for name in ("sub_size", "sub_anim", "hook_size", "logo_scale", "sub_uppercase"):
            if name in self.sv:
                self.sv[name].trace_add("write", lambda *_: self._draw_preview())
        self.v_anim.trace_add("write", lambda *_: self._draw_preview())
        self.after(200, self._draw_preview)

    def _pick_color(self, name):
        cur = getattr(self.st, name)
        c = colorchooser.askcolor(color=cur, title="Pilih warna")[1]
        if c:
            setattr(self.st, name, c.upper())
            self.color_btns[name].configure(fg_color=c)
            self._draw_preview()

    def _pick_logo(self):
        p = filedialog.askopenfilename(filetypes=[("Gambar", "*.png *.jpg *.jpeg *.webp")])
        if p:
            self.sv["logo_path"].set(p)

    def _on_canvas(self, e):
        W, H = 252, 448
        t = self.grid_target.get()
        cols, rows = 3, (3 if t == "logo" else 5)
        col = min(int(e.x / W * cols), cols - 1)
        row = min(int(e.y / H * rows), rows - 1)
        setattr(self.st, {"sub": "sub_pos", "hook": "hook_pos", "logo": "logo_pos"}[t], [col, row])
        self._draw_preview()

    def _load_preview_bg(self):
        if not self.proj or self.preview_bg is not None:
            return
        try:
            import cv2
            from PIL import Image, ImageTk
            cap = cv2.VideoCapture(str(self.proj.video))
            n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
            cap.set(cv2.CAP_PROP_POS_FRAMES, int(n * 0.3))
            ok, fr = cap.read()
            cap.release()
            if ok:
                h, w = fr.shape[:2]
                cw = min(w, int(h * 9 / 16))
                x0 = (w - cw) // 2
                im = Image.fromarray(cv2.cvtColor(fr[:, x0:x0 + cw], cv2.COLOR_BGR2RGB)).resize((252, 448))
                self.preview_bg = ImageTk.PhotoImage(im)
        except Exception:
            self.preview_bg = None

    def _draw_preview(self):
        c = self.cv
        c.delete("all")
        self._load_preview_bg()
        if self.preview_bg is not None:
            c.create_image(0, 0, image=self.preview_bg, anchor="nw")
        else:
            for i in range(0, 448, 4):
                g = 40 + int(i / 448 * 30)
                c.create_rectangle(0, i, 252, i + 4, fill=f"#{g:02x}{g:02x}{g + 10:02x}", outline="")
        W, H = 252, 448
        t = self.grid_target.get()
        cols, rows = 3, (3 if t == "logo" else 5)
        for i in range(1, cols):
            c.create_line(W * i / cols, 0, W * i / cols, H, fill="#666", dash=(2, 4))
        for j in range(1, rows):
            c.create_line(0, H * j / rows, W, H * j / rows, fill="#666", dash=(2, 4))
        pos = getattr(self.st, {"sub": "sub_pos", "hook": "hook_pos", "logo": "logo_pos"}[t])
        c.create_rectangle(W * pos[0] / cols, H * pos[1] / rows, W * (pos[0] + 1) / cols,
                           H * (pos[1] + 1) / rows, outline="#00E5FF", width=2)
        s = self.st
        sc = W / 1080
        # hook
        hx, hy = (s.hook_pos[0] + 0.5) / 3 * W, (s.hook_pos[1] + 0.5) / 5 * H
        hs = int(self.sv["hook_size"].get() * sc * 0.75) if "hook_size" in self.sv else 14
        box = {"yellow": "#FFE600", "red": "#E50914", "outline": ""}[HOOKS[self.v_hookstyle.get()]]
        fg = {"yellow": "#111", "red": "#fff", "outline": "#fff"}[HOOKS[self.v_hookstyle.get()]]
        txt = "HOOK STOP\nSCROLL DI SINI"
        if box:
            c.create_rectangle(hx - W * 0.36, hy - hs * 1.3, hx + W * 0.36, hy + hs * 1.3, fill=box, outline="")
        c.create_text(hx, hy, text=txt, fill=fg, font=("Arial", max(hs, 8), "bold"), justify="center")
        # subtitle
        sx, sy = (s.sub_pos[0] + 0.5) / 3 * W, (s.sub_pos[1] + 0.5) / 5 * H
        fs = max(int(self.sv["sub_size"].get() * sc * 0.72), 8) if "sub_size" in self.sv else 14
        c.create_text(sx, sy, text="KATA AKTIF", fill=s.sub_outer, font=("Arial", fs, "bold"))
        c.create_text(sx, sy, text="KATA AKTIF", fill=s.sub_fill, font=("Arial", fs, "bold"))
        # logo
        lx, ly = (s.logo_pos[0] + 0.5) / 3 * W, (s.logo_pos[1] + 0.5) / 3 * H
        ls = (self.sv["logo_scale"].get() if "logo_scale" in self.sv else 0.16) * W
        c.create_rectangle(lx - ls / 2, ly - ls / 2, lx + ls / 2, ly + ls / 2, outline="#fff", dash=(3, 2))
        c.create_text(lx, ly, text="LOGO", fill="#fff", font=("Arial", 8))

    # ------------------------------------------------------------ tab 4
    def _tab_render(self, tab):
        tab.grid_columnconfigure(1, weight=1)
        c = self.cfg
        s = self.st
        f = ctk.CTkFrame(tab, fg_color="transparent")
        f.grid(row=0, column=0, sticky="nw")
        f.grid_columnconfigure(1, weight=1)
        r = 0
        self.v_tl = tk.StringVar(value=inv(LANGS, c.target_lang))
        self._row(f, "Terjemahkan ke", lambda p: ctk.CTkOptionMenu(p, variable=self.v_tl, values=list(LANGS)), r); r += 1
        ctk.CTkLabel(f, text="Judul, hook, caption & subtitle diterjemahkan (butuh API key Gemini).", text_color="gray").grid(row=r, column=0, columnspan=2, sticky="w", padx=12); r += 1
        self.v_polish = tk.BooleanVar(value=c.use_gemini_polish)
        ctk.CTkCheckBox(f, text="Gemini SRT Optimizer (buang gumaman, perbaiki typo)", variable=self.v_polish).grid(row=r, column=0, columnspan=2, sticky="w", padx=12, pady=4); r += 1
        self.v_res = tk.StringVar(value=inv(RES, (s.out_width, s.out_height)))
        self._row(f, "Resolusi", lambda p: ctk.CTkOptionMenu(p, variable=self.v_res, values=list(RES)), r); r += 1
        self.v_cut = tk.BooleanVar(value=s.cut_silence)
        ctk.CTkCheckBox(f, text="Potong otomatis jeda bicara yang tidak penting", variable=self.v_cut).grid(row=r, column=0, columnspan=2, sticky="w", padx=12, pady=4); r += 1
        self.v_gap = tk.DoubleVar(value=s.silence_gap)
        self._row(f, "Jeda dianggap panjang (detik)", lambda p: ctk.CTkSlider(p, from_=0.25, to=1.2, variable=self.v_gap), r); r += 1
        self.v_fill = tk.BooleanVar(value=s.remove_fillers)
        ctk.CTkCheckBox(f, text="Buang filler ('eee', 'aaa', 'emm', 'uh', 'um') dari audio & video", variable=self.v_fill).grid(row=r, column=0, columnspan=2, sticky="w", padx=12, pady=4); r += 1
        self.v_ln = tk.BooleanVar(value=s.loudnorm)
        ctk.CTkCheckBox(f, text="Normalisasi volume (-16 LUFS)", variable=self.v_ln).grid(row=r, column=0, columnspan=2, sticky="w", padx=12, pady=4); r += 1
        self.v_th = tk.BooleanVar(value=c.make_thumbnail)
        ctk.CTkCheckBox(f, text="Buat thumbnail otomatis (9:16 & 16:9)", variable=self.v_th).grid(row=r, column=0, columnspan=2, sticky="w", padx=12, pady=4); r += 1
        b = ctk.CTkFrame(tab, fg_color="transparent")
        b.grid(row=1, column=0, sticky="w", padx=12, pady=16)
        self.btn_render = ctk.CTkButton(b, text="Render Klip Terpilih", height=44, command=self._render)
        self.btn_render.pack(side="left", padx=(0, 10))
        self.btn_stop = ctk.CTkButton(b, text="Batalkan", height=44, fg_color="#8a2d2d", command=self._stop)
        self.btn_stop.pack(side="left", padx=(0, 10))
        ctk.CTkButton(b, text="Buka folder hasil", height=44, fg_color="#444", command=self._open_out).pack(side="left")

    # ------------------------------------------------------------ settings
    def _collect(self):
        c, s = self.cfg, self.st
        c.last_source = self.v_src.get()
        c.api_key = self.v_key.get().strip()
        c.gemini_model, c.whisper_model, c.language = self.v_gmodel.get(), self.v_wh.get(), self.v_lang.get()
        for attr, v, dflt in (("clip_count", self.v_n, 5), ("min_sec", self.v_min, 30), ("max_sec", self.v_max, 75)):
            try:
                setattr(c, attr, max(1, int(float(v.get()))))
            except ValueError:
                setattr(c, attr, dflt)
        if c.max_sec < c.min_sec:
            c.max_sec = c.min_sec + 15
        c.output_dir = self.v_out.get().strip()
        c.target_lang = LANGS[self.v_tl.get()]
        c.use_gemini_polish = self.v_polish.get()
        c.make_thumbnail = self.v_th.get()
        for name, v in self.sv.items():
            setattr(s, name, v.get())
        s.layout = LAYOUTS[self.v_layout.get()]
        s.sub_anim = ANIMS[self.v_anim.get()]
        s.hook_style = HOOKS[self.v_hookstyle.get()]
        s.out_width, s.out_height = RES[self.v_res.get()]
        s.cut_silence, s.silence_gap = self.v_cut.get(), round(self.v_gap.get(), 2)
        s.remove_fillers, s.loudnorm = self.v_fill.get(), self.v_ln.get()
        c.style = s
        settings_mod.save(c)

    # ------------------------------------------------------------ aksi
    def _pick_video(self):
        p = filedialog.askopenfilename(filetypes=[("Video", "*.mp4 *.mkv *.mov *.webm *.avi *.m4v"), ("Semua", "*.*")])
        if p:
            self.v_src.set(p)

    def _pick_out(self):
        p = filedialog.askdirectory()
        if p:
            self.v_out.set(p)

    def _log(self, msg):
        self.q.put(("log", msg))

    def _prog(self, p, msg=""):
        self.q.put(("prog", (p, msg)))

    def _busy(self, on):
        st = "disabled" if on else "normal"
        self.btn_an.configure(state=st)
        self.btn_render.configure(state=st)

    def _start(self, fn):
        if self.worker and self.worker.is_alive():
            return
        self._collect()
        self._busy(True)
        self.bar.set(0)

        def run():
            try:
                fn()
            except Cancelled:
                self.q.put(("log", "Dibatalkan."))
            except Exception as e:  # tampilkan ke pengguna
                self.q.put(("error", str(e)))
            finally:
                self.q.put(("done", None))

        self.worker = threading.Thread(target=run, daemon=True)
        self.worker.start()

    def _analyze(self):
        if not self.v_src.get().strip():
            messagebox.showwarning("Clipper", "Isi link YouTube atau pilih file video dulu.")
            return

        def job():
            self.pipe = Pipeline(self.cfg, self._log, self._prog)
            proj = self.pipe.analyze(self.v_src.get())
            self.q.put(("project", proj))
        self._start(job)

    def _load_cache(self):
        p = filedialog.askopenfilename(filetypes=[("list_clip.json", "list_clip.json"), ("JSON", "*.json")])
        if not p:
            return
        try:
            self.proj = Pipeline.load_cache(Path(p))
        except Exception as e:
            messagebox.showerror("Clipper", f"Gagal memuat cache:\n{e}")
            return
        self.preview_bg = None
        self._fill_clips()
        self.tabs.set("2. Klip")
        self._log(f"Cache dimuat: {len(self.proj.clips)} klip.")

    def _render(self):
        if not self.proj:
            messagebox.showwarning("Clipper", "Belum ada klip. Jalankan analisis atau muat cache dulu.")
            return
        self._sync_clips()
        chosen = [c for c in self.proj.clips if c.selected]
        if not chosen:
            messagebox.showwarning("Clipper", "Pilih minimal satu klip di tab 'Klip'.")
            return
        for c in chosen:
            c.title = c.title or f"Klip {c.id}"

        def job():
            self.pipe = Pipeline(self.cfg, self._log, self._prog)
            outs = self.pipe.render(self.proj, chosen)
            self.q.put(("log", f"SELESAI. {len(outs)} klip tersimpan di: {self.proj.dir / 'clips'}"))
        self._start(job)

    def _stop(self):
        if self.pipe:
            self.pipe.cancel.set()
            self._log("Membatalkan setelah tahap ini selesai...")

    def _open_out(self):
        if not self.proj:
            return
        d = self.proj.dir / "clips"
        d.mkdir(exist_ok=True)
        if os.name == "nt":
            os.startfile(str(d))  # noqa
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(d)])
        else:
            subprocess.Popen(["xdg-open", str(d)])

    def _poll(self):
        try:
            while True:
                kind, data = self.q.get_nowait()
                if kind == "log":
                    self.log.configure(state="normal")
                    self.log.insert("end", data + "\n")
                    self.log.see("end")
                    self.log.configure(state="disabled")
                elif kind == "prog":
                    self.bar.set(max(0, min(1, data[0])))
                    if data[1]:
                        self.status.configure(text=data[1])
                elif kind == "project":
                    self.proj = data
                    self.preview_bg = None
                    self._fill_clips()
                    self.tabs.set("2. Klip")
                    self._draw_preview()
                elif kind == "error":
                    self.log.configure(state="normal")
                    self.log.insert("end", "ERROR: " + data + "\n")
                    self.log.configure(state="disabled")
                    messagebox.showerror("Clipper", data)
                elif kind == "done":
                    self._busy(False)
                    self.status.configure(text="Siap.")
        except queue.Empty:
            pass
        self.after(100, self._poll)

    def _close(self):
        try:
            self._collect()
        except Exception:
            pass
        self.destroy()


def main():
    App().mainloop()

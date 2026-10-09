"""Antarmuka desktop modern (customtkinter): sidebar + kartu + pratinjau berbingkai ponsel."""
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
from .pipeline import Cancelled, Pipeline, Project
from .subtitles import list_fonts
from .textproc import fmt_time

# ---- tema -------------------------------------------------------------------------------
BG, SIDEBAR, CARD, BORDER = "#0E1016", "#141722", "#1A1E2C", "#272C40"
FIELD, ACCENT, ACCENT_H = "#11141D", "#7C5CFF", "#6A49F2"
TEXT, MUTED = "#E9ECF5", "#8B91A8"
OK, WARN, DANGER = "#2ECC8F", "#F5B942", "#F0506E"
UI = "Segoe UI" if os.name == "nt" else "Helvetica"

ANIMS = {"Pop Zoom": "pop", "Karaoke Box": "karaoke", "Glow": "glow", "Kata Kunci": "keyword", "Polos": "plain"}
LAYOUTS = {"Face Tracking": "face", "Crop Tengah": "center", "Fit + Blur": "blur"}
HOOKS = {"Kuning": "yellow", "Merah": "red", "Outline": "outline"}
RES = {"1080 x 1920  Full HD": (1080, 1920), "720 x 1280  Cepat": (720, 1280)}
LANGS = {"Tanpa terjemahan": "", "Indonesia": "id", "English": "en", "Español": "es", "Português": "pt",
         "Français": "fr", "Deutsch": "de", "日本語": "ja", "한국어": "ko", "中文": "zh", "العربية": "ar",
         "हिन्दी": "hi", "Русский": "ru", "Türkçe": "tr", "ไทย": "th", "Tiếng Việt": "vi",
         "Melayu": "ms", "Italiano": "it", "Nederlands": "nl"}
SRC_LANGS = ["auto", "id", "en", "es", "pt", "fr", "de", "ja", "ko", "zh", "ar", "hi", "ru", "tr", "th", "vi", "ms"]
COLOR_FIELDS = [("Isi", "sub_fill"), ("Aktif", "sub_active"), ("Stroke dalam", "sub_inner"),
                ("Stroke luar", "sub_outer"), ("Kotak", "sub_box"), ("Glow", "sub_glow"),
                ("Kata kunci", "keyword_color")]
PAGES = [("source", "Sumber", "Video & pengaturan AI"), ("clips", "Klip", "Tinjau hasil analisis"),
         ("style", "Tampilan", "Subtitle, hook, logo, efek"), ("render", "Render", "Ekspor video & thumbnail")]
PW, PH = 252, 448   # ukuran kanvas pratinjau


def inv(d, v):
    return next((k for k, x in d.items() if x == v), next(iter(d)))


def font(size=13, weight="normal"):
    return ctk.CTkFont(family=UI, size=size, weight=weight)


class App(ctk.CTk):
    def __init__(self):
        super().__init__(fg_color=BG)
        ctk.set_appearance_mode("dark")
        self.title(f"Clipper {__version__}")
        self.geometry("1320x840")
        self.minsize(1180, 760)
        self.cfg = settings_mod.load()
        self.st = self.cfg.style
        self.proj: Project | None = None
        self.q: queue.Queue = queue.Queue()
        self.worker: threading.Thread | None = None
        self.pipe: Pipeline | None = None
        self.clip_rows: list = []
        self.grid_target = tk.StringVar(value="sub")
        self.color_btns, self.sv, self.nav, self.pages = {}, {}, {}, {}
        self.preview_bg = None
        self._log_open = False
        self._build()
        self.show("source")
        self.after(100, self._poll)
        self.protocol("WM_DELETE_WINDOW", self._close)

    # ================================================================ kerangka
    def _build(self):
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)
        side = ctk.CTkFrame(self, width=232, corner_radius=0, fg_color=SIDEBAR)
        side.grid(row=0, column=0, rowspan=2, sticky="nsw")
        side.grid_propagate(False)
        brand = ctk.CTkFrame(side, fg_color="transparent")
        brand.pack(fill="x", padx=22, pady=(26, 22))
        dot = ctk.CTkLabel(brand, text="✂", width=40, height=40, corner_radius=12, fg_color=ACCENT,
                           text_color="white", font=font(20, "bold"))
        dot.pack(side="left")
        tb = ctk.CTkFrame(brand, fg_color="transparent")
        tb.pack(side="left", padx=12)
        ctk.CTkLabel(tb, text="Clipper", font=font(20, "bold"), text_color=TEXT, anchor="w").pack(anchor="w")
        ctk.CTkLabel(tb, text="AI Video Clipper", font=font(11), text_color=MUTED, anchor="w").pack(anchor="w")
        for i, (key, title, sub) in enumerate(PAGES, 1):
            b = ctk.CTkButton(side, text=f"  {i}   {title}", anchor="w", height=46, corner_radius=12,
                              font=font(14, "bold"), fg_color="transparent", hover_color="#1E2336",
                              text_color=MUTED, command=lambda k=key: self.show(k))
            b.pack(fill="x", padx=14, pady=3)
            self.nav[key] = b
        ctk.CTkLabel(side, text="").pack(expand=True)
        ctk.CTkLabel(side, text=f"v{__version__}  •  proses lokal & privat", font=font(11),
                     text_color=MUTED).pack(pady=(0, 18))

        self.main = ctk.CTkFrame(self, fg_color="transparent")
        self.main.grid(row=0, column=1, sticky="nsew", padx=(26, 26), pady=(22, 0))
        self.main.grid_columnconfigure(0, weight=1)
        self.main.grid_rowconfigure(1, weight=1)
        hd = ctk.CTkFrame(self.main, fg_color="transparent")
        hd.grid(row=0, column=0, sticky="ew", pady=(0, 14))
        self.h_title = ctk.CTkLabel(hd, text="", font=font(26, "bold"), text_color=TEXT, anchor="w")
        self.h_title.pack(anchor="w")
        self.h_sub = ctk.CTkLabel(hd, text="", font=font(13), text_color=MUTED, anchor="w")
        self.h_sub.pack(anchor="w")
        host = ctk.CTkFrame(self.main, fg_color="transparent")
        host.grid(row=1, column=0, sticky="nsew")
        host.grid_columnconfigure(0, weight=1)
        host.grid_rowconfigure(0, weight=1)
        for key, _, _ in PAGES:
            pg = ctk.CTkScrollableFrame(host, fg_color="transparent", scrollbar_button_color=BORDER,
                                        scrollbar_button_hover_color=ACCENT)
            pg.grid(row=0, column=0, sticky="nsew")
            pg.grid_columnconfigure(0, weight=1)
            self.pages[key] = pg
        self._page_source(self.pages["source"])
        self._page_clips(self.pages["clips"])
        self._page_style(self.pages["style"])
        self._page_render(self.pages["render"])

        # bar aktivitas
        bar = ctk.CTkFrame(self, fg_color=SIDEBAR, corner_radius=14, border_width=1, border_color=BORDER)
        bar.grid(row=1, column=1, sticky="ew", padx=26, pady=16)
        bar.grid_columnconfigure(1, weight=1)
        self.status = ctk.CTkLabel(bar, text="Siap", font=font(13, "bold"), text_color=TEXT, anchor="w", width=210)
        self.status.grid(row=0, column=0, padx=(18, 8), pady=12, sticky="w")
        self.bar = ctk.CTkProgressBar(bar, height=8, progress_color=ACCENT, fg_color=BORDER)
        self.bar.set(0)
        self.bar.grid(row=0, column=1, sticky="ew", padx=8)
        self.pct = ctk.CTkLabel(bar, text="0%", font=font(12), text_color=MUTED, width=44)
        self.pct.grid(row=0, column=2)
        ctk.CTkButton(bar, text="Log ▾", width=64, height=30, corner_radius=8, font=font(12),
                      fg_color="#222740", hover_color="#2B3150", command=self._toggle_log).grid(row=0, column=3, padx=(4, 14))
        self.log = ctk.CTkTextbox(bar, height=150, fg_color=FIELD, text_color="#B9C0D8", corner_radius=10,
                                  font=ctk.CTkFont(family="Consolas" if os.name == "nt" else "Courier", size=12))
        self.log.configure(state="disabled")
        self.bar_frame = bar

    def show(self, key):
        for k, pg in self.pages.items():
            if k == key:
                pg.grid()
            else:
                pg.grid_remove()
        for k, b in self.nav.items():
            on = k == key
            b.configure(fg_color=ACCENT if on else "transparent", text_color="white" if on else MUTED,
                        hover_color=ACCENT_H if on else "#1E2336")
        t = next(p for p in PAGES if p[0] == key)
        self.h_title.configure(text=t[1])
        self.h_sub.configure(text={"source": "Masukkan link YouTube atau file video, lalu biarkan AI memilih momen terbaik.",
                                   "clips": "Centang klip yang ingin dirender dan sunting judul serta hook-nya.",
                                   "style": "Atur gaya visual. Klik sel pada pratinjau untuk memindahkan elemen.",
                                   "render": "Pilih opsi akhir lalu render semua klip terpilih."}[key])

    def _toggle_log(self, force=None):
        self._log_open = (not self._log_open) if force is None else force
        if self._log_open:
            self.log.grid(row=1, column=0, columnspan=4, sticky="ew", padx=14, pady=(0, 14))
        else:
            self.log.grid_forget()

    # ================================================================ komponen
    def card(self, parent, title, sub="", row=0, col=0, span=1, pady=(0, 16)):
        f = ctk.CTkFrame(parent, fg_color=CARD, corner_radius=16, border_width=1, border_color=BORDER)
        f.grid(row=row, column=col, columnspan=span, sticky="ew", pady=pady, padx=(0, 0))
        ctk.CTkLabel(f, text=title, font=font(15, "bold"), text_color=TEXT, anchor="w").pack(anchor="w", padx=22, pady=(18, 0))
        if sub:
            ctk.CTkLabel(f, text=sub, font=font(12), text_color=MUTED, anchor="w", wraplength=760,
                         justify="left").pack(anchor="w", padx=22, pady=(2, 0))
        body = ctk.CTkFrame(f, fg_color="transparent")
        body.pack(fill="x", padx=22, pady=(12, 20))
        body.grid_columnconfigure((0, 1), weight=1, uniform="c")
        return body

    def field(self, body, label, widget, r, c=0, span=1):
        ctk.CTkLabel(body, text=label, font=font(12), text_color=MUTED, anchor="w").grid(
            row=r * 2, column=c, columnspan=span, sticky="w", padx=(0, 14), pady=(8, 3))
        widget.grid(row=r * 2 + 1, column=c, columnspan=span, sticky="ew", padx=(0, 14))
        return widget

    def entry(self, p, var, ph="", show=None):
        return ctk.CTkEntry(p, textvariable=var, placeholder_text=ph, show=show, height=38, corner_radius=10,
                            fg_color=FIELD, border_color=BORDER, text_color=TEXT, font=font(13))

    def combo(self, p, var, values):
        return ctk.CTkComboBox(p, variable=var, values=values, height=38, corner_radius=10, fg_color=FIELD,
                               border_color=BORDER, button_color=BORDER, button_hover_color=ACCENT,
                               dropdown_fg_color=CARD, font=font(13))

    def menu(self, p, var, values):
        return ctk.CTkOptionMenu(p, variable=var, values=values, height=38, corner_radius=10, fg_color=FIELD,
                                 button_color=BORDER, button_hover_color=ACCENT, dropdown_fg_color=CARD, font=font(13),
                                 text_color=TEXT)

    def seg(self, p, var, values):
        return ctk.CTkSegmentedButton(p, variable=var, values=values, height=36, corner_radius=10, fg_color=FIELD,
                                      selected_color=ACCENT, selected_hover_color=ACCENT_H, unselected_color=FIELD,
                                      unselected_hover_color="#1E2336", font=font(12, "bold"))

    def switch(self, p, text, var):
        return ctk.CTkSwitch(p, text=text, variable=var, font=font(13), text_color=TEXT, progress_color=ACCENT,
                             button_color="#fff", button_hover_color="#ddd", fg_color=BORDER)

    def slider(self, body, label, var, lo, hi, r, c=0, steps=None, fmt="{:.0f}"):
        wrap = ctk.CTkFrame(body, fg_color="transparent")
        top = ctk.CTkFrame(wrap, fg_color="transparent")
        top.pack(fill="x")
        ctk.CTkLabel(top, text=label, font=font(12), text_color=MUTED).pack(side="left")
        val = ctk.CTkLabel(top, text=fmt.format(var.get()), font=font(12, "bold"), text_color=TEXT)
        val.pack(side="right")
        var.trace_add("write", lambda *_: val.configure(text=fmt.format(var.get())))
        ctk.CTkSlider(wrap, from_=lo, to=hi, variable=var, number_of_steps=steps, height=16,
                      progress_color=ACCENT, button_color="#fff", button_hover_color="#ddd",
                      fg_color=BORDER).pack(fill="x", pady=(5, 0))
        wrap.grid(row=r * 2, column=c, rowspan=2, sticky="ew", padx=(0, 14), pady=(8, 4))

    def btn(self, p, text, cmd, kind="ghost", **kw):
        colors = {"primary": (ACCENT, ACCENT_H, "white"), "ghost": ("#222740", "#2B3150", TEXT),
                  "danger": ("#3A1F2A", DANGER, "#FFB3C0")}[kind]
        return ctk.CTkButton(p, text=text, command=cmd, corner_radius=10, height=kw.pop("height", 38),
                             fg_color=colors[0], hover_color=colors[1], text_color=colors[2],
                             font=font(13, "bold"), **kw)

    # ================================================================ halaman 1
    def _page_source(self, pg):
        c = self.cfg
        body = self.card(pg, "Video sumber", "Tempel link YouTube (diunduh otomatis) atau pilih file dari komputer.", 0)
        self.v_src = tk.StringVar(value=c.last_source)
        self.field(body, "Link YouTube / lokasi file", self.entry(body, self.v_src, "https://www.youtube.com/watch?v=..."), 0, 0, 2)
        row = ctk.CTkFrame(body, fg_color="transparent")
        row.grid(row=2, column=0, columnspan=2, sticky="w", pady=(12, 0))
        self.btn(row, "Pilih file...", self._pick_video, width=130).pack(side="left", padx=(0, 10))
        self.btn(row, "Perbarui yt-dlp", self._update_ytdlp, width=140).pack(side="left")
        ctk.CTkLabel(row, text="  jika unduhan YouTube ditolak", font=font(12), text_color=MUTED).pack(side="left")

        body = self.card(pg, "Kecerdasan buatan", "Gemini memilih klip, merapikan & menerjemahkan. Transkripsi berjalan lokal.", 1)
        self.v_key = tk.StringVar(value=c.api_key)
        self.field(body, "API Key Gemini  (gratis di aistudio.google.com/apikey)", self.entry(body, self.v_key, "AIza...", "•"), 0, 0, 2)
        self.v_gmodel = tk.StringVar(value=c.gemini_model)
        self.field(body, "Model Gemini", self.combo(body, self.v_gmodel, ["gemini-2.5-flash", "gemini-2.5-pro", "gemini-2.0-flash"]), 1, 0)
        self.v_wh = tk.StringVar(value=c.whisper_model)
        self.field(body, "Model transkripsi (lokal)", self.combo(body, self.v_wh, ["tiny", "base", "small", "medium", "large-v3"]), 1, 1)
        self.v_lang = tk.StringVar(value=c.language)
        self.field(body, "Bahasa ucapan di video", self.combo(body, self.v_lang, SRC_LANGS), 2, 0)

        body = self.card(pg, "Klip yang dicari", "Durasi bisa diperpanjang otomatis agar pembahasan selesai tuntas.", 2)
        self.v_n, self.v_min, self.v_max = (tk.StringVar(value=str(x)) for x in (c.clip_count, c.min_sec, c.max_sec))
        body.grid_columnconfigure(2, weight=1, uniform="c")
        self.field(body, "Jumlah klip", self.entry(body, self.v_n), 0, 0)
        self.field(body, "Durasi min (detik)", self.entry(body, self.v_min), 0, 1)
        self.field(body, "Durasi maks (detik)", self.entry(body, self.v_max), 0, 2)
        self.v_out = tk.StringVar(value=c.output_dir)
        out = ctk.CTkFrame(body, fg_color="transparent")
        out.grid_columnconfigure(0, weight=1)
        self.entry(out, self.v_out, "(default: folder 'Clipper_output' di samping video)").grid(row=0, column=0, sticky="ew")
        self.btn(out, "Pilih...", self._pick_out, width=90).grid(row=0, column=1, padx=(10, 14))
        self.field(body, "Folder output", out, 1, 0, 3)

        act = ctk.CTkFrame(pg, fg_color="transparent")
        act.grid(row=3, column=0, sticky="w", pady=(4, 20))
        self.btn_an = self.btn(act, "▶  Analisis Video", self._analyze, "primary", width=210, height=48)
        self.btn_an.pack(side="left", padx=(0, 12))
        self.btn(act, "Muat list_clip.json", self._load_cache, height=48, width=180).pack(side="left")

    # ================================================================ halaman 2
    def _page_clips(self, pg):
        top = ctk.CTkFrame(pg, fg_color="transparent")
        top.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        self.btn(top, "Pilih semua", lambda: self._sel_all(True), width=110).pack(side="left", padx=(0, 8))
        self.btn(top, "Kosongkan", lambda: self._sel_all(False), width=100).pack(side="left", padx=(0, 8))
        self.btn(top, "Simpan perubahan", self._save_clips, width=150).pack(side="left")
        self.clip_info = ctk.CTkLabel(top, text="", font=font(12), text_color=MUTED)
        self.clip_info.pack(side="left", padx=14)
        self.clip_host = ctk.CTkFrame(pg, fg_color="transparent")
        self.clip_host.grid(row=1, column=0, sticky="ew")
        self.clip_host.grid_columnconfigure(0, weight=1)
        self._fill_clips()

    def _fill_clips(self):
        for w in self.clip_host.winfo_children():
            w.destroy()
        self.clip_rows = []
        if not self.proj or not self.proj.clips:
            e = ctk.CTkFrame(self.clip_host, fg_color=CARD, corner_radius=16, border_width=1, border_color=BORDER)
            e.grid(row=0, column=0, sticky="ew")
            ctk.CTkLabel(e, text="Belum ada klip", font=font(16, "bold"), text_color=TEXT).pack(pady=(34, 4))
            ctk.CTkLabel(e, text="Jalankan analisis di halaman Sumber, atau muat list_clip.json dari cache.",
                         font=font(13), text_color=MUTED).pack(pady=(0, 34))
            self.clip_info.configure(text="")
            return
        for r, c in enumerate(self.proj.clips):
            card = ctk.CTkFrame(self.clip_host, fg_color=CARD, corner_radius=16, border_width=1, border_color=BORDER)
            card.grid(row=r, column=0, sticky="ew", pady=(0, 12))
            card.grid_columnconfigure(2, weight=1)
            sel = tk.BooleanVar(value=c.selected)
            ctk.CTkCheckBox(card, text="", variable=sel, width=26, checkbox_width=22, checkbox_height=22,
                            corner_radius=7, fg_color=ACCENT, hover_color=ACCENT_H, border_color=BORDER).grid(
                row=0, column=0, rowspan=2, padx=(20, 12), pady=18)
            meta = ctk.CTkFrame(card, fg_color="transparent")
            meta.grid(row=0, column=1, rowspan=2, sticky="nw", pady=16, padx=(0, 18))
            ctk.CTkLabel(meta, text=f"Klip {c.id}", font=font(15, "bold"), text_color=TEXT).pack(anchor="w")
            ctk.CTkLabel(meta, text=f"{fmt_time(c.start)} – {fmt_time(c.end)}  •  {c.duration:.0f} dtk",
                         font=font(12), text_color=MUTED).pack(anchor="w", pady=(2, 6))
            col = OK if c.score >= 80 else WARN if c.score >= 60 else MUTED
            ctk.CTkLabel(meta, text=f"  Skor viral {c.score:.0f}  ", font=font(11, "bold"), text_color="#0E1016",
                         fg_color=col, corner_radius=8, height=22).pack(anchor="w")
            title, hook = tk.StringVar(value=c.title), tk.StringVar(value=c.hook)
            self.entry(card, title, "Judul").grid(row=0, column=2, sticky="ew", padx=(0, 20), pady=(16, 6))
            self.entry(card, hook, "Hook / teks stop-scroll").grid(row=1, column=2, sticky="ew", padx=(0, 20), pady=(0, 6))
            if c.reason:
                ctk.CTkLabel(card, text=c.reason, font=font(12), text_color=MUTED, anchor="w", wraplength=640,
                             justify="left").grid(row=2, column=1, columnspan=2, sticky="w", padx=(0, 20), pady=(0, 14))
            self.clip_rows.append((c, sel, title, hook))
        self.clip_info.configure(text=f"{len(self.proj.clips)} klip  •  {self.proj.video.name}")

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

    # ================================================================ halaman 3
    def _var(self, name, kind=tk.StringVar):
        v = kind(value=getattr(self.st, name))
        self.sv[name] = v
        return v

    def _page_style(self, pg):
        pg.grid_columnconfigure(0, weight=1)
        pg.grid_columnconfigure(1, weight=0)
        left = ctk.CTkFrame(pg, fg_color="transparent")
        left.grid(row=0, column=0, sticky="new", padx=(0, 20))
        left.grid_columnconfigure(0, weight=1)
        s, V = self.st, self._var

        body = self.card(left, "Layout & subtitle", "", 0)
        self.v_layout = tk.StringVar(value=inv(LAYOUTS, s.layout))
        self.field(body, "Layout 9:16", self.seg(body, self.v_layout, list(LAYOUTS)), 0, 0, 2)
        self.v_anim = tk.StringVar(value=inv(ANIMS, s.sub_anim))
        self.field(body, "Animasi subtitle", self.seg(body, self.v_anim, list(ANIMS)), 1, 0, 2)
        self.field(body, "Font", self.combo(body, V("sub_font"), list_fonts()), 2, 0)
        self.field(body, "Kata kunci (pisahkan koma)", self.entry(body, V("keywords"), "rahasia, kunci, gratis"), 2, 1)
        self.slider(body, "Ukuran", V("sub_size", tk.IntVar), 40, 140, 3, 0, 100)
        self.slider(body, "Kata per baris", V("sub_max_words", tk.IntVar), 1, 8, 3, 1, 7)
        self.slider(body, "Stroke dalam", V("sub_inner_w", tk.IntVar), 0, 14, 4, 0, 14)
        self.slider(body, "Stroke luar", V("sub_outer_w", tk.IntVar), 0, 20, 4, 1, 20)
        sw = ctk.CTkFrame(body, fg_color="transparent")
        sw.grid(row=10, column=0, columnspan=2, sticky="w", pady=(10, 0))
        self.switch(sw, "Subtitle aktif", V("sub_enabled", tk.BooleanVar)).pack(side="left", padx=(0, 26))
        self.switch(sw, "HURUF KAPITAL", V("sub_uppercase", tk.BooleanVar)).pack(side="left")
        cf = ctk.CTkFrame(body, fg_color="transparent")
        cf.grid(row=11, column=0, columnspan=2, sticky="w", pady=(16, 0))
        for i, (label, name) in enumerate(COLOR_FIELDS):
            cell = ctk.CTkFrame(cf, fg_color="transparent")
            cell.grid(row=0, column=i, padx=(0, 14))
            b = ctk.CTkButton(cell, text="", width=36, height=36, corner_radius=18, border_width=2,
                              border_color=BORDER, fg_color=getattr(s, name), hover_color=getattr(s, name),
                              command=lambda n=name: self._pick_color(n))
            b.pack()
            ctk.CTkLabel(cell, text=label, font=font(10), text_color=MUTED).pack(pady=(4, 0))
            self.color_btns[name] = b

        body = self.card(left, "Hook / headline awal", "Teks stop-scroll di beberapa detik pertama.", 1)
        sw = ctk.CTkFrame(body, fg_color="transparent")
        sw.grid(row=0, column=0, columnspan=2, sticky="w")
        self.switch(sw, "Tampilkan hook", V("hook_enabled", tk.BooleanVar)).pack(side="left", padx=(0, 26))
        self.switch(sw, "Voice-over AI (opsional)", V("hook_voice", tk.BooleanVar)).pack(side="left")
        self.v_hookstyle = tk.StringVar(value=inv(HOOKS, s.hook_style))
        self.field(body, "Gaya", self.seg(body, self.v_hookstyle, list(HOOKS)), 1, 0, 2)
        self.slider(body, "Ukuran hook", V("hook_size", tk.IntVar), 40, 140, 2, 0, 100)
        self.slider(body, "Durasi (detik)", V("hook_seconds", tk.DoubleVar), 1.5, 6, 2, 1, 9, "{:.1f}")

        body = self.card(left, "Logo & efek", "", 2)
        lf = ctk.CTkFrame(body, fg_color="transparent")
        lf.grid_columnconfigure(0, weight=1)
        self.entry(lf, V("logo_path"), "(tanpa logo)").grid(row=0, column=0, sticky="ew")
        self.btn(lf, "Pilih logo...", self._pick_logo, width=120).grid(row=0, column=1, padx=(10, 14))
        self.field(body, "Logo / watermark", lf, 0, 0, 2)
        self.slider(body, "Ukuran logo", V("logo_scale", tk.DoubleVar), 0.05, 0.4, 1, 0, None, "{:.2f}")
        self.slider(body, "Opasitas logo", V("logo_opacity", tk.DoubleVar), 0.2, 1.0, 1, 1, None, "{:.2f}")
        fx = ctk.CTkFrame(body, fg_color="transparent")
        fx.grid(row=6, column=0, columnspan=2, sticky="w", pady=(14, 0))
        for i, (label, name) in enumerate((("Zoom punch-in", "fx_punch"), ("Slow zoom", "fx_slowzoom"),
                                           ("Progress bar", "fx_progress"), ("Fade in/out", "fx_fade"),
                                           ("Color grade", "fx_grade"), ("Vignette", "fx_vignette"))):
            self.switch(fx, label, V(name, tk.BooleanVar)).grid(row=i // 3, column=i % 3, sticky="w", padx=(0, 28), pady=6)

        # --- pratinjau berbingkai ponsel
        right = ctk.CTkFrame(pg, fg_color=CARD, corner_radius=16, border_width=1, border_color=BORDER)
        right.grid(row=0, column=1, sticky="n")
        ctk.CTkLabel(right, text="Pratinjau", font=font(15, "bold"), text_color=TEXT).pack(pady=(18, 0))
        ctk.CTkLabel(right, text="Klik sel untuk memindahkan", font=font(12), text_color=MUTED).pack(pady=(0, 10))
        self.target_var = tk.StringVar(value="Subtitle")
        sg = ctk.CTkSegmentedButton(right, values=["Subtitle", "Hook", "Logo"], variable=self.target_var, height=34,
                                    fg_color=FIELD, selected_color=ACCENT, selected_hover_color=ACCENT_H,
                                    unselected_color=FIELD, font=font(12, "bold"),
                                    command=lambda v: (self.grid_target.set({"Subtitle": "sub", "Hook": "hook", "Logo": "logo"}[v]),
                                                       self._draw_preview()))
        sg.pack(padx=18)
        self.cv = tk.Canvas(right, width=PW + 24, height=PH + 24, bg=CARD, highlightthickness=0)
        self.cv.pack(padx=18, pady=(14, 8))
        self.cv.bind("<Button-1>", self._on_canvas)
        self.cap = ctk.CTkLabel(right, text="", font=font(11), text_color=MUTED)
        self.cap.pack(pady=(0, 18))
        for name in ("sub_size", "hook_size", "logo_scale", "sub_uppercase"):
            self.sv[name].trace_add("write", lambda *_: self._draw_preview())
        for v in (self.v_anim, self.v_hookstyle):
            v.trace_add("write", lambda *_: self._draw_preview())
        self.after(250, self._draw_preview)

    def _pick_color(self, name):
        c = colorchooser.askcolor(color=getattr(self.st, name), title="Pilih warna")[1]
        if c:
            setattr(self.st, name, c.upper())
            self.color_btns[name].configure(fg_color=c, hover_color=c)
            self._draw_preview()

    def _pick_logo(self):
        p = filedialog.askopenfilename(filetypes=[("Gambar", "*.png *.jpg *.jpeg *.webp")])
        if p:
            self.sv["logo_path"].set(p)

    def _on_canvas(self, e):
        x, y = e.x - 12, e.y - 12
        if not (0 <= x < PW and 0 <= y < PH):
            return
        t = self.grid_target.get()
        rows = 3 if t == "logo" else 5
        setattr(self.st, {"sub": "sub_pos", "hook": "hook_pos", "logo": "logo_pos"}[t],
                [min(int(x / PW * 3), 2), min(int(y / PH * rows), rows - 1)])
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
                im = Image.fromarray(cv2.cvtColor(fr[:, x0:x0 + cw], cv2.COLOR_BGR2RGB)).resize((PW, PH))
                self.preview_bg = ImageTk.PhotoImage(im)
        except Exception:
            self.preview_bg = None

    def _stroke_text(self, x, y, text, size, fill, inner, outer, iw, ow, anchor="center"):
        f = ("Arial", max(size, 7), "bold")
        for rad, col in ((ow + iw, outer), (iw, inner)):
            r = max(rad, 0)
            if r:
                for dx, dy in ((-r, 0), (r, 0), (0, -r), (0, r), (-r, -r), (r, r), (-r, r), (r, -r)):
                    self.cv.create_text(x + dx, y + dy, text=text, fill=col, font=f, anchor=anchor)
        self.cv.create_text(x, y, text=text, fill=fill, font=f, anchor=anchor)

    def _draw_preview(self):
        c, s = self.cv, self.st
        if not hasattr(self, "cv") or not self.cv.winfo_exists():
            return
        c.delete("all")
        self._load_preview_bg()
        ox = oy = 12
        c.create_rectangle(ox - 7, oy - 7, ox + PW + 7, oy + PH + 7, outline="#3A4060", width=3)
        if self.preview_bg is not None:
            c.create_image(ox, oy, image=self.preview_bg, anchor="nw")
        else:
            for i in range(0, PH, 4):
                k = int(34 + i / PH * 30)
                c.create_rectangle(ox, oy + i, ox + PW, oy + i + 4, fill=f"#{k // 2:02x}{k // 2:02x}{k + 20:02x}", outline="")
            c.create_text(ox + PW / 2, oy + PH / 2 + 60, text="(pratinjau memakai\nframe dari video\nsetelah analisis)",
                          fill="#5A6180", font=("Arial", 9), justify="center")
        t = self.grid_target.get()
        cols, rows = 3, (3 if t == "logo" else 5)
        for i in range(1, cols):
            c.create_line(ox + PW * i / cols, oy, ox + PW * i / cols, oy + PH, fill="#8B91A8", dash=(2, 5))
        for j in range(1, rows):
            c.create_line(ox, oy + PH * j / rows, ox + PW, oy + PH * j / rows, fill="#8B91A8", dash=(2, 5))
        pos = getattr(s, {"sub": "sub_pos", "hook": "hook_pos", "logo": "logo_pos"}[t])
        c.create_rectangle(ox + PW * pos[0] / cols + 2, oy + PH * pos[1] / rows + 2, ox + PW * (pos[0] + 1) / cols - 2,
                           oy + PH * (pos[1] + 1) / rows - 2, outline=ACCENT, width=2)
        sc = PW / 1080
        # hook
        if s.hook_enabled or True:
            hx, hy = ox + (s.hook_pos[0] + 0.5) / 3 * PW, oy + (s.hook_pos[1] + 0.5) / 5 * PH
            hs = int(self.sv["hook_size"].get() * sc * 0.62)
            kind = HOOKS[self.v_hookstyle.get()]
            if kind in ("yellow", "red"):
                bg, fg = ("#FFE600", "#111111") if kind == "yellow" else ("#E50914", "#FFFFFF")
                c.create_rectangle(hx - PW * 0.40, hy - hs * 1.55, hx + PW * 0.40, hy + hs * 1.55, fill=bg, outline="")
                c.create_text(hx, hy, text="HOOK STOP SCROLL\nDI SINI", fill=fg, font=("Arial", max(hs, 7), "bold"), justify="center")
            else:
                self._stroke_text(hx, hy, "HOOK STOP\nSCROLL", hs, "#FFFFFF", "#111111", "#FFE600", 1, 2)
        # subtitle
        sx, sy = ox + (s.sub_pos[0] + 0.5) / 3 * PW, oy + (s.sub_pos[1] + 0.5) / 5 * PH
        fs = int(self.sv["sub_size"].get() * sc * 0.6)
        txt = "KATA AKTIF" if self.sv["sub_uppercase"].get() else "Kata aktif"
        anim = ANIMS[self.v_anim.get()]
        if anim == "karaoke":
            c.create_rectangle(sx - PW * 0.2, sy - fs * 0.9, sx + PW * 0.2, sy + fs * 0.9, fill=s.sub_box, outline="")
        self._stroke_text(sx, sy, txt, fs, s.sub_active if anim in ("pop", "glow") else s.sub_fill,
                          s.sub_inner, s.sub_outer, max(1, s.sub_inner_w // 3), max(1, s.sub_outer_w // 3))
        # logo
        lx, ly = ox + (s.logo_pos[0] + 0.5) / 3 * PW, oy + (s.logo_pos[1] + 0.5) / 3 * PH
        ls = self.sv["logo_scale"].get() * PW
        c.create_oval(lx - ls / 2, ly - ls / 2, lx + ls / 2, ly + ls / 2, outline="#FFFFFF", dash=(3, 2))
        c.create_text(lx, ly, text="LOGO", fill="#FFFFFF", font=("Arial", 7, "bold"))
        self.cap.configure(text=f"Mengatur: {self.target_var.get()}  •  grid {cols}×{rows}")

    # ================================================================ halaman 4
    def _page_render(self, pg):
        c, s = self.cfg, self.st
        body = self.card(pg, "Bahasa & AI", "Terjemahan & perapian memerlukan API key Gemini.", 0)
        self.v_tl = tk.StringVar(value=inv(LANGS, c.target_lang))
        self.field(body, "Terjemahkan judul, hook, caption & subtitle ke", self.menu(body, self.v_tl, list(LANGS)), 0, 0)
        self.v_res = tk.StringVar(value=inv(RES, (s.out_width, s.out_height)))
        self.field(body, "Resolusi", self.menu(body, self.v_res, list(RES)), 0, 1)
        self.v_polish = tk.BooleanVar(value=c.use_gemini_polish)
        self.switch(body, "Gemini SRT Optimizer — buang gumaman & perbaiki typo", self.v_polish).grid(
            row=2, column=0, columnspan=2, sticky="w", pady=(16, 0))

        body = self.card(pg, "Audio & pemotongan", "", 1)
        self.v_cut = tk.BooleanVar(value=s.cut_silence)
        self.v_fill = tk.BooleanVar(value=s.remove_fillers)
        self.v_ln = tk.BooleanVar(value=s.loudnorm)
        self.v_th = tk.BooleanVar(value=c.make_thumbnail)
        self.switch(body, "Potong jeda bicara yang tidak penting", self.v_cut).grid(row=0, column=0, sticky="w", pady=6)
        self.switch(body, "Buang filler (eee, aaa, emm, uh, um)", self.v_fill).grid(row=0, column=1, sticky="w", pady=6)
        self.switch(body, "Normalisasi volume (-16 LUFS)", self.v_ln).grid(row=1, column=0, sticky="w", pady=6)
        self.switch(body, "Buat thumbnail otomatis (9:16 & 16:9)", self.v_th).grid(row=1, column=1, sticky="w", pady=6)
        self.v_gap = tk.DoubleVar(value=s.silence_gap)
        self.slider(body, "Jeda dianggap panjang (detik)", self.v_gap, 0.25, 1.2, 1, 0, None, "{:.2f}")

        act = ctk.CTkFrame(pg, fg_color="transparent")
        act.grid(row=2, column=0, sticky="w", pady=(4, 20))
        self.btn_render = self.btn(act, "▶  Render Klip Terpilih", self._render, "primary", width=250, height=50)
        self.btn_render.pack(side="left", padx=(0, 12))
        self.btn_stop = self.btn(act, "Batalkan", self._stop, "danger", width=110, height=50)
        self.btn_stop.pack(side="left", padx=(0, 12))
        self.btn(act, "Buka folder hasil", self._open_out, width=170, height=50).pack(side="left")

    # ================================================================ pengaturan
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
        c.use_gemini_polish, c.make_thumbnail = self.v_polish.get(), self.v_th.get()
        for name, v in self.sv.items():
            setattr(s, name, v.get())
        s.layout, s.sub_anim = LAYOUTS[self.v_layout.get()], ANIMS[self.v_anim.get()]
        s.hook_style = HOOKS[self.v_hookstyle.get()]
        s.out_width, s.out_height = RES[self.v_res.get()]
        s.cut_silence, s.silence_gap = self.v_cut.get(), round(self.v_gap.get(), 2)
        s.remove_fillers, s.loudnorm = self.v_fill.get(), self.v_ln.get()
        c.style = s
        settings_mod.save(c)

    # ================================================================ aksi
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
            except Exception as e:
                self.q.put(("error", str(e)))
            finally:
                self.q.put(("done", None))

        self.worker = threading.Thread(target=run, daemon=True)
        self.worker.start()

    def _update_ytdlp(self):
        from .media import update_ytdlp
        self._toggle_log(True)
        self._start(lambda: update_ytdlp(self._log))

    def _analyze(self):
        if not self.v_src.get().strip():
            messagebox.showwarning("Clipper", "Isi link YouTube atau pilih file video dulu.")
            return

        def job():
            self.pipe = Pipeline(self.cfg, self._log, self._prog)
            self.q.put(("project", self.pipe.analyze(self.v_src.get())))
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
        self.show("clips")
        self._log(f"Cache dimuat: {len(self.proj.clips)} klip.")

    def _render(self):
        if not self.proj:
            messagebox.showwarning("Clipper", "Belum ada klip. Jalankan analisis atau muat cache dulu.")
            return
        self._sync_clips()
        chosen = [c for c in self.proj.clips if c.selected]
        if not chosen:
            messagebox.showwarning("Clipper", "Pilih minimal satu klip di halaman Klip.")
            return
        for c in chosen:
            c.title = c.title or f"Klip {c.id}"

        def job():
            self.pipe = Pipeline(self.cfg, self._log, self._prog)
            outs = self.pipe.render(self.proj, chosen)
            self.q.put(("log", f"SELESAI. {len(outs)} klip tersimpan di: {self.proj.dir / 'clips'}"))
        self._toggle_log(True)
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

    def _append_log(self, text):
        self.log.configure(state="normal")
        self.log.insert("end", text + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def _poll(self):
        try:
            while True:
                kind, data = self.q.get_nowait()
                if kind == "log":
                    self._append_log(data)
                elif kind == "prog":
                    p = max(0, min(1, data[0]))
                    self.bar.set(p)
                    self.pct.configure(text=f"{p * 100:.0f}%")
                    if data[1]:
                        self.status.configure(text=data[1])
                elif kind == "project":
                    self.proj = data
                    self.preview_bg = None
                    self._fill_clips()
                    self.show("clips")
                    self._draw_preview()
                elif kind == "error":
                    self._append_log("ERROR: " + data)
                    self._toggle_log(True)
                    self.status.configure(text="Terjadi kesalahan", text_color=DANGER)
                    messagebox.showerror("Clipper", data)
                elif kind == "done":
                    self._busy(False)
                    if self.status.cget("text_color") == DANGER:
                        self.status.configure(text_color=TEXT)
                    elif self.bar.get() >= 0.999:
                        self.status.configure(text="Selesai ✓")
                    else:
                        self.status.configure(text="Siap")
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

"""Antarmuka desktop (customtkinter): alur berbasis proyek ala editor klip profesional."""
from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import colorchooser, filedialog, messagebox

import customtkinter as ctk

from . import __version__, encoders, library, settings as settings_mod
from .models import Style
from .pipeline import Cancelled, Pipeline, Project
from .presets import PRESETS
from .subtitles import list_fonts
from .textproc import fmt_time

# ---- tema -------------------------------------------------------------------------------
BG, SIDEBAR, CARD, BORDER = "#0E1016", "#141722", "#1A1E2C", "#272C40"
FIELD, ACCENT, ACCENT_H = "#11141D", "#7C5CFF", "#6A49F2"
TEXT, MUTED = "#E9ECF5", "#8B91A8"
OK, WARN, DANGER = "#2ECC8F", "#F5B942", "#F0506E"
UI = "Segoe UI" if os.name == "nt" else "Helvetica"

ANIMS = {"Pop Zoom": "pop", "Karaoke Box": "karaoke", "Glow": "glow", "Penekanan": "emphasis",
         "Kata Kunci": "keyword", "Polos": "plain"}
LAYOUTS = {"Face Tracking": "face", "Split Cam": "split", "Crop Tengah": "center", "Fit + Blur": "blur"}
HOOKS = {"Kuning": "yellow", "Merah": "red", "Outline": "outline"}
RES = {"9:16  1080 x 1920": (1080, 1920), "9:16  720 x 1280 (cepat)": (720, 1280),
       "1:1  1080 x 1080": (1080, 1080), "16:9  1920 x 1080": (1920, 1080)}
LANGS = {"Tanpa terjemahan": "", "Indonesia": "id", "English": "en", "Espa\u00f1ol": "es", "Portugu\u00eas": "pt",
         "Fran\u00e7ais": "fr", "Deutsch": "de", "\u65e5\u672c\u8a9e": "ja", "\ud55c\uad6d\uc5b4": "ko", "\u4e2d\u6587": "zh",
         "\u0627\u0644\u0639\u0631\u0628\u064a\u0629": "ar", "\u0939\u093f\u0928\u094d\u0926\u0940": "hi", "\u0420\u0443\u0441\u0441\u043a\u0438\u0439": "ru",
         "T\u00fcrk\u00e7e": "tr", "\u0e44\u0e17\u0e22": "th", "Ti\u1ebfng Vi\u1ec7t": "vi", "Melayu": "ms", "Italiano": "it",
         "Nederlands": "nl"}
SRC_LANGS = ["auto", "id", "en", "es", "pt", "fr", "de", "ja", "ko", "zh", "ar", "hi", "ru", "tr", "th", "vi", "ms"]
COLOR_FIELDS = [("Isi", "sub_fill"), ("Aktif", "sub_active"), ("Stroke dalam", "sub_inner"),
                ("Stroke luar", "sub_outer"), ("Kotak", "sub_box"), ("Glow", "sub_glow"),
                ("Kata kunci", "keyword_color")]
PAGES = [("home", "Beranda"), ("clips", "Klip"), ("style", "Template"), ("render", "Ekspor"),
         ("settings", "Pengaturan")]
POSATTR = {"sub": "sub_pos", "hook": "hook_pos", "logo": "logo_pos", "badge": "badge_pos", "mark": "wm_pos"}
PW, PH = 252, 448   # ukuran kanvas pratinjau
THUMB = (126, 224)


def inv(d, v):
    return next((k for k, x in d.items() if x == v), next(iter(d)))


def font(size=13, weight="normal"):
    return ctk.CTkFont(family=UI, size=size, weight=weight)


def parse_time(s: str, default: float) -> float:
    """'83.5' atau '1:23.5' -> detik."""
    try:
        parts = [float(x) for x in s.strip().split(":")]
    except ValueError:
        return default
    t = 0.0
    for p in parts:
        t = t * 60 + p
    return t


def open_path(p: Path) -> None:
    if os.name == "nt":
        os.startfile(str(p))  # noqa
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(p)])
    else:
        subprocess.Popen(["xdg-open", str(p)])


class App(ctk.CTk):
    def __init__(self):
        super().__init__(fg_color=BG)
        ctk.set_appearance_mode("dark")
        self.title(f"Clipper {__version__}")
        self.geometry("1360x860")
        self.minsize(1200, 780)
        self.cfg = settings_mod.load()
        self.st = self.cfg.style
        self.proj: Project | None = None
        self.q: queue.Queue = queue.Queue()
        self.worker: threading.Thread | None = None
        self.pipe: Pipeline | None = None
        self.clip_rows: list = []
        self.thumbs: dict = {}
        self._face_det = None
        self.grid_target = tk.StringVar(value="sub")
        self.color_btns, self.sv, self.nav, self.pages = {}, {}, {}, {}
        self.preview_bg = None
        self._log_open = False
        self._build()
        self.show("home")
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
        ctk.CTkLabel(brand, text="\u2702", width=40, height=40, corner_radius=12, fg_color=ACCENT,
                     text_color="white", font=font(20, "bold")).pack(side="left")
        tb = ctk.CTkFrame(brand, fg_color="transparent")
        tb.pack(side="left", padx=12)
        ctk.CTkLabel(tb, text="Clipper", font=font(20, "bold"), text_color=TEXT, anchor="w").pack(anchor="w")
        ctk.CTkLabel(tb, text="AI Video Clipper", font=font(11), text_color=MUTED, anchor="w").pack(anchor="w")
        icons = {"home": "\u2302", "clips": "\u25b6", "style": "\u270e", "render": "\u21e9", "settings": "\u2699"}
        for key, title in PAGES:
            if key == "settings":
                ctk.CTkFrame(side, height=1, fg_color=BORDER).pack(fill="x", padx=22, pady=(12, 8))
            b = ctk.CTkButton(side, text=f"  {icons[key]}   {title}", anchor="w", height=44, corner_radius=12,
                              font=font(14, "bold"), fg_color="transparent", hover_color="#1E2336",
                              text_color=MUTED, command=lambda k=key: self.show(k))
            b.pack(fill="x", padx=14, pady=2)
            self.nav[key] = b
        ctk.CTkLabel(side, text="").pack(expand=True)
        self.side_proj = ctk.CTkLabel(side, text="Belum ada proyek", font=font(11), text_color=MUTED,
                                      wraplength=190, justify="left")
        self.side_proj.pack(padx=22, pady=(0, 6), anchor="w")
        ctk.CTkLabel(side, text=f"v{__version__}  \u2022  proses lokal & privat", font=font(11),
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
        for key, _ in PAGES:
            pg = ctk.CTkScrollableFrame(host, fg_color="transparent", scrollbar_button_color=BORDER,
                                        scrollbar_button_hover_color=ACCENT)
            pg.grid(row=0, column=0, sticky="nsew")
            pg.grid_columnconfigure(0, weight=1)
            self.pages[key] = pg
        self._page_home(self.pages["home"])
        self._page_clips(self.pages["clips"])
        self._page_style(self.pages["style"])
        self._page_render(self.pages["render"])
        self._page_settings(self.pages["settings"])

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
        ctk.CTkButton(bar, text="Log \u25be", width=64, height=30, corner_radius=8, font=font(12),
                      fg_color="#222740", hover_color="#2B3150", command=self._toggle_log).grid(row=0, column=3, padx=(4, 14))
        self.log = ctk.CTkTextbox(bar, height=150, fg_color=FIELD, text_color="#B9C0D8", corner_radius=10,
                                  font=ctk.CTkFont(family="Consolas" if os.name == "nt" else "Courier", size=12))
        self.log.configure(state="disabled")

    def show(self, key):
        for k, pg in self.pages.items():
            pg.grid() if k == key else pg.grid_remove()
        for k, b in self.nav.items():
            on = k == key
            b.configure(fg_color=ACCENT if on else "transparent", text_color="white" if on else MUTED,
                        hover_color=ACCENT_H if on else "#1E2336")
        self.h_title.configure(text=dict(PAGES)[key])
        self.h_sub.configure(text={
            "home": "Tempel link video panjang, AI memilih momen terbaik dan membuat klip siap posting.",
            "clips": "Tinjau klip, atur durasi, cek pratinjau, lalu pilih yang akan diekspor.",
            "style": "Template merek: subtitle, hook, logo, dan efek. Simpan agar bisa dipakai ulang.",
            "render": "Opsi akhir lalu ekspor semua klip terpilih beserta thumbnail.",
            "settings": "API key, model transkripsi, folder output, dan pemeliharaan."}[key])
        if key == "home":
            self._fill_recent()

    def _toggle_log(self, force=None):
        self._log_open = (not self._log_open) if force is None else force
        if self._log_open:
            self.log.grid(row=1, column=0, columnspan=4, sticky="ew", padx=14, pady=(0, 14))
        else:
            self.log.grid_forget()

    # ================================================================ komponen
    def card(self, parent, title, sub="", row=0, col=0, span=1, pady=(0, 16)):
        f = ctk.CTkFrame(parent, fg_color=CARD, corner_radius=16, border_width=1, border_color=BORDER)
        f.grid(row=row, column=col, columnspan=span, sticky="ew", pady=pady)
        if title:
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

    def entry(self, p, var, ph="", show=None, height=38, width=None):
        kw = {"width": width} if width else {}
        return ctk.CTkEntry(p, textvariable=var, placeholder_text=ph, show=show, height=height, corner_radius=10,
                            fg_color=FIELD, border_color=BORDER, text_color=TEXT, font=font(13), **kw)

    def combo(self, p, var, values):
        return ctk.CTkComboBox(p, variable=var, values=values, height=38, corner_radius=10, fg_color=FIELD,
                               border_color=BORDER, button_color=BORDER, button_hover_color=ACCENT,
                               dropdown_fg_color=CARD, font=font(13))

    def menu(self, p, var, values, **kw):
        return ctk.CTkOptionMenu(p, variable=var, values=values, height=38, corner_radius=10, fg_color=FIELD,
                                 button_color=BORDER, button_hover_color=ACCENT, dropdown_fg_color=CARD, font=font(13),
                                 text_color=TEXT, **kw)

    def seg(self, p, var, values):
        return ctk.CTkSegmentedButton(p, variable=var, values=values, height=36, corner_radius=10, fg_color=FIELD,
                                      selected_color=ACCENT, selected_hover_color=ACCENT_H, unselected_color=FIELD,
                                      unselected_hover_color="#1E2336", font=font(12, "bold"))

    def switch(self, p, text, var, command=None):
        return ctk.CTkSwitch(p, text=text, variable=var, font=font(13), text_color=TEXT, progress_color=ACCENT,
                             button_color="#fff", button_hover_color="#ddd", fg_color=BORDER, command=command)

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

    # ================================================================ beranda
    def _page_home(self, pg):
        c = self.cfg
        hero = ctk.CTkFrame(pg, fg_color=CARD, corner_radius=20, border_width=1, border_color=BORDER)
        hero.grid(row=0, column=0, sticky="ew", pady=(0, 16))
        hero.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(hero, text="Ubah video panjang jadi klip viral", font=font(24, "bold"), text_color=TEXT,
                     anchor="w").grid(row=0, column=0, columnspan=2, sticky="w", padx=28, pady=(26, 0))
        ctk.CTkLabel(hero, text="Tempel link YouTube atau pilih file. Transkripsi berjalan di komputer Anda.",
                     font=font(13), text_color=MUTED, anchor="w").grid(row=1, column=0, columnspan=2, sticky="w", padx=28, pady=(2, 16))
        self.v_src = tk.StringVar(value=c.last_source)
        self.entry(hero, self.v_src, "https://www.youtube.com/watch?v=...", height=52).grid(
            row=2, column=0, sticky="ew", padx=(28, 12))
        self.btn_an = self.btn(hero, "\u25b6  Buat Klip", self._analyze, "primary", width=170, height=52)
        self.btn_an.grid(row=2, column=1, padx=(0, 28))
        sub = ctk.CTkFrame(hero, fg_color="transparent")
        sub.grid(row=3, column=0, columnspan=2, sticky="w", padx=28, pady=(12, 0))
        self.btn(sub, "Pilih file video...", self._pick_video, width=150).pack(side="left", padx=(0, 10))
        self.btn(sub, "Muat list_clip.json", self._load_cache, width=160).pack(side="left", padx=(0, 18))
        self.v_adv = tk.BooleanVar(value=False)
        self.switch(sub, "Opsi lanjutan", self.v_adv, self._toggle_adv).pack(side="left")
        self.adv = ctk.CTkFrame(hero, fg_color="transparent")
        self.adv.grid_columnconfigure((0, 1, 2), weight=1, uniform="a")
        self.v_n, self.v_min, self.v_max = (tk.StringVar(value=str(x)) for x in (c.clip_count, c.min_sec, c.max_sec))
        self.field(self.adv, "Jumlah klip", self.entry(self.adv, self.v_n), 0, 0)
        self.field(self.adv, "Durasi min (detik)", self.entry(self.adv, self.v_min), 0, 1)
        self.field(self.adv, "Durasi maks (detik)", self.entry(self.adv, self.v_max), 0, 2)
        self.v_lang = tk.StringVar(value=c.language)
        self.field(self.adv, "Bahasa ucapan di video", self.combo(self.adv, self.v_lang, SRC_LANGS), 1, 0)
        self.v_tpl_home = tk.StringVar(value="(template saat ini)")
        self.tpl_menu_home = self.menu(self.adv, self.v_tpl_home, ["(template saat ini)"] + library.list_templates())
        self.field(self.adv, "Template merek", self.tpl_menu_home, 1, 1, 2)
        ctk.CTkLabel(self.adv, text="Prompt kustom  (opsional, mis. \"cari momen lucu\" atau \"bagian tentang uang\")",
                     font=font(12), text_color=MUTED, anchor="w").grid(row=4, column=0, columnspan=3, sticky="w", pady=(10, 3))
        self.prompt = ctk.CTkTextbox(self.adv, height=64, fg_color=FIELD, border_width=1, border_color=BORDER,
                                     corner_radius=10, font=font(13), text_color=TEXT)
        self.prompt.grid(row=5, column=0, columnspan=3, sticky="ew", padx=(0, 14), pady=(0, 6))
        self.prompt.insert("1.0", c.clip_prompt)
        ctk.CTkFrame(hero, height=18, fg_color="transparent").grid(row=5, column=0)

        self.recent_card = ctk.CTkFrame(pg, fg_color=CARD, corner_radius=16, border_width=1, border_color=BORDER)
        self.recent_card.grid(row=1, column=0, sticky="ew")
        self.recent_body = None
        self._fill_recent()

    def _toggle_adv(self):
        if self.v_adv.get():
            self.adv.grid(row=4, column=0, columnspan=2, sticky="ew", padx=28, pady=(8, 0))
        else:
            self.adv.grid_remove()

    def _fill_recent(self):
        for w in self.recent_card.winfo_children():
            w.destroy()
        ctk.CTkLabel(self.recent_card, text="Proyek terbaru", font=font(15, "bold"), text_color=TEXT,
                     anchor="w").pack(anchor="w", padx=22, pady=(18, 6))
        items = library.list_projects()[:8]
        if not items:
            ctk.CTkLabel(self.recent_card, text="Belum ada proyek. Klip yang Anda buat akan muncul di sini.",
                         font=font(13), text_color=MUTED).pack(anchor="w", padx=22, pady=(4, 22))
            return
        for it in items:
            row = ctk.CTkFrame(self.recent_card, fg_color=FIELD, corner_radius=12)
            row.pack(fill="x", padx=18, pady=5)
            row.grid_columnconfigure(0, weight=1)
            ctk.CTkLabel(row, text=it["name"][:70], font=font(13, "bold"), text_color=TEXT, anchor="w").grid(
                row=0, column=0, sticky="w", padx=16, pady=(10, 0))
            when = time.strftime("%d %b %Y, %H:%M", time.localtime(it.get("updated", 0)))
            ctk.CTkLabel(row, text=f"{it['clips']} klip  \u2022  {when}", font=font(11), text_color=MUTED,
                         anchor="w").grid(row=1, column=0, sticky="w", padx=16, pady=(0, 10))
            self.btn(row, "Buka", lambda lf=it["list_file"]: self._open_project(lf), width=80, height=34).grid(
                row=0, column=1, rowspan=2, padx=14)
        ctk.CTkFrame(self.recent_card, height=12, fg_color="transparent").pack()

    def _open_project(self, list_file):
        try:
            self.proj = Pipeline.load_cache(Path(list_file))
        except Exception as e:
            messagebox.showerror("Clipper", f"Gagal membuka proyek:\n{e}")
            return
        self._after_project()

    # ================================================================ klip
    def _page_clips(self, pg):
        top = ctk.CTkFrame(pg, fg_color="transparent")
        top.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        self.btn(top, "Pilih semua", lambda: self._sel_all(True), width=110).pack(side="left", padx=(0, 8))
        self.btn(top, "Kosongkan", lambda: self._sel_all(False), width=100).pack(side="left", padx=(0, 8))
        self.btn(top, "Simpan perubahan", self._save_clips, width=150).pack(side="left", padx=(0, 8))
        self.btn(top, "Ekspor terpilih \u2192", lambda: self.show("render"), "primary", width=150).pack(side="left")
        self.clip_info = ctk.CTkLabel(top, text="", font=font(12), text_color=MUTED)
        self.clip_info.pack(side="left", padx=14)
        self.clip_host = ctk.CTkFrame(pg, fg_color="transparent")
        self.clip_host.grid(row=1, column=0, sticky="ew")
        self.clip_host.grid_columnconfigure(0, weight=1)
        self._fill_clips()

    def _thumb(self, clip):
        key = (str(self.proj.video), clip.id, round(clip.start, 1))
        if key in self.thumbs:
            return self.thumbs[key]
        img = None
        try:
            import cv2
            from PIL import Image
            cap = cv2.VideoCapture(str(self.proj.video))
            cap.set(cv2.CAP_PROP_POS_MSEC, (clip.start + min(1.5, clip.duration / 3)) * 1000)
            ok, fr = cap.read()
            cap.release()
            if ok:
                h, w = fr.shape[:2]
                cw = min(w, int(h * 9 / 16))
                cx = w / 2
                try:  # arahkan crop ke wajah terbesar agar thumbnail tidak menangkap sela kosong
                    if self._face_det is None:
                        from .face_track import FaceDetector
                        self._face_det = FaceDetector()
                    faces = self._face_det.detect(fr)
                    if faces:
                        fx, fy, fw, fh = max(faces, key=lambda b: b[2] * b[3])
                        cx = fx + fw / 2
                except Exception:
                    pass
                x0 = int(min(max(cx - cw / 2, 0), w - cw))
                im = Image.fromarray(cv2.cvtColor(fr[:, x0:x0 + cw], cv2.COLOR_BGR2RGB)).resize(THUMB)
                img = ctk.CTkImage(light_image=im, dark_image=im, size=THUMB)
        except Exception:
            img = None
        self.thumbs[key] = img
        return img

    def _fill_clips(self):
        for w in self.clip_host.winfo_children():
            w.destroy()
        self.clip_rows = []
        if not self.proj or not self.proj.clips:
            e = ctk.CTkFrame(self.clip_host, fg_color=CARD, corner_radius=16, border_width=1, border_color=BORDER)
            e.grid(row=0, column=0, sticky="ew")
            ctk.CTkLabel(e, text="Belum ada klip", font=font(16, "bold"), text_color=TEXT).pack(pady=(34, 4))
            ctk.CTkLabel(e, text="Buat klip dari halaman Beranda, atau buka proyek sebelumnya.",
                         font=font(13), text_color=MUTED).pack(pady=(0, 20))
            self.btn(e, "Ke Beranda", lambda: self.show("home"), "primary", width=140).pack(pady=(0, 34))
            self.clip_info.configure(text="")
            return
        for r, c in enumerate(self.proj.clips):
            card = ctk.CTkFrame(self.clip_host, fg_color=CARD, corner_radius=16, border_width=1, border_color=BORDER)
            card.grid(row=r, column=0, sticky="ew", pady=(0, 14))
            card.grid_columnconfigure(2, weight=1)
            sel = tk.BooleanVar(value=c.selected)
            ctk.CTkCheckBox(card, text="", variable=sel, width=26, checkbox_width=22, checkbox_height=22,
                            corner_radius=7, fg_color=ACCENT, hover_color=ACCENT_H, border_color=BORDER).grid(
                row=0, column=0, padx=(18, 8), pady=18, sticky="n")
            th = self._thumb(c)
            holder = ctk.CTkLabel(card, text="" if th else "tanpa\npratinjau", image=th, width=THUMB[0], height=THUMB[1],
                                  fg_color=FIELD, corner_radius=10, text_color=MUTED, font=font(11))
            holder.grid(row=0, column=1, padx=(0, 18), pady=16, sticky="n")
            mid = ctk.CTkFrame(card, fg_color="transparent")
            mid.grid(row=0, column=2, sticky="nsew", pady=14)
            mid.grid_columnconfigure((0, 1), weight=1, uniform="t")
            ctk.CTkLabel(mid, text=f"Klip {c.id}", font=font(15, "bold"), text_color=TEXT, anchor="w").grid(
                row=0, column=0, sticky="w")
            title, hook = tk.StringVar(value=c.title), tk.StringVar(value=c.hook)
            self.entry(mid, title, "Judul").grid(row=1, column=0, columnspan=2, sticky="ew", padx=(0, 14), pady=(6, 6))
            self.entry(mid, hook, "Hook / teks stop-scroll").grid(row=2, column=0, columnspan=2, sticky="ew", padx=(0, 14), pady=(0, 8))
            tr = ctk.CTkFrame(mid, fg_color="transparent")
            tr.grid(row=3, column=0, columnspan=2, sticky="w", pady=(2, 6))
            sv, ev = tk.StringVar(value=f"{c.start:.1f}"), tk.StringVar(value=f"{c.end:.1f}")
            ctk.CTkLabel(tr, text="Mulai", font=font(11), text_color=MUTED).pack(side="left")
            self.entry(tr, sv, width=84, height=32).pack(side="left", padx=(6, 14))
            ctk.CTkLabel(tr, text="Selesai", font=font(11), text_color=MUTED).pack(side="left")
            self.entry(tr, ev, width=84, height=32).pack(side="left", padx=(6, 14))
            ctk.CTkLabel(tr, text=f"{fmt_time(c.start)} \u2013 {fmt_time(c.end)}  \u2022  {c.duration:.0f} dtk",
                         font=font(11), text_color=MUTED).pack(side="left")
            if c.reason:
                ctk.CTkLabel(mid, text=c.reason, font=font(12), text_color=MUTED, anchor="w", wraplength=520,
                             justify="left").grid(row=4, column=0, columnspan=2, sticky="w", pady=(0, 6))
            self.btn(mid, "\u25b6  Pratinjau cepat", lambda cl=c: self._preview(cl), width=160, height=34).grid(
                row=5, column=0, sticky="w", pady=(4, 0))
            self._score_panel(card, c).grid(row=0, column=3, padx=(8, 20), pady=16, sticky="n")
            self.clip_rows.append((c, sel, title, hook, sv, ev))
        self.clip_info.configure(text=f"{len(self.proj.clips)} klip  \u2022  {self.proj.video.name}")

    def _score_panel(self, parent, c):
        f = ctk.CTkFrame(parent, fg_color=FIELD, corner_radius=14, width=190)
        col = OK if c.score >= 80 else WARN if c.score >= 60 else MUTED
        ctk.CTkLabel(f, text=f"{c.score:.0f}", font=font(34, "bold"), text_color=col).pack(padx=30, pady=(14, 0))
        ctk.CTkLabel(f, text="SKOR VIRAL", font=font(10, "bold"), text_color=MUTED).pack()
        if any((c.score_hook, c.score_flow, c.score_value, c.score_trend)):
            for label, v in (("Hook", c.score_hook), ("Alur", c.score_flow), ("Nilai", c.score_value), ("Tren", c.score_trend)):
                r = ctk.CTkFrame(f, fg_color="transparent")
                r.pack(fill="x", padx=16, pady=(8, 0))
                ctk.CTkLabel(r, text=label, font=font(11), text_color=MUTED, width=38, anchor="w").pack(side="left")
                pb = ctk.CTkProgressBar(r, height=6, progress_color=OK if v >= 75 else WARN if v >= 55 else MUTED,
                                        fg_color=BORDER, width=80)
                pb.set(max(0, min(1, v / 100)))
                pb.pack(side="left", padx=6)
                ctk.CTkLabel(r, text=f"{v:.0f}", font=font(11, "bold"), text_color=TEXT, width=24).pack(side="left")
        ctk.CTkFrame(f, height=14, fg_color="transparent").pack()
        return f

    def _sync_clips(self):
        for c, sel, title, hook, sv, ev in self.clip_rows:
            c.selected, c.title, c.hook = sel.get(), title.get(), hook.get()
            s, e = parse_time(sv.get(), c.start), parse_time(ev.get(), c.end)
            if e - s >= 3 and s >= 0:
                c.start, c.end = s, e

    def _sel_all(self, v):
        for row in self.clip_rows:
            row[1].set(v)

    def _save_clips(self):
        if not self.proj:
            return
        self._sync_clips()
        self.proj.save(self._params())
        self._log("list_clip.json disimpan.")

    def _params(self):
        c = self.cfg
        return {"count": c.clip_count, "min": c.min_sec, "max": c.max_sec, "model": c.gemini_model,
                "whisper": c.whisper_model, "prompt": c.clip_prompt.strip()}

    def _preview(self, clip):
        if not self.proj:
            return
        self._sync_clips()

        def job():
            self.pipe = Pipeline(self.cfg, self._log, self._prog)
            out = self.pipe.preview(self.proj, clip)
            self.q.put(("open", out))
        self._start(job)

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

        body = self.card(left, "Template merek", "Terapkan gaya siap pakai atau simpan gaya Anda sendiri.", 0)
        self.v_preset = tk.StringVar(value="Pilih template...")
        self.tpl_menu = self.menu(body, self.v_preset, self._tpl_names())
        self.field(body, "Terapkan", self.tpl_menu, 0, 0, 2)
        self.v_preset.trace_add("write", lambda *_: self._apply_preset())
        self.v_tplname = tk.StringVar()
        nm = ctk.CTkFrame(body, fg_color="transparent")
        nm.grid_columnconfigure(0, weight=1)
        self.entry(nm, self.v_tplname, "Nama template, mis. Channel Saya").grid(row=0, column=0, sticky="ew")
        self.btn(nm, "Simpan", self._save_tpl, "primary", width=90).grid(row=0, column=1, padx=(10, 0))
        self.btn(nm, "Hapus", self._del_tpl, "danger", width=80).grid(row=0, column=2, padx=(8, 14))
        self.field(body, "Simpan gaya saat ini sebagai", nm, 1, 0, 2)
        body = self.card(left, "Layout & subtitle", "", 1)
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
        self.slider(body, "Geser vertikal", V("sub_dy", tk.DoubleVar), -0.25, 0.25, 5, 0, None, "{:+.2f}")
        sw = ctk.CTkFrame(body, fg_color="transparent")
        sw.grid(row=11, column=0, columnspan=2, sticky="w", pady=(10, 0))
        self.switch(sw, "Subtitle aktif", V("sub_enabled", tk.BooleanVar)).pack(side="left", padx=(0, 26))
        self.switch(sw, "HURUF KAPITAL", V("sub_uppercase", tk.BooleanVar)).pack(side="left")
        cf = ctk.CTkFrame(body, fg_color="transparent")
        cf.grid(row=12, column=0, columnspan=2, sticky="w", pady=(16, 0))
        for i, (label, name) in enumerate(COLOR_FIELDS):
            cell = ctk.CTkFrame(cf, fg_color="transparent")
            cell.grid(row=0, column=i, padx=(0, 14))
            b = ctk.CTkButton(cell, text="", width=36, height=36, corner_radius=18, border_width=2,
                              border_color=BORDER, fg_color=getattr(s, name), hover_color=getattr(s, name),
                              command=lambda n=name: self._pick_color(n))
            b.pack()
            ctk.CTkLabel(cell, text=label, font=font(10), text_color=MUTED).pack(pady=(4, 0))
            self.color_btns[name] = b

        body = self.card(left, "Hook / headline awal", "Teks stop-scroll di beberapa detik pertama.", 2)
        sw = ctk.CTkFrame(body, fg_color="transparent")
        sw.grid(row=0, column=0, columnspan=2, sticky="w")
        self.switch(sw, "Tampilkan hook", V("hook_enabled", tk.BooleanVar)).pack(side="left", padx=(0, 26))
        self.switch(sw, "Voice-over AI (opsional)", V("hook_voice", tk.BooleanVar)).pack(side="left")
        self.v_hookstyle = tk.StringVar(value=inv(HOOKS, s.hook_style))
        self.field(body, "Gaya", self.seg(body, self.v_hookstyle, list(HOOKS)), 1, 0, 2)
        self.slider(body, "Ukuran hook", V("hook_size", tk.IntVar), 40, 140, 2, 0, 100)
        self.slider(body, "Durasi (detik)", V("hook_seconds", tk.DoubleVar), 1.5, 6, 2, 1, 9, "{:.1f}")

        body = self.card(left, "Branding teks", "Badge ajakan tonton video penuh & watermark nama channel.", 3)
        sw = ctk.CTkFrame(body, fg_color="transparent")
        sw.grid(row=0, column=0, columnspan=2, sticky="w")
        self.switch(sw, "Badge 'WATCH FULL VIDEO'", V("badge_enabled", tk.BooleanVar)).pack(side="left", padx=(0, 26))
        self.switch(sw, "Watermark teks", V("wm_enabled", tk.BooleanVar)).pack(side="left")
        self.field(body, "Teks badge", self.entry(body, V("badge_text"), "WATCH FULL VIDEO"), 1, 0)
        self.field(body, "Nama channel (di badge)", self.entry(body, V("badge_sub"), "Nama Channel"), 1, 1)
        self.field(body, "Teks watermark", self.entry(body, V("wm_text"), "NAMA CHANNEL+"), 2, 0)
        self.slider(body, "Opasitas watermark", V("wm_opacity", tk.DoubleVar), 0.1, 1.0, 2, 1, None, "{:.2f}")
        self.slider(body, "Ukuran watermark", V("wm_size", tk.IntVar), 24, 120, 3, 0, 96)

        body = self.card(left, "Logo & efek", "", 4)
        lf = ctk.CTkFrame(body, fg_color="transparent")
        lf.grid_columnconfigure(0, weight=1)
        self.entry(lf, V("logo_path"), "(tanpa logo)").grid(row=0, column=0, sticky="ew")
        self.btn(lf, "Pilih logo...", self._pick_logo, width=120).grid(row=0, column=1, padx=(10, 14))
        self.field(body, "Logo / watermark", lf, 0, 0, 2)
        self.slider(body, "Ukuran logo", V("logo_scale", tk.DoubleVar), 0.05, 0.4, 1, 0, None, "{:.2f}")
        self.slider(body, "Opasitas logo", V("logo_opacity", tk.DoubleVar), 0.2, 1.0, 1, 1, None, "{:.2f}")
        fx = ctk.CTkFrame(body, fg_color="transparent")
        fx.grid(row=6, column=0, columnspan=2, sticky="w", pady=(14, 0))
        for i, (label, name) in enumerate((("Zoom punch-in", "fx_punch"), ("Potong shot (close-up)", "fx_shots"), ("Slow zoom", "fx_slowzoom"),
                                           ("Progress bar", "fx_progress"), ("Fade in/out", "fx_fade"),
                                           ("Color grade", "fx_grade"), ("Vignette", "fx_vignette"))):
            self.switch(fx, label, V(name, tk.BooleanVar)).grid(row=i // 3, column=i % 3, sticky="w", padx=(0, 28), pady=6)

        # --- pratinjau berbingkai ponsel
        right = ctk.CTkFrame(pg, fg_color=CARD, corner_radius=16, border_width=1, border_color=BORDER)
        right.grid(row=0, column=1, sticky="n")
        ctk.CTkLabel(right, text="Pratinjau", font=font(15, "bold"), text_color=TEXT).pack(pady=(18, 0))
        ctk.CTkLabel(right, text="Klik sel untuk memindahkan", font=font(12), text_color=MUTED).pack(pady=(0, 10))
        self.target_var = tk.StringVar(value="Subtitle")
        sg = ctk.CTkSegmentedButton(right, values=["Subtitle", "Hook", "Logo", "Badge", "Mark"], variable=self.target_var, height=34,
                                    fg_color=FIELD, selected_color=ACCENT, selected_hover_color=ACCENT_H,
                                    unselected_color=FIELD, font=font(12, "bold"),
                                    command=lambda v: (self.grid_target.set({"Subtitle": "sub", "Hook": "hook", "Logo": "logo", "Badge": "badge", "Mark": "mark"}[v]),
                                                       self._draw_preview()))
        sg.pack(padx=18)
        self.cv = tk.Canvas(right, width=PW + 24, height=PH + 24, bg=CARD, highlightthickness=0)
        self.cv.pack(padx=18, pady=(14, 8))
        self.cv.bind("<Button-1>", self._on_canvas)
        self.cap = ctk.CTkLabel(right, text="", font=font(11), text_color=MUTED)
        self.cap.pack(pady=(0, 18))
        for name in ("sub_size", "hook_size", "logo_scale", "sub_uppercase", "badge_text", "badge_sub", "wm_text", "wm_size"):
            self.sv[name].trace_add("write", lambda *_: self._draw_preview())
        for v in (self.v_anim, self.v_hookstyle):
            v.trace_add("write", lambda *_: self._draw_preview())
        self.after(250, self._draw_preview)

    def _tpl_names(self):
        return list(PRESETS) + [f"\u2605 {n}" for n in library.list_templates()]

    def _refresh_tpl_menus(self):
        names = self._tpl_names()
        self.tpl_menu.configure(values=names)
        self.tpl_menu_home.configure(values=["(template saat ini)"] + library.list_templates())

    def _save_tpl(self):
        name = self.v_tplname.get().strip()
        if not name:
            messagebox.showwarning("Clipper", "Isi nama template dulu.")
            return
        self._collect()
        library.save_template(name, self.st)
        self._refresh_tpl_menus()
        self._log(f"Template '{name}' disimpan.")

    def _del_tpl(self):
        name = self.v_preset.get().lstrip("\u2605 ").strip() or self.v_tplname.get().strip()
        if name in library.list_templates() and messagebox.askyesno("Clipper", f"Hapus template '{name}'?"):
            library.delete_template(name)
            self._refresh_tpl_menus()

    def _apply_preset(self):
        name = self.v_preset.get()
        if name.startswith("\u2605 "):
            new = library.load_template(name[2:])
        else:
            data = PRESETS.get(name)
            if data is None:
                return
            base = Style().to_dict() if name == "CapCut Klasik" else self.st.to_dict()
            if name == "CapCut Klasik":
                base.update({k: v for k, v in self.st.to_dict().items() if k.startswith(("logo", "out_", "fps", "badge", "wm"))})
            base.update(data)
            new = Style.from_dict(base)
        for k, v in new.to_dict().items():
            setattr(self.st, k, v)
        for k, v in self.sv.items():
            v.set(getattr(self.st, k))
        self.v_layout.set(inv(LAYOUTS, self.st.layout))
        self.v_anim.set(inv(ANIMS, self.st.sub_anim))
        self.v_hookstyle.set(inv(HOOKS, self.st.hook_style))
        for k, b in self.color_btns.items():
            b.configure(fg_color=getattr(self.st, k), hover_color=getattr(self.st, k))
        self._draw_preview()

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
        setattr(self.st, POSATTR[t],
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
        pos = getattr(s, POSATTR[t])
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
        sx, sy = ox + (s.sub_pos[0] + 0.5) / 3 * PW, oy + ((s.sub_pos[1] + 0.5) / 5 + float(self.sv["sub_dy"].get())) * PH
        fs = int(self.sv["sub_size"].get() * sc * 0.6)
        txt = "KATA AKTIF" if self.sv["sub_uppercase"].get() else "kata aktif"
        anim = ANIMS[self.v_anim.get()]
        if anim == "karaoke":
            c.create_rectangle(sx - PW * 0.2, sy - fs * 0.9, sx + PW * 0.2, sy + fs * 0.9, fill=s.sub_box, outline="")
        self._stroke_text(sx, sy, txt, fs, s.sub_active if anim in ("pop", "glow", "emphasis") else s.sub_fill,
                          s.sub_inner, s.sub_outer, max(1, s.sub_inner_w // 3), max(1, s.sub_outer_w // 3))
        # badge & watermark
        bx, by = ox + (s.badge_pos[0] + 0.5) / 3 * PW, oy + (s.badge_pos[1] + 0.5) / 5 * PH
        bx = {0: ox + 10, 1: bx - 52, 2: ox + PW - 114}[s.badge_pos[0]]
        c.create_rectangle(bx, by - 8, bx + 18, by + 8, fill="#E61A1A", outline="")
        c.create_polygon(bx + 6, by - 4, bx + 6, by + 4, bx + 12, by, fill="white")
        c.create_text(bx + 24, by - 4, text=(s.badge_text or "WATCH FULL VIDEO")[:18], fill="white", anchor="w", font=("Arial", 6, "bold"))
        c.create_text(bx + 24, by + 5, text=(s.badge_sub or "channel")[:18], fill="#D8D8D8", anchor="w", font=("Arial", 5))
        wx, wy = ox + (s.wm_pos[0] + 0.5) / 3 * PW, oy + (s.wm_pos[1] + 0.5) / 5 * PH
        c.create_text(wx, wy, text=(s.wm_text or "WATERMARK")[:16], fill="#C9CCD6", font=("Arial", max(int(s.wm_size * PW / 1080 * 0.75), 6), "bold"))
        # logo
        lx, ly = ox + (s.logo_pos[0] + 0.5) / 3 * PW, oy + (s.logo_pos[1] + 0.5) / 3 * PH
        ls = self.sv["logo_scale"].get() * PW
        c.create_oval(lx - ls / 2, ly - ls / 2, lx + ls / 2, ly + ls / 2, outline="#FFFFFF", dash=(3, 2))
        c.create_text(lx, ly, text="LOGO", fill="#FFFFFF", font=("Arial", 7, "bold"))
        self.cap.configure(text=f"Mengatur: {self.target_var.get()}  •  grid {cols}×{rows}")

    # ================================================================ ekspor
    def _page_render(self, pg):
        c, s = self.cfg, self.st
        body = self.card(pg, "Bahasa & AI", "Terjemahan & perapian memerlukan API key Gemini.", 0)
        self.v_tl = tk.StringVar(value=inv(LANGS, c.target_lang))
        self.field(body, "Terjemahkan judul, hook, caption & subtitle ke", self.menu(body, self.v_tl, list(LANGS)), 0, 0)
        self.v_res = tk.StringVar(value=inv(RES, (s.out_width, s.out_height)))
        self.field(body, "Resolusi", self.menu(body, self.v_res, list(RES)), 0, 1)
        self.v_polish = tk.BooleanVar(value=c.use_gemini_polish)
        self.switch(body, "Gemini SRT Optimizer \u2014 buang gumaman & perbaiki typo", self.v_polish).grid(
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
        self.v_comp = tk.BooleanVar(value=c.compile_clips)
        self.switch(body, "Buat juga video kompilasi gabungan (min. 2 klip)", self.v_comp).grid(
            row=4, column=0, sticky="w", pady=(14, 0))
        self.v_ctr = tk.DoubleVar(value=c.compile_transition)
        self.slider(body, "Durasi transisi antar klip (detik)", self.v_ctr, 0.1, 1.0, 3, 1, None, "{:.2f}")

        body = self.card(pg, "Audio tambahan & performa", "Musik latar, efek suara hook, volume suara asli, dan encoder GPU.", 2)
        V = self._var
        self.field(body, "Musik latar (opsional)", self._file_row(body, V("bgm_path"), "(tanpa musik)", [("Audio", "*.mp3 *.wav *.m4a *.aac *.ogg")]), 0, 0)
        self.field(body, "Efek suara hook (opsional)", self._file_row(body, V("sfx_path"), "(tanpa SFX)", [("Audio", "*.mp3 *.wav *.m4a *.aac *.ogg")]), 0, 1)
        self.slider(body, "Volume musik latar (%)", V("bgm_volume", tk.DoubleVar), 0, 60, 1, 0, None, "{:.0f}")
        self.slider(body, "Volume SFX (%)", V("sfx_volume", tk.DoubleVar), 0, 200, 1, 1, None, "{:.0f}")
        self.slider(body, "Volume suara asli (%)", V("voice_volume", tk.DoubleVar), 50, 200, 2, 0, None, "{:.0f}")
        self.v_enc = tk.StringVar(value=s.encoder)
        self.field(body, "Encoder video  (auto = GPU bila ada)", self.menu(body, self.v_enc, encoders.CHOICES), 2, 1)
        self.enc_info = ctk.CTkLabel(body, text="Klik untuk mendeteksi GPU...", font=font(11), text_color=MUTED, anchor="w")
        self.enc_info.grid(row=6, column=0, columnspan=2, sticky="w", pady=(8, 0))
        self.btn(body, "Deteksi GPU", self._detect_gpu, width=120, height=32).grid(row=7, column=0, sticky="w", pady=(6, 0))

        act = ctk.CTkFrame(pg, fg_color="transparent")
        act.grid(row=3, column=0, sticky="w", pady=(4, 20))
        self.btn_render = self.btn(act, "\u25b6  Ekspor Klip Terpilih", self._render, "primary", width=250, height=50)
        self.btn_render.pack(side="left", padx=(0, 12))
        self.btn_stop = self.btn(act, "Batalkan", self._stop, "danger", width=110, height=50)
        self.btn_stop.pack(side="left", padx=(0, 12))
        self.btn(act, "Buka folder hasil", self._open_out, width=170, height=50).pack(side="left", padx=(0, 12))
        self.btn(act, "Kemas ZIP", self._make_zip, width=120, height=50).pack(side="left")

    def _file_row(self, parent, var, ph, types):
        f = ctk.CTkFrame(parent, fg_color="transparent")
        f.grid_columnconfigure(0, weight=1)
        self.entry(f, var, ph).grid(row=0, column=0, sticky="ew")
        self.btn(f, "Pilih", lambda: self._pick_file(var, types), width=70).grid(row=0, column=1, padx=(8, 0))
        return f

    def _pick_file(self, var, types):
        p = filedialog.askopenfilename(filetypes=types + [("Semua", "*.*")])
        if p:
            var.set(p)

    def _detect_gpu(self):
        self.enc_info.configure(text="Mendeteksi...")
        self.update_idletasks()

        def job():
            try:
                av = encoders.available()
                ok = [k.upper() for k, v in av.items() if v]
                self.q.put(("gpu", ("Terdeteksi: " + ", ".join(ok)) if ok else "Tidak ada GPU encoder yang bekerja; memakai CPU (libx264)."))
            except Exception as e:
                self.q.put(("gpu", f"Gagal mendeteksi: {e}"))
        threading.Thread(target=job, daemon=True).start()

    def _make_zip(self):
        if not self.proj or not (self.proj.dir / "clips").exists():
            messagebox.showinfo("Clipper", "Belum ada hasil ekspor untuk dikemas.")
            return
        z = Pipeline.zip_results(self.proj)
        self._log(f"ZIP dibuat: {z}")
        open_path(z.parent)

    # ================================================================ pengaturan
    def _page_settings(self, pg):
        c = self.cfg
        body = self.card(pg, "Kecerdasan buatan", "Gemini memilih klip, merapikan & menerjemahkan. Transkripsi berjalan lokal.", 0)
        self.v_key = tk.StringVar(value=c.api_key)
        self.field(body, "API Key Gemini  (gratis di aistudio.google.com/apikey)", self.entry(body, self.v_key, "AIza...", "\u2022"), 0, 0, 2)
        self.v_gmodel = tk.StringVar(value=c.gemini_model)
        self.field(body, "Model Gemini", self.combo(body, self.v_gmodel, ["gemini-2.5-flash", "gemini-2.5-pro", "gemini-2.0-flash"]), 1, 0)
        self.v_wh = tk.StringVar(value=c.whisper_model)
        self.field(body, "Model transkripsi (lokal)", self.combo(body, self.v_wh, ["tiny", "base", "small", "medium", "large-v3"]), 1, 1)
        body = self.card(pg, "Akses YouTube", "Jika YouTube menolak unduhan (bot check / video dibatasi usia), gunakan cookies atau proxy.", 1)
        self.v_ck = tk.StringVar(value=c.cookies_file)
        self.v_ckb = tk.StringVar(value=c.cookies_browser or "(tidak)")
        self.v_proxy = tk.StringVar(value=c.proxy)
        self.field(body, "File cookies (format Netscape)", self._file_row(body, self.v_ck, "(opsional)", [("Cookies", "*.txt")]), 0, 0)
        self.field(body, "atau ambil cookies dari browser", self.menu(body, self.v_ckb, ["(tidak)", "chrome", "edge", "firefox", "brave", "opera"]), 0, 1)
        self.field(body, "Proxy", self.entry(body, self.v_proxy, "http://user:pass@host:port (opsional)"), 1, 0, 2)
        body = self.card(pg, "Penyimpanan", "Hasil disimpan per proyek: klip, thumbnail, transkrip, dan list_clip.json.", 2)
        self.v_out = tk.StringVar(value=c.output_dir)
        out = ctk.CTkFrame(body, fg_color="transparent")
        out.grid_columnconfigure(0, weight=1)
        self.entry(out, self.v_out, "(default: folder 'Clipper_output' di samping video)").grid(row=0, column=0, sticky="ew")
        self.btn(out, "Pilih...", self._pick_out, width=90).grid(row=0, column=1, padx=(10, 14))
        self.field(body, "Folder output", out, 0, 0, 2)
        body = self.card(pg, "Pemeliharaan", "Jika unduhan YouTube ditolak, perbarui yt-dlp lalu coba lagi.", 3)
        self.btn(body, "Perbarui yt-dlp", self._update_ytdlp, width=160).grid(row=0, column=0, sticky="w")

    # ================================================================ pengaturan -> objek
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
        c.clip_prompt = self.prompt.get("1.0", "end").strip()
        c.output_dir = self.v_out.get().strip()
        c.cookies_file = self.v_ck.get().strip()
        c.cookies_browser = "" if self.v_ckb.get().startswith("(") else self.v_ckb.get()
        c.proxy = self.v_proxy.get().strip()
        c.target_lang = LANGS[self.v_tl.get()]
        c.use_gemini_polish, c.make_thumbnail = self.v_polish.get(), self.v_th.get()
        c.compile_clips, c.compile_transition = self.v_comp.get(), round(self.v_ctr.get(), 2)
        for name, v in self.sv.items():
            setattr(s, name, v.get())
        s.layout, s.sub_anim = LAYOUTS[self.v_layout.get()], ANIMS[self.v_anim.get()]
        s.hook_style = HOOKS[self.v_hookstyle.get()]
        s.out_width, s.out_height = RES[self.v_res.get()]
        s.encoder = self.v_enc.get()
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
        sel = self.v_tpl_home.get()
        if sel in library.list_templates():
            new = library.load_template(sel)
            for k, v in new.to_dict().items():
                setattr(self.st, k, v)
            for k, v in self.sv.items():
                v.set(getattr(self.st, k))
            self.v_layout.set(inv(LAYOUTS, self.st.layout))
            self.v_anim.set(inv(ANIMS, self.st.sub_anim))
            self.v_hookstyle.set(inv(HOOKS, self.st.hook_style))
            for k, b in self.color_btns.items():
                b.configure(fg_color=getattr(self.st, k), hover_color=getattr(self.st, k))

        def job():
            self.pipe = Pipeline(self.cfg, self._log, self._prog)
            self.q.put(("project", self.pipe.analyze(self.v_src.get())))
        self._toggle_log(True)
        self._start(job)

    def _load_cache(self):
        p = filedialog.askopenfilename(filetypes=[("list_clip.json", "list_clip.json"), ("JSON", "*.json")])
        if p:
            self._open_project(p)

    def _after_project(self):
        self.preview_bg = None
        self._fill_clips()
        self.side_proj.configure(text=f"Proyek: {self.proj.video.stem[:34]}")
        self.show("clips")
        self._draw_preview()

    def _render(self):
        if not self.proj:
            messagebox.showwarning("Clipper", "Belum ada klip. Buat klip atau buka proyek dulu.")
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
        open_path(d)

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
                    self._after_project()
                elif kind == "gpu":
                    self.enc_info.configure(text=data)
                elif kind == "open":
                    try:
                        open_path(data)
                    except Exception as e:
                        self._append_log(f"Tidak bisa membuka pratinjau: {e}")
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
                        self.status.configure(text="Selesai \u2713")
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

# Clipper — AI Video Clipper (aplikasi desktop / .exe)

Potong video panjang (podcast, wawancara, stream) menjadi klip vertikal 9:16 siap TikTok/Reels/Shorts —
tanpa langganan, tanpa batas kuota menit. Semua pemrosesan video berjalan **lokal**; hanya teks transkrip
yang dikirim ke Gemini (opsional, API key gratis dari <https://aistudio.google.com/apikey>).

## Fitur

| # | Fitur | Cara kerja |
|---|-------|-----------|
| 1 | **Natural Clip Selection** | Gemini memilih klip berdasarkan *nomor kalimat*, sehingga awal/akhir selalu di batas kalimat. Jaring pengaman lokal (`enforce_complete`) memajukan ujung klip sampai kalimat tuntas (tidak berakhir di "dan/tapi/karena…"). |
| 2 | **Smart Speaker Face Tracking** | `assets/face_detector.tflite` (MediaPipe) dipindai per-tile agar wajah kecil tetap terdeteksi; pembicara aktif dipilih dari gerak area mulut + histeresis; posisi crop distabilkan (median → deadband → Gaussian zero-phase) sehingga bebas getar. |
| 3 | **CapCut-style Double Stroke** | Subtitle ASS 2 lapis: stroke luar + stroke dalam + isi, warna & tebal bisa diatur. |
| 4 | **Animasi** | Pop Zoom per kata, Karaoke Highlight Box, Glow, Highlight Kata Kunci. |
| 5 | **Multi-Language** | Judul, hook, caption, hashtag, dan subtitle diterjemahkan (Gemini) dengan timing tetap sinkron. |
| 6 | **Gemini SRT Optimizer** | Buang gumaman/filler & perbaiki typo per kalimat, timing kata dipertahankan (difflib). |
| 7 | **Precision Grid** | Pratinjau interaktif: teks/hook grid 3×5, logo grid 3×3 — tinggal klik. |
| 8 | **Smart local cache** | `list_clip.json` + `transcript.json` per video; muat ulang tanpa transkrip/analisis ulang (hemat token). |
| 9 | **Pembahasan tuntas** | Lihat #1; durasi boleh melebihi batas maks (±25%) agar topik selesai. |
| 10 | **Potong jeda otomatis** | Jeda > ambang (default 0,45 s) dan filler "eee/aaa/emm/uh/um" dibuang dari video *dan* audio; subtitle ikut dipetakan ulang. |
| 11 | **Hook stop-scroll** | Headline animasi di awal + voice-over opsional (edge-tts, suara per bahasa). |
| 12 | **Thumbnail otomatis** | Frame terbaik (wajah jelas, tajam) + teks double stroke → 9:16 dan 16:9. |
| 14 | **Efek** | Zoom punch-in saat penekanan, slow zoom, progress bar, fade, color grade, vignette, latar blur. |

## Menjalankan dari source

```bash
python -m venv .venv && .venv\Scripts\activate      # Windows
pip install -r requirements.txt
# letakkan ffmpeg.exe & ffprobe.exe di assets/ffmpeg/ (atau pasang di PATH)
python run_clipper.py
```

## Membuat .exe

* **Windows lokal:** jalankan `build_exe.bat` → `dist\Clipper\Clipper.exe` (ffmpeg diunduh otomatis).
* **GitHub Actions:** *Actions → Build Clipper.exe → Run workflow*; unduh artifact `Clipper-windows`.

Pertama kali transkripsi, model Whisper diunduh otomatis (`small` ≈ 460 MB) ke `~/.clipper/models`.

## Alur pakai

1. **Sumber & Analisis**: tempel link YouTube atau pilih file, isi API key Gemini, klik *Analisis Video*.
2. **Klip**: centang klip, edit judul/hook.
3. **Tampilan & Efek**: gaya subtitle, warna, posisi (klik pratinjau), logo, efek.
4. **Render**: bahasa terjemahan, potong jeda, thumbnail → *Render Klip Terpilih*.

Hasil: `<output>/<nama video>/clips/*.mp4`, `*_thumb_*.jpg`, dan `*.txt` (judul, caption, hashtag).

## Catatan

* Tanpa API key, klip dipilih dengan heuristik lokal sederhana (tanpa terjemahan/optimizer).
* API key disimpan polos di `~/.clipper/settings.json`.
* Hook, subtitle, zoom, dan thumbnail menambah nilai transformatif, tetapi **tidak menjamin** video lolos
  kebijakan "konten berulang" platform. Gunakan hanya konten milik Anda atau yang berizin.

## Tes

```bash
pip install pytest && python -m pytest tests
```

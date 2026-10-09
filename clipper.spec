# -*- mode: python ; coding: utf-8 -*-
# Build: pyinstaller clipper.spec   (hasil: dist/Clipper/Clipper.exe)
from PyInstaller.utils.hooks import collect_all

datas, binaries, hiddenimports = [], [], []
for pkg in ("customtkinter", "mediapipe", "faster_whisper", "ctranslate2", "av", "tokenizers",
            "edge_tts", "yt_dlp", "google.genai", "huggingface_hub", "onnxruntime"):
    try:
        d, b, h = collect_all(pkg)
        datas += d; binaries += b; hiddenimports += h
    except Exception:
        pass

datas += [("assets", "assets")]   # face_detector.tflite, font, dan assets/ffmpeg/*.exe

a = Analysis(
    ["run_clipper.py"], pathex=["."], binaries=binaries, datas=datas,
    hiddenimports=hiddenimports, excludes=["matplotlib", "pytest", "IPython"],
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="Clipper", console=False,
          icon=None, disable_windowed_traceback=False)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="Clipper")

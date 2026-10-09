@echo off
REM Build Clipper.exe di Windows. Butuh Python 3.10-3.12 terpasang dan terhubung internet.
setlocal
if not exist .venv ( py -3.11 -m venv .venv || py -3 -m venv .venv )
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r requirements-dev.txt || goto :err

if not exist assets\ffmpeg\ffmpeg.exe (
  echo Mengunduh ffmpeg...
  mkdir assets\ffmpeg 2>nul
  powershell -NoProfile -Command "Invoke-WebRequest https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip -OutFile ffmpeg.zip; Expand-Archive ffmpeg.zip -DestinationPath ffmpeg_tmp -Force; Copy-Item ffmpeg_tmp\*\bin\ffmpeg.exe,ffmpeg_tmp\*\bin\ffprobe.exe assets\ffmpeg\; Remove-Item ffmpeg.zip,ffmpeg_tmp -Recurse -Force"
)
pyinstaller clipper.spec --noconfirm --clean || goto :err
echo.
echo SELESAI: dist\Clipper\Clipper.exe
exit /b 0
:err
echo BUILD GAGAL
exit /b 1

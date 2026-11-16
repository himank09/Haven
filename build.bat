@echo off
rem Build a standalone Windows app into dist\Haven\Haven.exe (no Python needed to run it).
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Run setup.bat first.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -m pip install -q pyinstaller
".venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean --windowed --name Haven ^
  --icon assets\icon.ico ^
  --add-data "haven\web;haven\web" --add-data "assets;assets" ^
  --collect-all pypdfium2 --collect-all pillow_heif --collect-all webview --collect-all imageio_ffmpeg ^
  --collect-submodules uvicorn --hidden-import clr ^
  app.py
if errorlevel 1 (
  echo Build failed.
  pause
  exit /b 1
)
echo.
echo Built: dist\Haven\Haven.exe
pause

@echo off
rem Start Haven from source (after setup.bat). Use run.bat debug to see errors in this window.
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Run setup.bat first.
  pause
  exit /b 1
)
if /i "%1"=="debug" (
  ".venv\Scripts\python.exe" app.py
  pause
) else (
  start "" ".venv\Scripts\pythonw.exe" app.py
)

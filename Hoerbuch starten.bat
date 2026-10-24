@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
    echo Die Python-Umgebung fehlt. Bitte zuerst das Projekt installieren.
    pause
    exit /b 1
)
".venv\Scripts\python.exe" -c "import PySide6" >nul 2>&1
if errorlevel 1 (
    echo Die Oberflaeche fehlt. Bitte einmal ausfuehren:
    echo .venv\Scripts\python.exe -m pip install -e ".[gui]"
    pause
    exit /b 1
)
start "" ".venv\Scripts\pythonw.exe" -m hoerbuch.gui

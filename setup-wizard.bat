@echo off
cd /d "%~dp0"
if exist ".venv\Scripts\pythonw.exe" (
    start "" ".venv\Scripts\pythonw.exe" "%~dp0scripts\setup_wizard.py"
) else (
    start "" pythonw "%~dp0scripts\setup_wizard.py"
)

@echo off
cd /d "%~dp0"
if exist ".venv\Scripts\pythonw.exe" (
    start "" ".venv\Scripts\pythonw.exe" "%~dp0scripts\die_mcp_console.py"
) else (
    start "" pythonw "%~dp0scripts\die_mcp_console.py"
)

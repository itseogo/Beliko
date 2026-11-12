@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Bitte zuerst install.bat ausfuehren.
  pause
  exit /b 1
)
echo Zum Beenden dieses Fenster schliessen oder Strg+C druecken.
.venv\Scripts\python run.py
pause

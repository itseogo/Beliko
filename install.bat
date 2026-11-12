@echo off
rem Installation unter Windows: legt eine eigene Python-Umgebung an und installiert die Pakete.
cd /d "%~dp0"
set PY=
py -3 --version >nul 2>nul && set PY=py -3
if "%PY%"=="" python --version >nul 2>nul && set PY=python
if "%PY%"=="" goto keinpython

%PY% -m venv .venv
if errorlevel 1 goto fehler
.venv\Scripts\python -m pip install --upgrade pip -q
.venv\Scripts\python -m pip install -r requirements.txt
if errorlevel 1 goto fehler

echo.
echo Installation fertig. Zum Starten die Datei start.bat doppelklicken.
pause
exit /b 0

:keinpython
echo Python wurde nicht gefunden. Bitte Python 3.10 oder neuer von python.org installieren
echo und dabei den Haken bei "Add python.exe to PATH" setzen. Danach diese Datei erneut starten.
pause
exit /b 1

:fehler
echo Die Installation ist fehlgeschlagen. Bitte die Meldungen oben ansehen.
pause
exit /b 1

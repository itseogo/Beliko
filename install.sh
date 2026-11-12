#!/usr/bin/env bash
# Installation: legt eine eigene Python-Umgebung an und installiert die Abhängigkeiten.
set -e
cd "$(dirname "$0")"

if ! command -v python3 >/dev/null; then
  echo "Python 3 fehlt. Installieren mit:  sudo apt install python3 python3-venv"; exit 1
fi
python3 - <<'PY' || { echo "Python 3.10 oder neuer wird benötigt."; exit 1; }
import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)
PY
python3 -m venv .venv 2>/dev/null || { echo "Das Modul venv fehlt. Installieren mit:  sudo apt install python3-venv"; exit 1; }
.venv/bin/pip install --quiet --upgrade pip
.venv/bin/pip install --quiet -r requirements.txt

cat > start.sh <<'EOS'
#!/usr/bin/env bash
cd "$(dirname "$0")"
exec .venv/bin/python run.py
EOS
chmod +x start.sh

echo
echo "Installation fertig."
if [ "$1" = "--service" ]; then
  sudo .venv/bin/python run.py install-service
else
  echo "Starten:               ./start.sh"
  echo "Mit Autostart:         ./install.sh --service"
fi

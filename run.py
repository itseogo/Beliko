#!/usr/bin/env python3
"""Startpunkt von BeLiKo (BestellLieferKontrolle).

  python run.py                    Server starten
  sudo python run.py install-service   als Systemdienst einrichten (Autostart, Linux)
"""
import os
import shutil
import socket
import subprocess
import sys
from pathlib import Path

HIER = Path(__file__).resolve().parent
sys.path.insert(0, str(HIER))


def lokale_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def install_service():
    if not hasattr(os, "geteuid"):
        sys.exit("Der Autostart-Dienst gibt es nur unter Linux. Unter Windows start.bat verwenden.")
    if os.geteuid() != 0:
        sys.exit("Bitte mit sudo starten:  sudo .venv/bin/python run.py install-service")
    if not shutil.which("systemctl"):
        sys.exit("systemd wurde nicht gefunden. Starte das Programm stattdessen mit ./start.sh")
    import pwd
    from einkauf import config
    user = os.environ.get("SUDO_USER") or "root"
    info = pwd.getpwnam(user)
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    for p in [config.DATA_DIR, *config.DATA_DIR.rglob("*")]:
        os.chown(p, info.pw_uid, info.pw_gid)
    port = int(config.load()["port"])
    caps = "AmbientCapabilities=CAP_NET_BIND_SERVICE\n" if port < 1024 else ""
    unit = f"""[Unit]
Description=BeLiKo (BestellLieferKontrolle)
After=network-online.target
Wants=network-online.target

[Service]
User={user}
WorkingDirectory={HIER}
Environment=EINKAUF_DATA={config.DATA_DIR}
ExecStart={sys.executable} {HIER / 'run.py'}
Restart=always
RestartSec=5
{caps}
[Install]
WantedBy=multi-user.target
"""
    Path("/etc/systemd/system/einkauf.service").write_text(unit)
    subprocess.run(["systemctl", "daemon-reload"], check=True)
    subprocess.run(["systemctl", "enable", "--now", "einkauf"], check=True)
    print(f"Dienst eingerichtet und gestartet. Aufruf im Browser: http://{lokale_ip()}:{port}")
    print("Status ansehen:  systemctl status einkauf    Protokoll:  journalctl -u einkauf -f")


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "install-service":
        return install_service()
    from waitress import serve
    from einkauf import create_app
    app = create_app()
    from einkauf import planer
    planer.starten(app)                      # automatischer Abruf der Lieferantendateien (je Lieferant einstellbar)
    cfg = app.extensions["cfg"]
    port = int(cfg["port"])
    print(f"BeLiKo läuft. Im Browser öffnen: http://{lokale_ip()}:{port}", flush=True)
    serve(app, host=cfg["host"], port=port, threads=6)


if __name__ == "__main__":
    main()

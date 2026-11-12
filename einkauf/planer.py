"""Kleiner Hintergrund-Planer: ruft Lieferantendateien automatisch ab (je Lieferant einstellbar)."""
import logging
import os
import threading
import time
from datetime import datetime, timedelta

from . import db, lieferantendateien
from .models import Supplier

log = logging.getLogger("beliko.planer")
_lock = threading.Lock()


def faellig(s, jetzt):
    if not s.active or not s.ugl_auto_min or s.ugl_auto_min <= 0 or lieferantendateien.pruefen(s):
        return False
    return s.ugl_letzter_abruf is None or jetzt - s.ugl_letzter_abruf >= timedelta(minutes=s.ugl_auto_min)


def tick(app, jetzt=None):
    """Ruft alle fälligen Lieferanten ab. Gibt die Zahl der abgerufenen Lieferanten zurück."""
    cfg = app.extensions["cfg"]
    if not cfg.get("setup_done"):
        return 0
    if app.extensions.get("SessionLocal") is None:
        try:
            db.init_db(app, cfg["db"])
        except Exception as e:                                  # z. B. NAS noch nicht erreichbar
            log.warning("Datenbank nicht erreichbar: %s", e)
            return 0
    jetzt = jetzt or datetime.now()
    n = 0
    # Die Entschlüsselung der Zugangsdaten braucht den Anwendungskontext (Schlüssel aus der Konfiguration).
    with _lock, app.app_context(), app.extensions["SessionLocal"]() as session:
        for s in session.query(Supplier).filter(Supplier.active.is_(True)).all():
            if not faellig(s, jetzt):
                continue
            try:
                lieferantendateien.abrufen(session, s)
            except lieferantendateien.AbrufFehler as e:
                log.warning("Abruf %s fehlgeschlagen: %s", s.name, e)
            session.commit()
            n += 1
    return n


def _lauf(app, pause):
    while True:
        time.sleep(pause)
        try:
            tick(app)
        except Exception:
            log.exception("Planer-Fehler")


def starten(app, pause=60):
    if os.environ.get("EINKAUF_KEIN_PLANER") == "1":
        return None
    t = threading.Thread(target=_lauf, args=(app, pause), daemon=True, name="beliko-planer")
    t.start()
    return t

"""Dienstprogramm zur Übertragung / Migration aller Daten zwischen SQLite und MariaDB.

Aufruf im Beliko-Verzeichnis:
  python -m einkauf.datenbank_kopieren
    -> Kopiert alle Tabellen und Daten aus einkauf-data/einkauf.db in die in config.json konfigurierte MariaDB.

  python -m einkauf.datenbank_kopieren --zurueck-zu-sqlite
    -> Setzt in config.json die Datenbank wieder auf SQLite zurück.
"""
import sys
from pathlib import Path
from sqlalchemy import create_engine, text

from . import config, db
from .models import Base


def daten_kopieren(src_engine, dst_engine, verbose=True):
    """Kopiert alle Daten aus src_engine in dst_engine."""
    db.migrate(dst_engine)

    with dst_engine.begin() as conn_dst:
        is_mysql = dst_engine.dialect.name in ("mysql", "mariadb")
        if is_mysql:
            conn_dst.execute(text("SET FOREIGN_KEY_CHECKS = 0"))

        # Zieltabelle leeren
        for t in reversed(Base.metadata.sorted_tables):
            conn_dst.execute(t.delete())

        # Daten übertragen
        total_rows = 0
        with src_engine.connect() as conn_src:
            for t in Base.metadata.sorted_tables:
                rows = [dict(r._mapping) for r in conn_src.execute(t.select())]
                if rows:
                    conn_dst.execute(t.insert(), rows)
                    total_rows += len(rows)
                    if verbose:
                        print(f"  ✓ {t.name}: {len(rows)} Zeile(n) kopiert")
                elif verbose:
                    print(f"  - {t.name}: 0 Zeilen (leer)")

        if is_mysql:
            conn_dst.execute(text("SET FOREIGN_KEY_CHECKS = 1"))

    return total_rows


def main():
    cfg = config.load()
    sqlite_datei = config.DATA_DIR / "einkauf.db"

    if "--zurueck-zu-sqlite" in sys.argv or "--sqlite" in sys.argv:
        print("Setze Datenbank in config.json zurück auf SQLite...")
        cfg["db"] = {"type": "sqlite"}
        config.save(cfg)
        print("✓ config.json aktualisiert. Bitte Dienst neustarten: sudo systemctl restart einkauf")
        return

    db_cfg = cfg.get("db")
    if not db_cfg or db_cfg.get("type") != "mariadb":
        print("Fehler: In config.json ist keine MariaDB konfiguriert.")
        print(f"Aktuelle Konfiguration: {db_cfg}")
        print("Möchtest du zurück zu SQLite? Dann starte: python -m einkauf.datenbank_kopieren --zurueck-zu-sqlite")
        sys.exit(1)

    if not sqlite_datei.exists():
        print(f"Fehler: Die SQLite-Datenbank wurde unter {sqlite_datei} nicht gefunden.")
        sys.exit(1)

    print(f"Quelle: SQLite ({sqlite_datei})")
    print(f"Ziel:   MariaDB ({db_cfg.get('user')}@{db_cfg.get('host')}:{db_cfg.get('port')}/{db_cfg.get('name')})")
    print("Starte Datenübertragung...")

    src_engine = create_engine(config.db_url({"type": "sqlite"}))
    dst_engine = create_engine(config.db_url(db_cfg))

    try:
        db.test_connection(db_cfg)
        gesamt = daten_kopieren(src_engine, dst_engine, verbose=True)
        print("--------------------------------------------------")
        print(f"ERFOLG! Insgesamt {gesamt} Datensätze nach MariaDB übertragen.")
        print("Deine Zugangsdaten und alle bisherigen Daten sind jetzt in MariaDB verfügbar.")
        print("Bitte starte den Dienst neu: sudo systemctl restart einkauf")
    except Exception as e:
        print(f"FEHLER bei der Datenübertragung: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()

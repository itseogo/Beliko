from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session, sessionmaker

from . import config
from .models import Base, Meta, NumberRange, Order

SCHEMA_VERSION = 12


def _spalten_ergaenzen(engine, tabelle, spalten):
    """Fügt fehlende Spalten zu einer bestehenden Tabelle hinzu (für Updates)."""
    vorhanden = {c["name"] for c in inspect(engine).get_columns(tabelle)}
    with engine.begin() as conn:
        for name, typ in spalten.items():
            if name not in vorhanden:
                conn.execute(text(f"ALTER TABLE {tabelle} ADD COLUMN {name} {typ} NULL"))


def migrate(engine):
    """Legt fehlende Tabellen an und führt Schema-Änderungen früherer Versionen aus."""
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        row = s.get(Meta, "schema_version")
        aktuell = int(row.value) if row else SCHEMA_VERSION
    if aktuell < 2:
        _spalten_ergaenzen(engine, "suppliers", {
            "ugl_server": "VARCHAR(255)", "ugl_port": "VARCHAR(10)",
            "ugl_pfad_eingang": "VARCHAR(500)", "ugl_pfad_ausgang": "VARCHAR(500)",
            "ugl_pfad_zugferd": "VARCHAR(500)",
        })
    if aktuell < 3:
        _spalten_ergaenzen(engine, "orders", {
            "status": "VARCHAR(20)", "bestellt_am": "DATE", "bezahlt_am": "DATE",
        })
        # Bestehende Bestellungen galten bisher als bestellt; Teillieferung/Komplett wird abgeleitet.
        with Session(engine) as s:
            for o in s.query(Order).all():
                if not o.status:
                    o.status = "bestellt"
                    o.bestellt_am = o.bestelldatum
                o.status_aktualisieren()
            s.commit()
    if aktuell < 4:
        _spalten_ergaenzen(engine, "orders", {"wunschtermin": "DATE"})
        _spalten_ergaenzen(engine, "order_items", {"kommission": "VARCHAR(300)", "hinweis": "VARCHAR(300)"})
    if aktuell < 5:
        # neue Tabellen (contacts, contact_persons, number_ranges) legt create_all an
        _spalten_ergaenzen(engine, "projects", {"contact_id": "INTEGER"})
    if aktuell < 6:
        _spalten_ergaenzen(engine, "number_ranges", {"muster": "VARCHAR(60)", "reset": "VARCHAR(10)", "periode": "VARCHAR(12)"})
        from . import nummern
        with Session(engine) as s:   # alte Einstellungen (Präfix/Trenner/Jahr/Stellen) in ein Muster umschreiben
            for r in s.query(NumberRange).all():
                if not r.muster:
                    teile = [t for t in (r.praefix, "YYYY" if r.mit_jahr else "") if t]
                    r.muster = (r.trenner or "").join(teile + ["X" * (r.stellen or 4)])
                    r.reset = "jahr" if r.mit_jahr else "nie"
                r.periode = nummern.periode(r)
            s.commit()
    if aktuell < 7:
        _spalten_ergaenzen(engine, "users", {"theme": "VARCHAR(10)"})
        _spalten_ergaenzen(engine, "suppliers", {
            "ids_url": "VARCHAR(500)", "ids_kndnr": "VARCHAR(50)", "ids_benutzer": "VARCHAR(100)",
            "ids_passwort_enc": "TEXT", "ids_version": "VARCHAR(10)", "ids_preis_modus": "VARCHAR(10)"})
        with engine.begin() as conn:
            conn.execute(text("UPDATE users SET theme = 'hell' WHERE theme IS NULL"))
            conn.execute(text("UPDATE suppliers SET ids_version = '2.5' WHERE ids_version IS NULL"))
            conn.execute(text("UPDATE suppliers SET ids_preis_modus = 'gesamt' WHERE ids_preis_modus IS NULL"))
            if engine.dialect.name in ("mysql", "mariadb"):   # Einzelpreise brauchen 4 Nachkommastellen (z. B. 0,0474 je Schraube)
                conn.execute(text("ALTER TABLE order_items MODIFY preis DECIMAL(12,4) NULL"))
    if aktuell < 8:
        _spalten_ergaenzen(engine, "suppliers", {"ids_aufruf": "VARCHAR(10)"})
        with engine.begin() as conn:
            conn.execute(text("UPDATE suppliers SET ids_aufruf = 'post' WHERE ids_aufruf IS NULL"))
    if aktuell < 10:
        # neue Tabelle supplier_files legt create_all an
        _spalten_ergaenzen(engine, "suppliers", {"ugl_auto_min": "INTEGER", "ugl_letzter_abruf": "DATETIME",
                                                  "ugl_abruf_status": "VARCHAR(300)", "ugl_tls_pruefen": "BOOLEAN"})
        with engine.begin() as conn:
            conn.execute(text("UPDATE suppliers SET ugl_tls_pruefen = 1 WHERE ugl_tls_pruefen IS NULL"))
    if aktuell < 11:
        # neue Tabellen lex_documents, lex_document_items, lex_article_rules legt create_all an
        _spalten_ergaenzen(engine, "suppliers", {"contact_id": "INTEGER"})
        _spalten_ergaenzen(engine, "projects", {"budget_modus": "VARCHAR(20)", "budget_faktor": "DECIMAL(6,3)"})
        with engine.begin() as conn:
            conn.execute(text("UPDATE projects SET budget_modus = 'manuell' WHERE budget_modus IS NULL"))
            conn.execute(text("UPDATE projects SET budget_faktor = 1.000 WHERE budget_faktor IS NULL"))
    if aktuell < 12:
        # neue Tabellen edit_locks, audit_logs, articles, supplier_invoices legt create_all an
        for tab in ("suppliers", "contacts", "projects", "orders", "lex_documents"):
            _spalten_ergaenzen(engine, tab, {"version": "INTEGER"})
            with engine.begin() as conn:
                conn.execute(text(f"UPDATE {tab} SET version = 1 WHERE version IS NULL"))
    with Session(engine) as s:
        row = s.get(Meta, "schema_version")
        if row is None:
            s.add(Meta(key="schema_version", value=str(SCHEMA_VERSION)))
        elif int(row.value) < SCHEMA_VERSION:
            row.value = str(SCHEMA_VERSION)
        s.commit()


def init_db(app, dbcfg):
    engine = create_engine(config.db_url(dbcfg), pool_pre_ping=True, pool_recycle=1800)
    migrate(engine)
    app.extensions["engine"] = engine
    app.extensions["SessionLocal"] = sessionmaker(engine, expire_on_commit=False)


def test_connection(dbcfg):
    engine = create_engine(config.db_url(dbcfg))
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    finally:
        engine.dispose()

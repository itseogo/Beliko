"""Test: Performance-Optimierung Artikelstamm & Lieferantenvergleich (Schema 16, Indizes, Fast Search)."""
import os, re, sys, tempfile
from decimal import Decimal

os.environ["EINKAUF_DATA"] = tempfile.mkdtemp(prefix="einkauf-speed-test-")
HIER = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HIER, ".."))
sys.path.insert(0, HIER)

from einkauf import create_app
from einkauf.models import Article, Supplier
from einkauf.views import _artikel_anzahl_je_lieferant, artikel_anzahl_cache_leeren
from sqlalchemy import inspect

app = create_app()
c = app.test_client()

tok = lambda h: re.search(r'name="_csrf" value="([^"]+)"', h).group(1)
def G(url): return c.get(url, follow_redirects=True).get_data(as_text=True)
def P(url, data, page=None):
    t = tok(c.get(page or url).get_data(as_text=True))
    return c.post(url, data=dict(data, _csrf=t), follow_redirects=True).get_data(as_text=True)

# 1. Setup
P("/setup/", {"type": "sqlite"})
P("/setup/admin", {"username": "admin", "firma": "Elektro Test GmbH", "password": "geheim1234", "password2": "geheim1234"})

# 2. Schema 16 & Indizes prüfen
with app.app_context():
    engine = app.extensions["engine"]
    insp = inspect(engine)
    idx_names = {ix["name"] for ix in insp.get_indexes("articles")}
    print(f"Vorhandene Indizes auf articles: {idx_names}")
    assert "ix_articles_hersteller_artnr" in idx_names
    assert "ix_articles_hersteller" in idx_names
    assert "ix_articles_sup_ean" in idx_names
    assert "ix_articles_sup_herstartnr" in idx_names
    assert "ix_articles_sup_artnr" in idx_names

# 3. Lieferanten und Artikel einfügen
P("/einstellungen/lieferanten/neu", {"name": "Fega&Schmidt", "active": "1"})
P("/einstellungen/lieferanten/neu", {"name": "Rexel", "active": "1"})

with app.app_context():
    SessionLocal = app.extensions["SessionLocal"]
    with SessionLocal() as db:
        s1 = db.query(Supplier).filter_by(name="Fega&Schmidt").first()
        s2 = db.query(Supplier).filter_by(name="Rexel").first()
        assert s1 and s2

        # Siemens Leitungsschutzschalter bei Fega
        a1 = Article(
            artikelnr="120462",
            bezeichnung="SIEM Leitungsschutzschalter",
            kurztext2="5SY4116-7 C16A 1polig 10kA",
            einheit="Stück",
            listenpreis=Decimal("32.10"),
            ean="4001869181394",
            hersteller="Siemens",
            hersteller_artnr="5SY4116-7",
            supplier_id=s1.id,
        )
        # Siemens Leitungsschutzschalter bei Rexel (gleiche EAN und Herst.-Artnr, andere Großhändler-Artnr)
        a2 = Article(
            artikelnr="2641482",
            bezeichnung="SIEM Leitungsschutzschalter",
            kurztext2="5SY4116-7",
            einheit="Stück",
            listenpreis=Decimal("29.90"),
            ean="4001869181394",
            hersteller="Siemens",
            hersteller_artnr="5SY4116-7",
            supplier_id=s2.id,
        )
        # Zweiter LS-Schalter ohne EAN, aber mit Hersteller-Artnr Match
        a3 = Article(
            artikelnr="120444",
            bezeichnung="SIEM Leitungsschutzschalter B16",
            kurztext2="5SY4116-6 B16A 1polig 10kA",
            einheit="Stück",
            listenpreis=Decimal("12.90"),
            ean=None,
            hersteller="Siemens",
            hersteller_artnr="5SY4116-6",
            supplier_id=s1.id,
        )
        a4 = Article(
            artikelnr="2641481",
            bezeichnung="SIEM Leitungsschutzschalter B16A",
            kurztext2="SIEMENSN 5SY4116-6",
            einheit="Stück",
            listenpreis=Decimal("11.50"),
            ean=None,
            hersteller="Siemens",
            hersteller_artnr="5SY4116-6",
            supplier_id=s2.id,
        )
        # Nur bei Fega vorhandener Einzelschalter
        a5 = Article(
            artikelnr="000156",
            bezeichnung="EATO Wendeschalter",
            kurztext2="T3-3-8401/Z",
            einheit="Stück",
            listenpreis=Decimal("106.39"),
            ean="4015080357391",
            hersteller="Eaton",
            hersteller_artnr="035739",
            supplier_id=s1.id,
        )
        db.add_all([a1, a2, a3, a4, a5])
        db.commit()

# Cache leeren für sauberen Test
artikel_anzahl_cache_leeren()

# 4. Test: Lieferantenvergleich mit Präfixsuche "5sy4116"
h_verg = G("/artikel?ansicht=vergleich&s1=1&s2=2&q=5sy4116")
assert "5SY4116-7" in h_verg
assert "32,10" in h_verg
assert "29,90" in h_verg
assert "5SY4116-6" in h_verg
assert "12,90" in h_verg
assert "11,50" in h_verg
# EATO Wendeschalter darf bei 5sy4116 nicht auftauchen
assert "EATO Wendeschalter" not in h_verg

# 5. Test: "Nur übereinstimmende Artikel" Checkbox
h_nur_gem = G("/artikel?ansicht=vergleich&s1=1&s2=2&nur_gemeinsame=1")
assert "5SY4116-7" in h_nur_gem
assert "EATO Wendeschalter" not in h_nur_gem

# 6. Test: Materialübersicht (Liste) mit Schnellsuche
h_liste_fast = G("/artikel?ansicht=liste&q=5sy4116")
assert "5SY4116-7" in h_liste_fast
assert "5SY4116-6" in h_liste_fast
assert "EATO" not in h_liste_fast

# 7. Test: Materialübersicht Teilstring-Fallback (Suche nach Begriff in Bezeichnung)
h_liste_sub = G("/artikel?ansicht=liste&q=Wendeschalter")
assert "EATO Wendeschalter" in h_liste_sub
assert "000156" in h_liste_sub
assert "5SY4116" not in h_liste_sub

# 8. Test: Cache-Funktion
with app.app_context():
    SessionLocal = app.extensions["SessionLocal"]
    with SessionLocal() as db:
        c1 = _artikel_anzahl_je_lieferant(db)
        assert c1.get(1) == 3
        assert c1.get(2) == 2
        artikel_anzahl_cache_leeren()

print("ALL SPEED AND MATCHING TESTS PASSED SUCCESSFULLY!")

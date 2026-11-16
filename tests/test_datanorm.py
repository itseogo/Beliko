"""Tests für Datanorm 4, Datanorm 5, reine Preis-Datanorm (Preispflege) und Kupferwerte."""
import io
import os
import re
import sys
import tempfile
from decimal import Decimal
from pathlib import Path

os.environ["EINKAUF_DATA"] = tempfile.mkdtemp(prefix="einkauf-test-")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from einkauf import create_app, datanorm, db
from einkauf.models import Article, Supplier, User

# Beispiel Rexel Datanorm 4 (aus Strukturaufschlüsselung.xlsx)
DN4_REXEL = (
    "A;N;2641481;00;SIEMENSN 5SY4116-6;Leitungsschutzschalter 230/400V 10kA, 1-;1;0;Stck;1190;8622;2\r\n"
    "B;N;2641481;5SY41166;5SY41166;;0;0;0;4001869181219;;2070;0;0\r\n"
    "A;N;1100386;00;KAB+LTG YSLY-JB 5X35;Steuerleitung mit farbigen Adern Schnitt;1;2;mtr;287644;0312;1\r\n"
    "B;N;1100386;YSLYJB5X35;;;1;150;16800;;;1080;0;0\r\n"
).encode("cp1252")

# Beispiel Fega Datanorm 5 (aus Strukturaufschlüsselung.xlsx)
DN5_FEGA = (
    "V;050;A;20250827;EUR;Artikelstammdaten;;;FEGA & Schmitt;Elektrogroßhandel GmbH;;Rettistr. 5;;;91522 Ansbach\r\n"
    "A;N;120462;SIEM Leitungsschutzschalter;5SY4116-7 C16A 1polig 10kA;STCK;1;1;2970;;37;20;5SY4116-7;;;;5SY4116-7;;4001869181394;;;;4;;;;;;1\r\n"
    "A;N;9381038;AMIC Kohlefilter;FWK124;STCK;1;1;2017;;12;39;1190623;;;;1190623;;5906006906238;;;;4;;;;;;1\r\n"
).encode("cp1252")

# Beispiel reine Preisdatei Datanorm (aus Strukturaufschlüsselung.xlsx Zeile 92-93)
DN_PREIS_FEGA = (
    "P;120462;1;1;3150\r\n"      # Neuer Listenpreis 31,50 €
    "P;9213174;1;100;480\r\n"     # Listenpreis 4,80 € / 100 Stk = 0,0480 €
    "P;9213174;2;100;322\r\n"     # EK-Preis 3,22 € / 100 Stk
).encode("cp1252")

# 1. Unit Tests für Datanorm-Einleser
r4 = datanorm.lesen(DN4_REXEL)
assert r4["is_dn5"] is False
assert len(r4["artikel"]) == 2

a1 = next(a for a in r4["artikel"] if a["artikelnr"] == "2641481")
assert a1["bezeichnung"] == "SIEMENSN 5SY4116-6"
assert a1["einheit"] == "Stück"
assert a1["listenpreis"] == Decimal("11.9000")
assert a1["ean"] == "4001869181219"

# Kabel mit PE 100 und Kupferwerten
kabel = next(a for a in r4["artikel"] if a["artikelnr"] == "1100386")
assert kabel["bezeichnung"] == "KAB+LTG YSLY-JB 5X35"
assert kabel["einheit"] == "m"
assert kabel["preiseinheit"] == 100
assert kabel["listenpreis"] == Decimal("28.7644")  # 287644 Cent pro 100m = 28,7644 € pro Meter!
assert kabel["kupfermerker"] == 1                  # 1 = pro 100m
assert kabel["kupferbasis"] == Decimal("150.000")  # 150 € / 100kg Basis
assert kabel["kupfergewicht"] == Decimal("16.800") # 16800 g = 16,8 kg Cu pro 100m

# 2. Datanorm 5 Fega
r5 = datanorm.lesen(DN5_FEGA)
assert r5["is_dn5"] is True
assert len(r5["artikel"]) == 2
f1 = next(a for a in r5["artikel"] if a["artikelnr"] == "120462")
assert f1["bezeichnung"] == "SIEM Leitungsschutzschalter"
assert f1["kurztext2"] == "5SY4116-7 C16A 1polig 10kA"
assert f1["einheit"] == "Stück"
assert f1["listenpreis"] == Decimal("29.7000")
assert f1["ean"] == "4001869181394"

# 3. Reine Preisdatei
rp = datanorm.lesen(DN_PREIS_FEGA)
assert rp["ist_reine_preisdatei"] is True
assert len(rp["preise"]) == 2
assert rp["preise"]["120462"]["listenpreis"] == Decimal("31.5000")
assert rp["preise"]["9213174"]["listenpreis"] == Decimal("0.0480")

# 4. Integrationstest mit Web-App
DB = {"type": "sqlite"}
app = create_app()
c = app.test_client()

def tok(html):
    return re.search(r'name="_csrf" value="([^"]+)"', html).group(1)

def get(url, **kw):
    return c.get(url, follow_redirects=True, **kw)

def post(url, data, page=None):
    t = tok(c.get(page or url).get_data(as_text=True))
    data = dict(data, _csrf=t)
    return c.post(url, data=data, follow_redirects=True)

# Setup
post("/setup/", DB)
post("/setup/admin", {"username": "admin", "firma": "Elektro Test", "password": "passwort123", "password2": "passwort123"})

# Lieferant anlegen
post("/einstellungen/lieferanten/neu", {"name": "Fega & Schmitt", "active": "1"})

# Schritt 1: Datanorm 5 Stamm importieren
t = tok(get("/artikel/import").get_data(as_text=True))
res = c.post("/artikel/import", data={
    "_csrf": t,
    "datei": (io.BytesIO(DN5_FEGA), "datanorm.001"),
    "supplier_id": "1",
    "modus": "auto",
}, follow_redirects=True).get_data(as_text=True)
assert "2 neue Artikel" in res
assert "120462" in res
assert "29,70" in res

# Schritt 2: Datanorm 4 Rexel importieren (Kabel mit Kupfer)
t = tok(get("/artikel/import").get_data(as_text=True))
res = c.post("/artikel/import", data={
    "_csrf": t,
    "datei": (io.BytesIO(DN4_REXEL), "datanorm.002"),
    "supplier_id": "1",
    "modus": "voll",
}, follow_redirects=True).get_data(as_text=True)
assert "YSLY-JB 5X35" in res
assert "28,76" in res
assert "16,8" in res or "Cu:" in res

# Schritt 3: Reine Preisdatei importieren (Preispflege)
t = tok(get("/artikel/import").get_data(as_text=True))
res = c.post("/artikel/import", data={
    "_csrf": t,
    "datei": (io.BytesIO(DN_PREIS_FEGA), "datpreis.001"),
    "supplier_id": "1",
    "modus": "nur_preise",
}, follow_redirects=True).get_data(as_text=True)
assert "Datanorm-Preispflege fertig" in res
assert "Preise aktualisiert" in res

# Prüfen, ob Preis von 120462 von 29,70 auf 31,50 aktualisiert wurde
with app.app_context():
    with app.extensions["SessionLocal"]() as s:
        art = s.query(Article).filter(Article.artikelnr == "120462").first()
        assert art is not None
        assert art.listenpreis == Decimal("31.5000")

print("DATANORM + PREISPFLEGE + KUPFER TESTS OK")

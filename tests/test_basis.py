"""Grundtest: Einrichtung, Rollen, Bestellstatus, Rückstand, Projekte (SQLite).
Aufruf: python tests/test_basis.py   (Datenbank per Umgebungsvariable TEST_DB=maria möglich, siehe CLAUDE.md)"""
import os, re, sys, tempfile
os.environ["EINKAUF_DATA"] = tempfile.mkdtemp(prefix="einkauf-test-")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

DB = ({"type": "mariadb", "host": "127.0.0.1", "port": "3306", "name": "einkauf", "user": "einkauf", "password": "T3stPw!x"}
      if os.environ.get("TEST_DB") == "maria" else {"type": "sqlite"})
from einkauf import create_app
app = create_app()
c = app.test_client()

def tok(html):
    return re.search(r'name="_csrf" value="([^"]+)"', html).group(1)

def get(url, **kw):
    r = c.get(url, follow_redirects=True, **kw); return r
def post(url, data, page=None):
    t = tok(c.get(page or url).get_data(as_text=True))
    data = dict(data, _csrf=t)
    return c.post(url, data=data, follow_redirects=True)

# 1 Setup-Sperre / Weiterleitung
r = c.get("/"); assert r.status_code == 302 and "/setup" in r.headers["Location"], r.headers
r = post("/setup/", DB)
assert "Schritt 2 von 2" in r.get_data(as_text=True), r.get_data(as_text=True)[:500]
r = post("/setup/admin", {"username": "chris", "password": "kurz", "password2": "kurz"})
assert "mindestens 6" in r.get_data(as_text=True)
r = post("/setup/admin", {"username": "chris", "firma": "Elektro Test", "password": "geheim1234", "password2": "geheim1234"})
assert "Einrichtung abgeschlossen" in r.get_data(as_text=True)
# nach Einrichtung: Setup gesperrt
r = c.get("/setup/"); assert r.status_code == 302 and r.headers["Location"].endswith("/")

# 2 Lieferant, Projekt
r = post("/einstellungen/lieferanten/neu", {"name": "Großhandel Müller", "kundennr": "4711", "ugl_verfahren": "sftp", "ugl_pfad": "sftp://x/y", "ugl_passwort": "geheimPW", "active": "1"})
assert "Lieferant angelegt" in r.get_data(as_text=True)
r = post("/projekte/neu", {"nummer": "P-001", "name": "Klimaanlage Koch", "kunde": "Koch", "status": "aktiv", "materialbudget": "1.200,50"})
assert "Projekt angelegt" in r.get_data(as_text=True), r.get_data(as_text=True)[:800]
r = post("/projekte/neu", {"nummer": "P-001", "name": "Doppelt"}, page="/projekte/neu")
assert "gibt es schon" in r.get_data(as_text=True)

# 3 Bestellung + Positionen
r = post("/bestellungen/neu", {"supplier_id": "1", "bestelldatum": "2026-10-20", "bestellnr": "B-1", "ab_nr": "AB-9"})
assert "Positionen" in r.get_data(as_text=True)
for bez, m, p, d in [("Außengerät 3,5kW", "1", "500,00", "2026-10-22"), ("Kältemittelleitung", "12", "4,50", "2026-11-05"), ("Kabel 5G1,5", "10", "", "")]:
    r = post("/bestellungen/1/position", {"bezeichnung": bez, "menge": m, "einheit": "Stück", "preis": p, "erw_lieferdatum": d, "project_id": "1"}, page="/bestellungen/1")
    assert "Position hinzugefügt" in r.get_data(as_text=True)

# 3b Neu: noch nicht im Rückstand, Baum zeigt Ordner
assert "0 Positionen im Rückstand" in get("/rueckstand").get_data(as_text=True)
h = get("/").get_data(as_text=True)
assert "Teillieferung" in h and "10 Oktober" in h and "Komplett" in h and "Abgeschlossen" in h
assert "steht noch auf" in get("/bestellungen/1").get_data(as_text=True)
r = post("/bestellungen/1/status", {"aktion": "bestellt"}, page="/bestellungen/1")
assert "als bestellt markiert" in r.get_data(as_text=True)
assert "Bestellt" in get("/bestellungen?status=bestellt").get_data(as_text=True)

# 4 Rückstand: alle 3 offen, erste überfällig (heute > 22.10.?)
r = get("/rueckstand"); h = r.get_data(as_text=True)
assert "3 Positionen im Rückstand" in h, re.sub(r"\s+", " ", h)[:1500]
assert 'class="ueberfaellig' in h

# 5 Teillieferung
r = post("/bestellungen/1/wareneingang", {"lieferschein_nr": "LS-1", "datum": "2026-10-25", "menge_1": "1", "menge_2": "5"}, page="/bestellungen/1")
assert "Wareneingang für 2 Positionen" in r.get_data(as_text=True) and "Status: Teillieferung" in r.get_data(as_text=True)
assert "Kältemittelleitung" in get("/bestellungen?status=teilgeliefert&jahr=2026&monat=10").get_data(as_text=True) or "Großhandel" in get("/bestellungen?status=teilgeliefert&jahr=2026&monat=10").get_data(as_text=True)
assert "Keine Bestellungen" in get("/bestellungen?status=teilgeliefert&jahr=2025").get_data(as_text=True)
h = get("/rueckstand").get_data(as_text=True)
assert "2 Positionen im Rückstand" in h
h1 = get("/bestellungen/1").get_data(as_text=True)
assert "Teilgeliefert" in h1
assert "Lieferschein &amp; Lieferdatum" in h1 or "Lieferschein" in h1
assert "LS-1" in h1
assert "25.10.2026" in h1

# 6 CSV
r = c.get("/rueckstand?csv=1"); assert r.status_code == 200 and "Kältemittelleitung" in r.get_data(as_text=True)
# 7 Projekt-Budget
h = get("/projekte?p=1&tab=uebersicht&status=alle").get_data(as_text=True)
assert "Rest vom Materialbudget" in h and "keinen Preis" in h

# 8 Alles buchen
r = post("/bestellungen/1/wareneingang", {"alles": "1", "datum": "2026-10-26"}, page="/bestellungen/1")
assert "0 Positionen im Rückstand" in get("/rueckstand").get_data(as_text=True)
assert "Status: Komplett geliefert" in r.get_data(as_text=True)
# Abschließen (bezahlt) und wieder öffnen
r = post("/bestellungen/1/status", {"aktion": "abschliessen", "bezahlt_am": "2026-10-27"}, page="/bestellungen/1")
assert "als bezahlt abgeschlossen" in r.get_data(as_text=True)
assert "Keine Bestellungen" in get("/bestellungen").get_data(as_text=True)          # Standardansicht: ohne Abgeschlossene
assert "Großhandel" in get("/bestellungen?status=abgeschlossen").get_data(as_text=True)
r = post("/bestellungen/1/status", {"aktion": "oeffnen"}, page="/bestellungen/1")
assert "wieder geöffnet" in r.get_data(as_text=True) and "Komplett geliefert" in r.get_data(as_text=True)
# Neue Position in komplette Bestellung -> wieder Teillieferung
r = post("/bestellungen/1/position", {"bezeichnung": "Nachbestellung", "menge": "2", "project_id": "1"}, page="/bestellungen/1")
assert "Teillieferung" in get("/bestellungen/1").get_data(as_text=True)
r = post("/bestellungen/1/status", {"aktion": "abschliessen"}, page="/bestellungen/1")
assert "nicht möglich" in r.get_data(as_text=True)

# 9 Benutzer: letzter Admin geschützt
r = post("/einstellungen/benutzer/neu", {"username": "anna", "password": "passwort123", "role": "leser"})
assert "Benutzer anna angelegt" in r.get_data(as_text=True)
r = post("/einstellungen/benutzer/1", {"role": "leser", "active": "1"})
assert "letzte aktive Admin" in r.get_data(as_text=True)

# 10 Leser darf nichts ändern, Admin-Seiten gesperrt
c.post("/logout", data={"_csrf": tok(get("/").get_data(as_text=True))})
r = post("/login", {"username": "anna", "password": "passwort123"})
assert "Übersicht" in r.get_data(as_text=True)
assert c.get("/einstellungen/benutzer").status_code == 403
assert c.get("/projekte/neu").status_code == 403
r = c.post("/bestellungen/1/wareneingang", data={"_csrf": tok(get("/").get_data(as_text=True))}); assert r.status_code == 403
# 11 falscher Login
c.post("/logout", data={"_csrf": tok(get("/").get_data(as_text=True))})
r = post("/login", {"username": "chris", "password": "falsch"}); assert "stimmt nicht" in r.get_data(as_text=True)
# 12 CSRF
assert c.post("/login", data={"username": "chris", "password": "geheim1234"}).status_code == 400
# Verschlüsselung
from einkauf.models import Supplier
with app.test_request_context():
    from einkauf import security
    S = app.extensions["SessionLocal"]()
    s = S.get(Supplier, 1); assert s.ugl_passwort_enc and "geheimPW" not in s.ugl_passwort_enc
    assert security.decrypt(s.ugl_passwort_enc) == "geheimPW"
print("ALLE TESTS OK")

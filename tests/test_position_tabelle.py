"""Test: Tabellarisches Hinzufügen von Positionen in der Bestelldetailansicht."""
import os, re, sys, tempfile
os.environ["EINKAUF_DATA"] = tempfile.mkdtemp(prefix="einkauf-test-")
HIER = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HIER, ".."))
sys.path.insert(0, HIER)

from einkauf import create_app
app = create_app(); c = app.test_client()
tok = lambda h: re.search(r'name="_csrf" value="([^"]+)"', h).group(1)
def G(url): return c.get(url, follow_redirects=True).get_data(as_text=True)
def P(url, data, page=None):
    t = tok(c.get(page or url).get_data(as_text=True))
    return c.post(url, data=dict(data, _csrf=t), follow_redirects=True).get_data(as_text=True)

P("/setup/", {"type": "sqlite"})
P("/setup/admin", {"username": "chris", "firma": "Elektro Test", "password": "geheim1234", "password2": "geheim1234"})
P("/einstellungen/lieferanten/neu", {"name": "Fega & Schmitt", "active": "1"})
P("/projekte/neu", {"nummer": "P-2026-0001", "name": "Testprojekt", "status": "aktiv"})

# Bestellung anlegen
P("/bestellungen/neu", {"supplier_id": "1", "bestelldatum": "2026-11-20", "bestellnr": "B-TEST-01", "schon_bestellt": "1"})

# 1. Bestelldetailseite pruefen: Tabelle fuer "Position hinzufuegen" vorhanden
h = G("/bestellungen/1")
assert 'Position hinzufügen</h3>' in h
assert 'table class="zeilen"' in h
assert 'name="row_artikelnr"' in h
assert 'name="row_bezeichnung"' in h
assert 'name="row_menge"' in h
assert 'name="row_einheit"' in h
assert 'name="row_preis"' in h
assert 'name="row_termin"' in h
assert 'name="row_projekt"' in h
assert 'name="row_kommission"' in h
assert '+ Zeile' in h

# 2. Einzelne Position tabellarisch hinzufuegen
h_post1 = P("/bestellungen/1/position", {
    "row_artikelnr": "1001",
    "row_bezeichnung": "Wanddose 68mm",
    "row_menge": "25",
    "row_einheit": "Stück",
    "row_preis": "0,85",
    "row_termin": "2026-11-25",
    "row_projekt": "1",
    "row_kommission": "Lager"
}, page="/bestellungen/1")
assert "1 Position hinzugefügt" in h_post1
assert "Wanddose 68mm" in h_post1
assert "1001" in h_post1
assert "25 Stück" in h_post1
assert "0,8500 €" in h_post1 or "0,85 €" in h_post1
assert "P-2026-0001" in h_post1

# 3. Mehrere Positionen auf einmal tabellarisch hinzufuegen
from werkzeug.datastructures import MultiDict
md = MultiDict([
    ("_csrf", tok(G("/bestellungen/1"))),
    ("row_artikelnr", "2001"),
    ("row_bezeichnung", "Kabel NYM 3x1.5"),
    ("row_menge", "100"),
    ("row_einheit", "m"),
    ("row_preis", "0,65"),
    ("row_termin", "2026-11-26"),
    ("row_projekt", "1"),
    ("row_kommission", "Etage 1"),
    ("row_artikelnr", "2002"),
    ("row_bezeichnung", "Kabel NYM 5x1.5"),
    ("row_menge", "50"),
    ("row_einheit", "m"),
    ("row_preis", "1,10"),
    ("row_termin", "2026-11-26"),
    ("row_projekt", ""),
    ("row_kommission", "Etage 2")
])
r_multi = c.post("/bestellungen/1/position", data=md, follow_redirects=True).get_data(as_text=True)
assert "2 Positionen hinzugefügt" in r_multi
assert "Kabel NYM 3x1.5" in r_multi
assert "Kabel NYM 5x1.5" in r_multi

# 4. Fallback fuer bisherige Einzelaufrufe pruefen
h_legacy = P("/bestellungen/1/position", {
    "artikelnr": "3001",
    "bezeichnung": "Legacy Schalter",
    "menge": "5",
    "einheit": "Stück",
    "preis": "4,20"
}, page="/bestellungen/1")
assert "Position hinzugefügt" in h_legacy
assert "Legacy Schalter" in h_legacy

print("TABELLEN-POSITIONEN OK")

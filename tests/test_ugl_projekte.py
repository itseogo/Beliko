"""Test: geteilte Projektansicht, Aufteilen, UGL-Upload mit Vorschau und Buchung (SQLite)."""
import os, re, sys, io, tempfile
os.environ["EINKAUF_DATA"] = tempfile.mkdtemp(prefix="einkauf-test-")
HIER = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HIER, ".."))
sys.path.insert(0, HIER)
from make_ugl import beispiel

DB = ({"type": "mariadb", "host": "127.0.0.1", "port": "3306", "name": "einkauf", "user": "einkauf", "password": "T3stPw!x"}
      if os.environ.get("TEST_DB") == "maria" else {"type": "sqlite"})
from einkauf import create_app
app = create_app(); c = app.test_client()
tok = lambda h: re.search(r'name="_csrf" value="([^"]+)"', h).group(1)
def G(url): return c.get(url, follow_redirects=True).get_data(as_text=True)
def P(url, data, page=None, files=None):
    t = tok(c.get(page or url).get_data(as_text=True))
    d = dict(data, _csrf=t)
    if files: d.update(files)
    return c.post(url, data=d, follow_redirects=True, content_type="multipart/form-data" if files else None).get_data(as_text=True)

P("/setup/", DB); P("/setup/admin", {"username": "chris", "password": "geheim1234", "password2": "geheim1234"})
P("/einstellungen/lieferanten/neu", {"name": "Fega & Schmitt", "active": "1"})
for nr, nm in [("22652080", "Audi Ingolstadt"), ("22652081", "Aumann Schaltschrank")]:
    P("/projekte/neu", {"nummer": nr, "name": nm, "kunde": "K", "status": "aktiv", "materialbudget": "1000"})

# Geteilte Ansicht
h = G("/projekte")
assert "Wähle oben ein Projekt aus" in h and "Audi Ingolstadt" in h and "Aumann" in h
h = G("/projekte?p=1")
assert "22652080 · Audi Ingolstadt" in h and "noch keine Bestellungen" in h
assert 'class="wahl"' in h and 'class="sel"' in h

# Bestellung wie im Screenshot (Fega, 10 Positionen), mit Wunschtermin
P("/bestellungen/neu", {"supplier_id": "1", "bestelldatum": "2026-10-24", "bestellnr": "22656347", "wunschtermin": "2026-10-30", "schon_bestellt": "1"})
pos = [("556023","JUNG Abdeckung","5","1"),("056309","PROT Geräteschraube","100","1"),("057433","1PROT Kupferband","3","1"),
       ("115418","KATH Verteiler","1","1"),("853346","KATH F-Stecker","10","1"),("263595","DOEP FI","2","1"),
       ("557607","JUNG Leitungsauslass","3","1"),("567465","WERA Bit-Set","1","1"),("9104201","PHOE Gehäuse","1","1"),("256019","JUNG Taster","1","1")]
for a, b, m, pid in pos:
    h = P("/bestellungen/1/position", {"artikelnr": a, "bezeichnung": b, "menge": m, "einheit": "Stück", "preis": "1,00", "project_id": pid, "kommission": "kirsch" if a == "115418" else ""}, page="/bestellungen/1")
assert "Wunschtermin 30.10.2026" in G("/bestellungen/1") and "Kommission: kirsch" in G("/bestellungen/1")

# Aufteilen: 5 Abdeckungen -> 2 auf Projekt 2
h = P("/positionen/1/aufteilen", {"menge_neu": "2", "project_id": "2", "kommission_neu": "ckg"}, page="/positionen/1")
assert "Position aufgeteilt" in h
assert P("/positionen/1/aufteilen", {"menge_neu": "9", "project_id": "2"}, page="/positionen/1").count("kleiner als die Gesamtmenge") >= 1

# Projektansicht: Bestellung erscheint unter Bestellt, mit Zurück-Link
h = G("/projekte?p=1&tab=bestellungen")
assert "Bestellt" in h and "22656347" in h and "von=1" in h
h = G("/bestellungen/1?von=1")
assert "Zurück zum Projekt 22652080" in h

# UGL-Upload mit der echten Datei
raw = beispiel()
h = P("/bestellungen/1/ugl", {}, page="/bestellungen/1", files={"datei": (io.BytesIO(raw), "B0261027.001")})
assert "Lieferantendatei prüfen" in h, h[:600]
assert "9104201" in h and "nicht dabei" not in h  # 9104201 steht in der Liste der fehlenden
assert "Offene Positionen, die nicht in der Datei stehen" in h
assert h.count('name="pos"') == 9, h.count('name="pos"')           # 9 Dateipositionen zuordenbar
assert "passt" in h
tk = re.search(r'name="token" value="([0-9a-f]{32})"', h).group(1)
# Position 1 (5 Stück) verteilt sich auf 3 + 2
assert "3 von 3 offen" in h and "2 von 2 offen" in h, re.sub(r"\s+"," ",h)[h.find("Abdeckung"):h.find("Abdeckung")+900]

# Übernehmen als Lieferschein
h = c.post("/bestellungen/1/ugl/uebernehmen", data={"_csrf": tok(c.get("/bestellungen/1").get_data(as_text=True)), "token": tk, "dateiname": "B0261027.001",
    "aktion": "lieferschein", "vermerken": "1", "pos": [str(i) for i in (1,2,3,4,5,6,7,8,10)], "lieferschein_nr": "LS-4711", "datum": "2026-10-27"}, follow_redirects=True).get_data(as_text=True)
assert "Wareneingang gebucht" in h and "Teillieferung" in h
assert "In Lieferdatei vom 27.10.2026 nicht dabei" in h
# Rückstand: nur noch die fehlende Position
h = G("/rueckstand")
assert "1 Positionen im Rückstand" in h and "PHOE Gehäuse" in h and "beim Lieferanten in Rückstand" in h
# Gleiche Vorschau-Datei kann nicht erneut übernommen werden
r = c.post("/bestellungen/1/ugl/uebernehmen", data={"_csrf": tok(c.get("/bestellungen/1").get_data(as_text=True)), "token": tk, "aktion": "lieferschein"}, follow_redirects=True).get_data(as_text=True)
assert "Vorschau ist abgelaufen" in r
# Token-Manipulation
assert c.post("/bestellungen/1/ugl/uebernehmen", data={"_csrf": tok(c.get("/bestellungen/1").get_data(as_text=True)), "token": "../../etc/passwd", "aktion": "ab"}).status_code == 400
# Gleiche Datei nochmal hochladen: alles ist geliefert -> keine Zuordnung
h = P("/bestellungen/1/ugl", {}, page="/bestellungen/1", files={"datei": (io.BytesIO(raw), "B0261027.001")})
assert "schon vollständig geliefert" in h
# Müll-Datei
h = P("/bestellungen/1/ugl", {}, page="/bestellungen/1", files={"datei": (io.BytesIO(b"hallo welt"), "x.txt")})
assert "Datei nicht lesbar" in h
# Als Auftragsbestätigung vermerken (zweite Bestellung)
P("/bestellungen/neu", {"supplier_id": "1", "bestelldatum": "2026-10-28", "schon_bestellt": "1"})
for a, b, m in [("556023","JUNG Abdeckung","5"),("9104201","PHOE Gehäuse","1")]:
    P("/bestellungen/2/position", {"artikelnr": a, "bezeichnung": b, "menge": m, "project_id": "1"}, page="/bestellungen/2")
h = P("/bestellungen/2/ugl", {}, page="/bestellungen/2", files={"datei": (io.BytesIO(raw), "B0261027.001")})
tk = re.search(r'name="token" value="([0-9a-f]{32})"', h).group(1)
h = c.post("/bestellungen/2/ugl/uebernehmen", data={"_csrf": tok(c.get("/bestellungen/2").get_data(as_text=True)), "token": tk, "aktion": "ab", "vermerken": "1", "pos": ["1"]}, follow_redirects=True).get_data(as_text=True)
assert "Bestätigung vermerkt" in h and "Vom Lieferanten bestätigt (27.10.2026)" in h and "nicht enthalten" in h and "AB 4755816401" in h
assert "Teillieferung" not in c.get("/bestellungen/2").get_data(as_text=True).split("Bisherige")[0].split("statusleiste")[1][:300]
print("NEUE FUNKTIONEN OK")

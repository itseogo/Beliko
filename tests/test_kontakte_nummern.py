"""Test: Kontakte (Anlegen, Suche, Ansprechpartner, Archiv, Kunde im Projekt) und Nummernkreise."""
import os, re, sys, tempfile
os.environ["EINKAUF_DATA"] = tempfile.mkdtemp(prefix="einkauf-test-")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from datetime import date
DB = ({"type": "mariadb", "host": "127.0.0.1", "port": "3306", "name": "einkauf", "user": "einkauf", "password": "T3stPw!x"}
      if os.environ.get("TEST_DB") == "maria" else {"type": "sqlite"})
from einkauf import create_app
from einkauf.models import Contact, NumberRange, Project
app = create_app(); c = app.test_client()
J = date.today().year
tok = lambda h: re.search(r'name="_csrf" value="([^"]+)"', h).group(1)
G = lambda u: c.get(u, follow_redirects=True).get_data(as_text=True)
def P(url, data, page=None):
    return c.post(url, data=dict(data, _csrf=tok(c.get(page or url).get_data(as_text=True))), follow_redirects=True).get_data(as_text=True)
def feld(h, name): return re.search(r'name="%s" value="([^"]*)"' % name, h).group(1)
def db(): return app.extensions["SessionLocal"]()

P("/setup/", DB); P("/setup/admin", {"username": "chris", "password": "geheim1234", "password2": "geheim1234"})
P("/einstellungen/lieferanten/neu", {"name": "Fega", "active": "1"})

# ---- Kontakte
h = G("/kontakte"); assert "Keine Kontakte" in h and "Kontakte" in G("/")          # Reiter/Baum vorhanden
h = P("/kontakte/neu", {"typ": "firma", "ist_kunde": "1"}, page="/kontakte/neu"); assert "Firmenname Pflicht" in h
h = P("/kontakte/neu", {"typ": "person", "vorname": "Anna"}, page="/kontakte/neu"); assert "Nachname Pflicht" in h
h = P("/kontakte/neu", {"typ": "firma", "firma": "Jäger Handling GmbH", "ist_kunde": "1", "kunde_nr": "10117", "re_strasse": "Hauptstr. 1",
        "re_plz": "74429", "re_ort": "Sulzbach-Laufen", "re_land": "de", "email_geschaeft": "info@jaeger.example", "tel_geschaeft": "07971 123",
        "leitweg_id": "04011000-1234512345-35"}, page="/kontakte/neu")
assert "Kontakt angelegen" not in h and "Jäger Handling GmbH" in h and "Sulzbach-Laufen (DE)" in h and "04011000-1234512345-35" in h
P("/kontakte/neu", {"typ": "firma", "firma": "Rexel Germany", "ist_lieferant": "1", "lieferant_nr": "70179"}, page="/kontakte/neu")
P("/kontakte/neu", {"typ": "person", "vorname": "Hans", "nachname": "Koch", "anrede": "Herr", "ist_kunde": "1", "re_ort": "Gaildorf"}, page="/kontakte/neu")
assert "Hans Koch" in G("/kontakte") and "Privatperson" in G("/kontakte")
assert "Rexel" not in G("/kontakte?rolle=kunden") and "Rexel" in G("/kontakte?rolle=lieferanten")
assert "Rexel" in G("/kontakte?q=70179") and "Jäger" not in G("/kontakte?q=70179") and "Jäger" in G("/kontakte?q=Sulzbach")
# Ansprechpartner
h = P("/kontakte/1/person", {"vorname": "", "nachname": ""}, page="/kontakte/1"); assert "mindestens Vor- oder Nachnamen" in h
h = P("/kontakte/1/person", {"anrede": "Herr", "vorname": "Max", "nachname": "Mustermann", "email": "max@jaeger.example", "primaer": "1"}, page="/kontakte/1")
assert "Max Mustermann" in h and "Hauptansprechpartner" in h
h = P("/kontakte/1/person/1/loeschen", {}, page="/kontakte/1"); assert "Max Mustermann" not in h

# ---- Kunde im Projekt: Auswahl aus Kontakten oder freier Text
h = G("/projekte/neu"); assert 'list="kunden-liste"' in h and 'value="Jäger Handling GmbH"' in h and "Rexel" not in h.split("<datalist")[1].split("</datalist>")[0]
nr = feld(h, "nummer"); assert nr == f"P-{J}-0001", nr
h = P("/projekte/neu", {"nummer": nr, "name": "Audi", "kunde": "jäger handling gmbh", "status": "aktiv"}, page="/projekte/neu")
assert "Projekt angelegt" in h and 'href="/kontakte/1"' in h and "Jäger Handling GmbH" in h        # Name aus Kontakt übernommen, verlinkt
h = P("/projekte/neu", {"nummer": f"P-{J}-0002", "name": "Privat", "kunde": "Familie Unbekannt", "status": "aktiv"}, page="/projekte/neu")
assert "Familie Unbekannt" in h and 'href="/kontakte/' not in h.split('id="unten"')[1].split("</section>")[0].split("Bearbeiten")[0]
with db() as s:
    assert s.get(Project, 1).contact_id == 1 and s.get(Project, 2).contact_id is None
# Kontakt umbenennen -> Projekte ziehen den Namen nach
h = P("/kontakte/1/bearbeiten", {"typ": "firma", "firma": "Jäger Handling AG", "ist_kunde": "1"}, page="/kontakte/1/bearbeiten")
assert "Kontakt gespeichert" in h and "Jäger Handling AG" in h
assert "Jäger Handling AG" in G("/projekte?p=1&status=alle")
# Archivieren: erscheint nicht mehr in Auswahl/Liste
P("/kontakte/3/archiv", {}, page="/kontakte/3")
assert "Hans Koch" not in G("/kontakte") and "Hans Koch" in G("/kontakte?archiv=1") and "Hans Koch" not in G("/projekte/neu").split("<datalist")[1]
# Lexoffice-Kontakte sind schreibgeschützt
with db() as s:
    k = s.get(Contact, 2); k.quelle = "lexoffice"; s.commit()
h = G("/kontakte/2/bearbeiten"); assert "kommt aus Lexoffice" in h and "Bearbeiten" not in h.split("<h1>")[1].split("</h1>")[0]
assert "Archivieren" not in G("/kontakte/2")

# ---- Nummernkreise: Vorschlag, Zähler, eigene Nummern
h = G("/projekte/neu"); assert feld(h, "nummer") == f"P-{J}-0003"                 # 0001, 0002 verbraucht
h = P("/projekte/neu", {"nummer": "SONDER-1", "name": "Sonderprojekt", "status": "aktiv"}, page="/projekte/neu")
assert "Projekt angelegt" in h and feld(G("/projekte/neu"), "nummer") == f"P-{J}-0003"      # eigene Nummer lässt Zähler stehen
P("/projekte/neu", {"nummer": f"P-{J}-0010", "name": "Hoch", "status": "aktiv"}, page="/projekte/neu")
assert feld(G("/projekte/neu"), "nummer") == f"P-{J}-0011"                          # höhere passende Nummer zieht Zähler nach
h = P("/projekte/neu", {"nummer": "SONDER-1", "name": "Doppelt", "status": "aktiv"}, page="/projekte/neu"); assert "gibt es schon" in h

# Bestellnummer
h = G("/bestellungen/neu"); assert feld(h, "bestellnr") == f"B-{J}-0001"
P("/bestellungen/neu", {"supplier_id": "1", "bestelldatum": f"{J}-01-05", "bestellnr": f"B-{J}-0001"}, page="/bestellungen/neu")
assert feld(G("/bestellungen/neu"), "bestellnr") == f"B-{J}-0002"
h = P("/bestellungen/neu", {"supplier_id": "1", "bestellnr": f"B-{J}-0001"}, page="/bestellungen/neu"); assert "gibt es schon" in h

# Einstellungen: Muster prüfen
def nk(projekt, bestellung, pn="1", bn="1", reset="auto"):
    return {"projekt_muster": projekt, "projekt_naechste": pn, "projekt_reset": reset, "projekt_start": "1",
            "bestellung_muster": bestellung, "bestellung_naechste": bn, "bestellung_reset": reset, "bestellung_start": "1"}
SEITE = "/einstellungen/nummernkreise"
h = G(SEITE); assert 'id="projekt-muster"' in h and "Nächste Nummer:" in h and f"P-{J}-0011" in h      # Vorschau mit aktuellem Zähler
assert "nur Buchstaben, Ziffern" in P(SEITE, nk("P!-XXXX", f"B-YYYY-XXXX"), page=SEITE)
assert "genau eine Folge aus X" in P(SEITE, nk("P-YYYY", "B-XXXX"), page=SEITE)
assert "genau eine Folge aus X" in P(SEITE, nk("P-XXXX-XX", "B-XXXX"), page=SEITE)
assert "reserviert" in P(SEITE, nk("P-YYY-XXXX", "B-XXXX"), page=SEITE)
assert "höchstens 10 Stellen" in P(SEITE, nk("XXXXXXXXXXX", "B-XXXX"), page=SEITE)
h = P(SEITE, nk("P-YYYY-XXXX", "B-XXXX", pn="0"), page=SEITE); assert "ab 1 sein" in h and 'value="B-XXXX"' in h   # Eingabe bleibt stehen
# Nummer wie in der Branchensoftware: 2265 + 4 Stellen; 22652082 existiert schon -> wird übersprungen
P("/projekte/neu", {"nummer": "22652082", "name": "Vorhanden", "status": "aktiv"}, page="/projekte/neu")
h = P(SEITE, nk("2265XXXX", "B-YYYY-XXXX", pn="2081", bn="7"), page=SEITE)
assert "Nummernkreise gespeichert" in h and "22652081" in h
assert feld(G("/projekte/neu"), "nummer") == "22652081"
P("/projekte/neu", {"nummer": "22652081", "name": "Neu", "status": "aktiv"}, page="/projekte/neu")
assert feld(G("/projekte/neu"), "nummer") == "22652083"                           # 22652082 ist belegt
assert feld(G("/bestellungen/neu"), "bestellnr") == f"B-{J}-0007"
# Jahreswechsel: Zähler beginnt neu
with db() as s:
    r = s.get(NumberRange, "bestellung"); r.periode = str(J - 1); r.naechste = 55; s.commit()
assert feld(G("/bestellungen/neu"), "bestellnr") == f"B-{J}-0002"   # Zähler beginnt bei 1; ...-0001 ist belegt und wird übersprungen
# Datumsmuster wie YYMMDDXXXX -> täglicher Neustart
heute = date.today(); jjmmtt = f"{heute.year % 100:02d}{heute.month:02d}{heute.day:02d}"
P(SEITE, nk("YYMMDDXXXX", "B-YYYY-XXXX"), page=SEITE)
assert feld(G("/projekte/neu"), "nummer") == f"{jjmmtt}0001", feld(G("/projekte/neu"), "nummer")
P("/projekte/neu", {"nummer": f"{jjmmtt}0001", "name": "Tag1", "status": "aktiv"}, page="/projekte/neu")
assert feld(G("/projekte/neu"), "nummer") == f"{jjmmtt}0002"
with db() as s:
    r = s.get(NumberRange, "projekt"); r.periode = "1999-01-01"; r.naechste = 77; s.commit()     # gestern war ein anderer Tag
assert feld(G("/projekte/neu"), "nummer") == f"{jjmmtt}0002"                         # Zähler zurück auf 1, 0001 belegt -> 0002
P(SEITE, nk("YYMMDDXXXX", "B-YYYY-XXXX", reset="nie"), page=SEITE)
with db() as s:
    r = s.get(NumberRange, "projekt"); assert r.reset == "nie" and r.periode == ""
# Rechte: Leser darf Kontakte ansehen, aber nichts ändern und nicht in die Einstellungen
P("/einstellungen/benutzer/neu", {"username": "leser1", "password": "passwort123", "role": "leser"}, page="/einstellungen/benutzer/neu")
c.post("/logout", data={"_csrf": tok(G("/"))})
assert "Übersicht" in P("/login", {"username": "leser1", "password": "passwort123"}, page="/login")
assert c.get("/kontakte").status_code == 200 and c.get("/kontakte/1").status_code == 200
assert c.get("/kontakte/neu").status_code == 403 and c.get("/kontakte/1/bearbeiten").status_code == 403
assert c.get("/einstellungen/nummernkreise").status_code == 403
assert "Bearbeiten" not in G("/kontakte/1").split("<h1>")[1].split("Ansprechpartner")[0]
print("KONTAKTE + NUMMERNKREISE OK")

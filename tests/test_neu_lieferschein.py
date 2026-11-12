"""Test: Name BeLiKo, Neu-Menü statt einzelner Anlegen-Buttons, Lieferschein erfassen und Liste."""
import os, re, sys, tempfile
os.environ["EINKAUF_DATA"] = tempfile.mkdtemp(prefix="einkauf-test-")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
DB = ({"type": "mariadb", "host": "127.0.0.1", "port": "3306", "name": "einkauf", "user": "einkauf", "password": "T3stPw!x"}
      if os.environ.get("TEST_DB") == "maria" else {"type": "sqlite"})
from einkauf import create_app
from einkauf.models import Delivery, Order
app = create_app(); c = app.test_client()
tok = lambda h: re.search(r'name="_csrf" value="([^"]+)"', h).group(1)
G = lambda u, cl=None: (cl or c).get(u, follow_redirects=True).get_data(as_text=True)
def P(url, data, page=None, cl=None):
    cl = cl or c
    return cl.post(url, data=dict(data, _csrf=tok(cl.get(page or url).get_data(as_text=True))), follow_redirects=True).get_data(as_text=True)
def db(): return app.extensions["SessionLocal"]()

# ---- Name
P("/setup/", DB); P("/setup/admin", {"username": "chris", "firma": "Elektro Test", "password": "geheim1234", "password2": "geheim1234"})
h = G("/login", app.test_client()); assert "BeLiKo" in h and "BestellLieferKontrolle" in h and "<title>Anmelden – BeLiKo</title>" in h
h = G("/"); assert 'class="brand"' in h and ">BeLiKo<" in h and "Elektro Test" in h and "– BeLiKo</title>" in h

# ---- Neu-Menü
kopf = h.split("</header>")[0]
assert 'id="neu-menu"' in kopf and ">Neu <" in kopf
for ziel, text in (("/bestellungen/neu", "Bestellung"), ("/lieferscheine/neu", "Lieferschein"), ("/ids", "Aus IDS übernehmen"), ("/projekte/neu", "Projekt anlegen"), ("/kontakte/neu", "Kontakt anlegen")):
    assert f'href="{ziel}">{text}</a>' in kopf, ziel
# Keine einzelnen Anlegen-Buttons mehr
for seite in ("/", "/bestellungen", "/projekte", "/kontakte", "/rueckstand", "/lieferscheine"):
    hh = G(seite)
    assert 'class="t-item add"' not in hh, seite
    assert not re.search(r'class="btn[^"]*"[^>]*>(Projekt anlegen|Bestellung erfassen|Kontakt anlegen)<', hh), seite
assert "Lieferant anlegen" in G("/einstellungen/lieferanten") and "Benutzer anlegen" in G("/einstellungen/benutzer")      # Einstellungen behalten ihre Buttons
assert "Lieferscheine</a>" in G("/")                                                                                        # Baum: Lieferscheine

# Leser sieht das Neu-Menü nicht
P("/einstellungen/benutzer/neu", {"username": "lena", "password": "passwort123", "role": "leser"}, page="/einstellungen/benutzer/neu")
le = app.test_client(); P("/login", {"username": "lena", "password": "passwort123"}, page="/login", cl=le)
assert 'id="neu-menu"' not in G("/", le) and le.get("/lieferscheine/neu").status_code == 403 and le.get("/lieferscheine").status_code == 200

# ---- Lieferschein erfassen
P("/einstellungen/lieferanten/neu", {"name": "Fega", "active": "1"}); P("/einstellungen/lieferanten/neu", {"name": "Rexel", "active": "1"})
P("/projekte/neu", {"nummer": "P1", "name": "Audi", "status": "aktiv"})
def bestellung(nr, lief, status, *pos):
    keys = ["artikelnr", "bezeichnung", "menge", "einheit", "preis", "termin", "projekt", "kommission", "hinweis"]
    d = {"supplier_id": str(lief), "bestellnr": nr, "projekt_alle": "1", "bestelldatum": "2026-10-20", **({"schon_bestellt": "1"} if status else {})}
    d.update({f"row_{k}": [p[i] for p in pos] for i, k in enumerate(keys)})
    P("/bestellungen/neu", d, page="/bestellungen/neu")
row = lambda art, bez, m: (art, bez, m, "Stück", "1,00", "", "", "", "")
bestellung("B-1", 1, True, row("A1", "Kabel", "10"), row("A2", "Dose", "4"))
bestellung("B-2", 1, True, row("A3", "Schalter", "6"))
bestellung("B-3", 1, False, row("A4", "Entwurfsteil", "1"))             # Status Neu: erscheint nicht
bestellung("B-4", 2, True, row("R1", "Rexel-Teil", "2"))

h = G("/lieferscheine/neu")
assert "Lieferant *" in h and "Kabel" not in h                                                            # ohne Auswahl keine Positionen
h = G("/lieferscheine/neu?lieferant=1")
assert "Kabel" in h and "Dose" in h and "Schalter" in h and "Entwurfsteil" not in h and "Rexel-Teil" not in h
assert "Bestellung B-1" in h and "Bestellung B-2" in h and h.count("name=\"menge_") == 3
assert "Dieser Lieferant hat keine offenen Positionen" in G("/lieferscheine/neu?lieferant=2").replace("Rexel-Teil", "") or "Rexel-Teil" in G("/lieferscheine/neu?lieferant=2")
ids_ = {}
with db() as s:
    for o in s.query(Order).all(): ids_[o.bestellnr] = [i.id for i in o.items]
def LS(daten, lief="1"): return P("/lieferscheine/neu", {"lieferant": lief, **daten}, page=f"/lieferscheine/neu?lieferant={lief}")
# Fehler
assert "keine gelieferte Menge" in LS({"lieferschein_nr": "LS-1", "datum": "2026-10-27"})
assert "keine Zahl" in LS({"lieferschein_nr": "LS-1", f"menge_{ids_['B-1'][0]}": "abc"})
assert "Negative Menge" in LS({"lieferschein_nr": "LS-1", f"menge_{ids_['B-1'][0]}": "-1"})
h = LS({"lieferschein_nr": "LS-1", f"menge_{ids_['B-1'][0]}": "abc"}); assert 'value="abc"' in h and 'value="LS-1"' in h      # Eingaben bleiben
# Teillieferung über zwei Bestellungen mit einer Lieferschein-Nr.
h = LS({"lieferschein_nr": "LS-1", "datum": "2026-10-27", "notiz": "Palette 1", f"menge_{ids_['B-1'][0]}": "10", f"menge_{ids_['B-1'][1]}": "1", f"menge_{ids_['B-2'][0]}": "6"})
assert "Lieferschein gebucht: 3 Positionen in 2 Bestellungen" in h and "LS-1" in h and "Palette 1" in h
with db() as s:
    st = {o.bestellnr: o.status for o in s.query(Order).all()}
    assert st == {"B-1": "teilgeliefert", "B-2": "komplett", "B-3": "neu", "B-4": "bestellt"}, st
    assert s.query(Delivery).filter(Delivery.lieferschein_nr == "LS-1").count() == 2
# Doppelte Nummer wird abgewiesen
assert "gibt es für diesen Lieferanten schon" in LS({"lieferschein_nr": "LS-1", f"menge_{ids_['B-1'][1]}": "1"})
# Anderer Lieferant darf dieselbe Nummer haben; „alles“ bucht den Rest
h = LS({"lieferschein_nr": "LS-1", "alles": "1"}, lief="2"); assert "Lieferschein gebucht: 1 Positionen in 1 Bestellungen" in h
h = LS({"lieferschein_nr": "LS-2", "alles": "1"}); assert "1 Positionen in 1 Bestellungen" in h
with db() as s: assert {o.bestellnr: o.status for o in s.query(Order).all()} == {"B-1": "komplett", "B-2": "komplett", "B-3": "neu", "B-4": "komplett"}
assert "keine offenen Positionen" in G("/lieferscheine/neu?lieferant=1")
# Liste und Filter
h = G("/lieferscheine"); assert h.count("LS-1") == 3 and "LS-2" in h
assert "LS-2" in G("/lieferscheine?q=LS-2") and "LS-1" not in G("/lieferscheine?q=LS-2")
assert "Rexel" in G("/lieferscheine?lieferant=2") and "LS-2" not in G("/lieferscheine?lieferant=2")
print("NEU-MENUE + LIEFERSCHEIN OK")

"""Test: Dark Mode je Benutzer, Bestellmaske mit Positionen in einem Schritt, IDS-Connect (Warenkorb vom Shop)."""
import html as H, io, os, re, sys, tempfile
DATEN = tempfile.mkdtemp(prefix="einkauf-test-")
os.environ["EINKAUF_DATA"] = DATEN
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from decimal import Decimal
from datetime import date
DB = ({"type": "mariadb", "host": "127.0.0.1", "port": "3306", "name": "einkauf", "user": "einkauf", "password": "T3stPw!x"}
      if os.environ.get("TEST_DB") == "maria" else {"type": "sqlite"})
from einkauf import create_app, formate, ids
from einkauf.models import Order, OrderItem, Supplier
app = create_app(); c = app.test_client()
tok = lambda h: re.search(r'name="_csrf" value="([^"]+)"', h).group(1)
G = lambda u, cl=None: (cl or c).get(u, follow_redirects=True).get_data(as_text=True)
def P(url, data, page=None, cl=None):
    cl = cl or c
    return cl.post(url, data=dict(data, _csrf=tok(cl.get(page or url).get_data(as_text=True))), follow_redirects=True).get_data(as_text=True)
def db(): return app.extensions["SessionLocal"]()

# ---------------- Formate
assert formate.preis(Decimal("0.0474")) == "0,0474 €" and formate.preis(Decimal("2.21")) == "2,21 €" and formate.preis(Decimal("1234.5")) == "1.234,50 €"
assert formate.preis_eingabe(Decimal("0.0474")) == "0,0474" and formate.preis_eingabe(Decimal("12")) == "12,00"

# ---------------- Einrichtung
P("/setup/", DB); P("/setup/admin", {"username": "chris", "password": "geheim1234", "password2": "geheim1234"})
P("/einstellungen/lieferanten/neu", {"name": "Fega", "active": "1", "ids_url": "https://shop.example.test/ids", "ids_kndnr": "108690",
    "ids_benutzer": "benutzer1", "ids_passwort": "geheim-pw", "ids_version": "2.5", "ids_preis_modus": "gesamt"})
P("/projekte/neu", {"nummer": "P1", "name": "Audi", "status": "aktiv"}); P("/projekte/neu", {"nummer": "P2", "name": "Aumann", "status": "aktiv"})
assert "IDS-Adresse muss" in P("/einstellungen/lieferanten/neu", {"name": "X", "ids_url": "ftp://nein"}, page="/einstellungen/lieferanten/neu")

# ---------------- Dark Mode
assert 'data-theme="light"' in G("/")
assert "Darstellung" in G("/konto")
P("/konto", {"aktion": "darstellung", "theme": "dunkel"}, page="/konto"); assert 'data-theme="dark"' in G("/") and 'value="dunkel" checked' in G("/konto")
P("/konto", {"aktion": "darstellung", "theme": "auto"}, page="/konto"); assert 'data-theme="auto"' in G("/")
P("/konto", {"aktion": "darstellung", "theme": "quatsch"}, page="/konto"); assert 'data-theme="light"' in G("/")
P("/konto", {"aktion": "darstellung", "theme": "dunkel"}, page="/konto")
assert 'data-theme="auto"' in G("/login", app.test_client())             # abgemeldet: folgt dem Gerät
css = c.get("/static/style.css").get_data(as_text=True)
assert 'data-theme="dark"' in css and "prefers-color-scheme: dark" in css and "color-scheme:dark" in css
P("/einstellungen/benutzer/neu", {"username": "emma", "password": "passwort123", "role": "einkaeufer"}, page="/einstellungen/benutzer/neu")
em = app.test_client(); P("/login", {"username": "emma", "password": "passwort123"}, page="/login", cl=em)
assert 'data-theme="light"' in G("/", em)                                 # Einstellung gilt nur für den eigenen Benutzer

# ---------------- Bestellmaske: alles in einem Schritt
h = G("/bestellungen/neu")
assert h.count('name="row_bezeichnung"') >= 7 and 'id="zeile-neu"' in h and 'name="projekt_alle"' in h and "Positionen" in h
def zeilen(*rows):
    keys = ["artikelnr", "bezeichnung", "menge", "einheit", "preis", "termin", "projekt", "kommission", "hinweis"]
    return {f"row_{k}": [r[i] for r in rows] for i, k in enumerate(keys)}
KOPF = {"supplier_id": "1", "bestelldatum": "2026-10-31", "bestellnr": "B-T-1", "projekt_alle": "1", "schon_bestellt": "1"}
Z1 = ("556023", "JUNG Abdeckung", "5", "Stück", "3,19", "", "", "kirsch 2x", "")
Z2 = ("", "", "", "Stück", "", "", "", "", "")                                   # leere Zeile wird ignoriert
Z3 = ("056309", "Geräteschraube", "100", "Stück", "0,0474", "2026-11-06", "-", "", "")
h = P("/bestellungen/neu", {**KOPF, **zeilen(Z1, Z2, Z3)}, page="/bestellungen/neu")
assert "Bestellung angelegt mit 2 Positionen" in h and "JUNG Abdeckung" in h and "0,0474 €" in h and "kirsch 2x" in h
with db() as s:
    o = s.query(Order).one(); i1, i3 = sorted(o.items, key=lambda i: i.id)
    assert o.status == "bestellt" and i1.project_id == 1 and i3.project_id is None and i3.preis == Decimal("0.0474") and i3.erw_lieferdatum == date(2026, 11, 6)
assert "JUNG Abdeckung" in G("/rueckstand")                                       # schon bestellt -> im Rückstand
h = P("/bestellungen/neu", {**KOPF, "bestellnr": "B-T-2", **zeilen(Z1, ("1", "Halbfertig", "", "Stück", "", "", "", "", ""))}, page="/bestellungen/neu")
assert "Zeile 2: Bezeichnung und eine Menge" in h and "Halbfertig" in h and 'value="JUNG Abdeckung"' in h          # Eingaben bleiben stehen
assert "Preis ist keine Zahl" in P("/bestellungen/neu", {**KOPF, "bestellnr": "B-T-2", **zeilen(("1", "X", "1", "Stück", "abc", "", "", "", ""))}, page="/bestellungen/neu")
assert "gibt es schon" in P("/bestellungen/neu", {**KOPF, **zeilen(Z1)}, page="/bestellungen/neu")
assert "Bitte einen Lieferanten" in P("/bestellungen/neu", {**KOPF, "supplier_id": "", "bestellnr": "B-T-3", **zeilen(Z1)}, page="/bestellungen/neu")
h = P("/bestellungen/neu", {"supplier_id": "1", "bestellnr": "B-T-4"}, page="/bestellungen/neu"); assert "Positionen kannst du jetzt ergänzen" in h

# ---------------- IDS-Connect
XML = """<?xml version="1.0" encoding="ISO-8859-1"?>
<Warenkorb xmlns="http://www.itek.de/Shop-Anbindung/Warenkorb/">
 <WarenkorbInfo><Date>2026-10-31</Date><Time>10:15:00</Time><RueckgabeKZ>Warenkorbrückgabe mit Bestellung</RueckgabeKZ><Version>2.5</Version></WarenkorbInfo>
 <Order>
  <OrderInfo><OrderConfNo>4755816999</OrderConfNo><DeliveryWeek>45</DeliveryWeek><DeliveryYear>2026</DeliveryYear>
   <ModeOfShipment>Lieferung</ModeOfShipment><Cur>EUR</Cur><Kommission>Müller Bau</Kommission><ZusatzText>Bitte vormittags</ZusatzText></OrderInfo>
  <OrderItem><ItemChara>normal</ItemChara><RefItems><Customer>1</Customer></RefItems><ArtNo>556023</ArtNo><Qty>5</Qty><QU>PCE</QU>
   <Kurztext>JUNG Abdeckung für Müllerstraße</Kurztext><OfferPrice>4.50</OfferPrice><NetPrice>15.95</NetPrice><PriceBasis>1</PriceBasis><Hinweis>Lieferzeit 3 Tage</Hinweis></OrderItem>
  <OrderItem><ItemChara>normal</ItemChara><ArtNo>ZK-50</ArtNo><Qty>50</Qty><QU>MTR</QU><Kurztext>Kabel NYM-J 5x1,5</Kurztext>
   <OfferPrice>10000</OfferPrice><NetPrice>522.00</NetPrice><PriceBasis>1000</PriceBasis></OrderItem>
  <OrderItem><ItemChara>alternate</ItemChara><ArtNo>ALT-1</ArtNo><Qty>1</Qty><QU>PCE</QU><Kurztext>Alternative Dose</Kurztext></OrderItem>
 </Order>
</Warenkorb>""".encode("iso-8859-1")

# Leser unit tests
r = ids.lesen(XML)
assert len(r["positionen"]) == 3 and r["ab_nr"] == "4755816999" and r["lieferdatum"] == date(2026, 11, 6) and r["lieferwoche"] == (2026, 45)
assert r["positionen"][1]["einheit"] == "m" and r["positionen"][0]["kurztext"].endswith("Müllerstraße")
assert ids.einzelpreis(r["positionen"][0], "gesamt") == Decimal("3.19") and ids.einzelpreis(r["positionen"][1], "gesamt") == Decimal("10.44")
assert ids.einzelpreis(r["positionen"][1], "einzel") == Decimal("0.522") and ids.einzelpreis(r["positionen"][2], "gesamt") is None
for schlecht in (b"<!DOCTYPE x [<!ENTITY a 'b'>]><Warenkorb/>", b"<Foo/>", b"kein xml"):
    try: ids.lesen(schlecht); raise SystemExit("hätte abgelehnt werden müssen: %r" % schlecht)
    except ids.IdsFehler: pass

def shop_start():
    h = P("/ids/start/1", {}, page="/ids")
    return h, re.search(r'name="hookurl" value="[^"]*?/ids/rueckgabe/([0-9a-f]{32})"', h).group(1)
h = G("/ids"); assert "Fega" in h and "Shop öffnen" in h
h, token = shop_start()
assert 'action="https://shop.example.test/ids"' in h and 'enctype="multipart/form-data"' in h
for n, w in [("kndnr", "108690"), ("name_kunde", "benutzer1"), ("pw_kunde", "geheim-pw"), ("action", "WKE"), ("version", "2.5")]:
    assert f'name="{n}" value="{w}"' in h, n
hook = re.search(r'name="hookurl" value="([^"]+)"', h).group(1); assert hook == f"http://localhost/ids/rueckgabe/{token}" and len(hook) <= 256
# Passwort bleibt beim Bearbeiten ohne neue Eingabe erhalten
P("/einstellungen/lieferanten/1", {"name": "Fega", "active": "1", "ids_url": "https://shop.example.test/ids", "ids_version": "2.5"}, page="/einstellungen/lieferanten/1")
assert 'name="pw_kunde" value="geheim-pw"' in P("/ids/start/1", {}, page="/ids")

# Der Shop schickt den Warenkorb per Browser (anderer Absender, kein Login, kein CSRF-Token)
shop = app.test_client()
assert shop.get(f"/ids/rueckgabe/{token}").status_code == 200
r1 = shop.post(f"/ids/rueckgabe/{token}", data={"warenkorb": (io.BytesIO(XML), "warenkorb.xml")}, content_type="multipart/form-data")
assert r1.status_code == 303 and r1.headers["Location"].endswith(f"/bestellungen/neu?ids={token}"), (r1.status_code, r1.headers.get("Location"))
assert shop.post(f"/ids/rueckgabe/{token}", data={"warenkorb": (io.BytesIO(XML), "w.xml")}, content_type="multipart/form-data").status_code == 410   # nur einmal
assert shop.post("/ids/rueckgabe/" + "0" * 32, data={"warenkorb": "x"}).status_code == 410
assert shop.post("/ids/rueckgabe/zzz", data={"warenkorb": "x"}).status_code == 404

# Formular ist vorbelegt
h = G(f"/bestellungen/neu?ids={token}")
assert "Warenkorb aus dem Shop von Fega" in h and 'name="ab_nr" value="4755816999"' in h and "mit Bestellung" in h
assert re.search(r'name="schon_bestellt" value="1" checked', h) and "Alternative Dose" in h.split("Nicht übernommen")[1]
assert "Müller Bau" in h and "Versandart: Lieferung" in h and "Bitte vormittags" in h
vals = lambda n: [H.unescape(x) for x in re.findall(r'name="%s" value="([^"]*)"' % n, h.split('id="zeilen"')[1].split("</tbody>")[0])]
assert vals("row_artikelnr")[:2] == ["556023", "ZK-50"] and vals("row_menge")[:2] == ["5", "50"] and vals("row_einheit")[:2] == ["Stück", "m"]
assert vals("row_preis")[:2] == ["3,19", "10,44"] and vals("row_termin")[:2] == ["2026-11-06", "2026-11-06"]
assert vals("row_bezeichnung")[0] == "JUNG Abdeckung für Müllerstraße" and "Shop: Lieferzeit 3 Tage" in h
# Speichern -> Bestellung mit Positionen
n = len(vals("row_artikelnr"))
rows = list(zip(*[(vals(f"row_{k}") if k != "projekt" else [""] * n) for k in ("artikelnr", "bezeichnung", "menge", "einheit", "preis", "termin", "projekt", "kommission", "hinweis")]))
rows = [r for r in rows if r[1]]
kopf = {"supplier_id": "1", "bestelldatum": "2026-10-31", "bestellnr": "B-IDS-1", "ab_nr": "4755816999", "projekt_alle": "2", "schon_bestellt": "1",
        "ids_token": token, "notiz": "Kommission im Shop: Müller Bau"}
h = P("/bestellungen/neu", {**kopf, **zeilen(*rows)}, page=f"/bestellungen/neu?ids={token}")
assert "Bestellung angelegt mit 2 Positionen" in h and "Shop: Lieferzeit 3 Tage" in h and "10,44 €" in h
with db() as s:
    o = s.query(Order).filter(Order.bestellnr == "B-IDS-1").one()
    assert o.ab_nr == "4755816999" and o.status == "bestellt" and len(o.items) == 2 and all(i.project_id == 2 for i in o.items)
    assert sorted(i.preis for i in o.items) == [Decimal("3.19"), Decimal("10.44")]
ids_dir = os.path.join(DATEN, "ids"); assert not [f for f in os.listdir(ids_dir) if f.startswith(token)]       # aufgeräumt
assert G(f"/bestellungen/neu?ids={token}").count("nicht mehr verfügbar") == 1

# Varianten der Rückgabe: Textfeld (UTF-8), URL-codiert, Rohtext; Fehlerfälle lassen den Token gültig
xml_utf8 = XML.decode("iso-8859-1").replace("ISO-8859-1", "UTF-8")
for nr, kw in enumerate([dict(data={"Warenkorb": xml_utf8}, content_type="multipart/form-data"), dict(data={"xml": xml_utf8}),
                         dict(data=xml_utf8.encode("utf-8"), content_type="application/xml")]):
    h, t = shop_start()
    assert shop.post(f"/ids/rueckgabe/{t}", data={"foo": "bar"}).status_code == 400                                 # kein Warenkorb
    assert shop.post(f"/ids/rueckgabe/{t}", data={"warenkorb": "<!DOCTYPE a [<!ENTITY b 'c'>]><Warenkorb/>"}).status_code == 400
    r2 = shop.post(f"/ids/rueckgabe/{t}", **kw); assert r2.status_code == 303, (nr, r2.status_code)
    assert "Müllerstraße" in G(f"/bestellungen/neu?ids={t}"), nr
# Preismodus „eine Einheit“
with db() as s: s.get(Supplier, 1).ids_preis_modus = "einzel"; s.commit()
h, t = shop_start(); shop.post(f"/ids/rueckgabe/{t}", data={"warenkorb": (io.BytesIO(XML), "w.xml")}, content_type="multipart/form-data")
h2 = G(f"/bestellungen/neu?ids={t}"); assert "0,522" in h2 and "eine Einheit" in h2
# Fremder Benutzer sieht den Warenkorb nicht
assert "nicht mehr verfügbar" in G(f"/bestellungen/neu?ids={t}", em)
# Ohne Anmeldung -> Login, danach zurück zum Warenkorb (Parameter bleiben erhalten)
anon = app.test_client(); loc = anon.get(f"/bestellungen/neu?ids={t}").headers["Location"]; assert "next=" in loc and "ids%3D" in loc or "ids=" in loc
print("IDS + MASKE + DUNKEL OK")

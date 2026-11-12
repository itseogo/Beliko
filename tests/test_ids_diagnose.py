"""Test: IDS-Verbindungstest, Selbsttest der Rückgabe, GET-Aufruf und Versionsauswahl (mit einem kleinen Schein-Shop)."""
import html as H, os, re, sys, tempfile, threading
from http.server import BaseHTTPRequestHandler, HTTPServer
os.environ["EINKAUF_DATA"] = tempfile.mkdtemp(prefix="einkauf-test-")
os.environ["NO_PROXY"] = os.environ["no_proxy"] = "127.0.0.1,localhost"
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from urllib.parse import parse_qs, urlparse
DB = ({"type": "mariadb", "host": "127.0.0.1", "port": "3306", "name": "einkauf", "user": "einkauf", "password": "T3stPw!x"}
      if os.environ.get("TEST_DB") == "maria" else {"type": "sqlite"})
from einkauf import create_app, ids

# ---- Schein-Shop: antwortet auf SV/LI wie ein IDS-Shop, unter /normal wie eine gewöhnliche Webseite
EMPFANGEN = []
class Shop(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_POST(self):
        laenge = int(self.headers.get("Content-Length", 0)); body = self.rfile.read(laenge)
        felder = {n: w.decode() for n, w in ids.formular_teile(self.headers.get("Content-Type", ""), body)}
        EMPFANGEN.append((self.path, felder))
        if self.path.startswith("/normal"):
            antwort, typ = b"<!doctype html><html><body><h1>Willkommen im Shop</h1><script>x()</script></body></html>", "text/html"
        elif felder.get("action") == "SV":
            antwort, typ = "<Schnittstellenversionen><Version>2.0</Version><Version>2.5</Version></Schnittstellenversionen>".encode(), "text/xml"
        elif felder.get("action") == "LI":
            antwort, typ = ("<Logininformationen><Kundennummer_erforderlich>true</Kundennummer_erforderlich><Benutzername_erforderlich>true</Benutzername_erforderlich>"
                            "<Passwort_erforderlich>true</Passwort_erforderlich></Logininformationen>").encode(), "text/xml"
        else:
            antwort, typ = b"<html>Shop</html>", "text/html"
        self.send_response(200); self.send_header("Content-Type", typ); self.send_header("Content-Length", str(len(antwort))); self.end_headers(); self.wfile.write(antwort)
server = HTTPServer(("127.0.0.1", 0), Shop); PORT = server.server_address[1]
threading.Thread(target=server.serve_forever, daemon=True).start()
BASIS = f"http://127.0.0.1:{PORT}"

app = create_app(); c = app.test_client()
tok = lambda h: re.search(r'name="_csrf" value="([^"]+)"', h).group(1)
G = lambda u, cl=None: (cl or c).get(u, follow_redirects=True).get_data(as_text=True)
def P(url, data, page=None, cl=None, folgen=True):
    cl = cl or c
    return cl.post(url, data=dict(data, _csrf=tok(cl.get(page or url).get_data(as_text=True))), follow_redirects=folgen)
def liefer(**kw):
    daten = {"name": "Fega", "active": "1", "ids_url": BASIS + "/ids", "ids_kndnr": "108690", "ids_benutzer": "benutzer1", "ids_passwort": "geheim-pw",
             "ids_version": "2.5", "ids_preis_modus": "gesamt", "ids_aufruf": "post"}; daten.update(kw); return daten

P("/setup/", DB); P("/setup/admin", {"username": "chris", "password": "geheim1234", "password2": "geheim1234"})
P("/einstellungen/lieferanten/neu", liefer())

# ---- Verbindungstest: gute IDS-Adresse
h = P("/einstellungen/lieferanten/1/ids-test", {}, page="/einstellungen/lieferanten/1").get_data(as_text=True)
assert "verhält sich wie ein IDS-Zugang" in h and "2.0, 2.5" in h
assert "Eingestellte Version <b>2.5</b> wird vom Shop unterstützt" in h
assert "Kundennummer <b>ja</b>" in h and "Passwort <b>ja</b>" in h
assert "••••••••" in h and "geheim-pw" not in h                                           # Passwort wird nie angezeigt
sv = [f for p, f in EMPFANGEN if f.get("action") == "SV"][0]
assert sv["kndnr"] == "108690" and sv["name_kunde"] == "benutzer1" and sv["pw_kunde"] == "geheim-pw"   # Shop bekam die Anmeldung
# Version, die der Shop nicht kennt
P("/einstellungen/lieferanten/1", liefer(ids_version="2.3"), page="/einstellungen/lieferanten/1")
h = P("/einstellungen/lieferanten/1/ids-test", {}, page="/einstellungen/lieferanten/1").get_data(as_text=True)
assert "unterstützt laut Antwort nur die Versionen" in h and "2.3" in h
# Fehlende Angaben werden benannt
P("/einstellungen/lieferanten/1", liefer(ids_kndnr="", ids_version="2.5"), page="/einstellungen/lieferanten/1")
assert "Es fehlt die Kundennummer" in P("/einstellungen/lieferanten/1/ids-test", {}, page="/einstellungen/lieferanten/1").get_data(as_text=True)
# Normale Webseite statt IDS
P("/einstellungen/lieferanten/1", liefer(ids_url=BASIS + "/normal"), page="/einstellungen/lieferanten/1")
h = P("/einstellungen/lieferanten/1/ids-test", {}, page="/einstellungen/lieferanten/1").get_data(as_text=True)
assert "Keine IDS-Antwort erhalten" in h and "normalen Webseite" in h and "Willkommen im Shop" in h and "x()" not in h      # Skript wird nicht angezeigt
# Nicht erreichbar
P("/einstellungen/lieferanten/1", liefer(ids_url="http://127.0.0.1:9/ids"), page="/einstellungen/lieferanten/1")
h = P("/einstellungen/lieferanten/1/ids-test", {}, page="/einstellungen/lieferanten/1").get_data(as_text=True)
assert "Verbindung nicht möglich" in h and "Keine IDS-Antwort erhalten" in h
# ohne Adresse
P("/einstellungen/lieferanten/1", liefer(ids_url=""), page="/einstellungen/lieferanten/1")
assert "zuerst die IDS-Adresse" in P("/einstellungen/lieferanten/1/ids-test", {}, page="/einstellungen/lieferanten/1").get_data(as_text=True)

# ---- Aufruf per GET und Version "nicht senden"
P("/einstellungen/lieferanten/1", liefer(ids_aufruf="get", ids_version="2.0"), page="/einstellungen/lieferanten/1")
r = P("/ids/start/1", {}, page="/ids", folgen=False)
assert r.status_code == 303
q = urlparse(r.headers["Location"]); p = parse_qs(q.query)
assert q.netloc == f"127.0.0.1:{PORT}" and q.path == "/ids" and p["action"] == ["WKE"] and p["version"] == ["2.0"]
assert p["kndnr"] == ["108690"] and p["name_kunde"] == ["benutzer1"] and p["pw_kunde"] == ["geheim-pw"]
assert re.fullmatch(r"http://localhost/ids/rueckgabe/[0-9a-f]{32}", p["hookurl"][0])
P("/einstellungen/lieferanten/1", liefer(ids_aufruf="get", ids_version="", ids_url=BASIS + "/ids?mandant=7"), page="/einstellungen/lieferanten/1")
r = P("/ids/start/1", {}, page="/ids", folgen=False); p = parse_qs(urlparse(r.headers["Location"]).query)
assert "version" not in p and p["mandant"] == ["7"] and p["action"] == ["WKE"]                 # bestehende Parameter der Adresse bleiben
P("/einstellungen/lieferanten/1", liefer(ids_aufruf="post", ids_version=""), page="/einstellungen/lieferanten/1")
h = P("/ids/start/1", {}, page="/ids").get_data(as_text=True)
assert 'name="action" value="WKE"' in h and 'name="version"' not in h and 'method="post"' in h
P("/einstellungen/lieferanten/1", liefer(ids_version="9.9"), page="/einstellungen/lieferanten/1")
assert 'name="version" value="2.5"' in P("/ids/start/1", {}, page="/ids").get_data(as_text=True)    # ungültige Version -> Standard

# ---- Selbsttest der Rückgabe über den Browserweg
h = P("/ids/selbsttest/1", {}, page="/ids").get_data(as_text=True)
hook = re.search(r'<form id="test" method="post" action="([^"]+)"', h).group(1)
xml = H.unescape(re.search(r'name="warenkorb" value="([^"]*)"', h).group(1))
assert re.fullmatch(r"http://localhost/ids/rueckgabe/[0-9a-f]{32}", hook) and "Testartikel" in xml
r = c.post(urlparse(hook).path, data={"warenkorb": xml}, content_type="multipart/form-data", follow_redirects=True)
h = r.get_data(as_text=True)
assert "Testartikel (Selbsttest der Rückgabe)" in h and 'value="TEST-1"' in h and "Selbsttest" in h and 'value="10"' in h
# ---- Rechte: Verbindungstest nur für Admins, Selbsttest für Einkäufer
P("/einstellungen/benutzer/neu", {"username": "emma", "password": "passwort123", "role": "einkaeufer"}, page="/einstellungen/benutzer/neu")
em = app.test_client(); P("/login", {"username": "emma", "password": "passwort123"}, page="/login", cl=em)
assert em.post("/einstellungen/lieferanten/1/ids-test", data={"_csrf": tok(em.get("/ids").get_data(as_text=True))}).status_code == 403
assert "Selbsttest der Rückgabe" in P("/ids/selbsttest/1", {}, page="/ids", cl=em).get_data(as_text=True)
assert "Im Shop fehlt der Button" in G("/ids") and "Verbindungstest" in G("/ids")
print("IDS-DIAGNOSE OK")

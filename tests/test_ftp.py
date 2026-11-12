"""Test: Abruf von Lieferantendateien per FTP, FTPS und Ordner, Dateiliste, Zuordnung zur Bestellung, Planer.
Braucht pyftpdlib (und für FTPS pyOpenSSL): pip install pyftpdlib pyopenssl. Ohne pyftpdlib wird der Test übersprungen."""
import os, re, sys, tempfile, threading
from datetime import datetime, timedelta
os.environ["EINKAUF_DATA"] = tempfile.mkdtemp(prefix="einkauf-test-")
os.environ["EINKAUF_KEIN_PLANER"] = "1"
HIER = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HIER, "..")); sys.path.insert(0, HIER)
try:
    from pyftpdlib.authorizers import DummyAuthorizer
    from pyftpdlib.handlers import FTPHandler
    from pyftpdlib.servers import ThreadedFTPServer
except ImportError:
    print("FTP-TEST ÜBERSPRUNGEN (pyftpdlib fehlt)"); sys.exit(0)
try:
    from pyftpdlib.handlers import TLS_FTPHandler
    import OpenSSL  # noqa: F401
    TLS = True
except ImportError:
    TLS = False
from pathlib import Path
from make_ugl import beispiel
DB = ({"type": "mariadb", "host": "127.0.0.1", "port": "3306", "name": "einkauf", "user": "einkauf", "password": "T3stPw!x"}
      if os.environ.get("TEST_DB") == "maria" else {"type": "sqlite"})
from einkauf import create_app, lieferantendateien, planer
from einkauf.models import Order, Supplier, SupplierFile

# ---- Schein-Server: Verzeichnisse wie bei Fega (/QDLS/OUT/50/108690/), nur lesbar
WURZEL = Path(tempfile.mkdtemp(prefix="ftproot-"))
AUS = WURZEL / "QDLS/OUT/50/108690"; AUS.mkdir(parents=True); (WURZEL / "QDLS/IN/50/108690").mkdir(parents=True)
(AUS / "B0261027.001").write_bytes(beispiel())
(AUS / "B0261030.002").write_bytes(beispiel(positionen=[(9, "9104201", "PHOE Gehaeuse", "RPI-BC", 1, "STK")]))
(AUS / "README.txt").write_bytes(b"Das ist keine UGL-Datei.")
(AUS / "Datei mit Leerzeichen.001").write_bytes(b"x")
(AUS / "GROSS.001").write_bytes(b"A" * 6000)
(WURZEL / "QDLS/IN/50/108690/B-eingang.001").write_bytes(b"nicht abrufen")
lieferantendateien.MAX_BYTES = 5000
auth = DummyAuthorizer(); auth.add_user("lief", "pw", str(WURZEL), perm="elr")
class H(FTPHandler): authorizer = auth
srv = ThreadedFTPServer(("127.0.0.1", 0), H); PORT = srv.address[1]
threading.Thread(target=srv.serve_forever, daemon=True).start()
PORT_TLS = None
if TLS:
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID
    schluessel = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
    zert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(schluessel.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(datetime.utcnow() - timedelta(days=1)).not_valid_after(datetime.utcnow() + timedelta(days=2)).sign(schluessel, hashes.SHA256()))
    pem = WURZEL.parent / "ftps.pem"
    pem.write_bytes(zert.public_bytes(serialization.Encoding.PEM) + schluessel.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL, serialization.NoEncryption()))
    class HT(TLS_FTPHandler):
        authorizer = auth; certfile = str(pem); tls_control_required = True; tls_data_required = True
    srv2 = ThreadedFTPServer(("127.0.0.1", 0), HT); PORT_TLS = srv2.address[1]
    threading.Thread(target=srv2.serve_forever, daemon=True).start()

app = create_app(); c = app.test_client()
tok = lambda h: re.search(r'name="_csrf" value="([^"]+)"', h).group(1)
G = lambda u, cl=None: (cl or c).get(u, follow_redirects=True).get_data(as_text=True)
def P(url, data, page=None, cl=None):
    cl = cl or c
    return cl.post(url, data=dict(data, _csrf=tok(cl.get(page or url).get_data(as_text=True))), follow_redirects=True).get_data(as_text=True)
def db(): return app.extensions["SessionLocal"]()
def lief(**kw):
    d = {"name": "Fega", "active": "1", "ugl_verfahren": "ftp", "ugl_server": "127.0.0.1", "ugl_port": str(PORT), "ugl_pfad_ausgang": "/QDLS/OUT/50/108690/",
         "ugl_pfad_eingang": "/QDLS/IN/50/108690/", "ugl_benutzer": "lief", "ugl_passwort": "pw", "ids_preis_modus": "gesamt", "ids_version": "2.5"}
    d.update(kw); return d
SEITE = "/einstellungen/lieferanten/1"

P("/setup/", DB); P("/setup/admin", {"username": "chris", "password": "geheim1234", "password2": "geheim1234"})
P("/einstellungen/lieferanten/neu", lief())

# ---- Verbindungstest
h = P(SEITE + "/ftp-test", {}, page=SEITE)
assert "Verbindung in Ordnung" in h and "B0261027.001" in h and "B0261030.002" in h and "B-eingang" not in h
assert "Im Ordner liegen 5 Dateien" in h and "1 mit einem Namen" in h and "Datei mit Leerzeichen" not in h        # unsichere Namen werden nicht angeboten
for aenderung, erwartet in [({"ugl_passwort": "falsch"}, "Anmeldung wurde abgelehnt"), ({"ugl_pfad_ausgang": "/gibt/es/nicht/"}, "nicht gefunden"),
                            ({"ugl_port": "9"}, "abgelehnt" ), ({"ugl_server": "gibt-es-nicht.invalid"}, "nicht gefunden")]:
    P(SEITE, lief(**aenderung), page=SEITE)
    h = P(SEITE + "/ftp-test", {}, page=SEITE); assert "Verbindung nicht möglich" in h and erwartet in h, (aenderung, re.sub(r"<[^>]+>", " ", h)[-400:])
P(SEITE, lief(), page=SEITE)
P(SEITE, lief(ugl_verfahren="sftp"), page=SEITE); assert "SFTP ist noch nicht umgesetzt" in P(SEITE + "/ftp-test", {}, page=SEITE)
P(SEITE, lief(), page=SEITE)

# ---- Abruf
assert "Keine Dateien" in G("/dateien") and "Lieferantendateien</a>" in G("/")
h = P("/dateien/abrufen", {"lieferant": "1"}, page="/dateien")
assert "Fega: 3 neue Dateien, 0 schon bekannt, 2 übersprungen" in h, re.sub(r"<[^>]+>", " ", h)[300:900]       # 001, 002, README; GROSS (zu groß) und der Name mit Leerzeichen werden übersprungen
with db() as s:
    fs = {f.name: f for f in s.query(SupplierFile).all()}
    assert set(fs) == {"B0261027.001", "B0261030.002", "README.txt"}
    a = fs["B0261027.001"]; assert (a.status, a.belegnr, a.belegart, a.kennung, a.positionen) == ("neu", "4755816401", "AB", "LS", 9) and a.datei_datum.isoformat() == "2026-10-27"
    assert fs["B0261030.002"].positionen == 1 and fs["README.txt"].status == "fehler" and "Keine lesbare UGL-Datei" in fs["README.txt"].hinweis
    assert (lieferantendateien.config.DATA_DIR / a.pfad).read_bytes() == beispiel()                       # Inhalt unverändert gespeichert
    assert s.get(Supplier, 1).ugl_letzter_abruf and "3 neu" in s.get(Supplier, 1).ugl_abruf_status
h = P("/dateien/abrufen", {"lieferant": "1"}, page="/dateien"); assert "0 neue Dateien, 3 schon bekannt" in h                  # nichts doppelt
assert sorted(p.name for p in AUS.iterdir()) == sorted(["B0261027.001", "B0261030.002", "README.txt", "Datei mit Leerzeichen.001", "GROSS.001"])   # Server unberührt
h = G("/dateien"); assert "B0261027.001" in h and "4755816401" in h and "README.txt" not in h                   # Standardliste: nur Neue lesbare
assert "README.txt" in G("/dateien?status=fehler") and "B0261030.002" in G("/dateien?status=alle")
assert re.search(r'Lieferantendateien</a>|Lieferantendateien <span class="n">2</span>', G("/")) and '<span class="n">2</span>' in G("/")

# ---- Zuordnung zur Bestellung
keys = ["artikelnr", "bezeichnung", "menge", "einheit", "preis", "termin", "projekt", "kommission", "hinweis"]
def bestellung(nr, *pos):
    d = {"supplier_id": "1", "bestellnr": nr, "bestelldatum": "2026-10-20", "schon_bestellt": "1"}
    d.update({f"row_{k}": [p[i] for p in pos] for i, k in enumerate(keys)}); P("/bestellungen/neu", d, page="/bestellungen/neu")
z = lambda art, bez, m: (art, bez, m, "Stück", "1,00", "", "", "", "")
bestellung("B-1", z("556023", "Abdeckung", "5"), z("056309", "Schraube", "100"), z("057433", "Kupferband", "3"), z("115418", "Verteiler", "1"), z("853346", "F-Stecker", "10"),
           z("263595", "FI", "2"), z("557607", "Leitungsauslass", "3"), z("567465", "Bit-Set", "1"), z("9104201", "Gehäuse", "1"), z("256019", "Taster", "1"))
bestellung("B-2", z("X1", "Fremdteil", "1"))
with db() as s: fid1 = s.query(SupplierFile).filter(SupplierFile.name == "B0261027.001").one().id; fid2 = s.query(SupplierFile).filter(SupplierFile.name == "B0261030.002").one().id; fid3 = s.query(SupplierFile).filter(SupplierFile.name == "README.txt").one().id
h = G(f"/dateien/{fid1}")
assert "Belegart laut Datei <b>AB</b>" in h and "9 von 9 Positionen" in h and "B-1" in h and "B-2" not in h and h.index("9 Positionen der Datei") < len(h)
assert "Keine Bestellung dieses Lieferanten" not in h
h = P(f"/dateien/{fid1}/pruefen", {"bestellung": "1"}, page=f"/dateien/{fid1}")
assert "Lieferantendatei prüfen" in h and f'name="datei_id" value="{fid1}"' in h and h.count('name="pos"') == 9
token = re.search(r'name="token" value="([0-9a-f]{32})"', h).group(1)
h = c.post("/bestellungen/1/ugl/uebernehmen", data={"_csrf": tok(c.get("/bestellungen/1").get_data(as_text=True)), "token": token, "dateiname": "B0261027.001", "datei_id": str(fid1),
        "aktion": "lieferschein", "vermerken": "1", "pos": [str(i) for i in (1, 2, 3, 4, 5, 6, 7, 8, 10)], "lieferschein_nr": "4755816401", "datum": "2026-10-27"}, follow_redirects=True).get_data(as_text=True)
assert "Wareneingang gebucht" in h and "Teillieferung" in h
with db() as s:
    f = s.get(SupplierFile, fid1); assert (f.status, f.bestell_id, f.aktion) == ("verarbeitet", 1, "lieferschein") and f.verarbeitet_am
assert "als Lieferschein gebucht" in G(f"/dateien/{fid1}") and "B0261027.001" not in G("/dateien")                 # verschwindet aus „Neu“
assert "B0261027.001" in G("/dateien?status=verarbeitet")
# zweite Datei: Position 9 -> Bestellung wird komplett
h = G(f"/dateien/{fid2}"); assert "1 von 1 Positionen" in h
h = P(f"/dateien/{fid2}/pruefen", {"bestellung": "1"}, page=f"/dateien/{fid2}"); token = re.search(r'name="token" value="([0-9a-f]{32})"', h).group(1)
h = c.post("/bestellungen/1/ugl/uebernehmen", data={"_csrf": tok(c.get("/bestellungen/1").get_data(as_text=True)), "token": token, "dateiname": "B0261030.002", "datei_id": str(fid2),
        "aktion": "lieferschein", "pos": ["9"], "lieferschein_nr": "4755816402", "datum": "2026-10-30"}, follow_redirects=True).get_data(as_text=True)
assert "Komplett geliefert" in h
# falsche Zuordnung / ohne Auswahl
assert "Bitte eine Bestellung wählen" in P(f"/dateien/{fid3}/pruefen", {}, page=f"/dateien/{fid3}")
# Ignorieren und zurück
assert "Datei ignoriert" in P(f"/dateien/{fid3}/status", {"aktion": "ignorieren"}, page=f"/dateien/{fid3}") and "README.txt" in G("/dateien?status=ignoriert")
assert "wieder auf „Neu“" in P(f"/dateien/{fid3}/status", {"aktion": "neu"}, page=f"/dateien/{fid3}")
assert "nicht möglich" in P(f"/dateien/{fid1}/status", {"aktion": "ignorieren"}, page=f"/dateien/{fid1}")          # Verarbeitetes bleibt verarbeitet

# ---- Planer: automatisch nach Zeitplan
(AUS / "B0261031.003").write_bytes(beispiel(positionen=[(1, "556023", "JUNG Abdeckung", "", 2, "STK")]))
P(SEITE, lief(ugl_auto_min="15"), page=SEITE)
with db() as s: assert s.get(Supplier, 1).ugl_auto_min == 15
assert planer.tick(app) == 0                                                                       # gerade erst abgerufen: noch nicht fällig
with db() as s: s.get(Supplier, 1).ugl_letzter_abruf = datetime.now() - timedelta(minutes=20); s.commit()
assert planer.tick(app) == 1
with db() as s: assert s.query(SupplierFile).filter(SupplierFile.name == "B0261031.003").count() == 1
assert planer.tick(app) == 0
P(SEITE, lief(ugl_auto_min="0"), page=SEITE)
with db() as s: s.get(Supplier, 1).ugl_letzter_abruf = datetime.now() - timedelta(days=2); s.commit()
assert planer.tick(app) == 0                                                                       # ohne Auto-Einstellung nie
P(SEITE, lief(ugl_auto_min="15", ugl_passwort="falsch"), page=SEITE)
with db() as s: s.get(Supplier, 1).ugl_letzter_abruf = None; s.commit()
assert planer.tick(app) == 1
with db() as s: assert "Anmeldung" in s.get(Supplier, 1).ugl_abruf_status                         # Fehler wird gemerkt, Planer läuft weiter

# ---- Ordner (z. B. Netzlaufwerk)
ordner = Path(tempfile.mkdtemp(prefix="lieferordner-")); (ordner / "L0261101.001").write_bytes(beispiel(positionen=[(1, "556023", "x", "", 1, "STK")]))
P("/einstellungen/lieferanten/neu", lief(name="Ordnerlieferant", ugl_verfahren="datei", ugl_pfad_ausgang=str(ordner), ugl_server="", ugl_port=""))
h = P("/dateien/abrufen", {"lieferant": "2"}, page="/dateien"); assert "Ordnerlieferant: 1 neue Dateien" in h
P("/einstellungen/lieferanten/2", lief(name="Ordnerlieferant", ugl_verfahren="datei", ugl_pfad_ausgang=str(ordner / "gibt-es-nicht")), page="/einstellungen/lieferanten/2")
assert "wurde nicht gefunden" in P("/dateien/abrufen", {"lieferant": "2"}, page="/dateien")

# ---- FTPS
if TLS:
    P(SEITE, lief(ugl_verfahren="ftps", ugl_port=str(PORT_TLS), ugl_tls_pruefen="1"), page=SEITE)
    h = P(SEITE + "/ftp-test", {}, page=SEITE); assert "Zertifikat" in h and "nicht vertrauenswürdig" in h, re.sub(r"<[^>]+>", " ", h)[-300:]
    P(SEITE, lief(ugl_verfahren="ftps", ugl_port=str(PORT_TLS), ugl_tls_pruefen="0"), page=SEITE)
    h = P(SEITE + "/ftp-test", {}, page=SEITE); assert "Verbindung in Ordnung" in h and "B0261027.001" in h
    (AUS / "B0261099.009").write_bytes(beispiel(positionen=[(1, "556023", "x", "", 1, "STK")]))
    assert "1 neue Dateien" in P("/dateien/abrufen", {"lieferant": "1"}, page="/dateien")
    print("(FTPS geprüft)")
else:
    print("(FTPS übersprungen: pyOpenSSL fehlt)")

# ---- Rechte
P("/einstellungen/benutzer/neu", {"username": "emma", "password": "passwort123", "role": "einkaeufer"}, page="/einstellungen/benutzer/neu")
P("/einstellungen/benutzer/neu", {"username": "lena", "password": "passwort123", "role": "leser"}, page="/einstellungen/benutzer/neu")
em, le = app.test_client(), app.test_client()
P("/login", {"username": "emma", "password": "passwort123"}, page="/login", cl=em); P("/login", {"username": "lena", "password": "passwort123"}, page="/login", cl=le)
assert em.post(SEITE + "/ftp-test", data={"_csrf": tok(em.get("/dateien").get_data(as_text=True))}).status_code == 403          # Test nur Admin
assert "Fega:" in P("/dateien/abrufen", {"lieferant": "1"}, page="/dateien", cl=em)                                         # Abruf: Einkäufer ja
assert le.get("/dateien").status_code == 200 and le.post("/dateien/abrufen", data={"_csrf": tok(le.get("/dateien").get_data(as_text=True))}).status_code == 403
assert "Jetzt alle abrufen" not in G("/dateien", le)
print("FTP-ABRUF OK")

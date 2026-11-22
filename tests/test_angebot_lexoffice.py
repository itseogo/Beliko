"""Test: Lokales Angebot im Projekt erstellen, bearbeiten und als Entwurf an Lexoffice (/v1/quotations) senden."""
import json
import os
import re
import sys
import tempfile
import threading
from decimal import Decimal
from http.server import BaseHTTPRequestHandler, HTTPServer

os.environ["EINKAUF_DATA"] = tempfile.mkdtemp(prefix="einkauf-angebot-test-")
HIER = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HIER, ".."))
sys.path.insert(0, HIER)

from einkauf import create_app, einstellungen, lexoffice, security
from einkauf.models import Contact, LexDocument

lexoffice.PAUSE = 0.0
lexoffice._schlafen = lambda _s: None

# Schein-Lexoffice-Server für POST /v1/quotations und GET /v1/quotations/<id>
EMPFAENGER = {"post_payload": None, "post_pfad": None}


class ScheinLexHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def do_POST(self):
        laenge = int(self.headers.get("Content-Length", "0"))
        body = json.loads(self.rfile.read(laenge).decode("utf-8"))
        EMPFAENGER["post_pfad"] = self.path
        EMPFAENGER["post_payload"] = body
        resp = {
            "id": "lex-quot-99887766",
            "resourceUri": "https://api.lexware.io/v1/quotations/lex-quot-99887766",
            "version": 1,
        }
        raw = json.dumps(resp).encode("utf-8")
        self.send_response(201)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        resp = {
            "id": "lex-quot-99887766",
            "version": 1,
            "voucherStatus": "draft",
            "voucherNumber": "AG-2026-9001",
            "updatedDate": "2026-11-22T17:40:00.000+01:00",
        }
        raw = json.dumps(resp).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


srv = HTTPServer(("127.0.0.1", 0), ScheinLexHandler)
port = srv.server_address[1]
threading.Thread(target=srv.serve_forever, daemon=True).start()

app = create_app()
c = app.test_client()
tok = lambda h: re.search(r'name="_csrf" value="([^"]+)"', h).group(1)
def G(url): return c.get(url, follow_redirects=True).get_data(as_text=True)
def P(url, data, page=None):
    t = tok(c.get(page or url).get_data(as_text=True))
    return c.post(url, data=dict(data, _csrf=t), follow_redirects=True).get_data(as_text=True)

P("/setup/", {"type": "sqlite"})
P("/setup/admin", {"username": "chris", "firma": "Elektro Test", "password": "geheim1234", "password2": "geheim1234"})

# Lexoffice-Kunde & Projekt anlegen + Schein-API konfigurieren
with app.app_context():
    with app.extensions["SessionLocal"]() as db_s:
        k = Contact(
            typ="firma", firma="Kunde Muster GmbH", ist_kunde=True,
            lexoffice_id="lex-contact-12345", re_strasse="Hauptstr. 1", re_plz="70173", re_ort="Stuttgart", re_land="DE",
        )
        db_s.add(k)
        einstellungen.schreiben(db_s, "lex_url", f"http://127.0.0.1:{port}")
        einstellungen.schreiben(db_s, "lex_key_enc", security.encrypt("test-api-key-123"))
        db_s.commit()
        cid = k.id

P("/projekte/neu", {"nummer": "P-2026-0050", "name": "Wallbox Garage", "contact_id": str(cid), "status": "aktiv"})

# 1. Button "+ Neues Angebot" im Projekt-Vorgang prüfen
h_proj = G("/projekte?p=1&tab=vorgang&status=alle")
assert "+ Neues Angebot" in h_proj
assert "/angebote/neu?p=1" in h_proj

# 2. Lokales Angebot als Entwurf erstellen (2 Positionen)
h_form = G("/angebote/neu?p=1")
assert "Kunde Muster GmbH (Stuttgart) ✓ Lexoffice" in h_form
t = tok(h_form)
h_neu = c.post("/angebote/neu?p=1", data={
    "_csrf": t,
    "project_id": "1",
    "contact_id": str(cid),
    "kunde_name": "Kunde Muster GmbH",
    "datum": "2026-11-22",
    "gueltig_bis": "2026-12-22",
    "mwst_satz": "19",
    "titel": "Angebot Wallbox 11 kW",
    "einleitung": "Gerne bieten wir an:",
    "schlusstext": "Zahlbar in 14 Tagen.",
    "pos_bez": ["Wallbox 11 kW", "Montage & Inbetriebnahme"],
    "pos_beschr": ["inkl. FI-Schutz", "Pauschal"],
    "pos_menge": ["1", "3"],
    "pos_einheit": ["Stück", "Std"],
    "pos_ep": ["850,00", "65,00"],
    "pos_rabatt": ["0", "10"],
    "pos_ka": ["material", "arbeit"],
    "aktion": "entwurf",
}, follow_redirects=True).get_data(as_text=True)

assert "Angebot als Entwurf in BeLiKo gespeichert" in h_neu
assert "An Lexoffice senden" in h_neu
assert "Wallbox 11 kW" in h_neu
assert "850,00" in h_neu

with app.app_context():
    with app.extensions["SessionLocal"]() as db_s:
        doc = db_s.query(LexDocument).first()
        assert doc is not None
        assert doc.ist_lokal is True
        assert doc.project_id == 1
        assert doc.netto == Decimal("1025.50")  # 850 + (3 * 65 * 0.9 = 175.50)
        assert doc.materialwert == Decimal("850.00")
        did = doc.id

# 3. Lokales Angebot bearbeiten
t = tok(G(f"/angebote/{did}/bearbeiten?von=1"))
h_edit = c.post(f"/angebote/{did}/bearbeiten?von=1", data={
    "_csrf": t,
    "project_id": "1",
    "contact_id": str(cid),
    "kunde_name": "Kunde Muster GmbH",
    "datum": "2026-11-22",
    "gueltig_bis": "2026-12-22",
    "mwst_satz": "19",
    "titel": "Angebot Wallbox 11 kW (v2)",
    "pos_bez": ["Wallbox 11 kW"],
    "pos_beschr": ["inkl. FI-Schutz"],
    "pos_menge": ["2"],
    "pos_einheit": ["Stück"],
    "pos_ep": ["800,00"],
    "pos_rabatt": ["0"],
    "pos_ka": ["material"],
    "aktion": "entwurf",
}, follow_redirects=True).get_data(as_text=True)
assert "Angebot gespeichert." in h_edit
assert "1.600,00" in h_edit

# 4. Angebot an Lexoffice senden (POST /angebote/<did>/lexoffice)
h_send = P(f"/angebote/{did}/lexoffice?von=1", {}, page=f"/lexoffice/belege/{did}?von=1")
assert "als Entwurf an Lexoffice übertragen" in h_send
assert "AG-2026-9001" in h_send
assert "An Lexoffice senden" not in h_send  # Nicht doppelt sendbar!

# Payload prüfen, der an Lexoffice ging
assert EMPFAENGER["post_pfad"] == "/v1/quotations"
pl = EMPFAENGER["post_payload"]
assert pl["address"] == {"contactId": "lex-contact-12345"}
assert pl["title"] == "Angebot Wallbox 11 kW (v2)"
assert len(pl["lineItems"]) == 1
assert pl["lineItems"][0]["quantity"] == 2.0
assert pl["lineItems"][0]["unitPrice"]["netAmount"] == 800.0
assert pl["lineItems"][0]["unitPrice"]["taxRatePercentage"] == 19.0

with app.app_context():
    with app.extensions["SessionLocal"]() as db_s:
        doc = db_s.get(LexDocument, did)
        assert doc.ist_lokal is False
        assert doc.lexoffice_id == "lex-quot-99887766"
        assert doc.nummer == "AG-2026-9001"
        assert doc.status == "draft"

srv.shutdown()
print("ANGEBOT ERSTELLEN + BEARBEITEN + LEXOFFICE SENDEN TESTS OK")

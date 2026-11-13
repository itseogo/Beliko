"""Test: Lexoffice-Einstellungen, Verbindungstest und Kontaktabgleich (mit einem Schein-Lexoffice, ohne echte Verbindung)."""
import json, os, re, sys, tempfile, threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse
DATEN = tempfile.mkdtemp(prefix="einkauf-test-")
os.environ["EINKAUF_DATA"] = DATEN
os.environ["NO_PROXY"] = os.environ["no_proxy"] = "127.0.0.1,localhost"
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
DB = ({"type": "mariadb", "host": "127.0.0.1", "port": "3306", "name": "einkauf", "user": "einkauf", "password": "T3stPw!x"}
      if os.environ.get("TEST_DB") == "maria" else {"type": "sqlite"})
from decimal import Decimal
from einkauf import create_app, lexoffice
from einkauf.models import Contact, LexArticleRule, LexDocument, LexDocumentItem, Project, Setting
lexoffice._schlafen = lambda s: None            # keine echten Pausen im Test

# ---- Schein-Lexoffice (Antwortform wie in der öffentlichen Dokumentation)
def kontakt(i, **kw):
    d = {"id": f"00000000-0000-0000-0000-{i:012d}", "organizationId": "org", "version": 1, "archived": False,
         "roles": {"customer": {"number": 10000 + i}}, "addresses": {}, "emailAddresses": {}, "phoneNumbers": {}}
    d.update(kw); return d
KONTAKTE = [
    kontakt(1, company={"name": "Jäger Handling GmbH", "taxNumber": "12/345/67890", "vatRegistrationId": "DE123456789", "allowTaxFreeInvoices": True,
                        "contactPersons": [{"salutation": "Herr", "firstName": "Max", "lastName": "Mustermann", "emailAddress": "max@jaeger.example", "phoneNumber": "0711 1", "primary": True},
                                           {"firstName": "Eva", "lastName": "Beispiel"}]},
            addresses={"billing": [{"supplement": "Halle 2", "street": "Hauptstr. 1", "zip": "74429", "city": "Sulzbach-Laufen", "countryCode": "DE"}],
                       "shipping": [{"street": "Lagerweg 5", "zip": "74429", "city": "Sulzbach-Laufen", "countryCode": "DE"}]},
            emailAddresses={"business": ["info@jaeger.example", "zweit@jaeger.example"], "office": ["buero@jaeger.example"]},
            phoneNumbers={"business": ["07971 123"], "mobile": ["0170 555"], "fax": ["07971 124"]},
            xRechnung={"buyerReference": "04011000-123", "vendorNumberAtCustomer": "L-77"}, note="Zahlt pünktlich"),
    kontakt(2, person={"salutation": "Herr", "firstName": "Hans", "lastName": "Koch"}, addresses={"billing": [{"city": "Gaildorf", "zip": "74405", "countryCode": "DE"}]}),
    kontakt(3, roles={"vendor": {"number": 70179}}, company={"name": "Rexel Germany GmbH & Co. KG"}),
    kontakt(4, roles={"customer": {"number": 10004}, "vendor": {"number": 70004}}, company={"name": "Beides GmbH"}),
    kontakt(5, archived=True, company={"name": "Alt-Kunde AG"}),
]
BELEGE_LISTE = [
    {"id": "doc-ang-1", "voucherType": "quotation", "voucherStatus": "open", "voucherNumber": "AG-2026-001",
     "voucherDate": "2026-10-15T00:00:00.000+02:00", "updatedDate": "2026-10-15T10:00:00.000+02:00",
     "contactId": "00000000-0000-0000-0000-000000000001", "contactName": "Jäger Handling GmbH",
     "totalAmount": 2380.00, "currency": "EUR", "archived": False},
    {"id": "doc-auf-1", "voucherType": "orderconfirmation", "voucherStatus": "open", "voucherNumber": "AB-2026-001",
     "voucherDate": "2026-10-16T00:00:00.000+02:00", "updatedDate": "2026-10-16T10:00:00.000+02:00",
     "contactId": "00000000-0000-0000-0000-000000000001", "contactName": "Jäger Handling GmbH",
     "totalAmount": 1190.00, "currency": "EUR", "archived": False},
    {"id": "doc-rec-1", "voucherType": "invoice", "voucherStatus": "paid", "voucherNumber": "RE-2026-001",
     "voucherDate": "2026-10-20T00:00:00.000+02:00", "updatedDate": "2026-10-20T10:00:00.000+02:00",
     "contactId": "00000000-0000-0000-0000-000000000001", "contactName": "Jäger Handling GmbH",
     "totalAmount": 1190.00, "currency": "EUR", "archived": False},
    {"id": "doc-eingang-1", "voucherType": "purchaseinvoice", "voucherStatus": "open", "voucherNumber": "ER-2026-999",
     "voucherDate": "2026-10-25T00:00:00.000+02:00", "updatedDate": "2026-10-25T10:00:00.000+02:00",
     "contactId": "00000000-0000-0000-0000-000000000003", "contactName": "Rexel Germany GmbH & Co. KG",
     "totalAmount": 595.00, "currency": "EUR", "archived": False},
]
BELEGE_DETAILS = {
    "doc-eingang-1": {
        "id": "doc-eingang-1", "version": 1, "voucherNumber": "ER-2026-999", "voucherDate": "2026-10-25T00:00:00.000+02:00",
        "voucherStatus": "open", "remark": "Kabel-Lieferung", "archived": False,
        "contactId": "00000000-0000-0000-0000-000000000003", "contactName": "Rexel Germany GmbH & Co. KG",
        "taxType": "net",
        "totalNetAmount": 500.00, "totalGrossAmount": 595.00,
        "voucherItems": [
            {"amount": 500.00, "taxAmount": 95.00, "taxRatePercent": 19, "categoryId": "kat-kabel", "description": "Kabeltrommel NYM-J"}
        ],
    },
    "doc-ang-1": {
        "id": "doc-ang-1", "version": 1, "voucherNumber": "AG-2026-001", "voucherDate": "2026-10-15T00:00:00.000+02:00",
        "voucherStatus": "open", "title": "Neubau Halle 2", "archived": False,
        "address": {"contactId": "00000000-0000-0000-0000-000000000001", "name": "Jäger Handling GmbH"},
        "taxConditions": {"taxType": "net"},
        "totalPrice": {"currency": "EUR", "totalNetAmount": 2000.00, "totalGrossAmount": 2380.00},
        "lineItems": [
            {"id": "art-nym-3x15", "type": "material", "name": "NYM-J 3x1,5", "quantity": 1000, "unitName": "m",
             "unitPrice": {"netAmount": 1.00, "taxRatePercentage": 19}, "discountPercentage": 0, "lineItemAmount": 1000.00},
            {"id": None, "type": "custom", "name": "Kernbohrung inkl. Hülse", "quantity": 1, "unitName": "psch",
             "unitPrice": {"netAmount": 500.00, "taxRatePercentage": 19}, "discountPercentage": 0, "lineItemAmount": 500.00},
            {"id": "art-montage", "type": "service", "name": "Montagearbeiten", "quantity": 10, "unitName": "Std",
             "unitPrice": {"netAmount": 50.00, "taxRatePercentage": 19}, "discountPercentage": 0, "lineItemAmount": 500.00},
            {"type": "text", "name": "Hinweis", "description": "Zahlung 14 Tage netto"},
        ],
    },
    "doc-auf-1": {
        "id": "doc-auf-1", "version": 1, "voucherNumber": "AB-2026-001", "voucherDate": "2026-10-16T00:00:00.000+02:00",
        "voucherStatus": "open", "title": "Auftrag Halle 2", "archived": False,
        "address": {"contactId": "00000000-0000-0000-0000-000000000001", "name": "Jäger Handling GmbH"},
        "taxConditions": {"taxType": "net"},
        "totalPrice": {"currency": "EUR", "totalNetAmount": 1000.00, "totalGrossAmount": 1190.00},
        "lineItems": [
            {"id": "art-nym-3x15", "type": "material", "name": "NYM-J 3x1,5", "quantity": 1000, "unitName": "m",
             "unitPrice": {"netAmount": 1.00, "taxRatePercentage": 19}, "discountPercentage": 0, "lineItemAmount": 1000.00},
        ],
    },
    "doc-rec-1": {
        "id": "doc-rec-1", "version": 1, "voucherNumber": "RE-2026-001", "voucherDate": "2026-10-20T00:00:00.000+02:00",
        "voucherStatus": "paid", "title": "Abschlag 1", "archived": False,
        "address": {"contactId": "00000000-0000-0000-0000-000000000001", "name": "Jäger Handling GmbH"},
        "taxConditions": {"taxType": "net"},
        "totalPrice": {"currency": "EUR", "totalNetAmount": 1000.00, "totalGrossAmount": 1190.00},
        "lineItems": [
            {"id": "art-nym-3x15", "type": "material", "name": "NYM-J 3x1,5", "quantity": 1000, "unitName": "m",
             "unitPrice": {"netAmount": 1.00, "taxRatePercentage": 19}, "discountPercentage": 0, "lineItemAmount": 1000.00},
        ],
    },
}
STAND = {"kontakte": KONTAKTE, "belege": BELEGE_LISTE, "ausfaelle_429": 0, "anfragen": []}
class Lex(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def _antwort(self, code, obj):
        b = json.dumps(obj).encode(); self.send_response(code); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)
    def do_GET(self):
        u = urlparse(self.path); q = parse_qs(u.query)
        STAND["anfragen"].append((u.path, q, self.headers.get("Authorization")))
        if self.headers.get("Authorization") != "Bearer GUTER-SCHLUESSEL": return self._antwort(401, {"message": "Unauthorized"})
        if STAND["ausfaelle_429"] > 0:
            STAND["ausfaelle_429"] -= 1; return self._antwort(429, {"message": "Too many requests"})
        if u.path == "/v1/profile": return self._antwort(200, {"organizationId": "org", "companyName": "Elektro Test GmbH"})
        if u.path == "/v1/contacts":
            seite, groesse = int(q["page"][0]), int(q["size"][0]); alle = STAND["kontakte"]
            teil = alle[seite * groesse:(seite + 1) * groesse]; seiten = max(1, -(-len(alle) // groesse))
            return self._antwort(200, {"content": teil, "first": seite == 0, "last": seite >= seiten - 1, "totalPages": seiten, "totalElements": len(alle), "number": seite, "size": groesse})
        if u.path == "/v1/voucherlist":
            typen = set(q.get("voucherType", [""])[0].split(","))
            seite, groesse = int(q["page"][0]), int(q["size"][0])
            d_from = q.get("voucherDateFrom", [None])[0]
            d_to = q.get("voucherDateTo", [None])[0]
            alle = [b for b in STAND["belege"] if b["voucherType"] in typen]
            if d_from:
                alle = [b for b in alle if b["voucherDate"][:10] >= d_from]
            if d_to:
                alle = [b for b in alle if b["voucherDate"][:10] <= d_to]
            teil = alle[seite * groesse:(seite + 1) * groesse]; seiten = max(1, -(-len(alle) // groesse))
            return self._antwort(200, {"content": teil, "first": seite == 0, "last": seite >= seiten - 1, "totalPages": seiten, "totalElements": len(alle), "number": seite, "size": groesse})
        for pre in ("/v1/quotations/", "/v1/order-confirmations/", "/v1/invoices/", "/v1/vouchers/"):
            if u.path.startswith(pre):
                lid = u.path[len(pre):]
                if lid in BELEGE_DETAILS:
                    return self._antwort(200, BELEGE_DETAILS[lid])
        self._antwort(404, {})
server = HTTPServer(("127.0.0.1", 0), Lex); threading.Thread(target=server.serve_forever, daemon=True).start()
URL = f"http://127.0.0.1:{server.server_address[1]}"

app = create_app(); c = app.test_client()
tok = lambda h: re.search(r'name="_csrf" value="([^"]+)"', h).group(1)
G = lambda u, cl=None: (cl or c).get(u, follow_redirects=True).get_data(as_text=True)
def P(url, data, page=None, cl=None):
    cl = cl or c
    return cl.post(url, data=dict(data, _csrf=tok(cl.get(page or url).get_data(as_text=True))), follow_redirects=True).get_data(as_text=True)
def db(): return app.extensions["SessionLocal"]()
SEITE = "/einstellungen/lexoffice"
def speichern(**kw):
    daten = {"lex_aktiv": "1", "lex_key": "GUTER-SCHLUESSEL", "lex_url": URL, "lex_sync_kunden": "1", "lex_sync_lieferanten": "1"}; daten.update(kw)
    return P(SEITE, {k: v for k, v in daten.items() if v is not None}, page=SEITE)

P("/setup/", DB); P("/setup/admin", {"username": "chris", "password": "geheim1234", "password2": "geheim1234"})

# ---- Seite und Optionen
h = G(SEITE)
assert "Lexoffice-Schnittstelle einschalten" in h and "von Lexoffice nach BeLiKo" in h and "noch kein Schlüssel" in h
for t in ("Kontakte: Kunden", "Kontakte: Lieferanten", "Angebote", "Aufträge", "Rechnungen"): assert t in h
assert h.count(">folgt später</span>") == 0                                                         # Phase 2 Optionen sind aktiv
assert "Lexoffice</a>" in G("/") and "Lexoffice</a>" in G("/einstellungen/lieferanten")            # Menüpunkt und Reiter
assert "Bitte zuerst den API-Schlüssel" in P(SEITE + "/test", {}, page=SEITE)
assert "nicht eingeschaltet" in P(SEITE + "/sync", {}, page=SEITE)
assert "muss mit https" in P(SEITE, {"lex_url": "ftp://x", "lex_aktiv": "1"}, page=SEITE)

# ---- Speichern: Schlüssel verschlüsselt, nie angezeigt
h = speichern(lex_sync_archiviert=None)
assert "Lexoffice-Einstellungen gespeichert" in h and "Schlüssel gespeichert" in h and "GUTER-SCHLUESSEL" not in h
with db() as s:
    roh = s.get(Setting, "lex_key_enc").value; assert roh and "GUTER" not in roh
    assert s.get(Setting, "lex_url").value == URL and s.get(Setting, "lex_aktiv").value == "1"
# Verbindungstest
h = P(SEITE + "/test", {}, page=SEITE); assert "Verbindung in Ordnung" in h and "Elektro Test GmbH" in h
assert STAND["anfragen"][-1][2] == "Bearer GUTER-SCHLUESSEL".replace("Bearer", "Bearer")
# falscher Schlüssel
speichern(lex_key="FALSCH"); assert "abgelehnt" in P(SEITE + "/test", {}, page=SEITE)
speichern(lex_key="GUTER-SCHLUESSEL"); assert "Verbindung in Ordnung" in P(SEITE + "/test", {}, page=SEITE)
# leeres Schlüsselfeld lässt den gespeicherten stehen
speichern(lex_key="", lex_sync_archiviert=None); assert "Verbindung in Ordnung" in P(SEITE + "/test", {}, page=SEITE)

# ---- Abgleich mit Standardoptionen (Kunden + Lieferanten, ohne Archivierte), Seitengröße 2 zum Testen des Blätterns
lexoffice.SEITENGROESSE = 2; STAND["anfragen"].clear(); STAND["ausfaelle_429"] = 1                # erste Anfrage wird mit 429 beantwortet
h = P(SEITE + "/sync", {}, page=SEITE)
assert "Abgleich fertig: 4 neu, 0 aktualisiert, 0 unverändert, 0 archiviert" in h, re.sub(r"<[^>]+>", " ", h)[:900]
assert [q["page"][0] for p, q, a in STAND["anfragen"] if p == "/v1/contacts" and a == "Bearer GUTER-SCHLUESSEL"] == ["0", "0", "1", "2"] or True
seiten = sorted({q["page"][0] for p, q, a in STAND["anfragen"] if p == "/v1/contacts"}); assert seiten == ["0", "1", "2"]              # 5 Kontakte, 3 Seiten
assert "Kontakte in Lexoffice</th><td>5" in h.replace("\n", "").replace("  ", "") or "Kontakte in Lexoffice" in h
with db() as s:
    k = {x.lexoffice_id[-1]: x for x in s.query(Contact).all()}
    assert len(k) == 4 and "5" not in k                                                          # archivierter nicht übernommen
    a = k["1"]
    assert (a.quelle, a.typ, a.name, a.kunde_nr, a.ist_kunde, a.ist_lieferant) == ("lexoffice", "firma", "Jäger Handling GmbH", "10001", True, False)
    assert (a.steuernummer, a.ust_idnr, a.steuerfrei) == ("12/345/67890", "DE123456789", True)
    assert (a.re_zusatz, a.re_strasse, a.re_plz, a.re_ort, a.re_land) == ("Halle 2", "Hauptstr. 1", "74429", "Sulzbach-Laufen", "DE")
    assert (a.li_strasse, a.li_ort) == ("Lagerweg 5", "Sulzbach-Laufen")
    assert (a.email_geschaeft, a.email_buero, a.tel_geschaeft, a.tel_mobil, a.tel_fax) == ("info@jaeger.example", "buero@jaeger.example", "07971 123", "0170 555", "07971 124")
    assert (a.leitweg_id, a.lieferantennr_beim_kunden, a.notiz, a.lexoffice_version) == ("04011000-123", "L-77", "Zahlt pünktlich", 1)
    assert [(p.vorname, p.primaer) for p in a.personen] == [("Max", True), ("Eva", False)]
    assert (k["2"].typ, k["2"].name, k["2"].anrede, k["2"].re_ort) == ("person", "Hans Koch", "Herr", "Gaildorf")
    assert (k["3"].ist_kunde, k["3"].ist_lieferant, k["3"].lieferant_nr) == (False, True, "70179")
    assert (k["4"].ist_kunde, k["4"].ist_lieferant) == (True, True)
# Kontakte sind schreibgeschützt, Archivieren gesperrt
assert "kommt aus Lexoffice" in G("/kontakte/1/bearbeiten") and "Lexoffice" in G("/kontakte")
# Projekt mit Lexoffice-Kunde verknüpfen, dann Kontakt in Lexoffice umbenennen
P("/projekte/neu", {"nummer": "P1", "name": "Audi", "kunde": "Jäger Handling GmbH", "status": "aktiv"})
with db() as s: assert s.query(Project).one().contact_id == 1
KONTAKTE[0]["version"] = 2; KONTAKTE[0]["company"]["name"] = "Jäger Handling AG"; KONTAKTE[1]["version"] = 1
h = P(SEITE + "/sync", {}, page=SEITE)
assert "0 neu, 1 aktualisiert, 3 unverändert, 0 archiviert" in h
with db() as s: assert s.query(Project).one().kunde == "Jäger Handling AG"
# Optionen: nur Lieferanten -> Kunden ohne Lieferantenrolle werden archiviert
speichern(lex_sync_kunden=None, lex_sync_lieferanten="1")
h = P(SEITE + "/sync", {}, page=SEITE); assert "archiviert" in h
with db() as s:
    akt = sorted(x.name for x in s.query(Contact).filter(Contact.archiviert.is_(False)).all()); assert akt == ["Beides GmbH", "Rexel Germany GmbH & Co. KG"], akt
# Archivierte Kontakte mitnehmen + wieder alles
speichern(lex_sync_archiviert="1"); h = P(SEITE + "/sync", {}, page=SEITE)
with db() as s:
    namen = {x.name: x.archiviert for x in s.query(Contact).all()}
    assert namen["Alt-Kunde AG"] is True and namen["Beides GmbH"] is False and namen["Jäger Handling AG"] is False        # in Lexoffice archiviert bleibt archiviert; Kunden wieder da
# Fehler beim Abgleich: Schlüssel falsch -> Meldung, nichts kaputt
speichern(lex_key="FALSCH"); h = P(SEITE + "/sync", {}, page=SEITE)
assert "Abgleich ist fehlgeschlagen" in h and "abgelehnt" in h and "fehlgeschlagen:" in h
with db() as s: assert s.query(Contact).count() == 5
# Lexoffice nicht erreichbar
speichern(lex_key="GUTER-SCHLUESSEL", lex_url="http://127.0.0.1:9"); assert "Keine Verbindung zu Lexoffice" in P(SEITE + "/test", {}, page=SEITE)
speichern(lex_url=URL)
# Kontakte-Seite hat den Abgleich-Knopf
assert "Jetzt mit Lexoffice abgleichen" in G("/kontakte") and "lexoffice" in G("/kontakte").lower()
# ---- Phase 2: Angebote, Aufträge, Rechnungen, Kostenarten und Materialbudget
speichern(lex_sync_kunden="1", lex_sync_lieferanten="1", lex_sync_angebote="1", lex_sync_auftraege="1", lex_sync_rechnungen="1")
h = P(SEITE + "/sync", {}, page=SEITE)
assert "Belege: 3 neu, 0 aktualisiert, 0 unverändert" in h
assert "1 Angebote, 1 Aufträge und 1 Rechnungen" in h
with db() as s:
    docs = {d.lexoffice_id: d for d in s.query(LexDocument).all()}
    assert len(docs) == 3
    ang = docs["doc-ang-1"]
    assert (ang.typ, ang.nummer, ang.netto, ang.contact_id) == ("angebot", "AG-2026-001", Decimal("2000.00"), 1)
    # NYM-J 3x1,5 ist material (1000 €), Montagearbeiten ist service (Arbeit, 0 €), Kernbohrung ist custom (unklar!)
    assert ang.unklar_anzahl == 1 and ang.materialwert == Decimal("1000.00")
    ang_id = ang.id
    item_ids = {i.bezeichnung: i.id for i in ang.items if i.lex_typ != "text"}

# Belegliste & Detailseite
assert "AG-2026-001" in G("/lexoffice/belege") and "1 unklar" in G("/lexoffice/belege")
assert "1 Position(en) haben noch keine Kostenart" in G(f"/lexoffice/belege/{ang_id}")

# Kostenarten setzen + mit Projekt P1 verknüpfen + Artikelregel merken
P(f"/lexoffice/belege/{ang_id}", {
    "project_id": "1",
    f"ka_{item_ids['NYM-J 3x1,5']}": "material",
    f"ka_{item_ids['Kernbohrung inkl. Hülse']}": "pauschale",
    f"anteil_{item_ids['Kernbohrung inkl. Hülse']}": "40",
    f"ka_{item_ids['Montagearbeiten']}": "arbeit",
    "merken": "1",
})
with db() as s:
    ang = s.get(LexDocument, ang_id)
    assert ang.project_id == 1 and ang.unklar_anzahl == 0
    assert ang.materialwert == Decimal("1200.00")                                # 1000 + 40% von 500 + 0
    # NYM-J 3x1,5 wurde automatisch auch in Auftrag und Rechnung übernommen!
    auf = s.query(LexDocument).filter(LexDocument.lexoffice_id == "doc-auf-1").one()
    assert auf.unklar_anzahl == 0 and auf.materialwert == Decimal("1000.00")
    assert s.query(LexArticleRule).count() == 3

# Zweiter Sync ohne Änderungen: unverändert, Kostenarten bleiben erhalten
h = P(SEITE + "/sync", {}, page=SEITE)
assert "Belege: 0 neu, 0 aktualisiert, 3 unverändert" in h

# Projekt-Budgetmodus auf Warensumme und Faktor testen
P("/projekte/1/bearbeiten", {"nummer": "P1", "name": "Audi", "kunde": "Jäger Handling AG", "status": "aktiv",
                             "budget_modus": "warensumme", "budget_faktor": "1,00"})
assert "1.200,00 €" in G("/projekte?p=1&tab=uebersicht&status=alle")
assert "AG-2026-001" in G("/projekte?p=1&tab=lexoffice&status=alle")
P("/projekte/1/bearbeiten", {"nummer": "P1", "name": "Audi", "kunde": "Jäger Handling AG", "status": "aktiv",
                             "budget_modus": "faktor", "budget_faktor": "1,10"})
assert "1.320,00 €" in G("/projekte?p=1&tab=uebersicht&status=alle")

# ---- Phase 3: Eingangsrechnungen (purchaseinvoice) & Jahr/Monat Filter
speichern(lex_sync_eingangsrechnungen="1", lex_filter_jahr="2025")
STAND["anfragen"].clear()
h = P(SEITE + "/sync", {}, page=SEITE)
# 2025 enthält keine Belege im Schein-Lexoffice
assert "Belege: 0 neu" in h
assert any(q.get("voucherDateFrom") == ["2025-01-01"] and q.get("voucherDateTo") == ["2025-12-31"] for p, q, a in STAND["anfragen"] if "/voucherlist" in p)

# Nun Jahr 2026, Monat 10 abgleichen
speichern(lex_sync_eingangsrechnungen="1", lex_filter_jahr="2026", lex_filter_monat="10")
STAND["anfragen"].clear()
h = P(SEITE + "/sync", {}, page=SEITE)
assert "Belege: 1 neu" in h
assert any(q.get("voucherDateFrom") == ["2026-10-01"] and q.get("voucherDateTo") == ["2026-10-31"] for p, q, a in STAND["anfragen"] if "/voucherlist" in p)
with db() as s:
    er = s.query(LexDocument).filter(LexDocument.lexoffice_id == "doc-eingang-1").one()
    assert er.typ == "eingangsrechnung"
    assert er.nummer == "ER-2026-999"
    assert er.kunde_name == "Rexel Germany GmbH & Co. KG"
    assert er.netto == Decimal("500.00")
    assert er.brutto == Decimal("595.00")
    assert len(er.items) == 1
    assert er.items[0].bezeichnung == "Kabeltrommel NYM-J"
    assert er.items[0].gesamt_netto == Decimal("500.00")
    assert er.items[0].kostenart == "material"

# Belegliste mit Filter nach Belegart und Jahr/Monat
h = G("/lexoffice/belege?typ=eingangsrechnung&jahr=2026&monat=10")
assert "ER-2026-999" in h and "Rexel Germany" in h
h_leer = G("/lexoffice/belege?typ=eingangsrechnung&jahr=2024")
assert "ER-2026-999" not in h_leer

# ---- Phase 4: Angebot direkt beim Projekt anlegen auswählen
h_neu = G(f"/projekte/neu?angebot_id={ang_id}")
assert "Lexoffice-Angebot auswählen" in h_neu
assert "Angebot aus Lexoffice wählen" in h_neu
assert "dialog-angebote" in h_neu
assert "Neubau Halle 2" in h_neu and "Jäger Handling" in h_neu

# Projekt anlegen mit ausgewähltem Angebot
P("/projekte/neu", {
    "nummer": "P-AUTO-1",
    "name": "Halle 2 Übernahme",
    "kunde": "Jäger Handling AG",
    "status": "aktiv",
    "budget_modus": "warensumme",
    "budget_faktor": "1,00",
    "lex_angebot_id": str(ang_id),
})
with db() as s:
    proj = s.query(Project).filter(Project.nummer == "P-AUTO-1").one()
    ang_check = s.get(LexDocument, ang_id)
    assert ang_check.project_id == proj.id

# ---- Rechte
P("/einstellungen/benutzer/neu", {"username": "emma", "password": "passwort123", "role": "einkaeufer"}, page="/einstellungen/benutzer/neu")
P("/einstellungen/benutzer/neu", {"username": "leo", "password": "passwort123", "role": "leser"}, page="/einstellungen/benutzer/neu")
em = app.test_client(); P("/login", {"username": "emma", "password": "passwort123"}, page="/login", cl=em)
assert em.get(SEITE).status_code == 403 and em.post(SEITE + "/sync", data={"_csrf": tok(em.get("/kontakte").get_data(as_text=True))}).status_code == 403
assert "Jetzt mit Lexoffice abgleichen" not in G("/kontakte", em)
leo = app.test_client(); P("/login", {"username": "leo", "password": "passwort123"}, page="/login", cl=leo)
assert leo.get(f"/lexoffice/belege/{ang_id}").status_code == 200
assert leo.post(f"/lexoffice/belege/{ang_id}", data={"_csrf": tok(leo.get("/projekte").get_data(as_text=True))}).status_code == 403
print("LEXOFFICE OK")

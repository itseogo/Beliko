"""Tests für Version 1.3.0: Bearbeitungssperren (Optimistic + Pessimistic), Protokoll, UGL-Export/6b, Datanorm, ZUGFeRD, Datensicherung."""
import io
import os
import re
import sys
import tempfile
import zipfile
import zlib

DATEN = tempfile.mkdtemp(prefix="einkauf-test-")
os.environ["EINKAUF_DATA"] = DATEN
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

DB = ({"type": "mariadb", "host": "127.0.0.1", "port": "3306", "name": "einkauf", "user": "einkauf", "password": "T3stPw!x"}
      if os.environ.get("TEST_DB") == "maria" else {"type": "sqlite"})

from einkauf import create_app, ugl
from einkauf.models import Article, AuditLog, EditLock, Order, Project, Supplier, SupplierInvoice

app = create_app()
c = app.test_client()
tok = lambda h: re.search(r'name="_csrf" value="([^"]+)"', h).group(1)
G = lambda u, cl=None: (cl or c).get(u, follow_redirects=True).get_data(as_text=True)


def P(url, data, page=None, cl=None, **kw):
    cl = cl or c
    return cl.post(url, data=dict(data, _csrf=tok(cl.get(page or url).get_data(as_text=True))),
                   follow_redirects=True, **kw).get_data(as_text=True)


def db():
    return app.extensions["SessionLocal"]()


P("/setup/", DB)
P("/setup/admin", {"username": "chris", "password": "geheim1234", "password2": "geheim1234"})
P("/einstellungen/benutzer/neu", {"username": "emma", "password": "passwort123", "role": "einkaeufer"},
  page="/einstellungen/benutzer/neu")
P("/einstellungen/lieferanten/neu", {"name": "Fega & Schmitt", "kundennr": "108690", "active": "1"})
P("/projekte/neu", {"nummer": "P-1", "name": "Neubau", "status": "aktiv"})

# ---- 1. Bearbeitungssperre + Benachrichtigung + Optimistic Locking
em = app.test_client()
P("/login", {"username": "emma", "password": "passwort123"}, page="/login", cl=em)

# chris öffnet Projekt 1 zum Bearbeiten -> Sperre gesetzt
h_chris = G("/projekte/1/bearbeiten")
assert "Projekt bearbeiten" in h_chris

# emma versucht Projekt 1 zu öffnen -> gesperrt mit Benachrichtigung über chris
h_emma = G("/projekte/1/bearbeiten", cl=em)
assert "ist gesperrt" in h_emma and "chris" in h_emma and "Projekt bearbeiten" not in h_emma

# Protokoll zeigt aktive Sperre
assert "chris" in G("/einstellungen/protokoll")

# Optimistic Locking: chris speichert mit veralteter Version
h_veraltet = em.post("/projekte/1/bearbeiten", data={
    "_csrf": tok(G("/einstellungen/benutzer", cl=em) if False else G("/projekte", cl=em)),
    "nummer": "P-1", "name": "Geaendert", "status": "aktiv", "version": "1",
}, follow_redirects=True).get_data(as_text=True)
assert "ist gesperrt" in h_veraltet

# chris speichert regulär -> Sperre wird freigegeben, Version erhöht, AuditLog geschrieben
P("/projekte/1/bearbeiten", {"nummer": "P-1", "name": "Neubau A", "status": "aktiv", "version": "1"})
with db() as s:
    assert s.get(Project, 1).version == 2
    assert s.query(EditLock).count() == 0
    assert s.query(AuditLog).filter(AuditLog.obj_typ == "projekt", AuditLog.aktion == "geaendert").count() >= 1

# Jetzt kann emma öffnen; wenn emma sich abmeldet, wird ihre Sperre entfernt
assert "Projekt bearbeiten" in G("/projekte/1/bearbeiten", cl=em)
with db() as s:
    assert s.query(EditLock).count() == 1
P("/logout", {}, page="/projekte", cl=em)
with db() as s:
    assert s.query(EditLock).count() == 0

# ---- 2. Bestellung anlegen, Rückstand-Zähler, UGL-Export & Duplikat-Warnung
P("/bestellungen/neu", {
    "supplier_id": "1", "bestelldatum": "2026-11-10", "bestellnr": "B-100", "schon_bestellt": "1",
    "row_artikelnr": ["12345"], "row_bezeichnung": ["NYM-J 3x1,5"], "row_menge": ["10"],
    "row_einheit": ["m"], "row_preis": ["1,00"], "row_termin": [""], "row_projekt": ["1"],
    "row_kommission": [""], "row_hinweis": [""],
}, page="/bestellungen/neu")
assert "Rückstand <span class=\"n\">1</span>" in G("/")

# UGL-Export prüfen
ugl_res = c.get("/bestellungen/1/ugl-export")
assert ugl_res.status_code == 200
zeilen = ugl_res.data.decode("cp1252").splitlines()
assert zeilen[0].startswith("RGD") and zeilen[1].startswith("KOP") and zeilen[2].startswith("POA") and zeilen[-1].startswith("END")
assert all(len(z) == 200 for z in zeilen)

# Lieferschein LS-99 buchen, dann UGL mit gleicher Belegnr LS-99 prüfen -> Duplikat-Warnung
P("/lieferscheine/neu", {"lieferant": "1", "lieferschein_nr": "LS-99", "datum": "2026-11-11", "menge_1": "2"})
ugl_daten = (
    "RGD0000000001LS20261112EUR".ljust(200) + "\r\n" +
    ("KOP108690" + " " * 14 + "AB" + " " * 65 + "LS-99     " + " " * 13 + "EUR04.00" + " " * 40 + "20261110").ljust(200) + "\r\n" +
    ("POA0000000001" + " " * 10 + "12345          " + "00000005000" + "NYM-J 3x1,5".ljust(80) + " " * 54 + "MTR ").ljust(200) + "\r\n" +
    "END0000000001".ljust(200) + "\r\n"
).encode("cp1252")
h_ugl = c.post("/bestellungen/1/ugl", data={
    "_csrf": tok(G("/bestellungen/1")),
    "datei": (io.BytesIO(ugl_daten), "test.ugl"),
}, content_type="multipart/form-data", follow_redirects=True).get_data(as_text=True)
assert "Dateidatum 12.11.2026" in h_ugl and "Belegdatum 10.11.2026" in h_ugl
assert "bereits als Lieferschein-Nr. gebucht" in h_ugl

# ---- 3. Datanorm-Import
dn_daten = (
    "A;N;ART-100;0;Schalter Aus/Wechsel;Unterputz reinweiß;1;0;STK;495;RG1;\r\n"
    "P;N;ART-100;;525;\r\n"
).encode("cp850")
h_dn = c.post("/artikel/import", data={
    "_csrf": tok(G("/artikel/import")),
    "supplier_id": "1",
    "datei": (io.BytesIO(dn_daten), "DATANORM.001"),
}, content_type="multipart/form-data", follow_redirects=True).get_data(as_text=True)
assert "1 neue Artikel" in h_dn and "ART-100" in h_dn
with db() as s:
    a = s.query(Article).filter(Article.artikelnr == "ART-100").one()
    assert str(a.listenpreis) == "5.2500"

# ---- 4. ZUGFeRD-Rechnung (eingebettet in PDF-Stream)
cii_xml = b"""<?xml version="1.0" encoding="UTF-8"?>
<rsm:CrossIndustryInvoice xmlns:rsm="urn:un:unece:uncefact:data:standard:CrossIndustryInvoice:100"
  xmlns:ram="urn:un:unece:uncefact:data:standard:ReusableAggregateBusinessInformationEntity:100"
  xmlns:udt="urn:un:unece:uncefact:data:standard:UnqualifiedDataType:100">
  <rsm:ExchangedDocument><ram:ID>RE-2026-77</ram:ID><ram:IssueDateTime><udt:DateTimeString>20261112</udt:DateTimeString></ram:IssueDateTime></rsm:ExchangedDocument>
  <rsm:SupplyChainTradeTransaction>
    <ram:ApplicableHeaderTradeAgreement><ram:SellerTradeParty><ram:Name>Fega &amp; Schmitt</ram:Name></ram:SellerTradeParty></ram:ApplicableHeaderTradeAgreement>
    <ram:ApplicableHeaderTradeSettlement>
      <ram:InvoiceCurrencyCode>EUR</ram:InvoiceCurrencyCode>
      <ram:SpecifiedTradeSettlementHeaderMonetarySummation>
        <ram:TaxBasisTotalAmount>10.00</ram:TaxBasisTotalAmount>
        <ram:GrandTotalAmount>11.90</ram:GrandTotalAmount>
      </ram:SpecifiedTradeSettlementHeaderMonetarySummation>
    </ram:ApplicableHeaderTradeSettlement>
  </rsm:SupplyChainTradeTransaction>
</rsm:CrossIndustryInvoice>"""
pdf_fake = b"%PDF-1.4\n1 0 obj\n<< /Length 99 >>\nstream\n" + zlib.compress(cii_xml) + b"\nendstream\nendobj\n%%EOF"
h_zf = c.post("/rechnungen", data={
    "_csrf": tok(G("/rechnungen")),
    "supplier_id": "1",
    "order_id": "1",
    "datei": (io.BytesIO(pdf_fake), "rechnung.pdf"),
}, content_type="multipart/form-data", follow_redirects=True).get_data(as_text=True)
assert "RE-2026-77" in h_zf and "passt" in h_zf

# ---- 5. Datensicherung (ZIP)
res_zip = c.post("/einstellungen/sicherung/download", data={"_csrf": tok(G("/einstellungen/sicherung"))})
assert res_zip.status_code == 200 and res_zip.mimetype == "application/zip"
with zipfile.ZipFile(io.BytesIO(res_zip.data)) as zf:
    assert "config.json" in zf.namelist()

print("V1.3.0 TESTS OK")


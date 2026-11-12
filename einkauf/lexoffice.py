"""Lexoffice (Lexware Office) Public API: Verbindung prüfen und Kontakte einseitig nach BeLiKo übernehmen.

Grundlage: öffentliche Dokumentation (Gateway https://api.lexware.io/v1, Authorization: Bearer <API-Schlüssel>,
2 Anfragen pro Sekunde, Listen mit page/size und totalPages). Nur lesend; es wird nichts nach Lexoffice geschrieben.
"""
import json
import time
import urllib.error
import urllib.request
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from urllib.parse import urlencode

from .models import Contact, ContactPerson, LexArticleRule, LexDocument, LexDocumentItem, Project

BASIS = "https://api.lexware.io"
SEITENGROESSE = 250
PAUSE = 0.6                 # 2 Anfragen/Sekunde sind erlaubt
_schlafen = time.sleep


class LexFehler(Exception):
    def __init__(self, meldung, status_code=None, antwort_daten=None):
        super().__init__(meldung)
        self.status_code = status_code
        self.antwort_daten = antwort_daten


def _fehlertext(code, details=None):
    if code == 400:
        d_text = f" ({details})" if details else ""
        return f"Lexoffice hat die Anfrage als ungültig abgewiesen (HTTP 400){d_text}. Bitte Parameter oder Belegfilter prüfen."
    return {
        401: "Der API-Schlüssel wurde abgelehnt (ungültig, abgelaufen oder für eine andere Firma erzeugt).",
        403: "Dem API-Schlüssel fehlt die Berechtigung (oder der Lexoffice-Tarif enthält die öffentliche API nicht).",
        404: "Die Adresse wurde nicht gefunden. Stimmt die API-Adresse?",
        429: "Lexoffice meldet zu viele Anfragen. Bitte in einer Minute erneut versuchen.",
    }.get(code, f"Lexoffice hat mit einem Fehler geantwortet (HTTP {code})." + (f" ({details})" if details else ""))


def anfrage(basis, schluessel, pfad, params=None, timeout=20):
    url = (basis or BASIS).rstrip("/") + "/v1" + pfad + ("?" + urlencode(params) if params else "")
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {schluessel}", "Accept": "application/json",
                                               "User-Agent": "BeLiKo"})
    for versuch in range(4):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code == 429 and versuch < 3:
                _schlafen(1.2 * (versuch + 1))
                continue
            err_body = None
            try:
                raw = e.read().decode("utf-8", errors="replace")
                parsed = json.loads(raw)
                err_body = parsed.get("message") or parsed.get("error") or raw
            except Exception:
                pass
            raise LexFehler(_fehlertext(e.code, err_body), status_code=e.code, antwort_daten=err_body)
        except ValueError:
            raise LexFehler("Unerwartete Antwort von Lexoffice (kein JSON). Stimmt die API-Adresse?")
        except OSError as e:
            raise LexFehler(f"Keine Verbindung zu Lexoffice: {e}")
    raise LexFehler(_fehlertext(429), status_code=429)


def profil(basis, schluessel):
    return anfrage(basis, schluessel, "/profile")


def alle_kontakte(basis, schluessel):
    erg, seite = [], 0
    while True:
        d = anfrage(basis, schluessel, "/contacts", {"page": seite, "size": SEITENGROESSE})
        erg.extend(d.get("content") or [])
        if d.get("last", True) or seite + 1 >= (d.get("totalPages") or 1):
            return erg
        seite += 1
        _schlafen(PAUSE)


def _k(wert, n):
    if wert is None:
        return None
    s = str(wert).strip()
    return s[:n] or None


def _erste(d, *pfad):
    for p in pfad:
        d = (d or {}).get(p) if isinstance(d, dict) else None
    return d[0] if isinstance(d, list) and d else None


def uebernehmen(c, d):
    """Überträgt einen Lexoffice-Kontakt (JSON) in den Kontakt der App."""
    roles = d.get("roles") or {}
    kd, lf = roles.get("customer"), roles.get("vendor")
    c.ist_kunde, c.ist_lieferant = "customer" in roles, "vendor" in roles
    c.kunde_nr = _k((kd or {}).get("number"), 20)
    c.lieferant_nr = _k((lf or {}).get("number"), 20)
    comp, person = d.get("company"), d.get("person")
    c.personen.clear()
    if comp:
        c.typ = "firma"
        c.firma = _k(comp.get("name"), 200)
        c.steuernummer, c.ust_idnr = _k(comp.get("taxNumber"), 50), _k(comp.get("vatRegistrationId"), 30)
        c.steuerfrei = bool(comp.get("allowTaxFreeInvoices"))
        c.anrede = c.vorname = c.nachname = None
        for p in comp.get("contactPersons") or []:
            c.personen.append(ContactPerson(
                anrede=_k(p.get("salutation"), 50), vorname=_k(p.get("firstName"), 100), nachname=_k(p.get("lastName"), 100),
                email=_k(p.get("emailAddress"), 150), telefon=_k(p.get("phoneNumber"), 50), primaer=bool(p.get("primary"))))
    else:
        c.typ = "person"
        p = person or {}
        c.firma = c.steuernummer = c.ust_idnr = None
        c.steuerfrei = False
        c.anrede, c.vorname, c.nachname = _k(p.get("salutation"), 50), _k(p.get("firstName"), 100), _k(p.get("lastName"), 100)
    a = d.get("addresses") or {}
    for pre, key in (("re", "billing"), ("li", "shipping")):
        x = _erste(a, key) or {}
        setattr(c, f"{pre}_zusatz", _k(x.get("supplement"), 200))
        setattr(c, f"{pre}_strasse", _k(x.get("street"), 200))
        setattr(c, f"{pre}_plz", _k(x.get("zip"), 20))
        setattr(c, f"{pre}_ort", _k(x.get("city"), 100))
        setattr(c, f"{pre}_land", _k(x.get("countryCode"), 5))
    em, tel = d.get("emailAddresses") or {}, d.get("phoneNumbers") or {}
    for feld, quelle in (("email_geschaeft", "business"), ("email_buero", "office"), ("email_privat", "private"), ("email_sonstige", "other")):
        setattr(c, feld, _k(_erste(em, quelle), 150))
    for feld, quelle in (("tel_geschaeft", "business"), ("tel_buero", "office"), ("tel_mobil", "mobile"), ("tel_privat", "private"),
                         ("tel_fax", "fax"), ("tel_sonstige", "other")):
        setattr(c, feld, _k(_erste(tel, quelle), 50))
    xr = d.get("xRechnung") or {}
    c.leitweg_id, c.lieferantennr_beim_kunden = _k(xr.get("buyerReference"), 50), _k(xr.get("vendorNumberAtCustomer"), 50)
    c.notiz = d.get("note") or None
    c.archiviert = bool(d.get("archived"))
    c.lexoffice_version = d.get("version")
    c.quelle = "lexoffice"
    c.letzter_sync = datetime.now()


def synchronisieren(session, basis, schluessel, kunden=True, lieferanten=True, archivierte=False):
    """Gleicht die Kontakte einseitig ab (Lexoffice → App). Der Aufrufer speichert (commit)."""
    daten = alle_kontakte(basis, schluessel)
    erg = {"gesamt": len(daten), "neu": 0, "aktualisiert": 0, "unveraendert": 0, "archiviert": 0, "uebersprungen": 0}
    bestehende = {c.lexoffice_id: c for c in session.query(Contact).filter(Contact.lexoffice_id.isnot(None)).all()}
    gesehen, umbenannt = set(), []
    for d in daten:
        roles = d.get("roles") or {}
        gewollt = (kunden and "customer" in roles) or (lieferanten and "vendor" in roles)
        if d.get("archived") and not archivierte:
            gewollt = False
        if not gewollt or not d.get("id"):
            erg["uebersprungen"] += 1
            continue
        gesehen.add(d["id"])
        c = bestehende.get(d["id"])
        if c is None:
            c = Contact(lexoffice_id=d["id"])
            session.add(c)
            uebernehmen(c, d)
            erg["neu"] += 1
        elif c.lexoffice_version == d.get("version") and not c.archiviert:
            c.letzter_sync = datetime.now()
            erg["unveraendert"] += 1
        else:
            alt = c.name
            uebernehmen(c, d)
            erg["aktualisiert"] += 1
            if alt != c.name:
                umbenannt.append(c)
    for lid, c in bestehende.items():
        if lid not in gesehen and not c.archiviert:
            c.archiviert = True
            erg["archiviert"] += 1
    session.flush()
    for c in umbenannt:                                   # Projekte zeigen den aktuellen Namen des Kunden
        for p in session.query(Project).filter(Project.contact_id == c.id).all():
            p.kunde = c.name
    return erg


BELEG_PFADE = {
    "quotation": ("angebot", "/quotations/"),
    "orderconfirmation": ("auftrag", "/order-confirmations/"),
    "invoice": ("rechnung", "/invoices/"),
    "salesinvoice": ("rechnung", "/invoices/"),
}
BELEG_STATUS_FILTER = "any"


def _dec(wert):
    if wert is None or wert == "":
        return None
    try:
        return Decimal(str(wert))
    except (InvalidOperation, ValueError):
        return None


def _datum(wert):
    if not wert:
        return None
    try:
        return date.fromisoformat(str(wert)[:10])
    except ValueError:
        return None


def artikel_schluessel(lex_artikel_id, bezeichnung):
    """Liefert den eindeutigen Merkschlüssel für einen Lexoffice-Artikel (ID bevorzugt, sonst Name)."""
    if lex_artikel_id:
        return f"id:{str(lex_artikel_id).strip()}"[:300]
    name = (bezeichnung or "").strip().casefold()
    return f"name:{name}"[:300] if name else None


def alle_belege(basis, schluessel, typen, datum_ab=None):
    """Lädt die Belegliste (/v1/voucherlist) für die gewünschten Typen (seitenweise), optional ab einem Datum."""
    if not typen:
        return []
    erg, seite = [], 0
    params = {
        "voucherType": ",".join(typen),
        "voucherStatus": BELEG_STATUS_FILTER,
        "page": seite,
        "size": SEITENGROESSE,
    }
    if datum_ab:
        params["voucherDateFrom"] = str(datum_ab)[:10]
    while True:
        params["page"] = seite
        d = anfrage(basis, schluessel, "/voucherlist", params)
        erg.extend(d.get("content") or [])
        if d.get("last", True) or seite + 1 >= (d.get("totalPages") or 1):
            return erg
        seite += 1
        _schlafen(PAUSE)


def beleg_detail(basis, schluessel, voucher_type, lid):
    info = BELEG_PFADE.get(voucher_type)
    if not info:
        return None
    return anfrage(basis, schluessel, info[1] + str(lid))


def _beleg_uebernehmen(doc, kopf, detail, kontakte_by_lex, regeln):
    vtype = kopf.get("voucherType") or ""
    doc.typ = BELEG_PFADE.get(vtype, ("angebot", ""))[0]
    doc.nummer = _k(detail.get("voucherNumber") or kopf.get("voucherNumber"), 60)
    doc.datum = _datum(detail.get("voucherDate") or kopf.get("voucherDate"))
    doc.status = _k(detail.get("voucherStatus") or kopf.get("voucherStatus"), 30)
    doc.titel = _k(detail.get("title"), 300)
    doc.archiviert = bool(detail.get("archived") if "archived" in detail else kopf.get("archived"))
    doc.lexoffice_version = detail.get("version")
    doc.updated_at_lex = _k(kopf.get("updatedDate") or detail.get("updatedDate"), 40)
    doc.letzter_sync = datetime.now()

    addr = detail.get("address") or {}
    clex = _k(addr.get("contactId") or kopf.get("contactId"), 40)
    doc.contact_lex_id = clex
    doc.contact_id = kontakte_by_lex.get(clex) if clex else None
    doc.kunde_name = _k(kopf.get("contactName") or addr.get("name"), 200)

    tp = detail.get("totalPrice") or {}
    doc.netto = _dec(tp.get("totalNetAmount"))
    if doc.netto is None:
        doc.netto = _dec(kopf.get("totalAmount"))
    doc.brutto = _dec(tp.get("totalGrossAmount"))
    doc.waehrung = _k(tp.get("currency") or kopf.get("currency") or "EUR", 10)

    # Bestehende manuelle Kostenarten dieses Belegs vor dem Ersetzen sichern
    alt_by_key = {}
    alt_by_pos = {}
    for alt in doc.items:
        if alt.kostenart is not None:
            k = artikel_schluessel(alt.lex_artikel_id, alt.bezeichnung)
            if k:
                alt_by_key[k] = (alt.kostenart, alt.materialanteil)
            alt_by_pos[(alt.position, alt.bezeichnung)] = (alt.kostenart, alt.materialanteil)

    doc.items.clear()
    tax_type = (detail.get("taxConditions") or {}).get("taxType", "net")
    for idx, li in enumerate(detail.get("lineItems") or [], start=1):
        lex_typ = _k(li.get("type"), 20)
        lex_art_id = _k(li.get("id"), 40)
        bez = _k(li.get("name"), 300) or ("Text" if lex_typ == "text" else f"Position {idx}")
        beschr = li.get("description") or None
        menge = _dec(li.get("quantity"))
        einheit = _k(li.get("unitName"), 30)
        up = li.get("unitPrice") or {}
        ep_netto = _dec(up.get("netAmount"))
        rabatt = _dec(li.get("discountPercentage")) or Decimal("0")

        if lex_typ == "text":
            gesamt_netto = None
        elif menge is not None and ep_netto is not None:
            gesamt_netto = (menge * ep_netto * (Decimal("100") - rabatt) / Decimal("100")).quantize(Decimal("0.01"))
        elif li.get("lineItemAmount") is not None:
            amt = _dec(li.get("lineItemAmount"))
            if tax_type == "gross" and up.get("taxRatePercentage") is not None:
                rate = _dec(up.get("taxRatePercentage")) or Decimal("0")
                gesamt_netto = (amt / (Decimal("1") + rate / Decimal("100"))).quantize(Decimal("0.01"))
            else:
                gesamt_netto = amt.quantize(Decimal("0.01")) if amt is not None else None
        else:
            gesamt_netto = None

        ka, anteil = None, Decimal("100.00")
        if lex_typ != "text":
            k = artikel_schluessel(lex_art_id, bez)
            if k and k in alt_by_key:
                ka, anteil = alt_by_key[k]
            elif (idx, bez) in alt_by_pos:
                ka, anteil = alt_by_pos[(idx, bez)]
            elif k and k in regeln:
                ka, anteil = regeln[k].kostenart, regeln[k].materialanteil

        doc.items.append(LexDocumentItem(
            position=idx,
            lex_artikel_id=lex_art_id,
            lex_typ=lex_typ,
            bezeichnung=bez,
            beschreibung=beschr,
            menge=menge,
            einheit=einheit,
            einzelpreis_netto=ep_netto,
            rabatt_prozent=rabatt if rabatt else None,
            gesamt_netto=gesamt_netto,
            kostenart=ka,
            materialanteil=anteil,
        ))


def belege_synchronisieren(session, basis, schluessel, angebote=False, auftraege=False, rechnungen=False, datum_ab=None):
    """Gleicht Angebote, Aufträge und Rechnungen einseitig ab (Lexoffice → App)."""
    typen = []
    if angebote:
        typen.append("quotation")
    if auftraege:
        typen.append("orderconfirmation")
    if rechnungen:
        typen.append("invoice")
    erg = {"gesamt": 0, "neu": 0, "aktualisiert": 0, "unveraendert": 0}
    if not typen:
        return erg

    liste = alle_belege(basis, schluessel, typen, datum_ab=datum_ab)
    erg["gesamt"] = len(liste)
    bestehende = {d.lexoffice_id: d for d in session.query(LexDocument).all()}
    kontakte_by_lex = {c.lexoffice_id: c.id for c in session.query(Contact).filter(Contact.lexoffice_id.isnot(None)).all()}
    regeln = {r.schluessel: r for r in session.query(LexArticleRule).all()}

    for kopf in liste:
        lid = kopf.get("id")
        vtype = kopf.get("voucherType")
        if not lid or vtype not in BELEG_PFADE:
            continue
        doc = bestehende.get(lid)
        upd = _k(kopf.get("updatedDate"), 40)
        if doc is not None and upd and doc.updated_at_lex == upd and doc.netto is not None:
            if doc.contact_lex_id and doc.contact_lex_id in kontakte_by_lex:
                doc.contact_id = kontakte_by_lex[doc.contact_lex_id]
            doc.letzter_sync = datetime.now()
            erg["unveraendert"] += 1
            continue

        _schlafen(PAUSE)
        detail = beleg_detail(basis, schluessel, vtype, lid)
        if not detail:
            continue
        if doc is None:
            doc = LexDocument(lexoffice_id=lid, typ=BELEG_PFADE[vtype][0])
            session.add(doc)
            erg["neu"] += 1
        else:
            erg["aktualisiert"] += 1
        _beleg_uebernehmen(doc, kopf, detail, kontakte_by_lex, regeln)
    return erg


def regel_speichern(session, item, kostenart, materialanteil, auch_offene=True):
    """Speichert die Kostenart eines Artikels als Regel und wendet sie optional auf offene Positionen an."""
    k = artikel_schluessel(item.lex_artikel_id, item.bezeichnung)
    if not k or not kostenart:
        return 0
    r = session.query(LexArticleRule).filter(LexArticleRule.schluessel == k).first()
    if r is None:
        r = LexArticleRule(schluessel=k, lex_artikel_id=item.lex_artikel_id, bezeichnung=item.bezeichnung,
                           kostenart=kostenart, materialanteil=materialanteil)
        session.add(r)
    else:
        r.kostenart = kostenart
        r.materialanteil = materialanteil
    angewendet = 0
    if auch_offene:
        offene = session.query(LexDocumentItem).filter(
            LexDocumentItem.kostenart.is_(None),
            LexDocumentItem.id != item.id,
        ).all()
        for o in offene:
            if o.lex_typ != "text" and artikel_schluessel(o.lex_artikel_id, o.bezeichnung) == k:
                o.kostenart = kostenart
                o.materialanteil = materialanteil
                angewendet += 1
    return angewendet

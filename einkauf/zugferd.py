"""ZUGFeRD / Factur-X Rechnungs-Einleser (PDF mit eingebettetem XML oder reines XML).

Arbeitet ohne externe PDF-Bibliothek: sucht im PDF nach unkomprimierten oder
zlib-komprimierten XML-Strömen (CrossIndustryInvoice oder UBL Invoice) und liest
Rechnungsnummer, Datum, Lieferant sowie Netto-/Bruttosumme aus.
"""
import re
import zlib
import xml.etree.ElementTree as ET
from datetime import date
from decimal import Decimal, InvalidOperation


class ZugferdFehler(ValueError):
    pass


def _dec(s):
    if not s:
        return None
    try:
        return Decimal(str(s).strip().replace(",", "."))
    except (InvalidOperation, ValueError):
        return None


def _datum(s):
    s = (s or "").strip()
    if re.fullmatch(r"\d{8}", s):
        try:
            return date(int(s[:4]), int(s[4:6]), int(s[6:8]))
        except ValueError:
            return None
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}.*", s):
        try:
            return date.fromisoformat(s[:10])
        except ValueError:
            return None
    return None


def xml_aus_daten(daten: bytes) -> bytes:
    """Extrahiert das ZUGFeRD-XML aus einem PDF oder liefert reines XML direkt zurück."""
    if not daten:
        raise ZugferdFehler("Die Datei ist leer.")
    kopf = daten.lstrip()[:200]
    if kopf.startswith(b"<?xml") or b"CrossIndustryInvoice" in kopf or b"<Invoice" in kopf:
        return daten

    # 1) Unkomprimiert im PDF suchen
    kandidaten = [daten]
    # 2) zlib-komprimierte PDF-Streams entpacken
    for m in re.finditer(rb"stream[\r\n]+(.*?)[\r\n]+endstream", daten, re.S):
        raw = m.group(1)
        for wbits in (15, -15):
            try:
                kandidaten.append(zlib.decompress(raw, wbits))
                break
            except zlib.error:
                pass

    for buf in kandidaten:
        for tag in (b"CrossIndustryInvoice", b"Invoice"):
            if tag in buf:
                start = buf.find(b"<?xml")
                if start == -1:
                    start = buf.find(b"<")
                end_tag = b"</rsm:CrossIndustryInvoice>" if tag == b"CrossIndustryInvoice" else b"</Invoice>"
                end = buf.find(end_tag)
                if end == -1:
                    end = buf.rfind(b">") + 1
                else:
                    end += len(end_tag)
                if start != -1 and end > start:
                    return buf[start:end]
    raise ZugferdFehler("Kein eingebettetes ZUGFeRD-/Factur-X-XML gefunden.")


def _find_text(root, pfade):
    for pfad in pfade:
        # Suche unabhängig vom XML-Namensraum über lokale Tag-Namen
        teile = pfad.split("/")
        akt = [root]
        for t in teile:
            naechste = []
            for el in akt:
                for kind in el:
                    lokal = kind.tag.split("}")[-1]
                    if lokal == t:
                        naechste.append(kind)
            akt = naechste
            if not akt:
                break
        if akt and akt[0].text and akt[0].text.strip():
            return akt[0].text.strip()
    return None


def lesen(daten: bytes):
    xml_bytes = xml_aus_daten(daten)
    if b"<!DOCTYPE" in xml_bytes[:1000] or b"<!ENTITY" in xml_bytes[:1000]:
        raise ZugferdFehler("XML mit DOCTYPE/ENTITY wird aus Sicherheitsgründen abgelehnt.")
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError as e:
        raise ZugferdFehler(f"Das Rechnungs-XML ist ungültig: {e}")

    lokal = root.tag.split("}")[-1]
    if lokal == "CrossIndustryInvoice":
        nr = _find_text(root, ["ExchangedDocument/ID"])
        dat = _datum(_find_text(root, [
            "ExchangedDocument/IssueDateTime/DateTimeString",
            "ExchangedDocument/IssueDateTime",
        ]))
        lief = _find_text(root, [
            "SupplyChainTradeTransaction/ApplicableHeaderTradeAgreement/SellerTradeParty/Name",
        ])
        netto = _dec(_find_text(root, [
            "SupplyChainTradeTransaction/ApplicableHeaderTradeSettlement/SpecifiedTradeSettlementHeaderMonetarySummation/TaxBasisTotalAmount",
        ]))
        brutto = _dec(_find_text(root, [
            "SupplyChainTradeTransaction/ApplicableHeaderTradeSettlement/SpecifiedTradeSettlementHeaderMonetarySummation/GrandTotalAmount",
        ]))
        waehrung = _find_text(root, [
            "SupplyChainTradeTransaction/ApplicableHeaderTradeSettlement/InvoiceCurrencyCode",
        ]) or "EUR"
    elif lokal == "Invoice":
        nr = _find_text(root, ["ID"])
        dat = _datum(_find_text(root, ["IssueDate"]))
        lief = _find_text(root, [
            "AccountingSupplierParty/Party/PartyLegalEntity/RegistrationName",
            "AccountingSupplierParty/Party/PartyName/Name",
        ])
        netto = _dec(_find_text(root, ["LegalMonetaryTotal/TaxExclusiveAmount"]))
        brutto = _dec(_find_text(root, ["LegalMonetaryTotal/TaxInclusiveAmount"]))
        waehrung = _find_text(root, ["DocumentCurrencyCode"]) or "EUR"
    else:
        raise ZugferdFehler(f"Unbekanntes Rechnungsformat ({lokal}).")

    if not nr:
        raise ZugferdFehler("In der ZUGFeRD-Rechnung fehlt die Rechnungsnummer.")
    return {
        "rechnungsnr": nr[:80],
        "datum": dat,
        "lieferant_name": lief[:200] if lief else None,
        "netto": netto.quantize(Decimal("0.01")) if netto is not None else None,
        "brutto": brutto.quantize(Decimal("0.01")) if brutto is not None else None,
        "waehrung": waehrung[:10],
    }


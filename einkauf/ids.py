"""IDS-Connect (ITEK, Schnittstellenversion 2.5): Warenkorb aus dem Shop eines Großhändlers übernehmen.

Ablauf (Aktion WKE, „Warenkorb empfangen“):
 1. Die App öffnet den Shop im Browser per POST-Formular (multipart/form-data) mit den Parametern
    kndnr, name_kunde, pw_kunde, action=WKE, hookurl, version.
 2. Der Anwender stellt im Shop den Warenkorb zusammen und löst „Warenkorb übertragen“ aus.
 3. Der Shop sendet den Warenkorb als XML per Formular-POST an die hookurl der App.
Dieser Teil liest und deutet das XML. Nicht geprüft gegen einen echten Shop; Grundlage ist die veröffentlichte
Spezifikation 2.5. Der Name des Formularfelds mit dem XML ist dort nicht ausdrücklich genannt, deshalb wird
jedes Feld und jede Datei untersucht.
"""
import re
import xml.etree.ElementTree as ET
from datetime import date
from decimal import Decimal, InvalidOperation

# Mengeneinheiten laut Codeliste der Spezifikation
EINHEITEN = {
    "PCE": "Stück", "MTR": "m", "KGM": "kg", "LTR": "l", "SET": "Satz", "PR": "Paar", "MTK": "m²", "MTQ": "m³",
    "CMT": "cm", "MMT": "mm", "GRM": "g", "TNE": "t", "DZN": "Dutzend", "KTM": "km", "HLT": "hl", "CMQ": "cm³", "CMK": "cm²",
}
MAX_BYTES = 5_000_000


class IdsFehler(ValueError):
    pass


def formular_teile(content_type, body):
    """Zerlegt eine Formular-Anfrage in [(Feldname, Rohbytes)], ohne den Zeichensatz umzuwandeln.

    Shops senden das XML oft in ISO-8859-1 (steht in der XML-Deklaration). Würde die Web-Bibliothek
    die Felder als UTF-8 lesen, gingen Umlaute verloren. Deshalb wird hier selbst zerlegt."""
    ct = (content_type or "").lower()
    teile = []
    if ct.startswith("multipart/"):
        from email import policy
        from email.parser import BytesParser
        kopf = b"MIME-Version: 1.0\r\nContent-Type: " + (content_type or "").encode("latin-1", "replace") + b"\r\n\r\n"
        try:
            nachricht = BytesParser(policy=policy.default).parsebytes(kopf + body)
            for teil in nachricht.iter_parts():
                name = teil.get_param("name", header="content-disposition") or ""
                teile.append((str(name), teil.get_payload(decode=True) or b""))
        except Exception:
            pass
    elif ct.startswith("application/x-www-form-urlencoded"):
        from urllib.parse import unquote_to_bytes
        for paar in body.split(b"&"):
            name, _, wert = paar.partition(b"=")
            teile.append((unquote_to_bytes(name.replace(b"+", b" ")).decode("utf-8", "replace"),
                          unquote_to_bytes(wert.replace(b"+", b" "))))
    return teile


def finde_xml(teile, rohdaten=b""):
    """Sucht den Warenkorb in den Formularteilen (bevorzugt das Feld „warenkorb“) oder im Rohtext der Anfrage."""
    kandidaten = list(teile) + [("(Rohdaten)", rohdaten)]
    kandidaten.sort(key=lambda k: 0 if k[0].lower() == "warenkorb" else 1)
    for _, inhalt in kandidaten:
        if inhalt and re.search(rb"<\s*(\w+:)?Warenkorb\b", inhalt[:20000]):
            return inhalt.strip()
    return None


def _lokal(tag):
    return tag.rsplit("}", 1)[-1]


def _kind(e, name):
    if e is None:
        return None
    for c in e:
        if _lokal(c.tag) == name:
            return c
    return None


def _pfad(e, pfad):
    for name in pfad.split("/"):
        e = _kind(e, name)
        if e is None:
            return None
    return e


def _text(e, pfad):
    x = _pfad(e, pfad)
    return (x.text or "").strip() if x is not None and x.text else ""


def _dez(s):
    try:
        return Decimal(s.strip()) if s and s.strip() else None
    except InvalidOperation:
        return None


def _datum(s):
    try:
        return date.fromisoformat(s.strip()) if s and s.strip() else None
    except ValueError:
        return None


def lesen(daten: bytes):
    if len(daten) > MAX_BYTES:
        raise IdsFehler("Der Warenkorb ist zu groß.")
    if re.search(rb"<!\s*(DOCTYPE|ENTITY)", daten, re.I):
        raise IdsFehler("Der Warenkorb enthält eine Dokumenttyp-Definition und wird aus Sicherheitsgründen nicht gelesen.")
    try:
        wurzel = ET.fromstring(daten)
    except ET.ParseError as e:
        raise IdsFehler(f"Der Warenkorb ist kein gültiges XML: {e}")
    if _lokal(wurzel.tag) != "Warenkorb":
        raise IdsFehler("Das XML ist kein IDS-Warenkorb (Wurzelelement „Warenkorb“ fehlt).")

    info = _kind(wurzel, "WarenkorbInfo")
    order = _kind(wurzel, "Order")
    oi = _kind(order, "OrderInfo")
    r = {
        "datum": _datum(_text(info, "Date")), "uhrzeit": _text(info, "Time"),
        "rueckgabe": _text(info, "RueckgabeKZ"), "version": _text(info, "Version"),
        "anfragenr": _text(oi, "InquiryNo"), "angebotsnr": _text(oi, "OfferNo"),
        "bestellnr_handwerker": _text(oi, "PartNo"), "ab_nr": _text(oi, "OrderConfNo"),
        "versandart": _text(oi, "ModeOfShipment"), "waehrung": _text(oi, "Cur"),
        "zusatztext": _text(oi, "ZusatzText"), "kommission": _text(oi, "Kommission"),
        "lieferdatum": _datum(_text(oi, "DeliveryDate")), "lieferwoche": None, "positionen": [], "warnungen": [],
        "lieferant_nr": _text(order, "SupplierInfo/IDNo"), "kunden_nr": _text(order, "CustomerInfo/IDNo"),
    }
    try:
        w, j = _text(oi, "DeliveryWeek"), _text(oi, "DeliveryYear")
        if w and j and not r["lieferdatum"]:
            r["lieferwoche"] = (int(j), int(w))
            r["lieferdatum"] = date.fromisocalendar(int(j), int(w), 5)       # Freitag der Lieferwoche
    except ValueError:
        r["warnungen"].append("Die Lieferwoche im Warenkorb ist nicht lesbar und wird ignoriert.")

    for nr, it in enumerate([x for x in (order if order is not None else []) if _lokal(x.tag) == "OrderItem"], 1):
        qty = _dez(_text(it, "Qty"))
        qu = _text(it, "QU")
        r["positionen"].append({
            "nr": nr, "art": _text(it, "ItemChara") or "normal",
            "ref_kunde": _text(it, "RefItems/Customer"), "ref_lieferant": _text(it, "RefItems/Supplier"),
            "artikelnr": _text(it, "ArtNo"), "ean": _text(it, "EAN"),
            "menge": qty, "einheit_code": qu, "einheit": EINHEITEN.get(qu, qu),
            "kurztext": _text(it, "Kurztext"), "langtext": _text(it, "Langtext"),
            "listenpreis": _dez(_text(it, "OfferPrice")), "nettopreis": _dez(_text(it, "NetPrice")),
            "preisbasis": _dez(_text(it, "PriceBasis")), "mwst": _dez(_text(it, "VAT")),
            "hinweis": _text(it, "Hinweis"), "fehlercode": _text(it, "Fehlercode"), "fehlertext": _text(it, "Fehlertext"),
        })
    if not r["positionen"]:
        r["warnungen"].append("Der Warenkorb enthält keine Positionen.")
    if r["version"] and r["version"] not in ("1.3", "2.0", "2.1", "2.2", "2.3", "2.5"):
        r["warnungen"].append(f"Unbekannte Schnittstellenversion {r['version']}.")
    return r


def einzelpreis(pos, modus="gesamt"):
    """Einzelpreis netto je Mengeneinheit.

    gesamt: Der Nettopreis gilt laut Spezifikation für die ganze Anfragemenge (Beispiel dort: 50 m = 522 €).
    einzel: Der Nettopreis gilt je Einheit (bzw. je „Preisbasis“ Einheiten).
    """
    netto, menge, basis = pos["nettopreis"], pos["menge"], pos["preisbasis"]
    if netto is None:
        return None
    if modus == "einzel":
        return netto / basis if basis and basis > 0 else netto
    return netto / menge if menge and menge > 0 else None


# ----------------------------------------------------------------- Diagnose
VERSIONEN = ["2.5", "2.3", "2.2", "2.1", "2.0", "1.3"]     # laut Spezifikation erlaubte Werte
BEISPIEL_WARENKORB = """<?xml version="1.0" encoding="UTF-8"?>
<Warenkorb xmlns="http://www.itek.de/Shop-Anbindung/Warenkorb/">
 <WarenkorbInfo><Date>{datum}</Date><Time>12:00:00</Time><RueckgabeKZ>Warenkorbrückgabe</RueckgabeKZ><Version>2.5</Version></WarenkorbInfo>
 <Order>
  <OrderInfo><ModeOfShipment>Lieferung</ModeOfShipment><Cur>EUR</Cur><Kommission>Selbsttest</Kommission></OrderInfo>
  <OrderItem><ArtNo>TEST-1</ArtNo><Qty>2</Qty><QU>PCE</QU><Kurztext>Testartikel (Selbsttest der Rückgabe)</Kurztext><NetPrice>9.80</NetPrice><PriceBasis>1</PriceBasis></OrderItem>
  <OrderItem><ArtNo>TEST-2</ArtNo><Qty>10</Qty><QU>MTR</QU><Kurztext>Testkabel (Selbsttest der Rückgabe)</Kurztext><NetPrice>25.00</NetPrice><PriceBasis>1</PriceBasis></OrderItem>
 </Order>
</Warenkorb>"""


def multipart(felder):
    import secrets
    grenze = "----einkauf" + secrets.token_hex(12)
    teile = []
    for name, wert in felder:
        teile.append(f'--{grenze}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n'.encode() + str(wert).encode("utf-8") + b"\r\n")
    teile.append(f"--{grenze}--\r\n".encode())
    return b"".join(teile), f"multipart/form-data; boundary={grenze}"


def abfrage(url, felder, timeout=15):
    """Schickt die Felder wie ein Browser (POST, multipart) an den Shop. Gibt Status, Typ und Antworttext zurück."""
    import urllib.error
    import urllib.request
    body, ct = multipart(felder)
    req = urllib.request.Request(url, data=body, method="POST", headers={"Content-Type": ct, "User-Agent": "Einkauf-IDS-Test"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return {"status": r.status, "typ": r.headers.get("Content-Type", ""), "daten": r.read(300_000), "url": r.geturl()}
    except urllib.error.HTTPError as e:
        return {"status": e.code, "typ": e.headers.get("Content-Type", "") if e.headers else "", "daten": e.read(300_000), "url": url}
    except Exception as e:
        return {"status": None, "typ": "", "daten": b"", "url": url, "fehler": f"{type(e).__name__}: {e}"}


def deuten(antwort):
    """Wertet die Antwort auf eine IDS-Abfrage (SV oder LI) aus."""
    if antwort.get("fehler"):
        return {"art": "netzwerk", "text": antwort["fehler"]}
    text = antwort["daten"].decode("utf-8", "replace").strip()
    if re.search(r"<\s*Schnittstellenversionen", text):
        return {"art": "versionen", "werte": re.findall(r"<Version>\s*([^<\s]+)\s*</Version>", text), "text": text[:500]}
    if re.search(r"<\s*Logininformationen", text):
        werte = {k: v.lower() == "true" for k, v in re.findall(r"<(Kundennummer_erforderlich|Benutzername_erforderlich|Passwort_erforderlich)>\s*(\w+)\s*<", text)}
        return {"art": "login", "werte": werte, "text": text[:500]}
    if re.match(r"(?is)\s*(<!doctype html|<html)", text):
        return {"art": "html", "text": re.sub(r"\s+", " ", re.sub(r"(?is)<(script|style).*?</\1>|<[^>]+>", " ", text))[:400]}
    return {"art": "unbekannt", "text": text[:500]}

"""Einfacher Einleser für Datanorm-Dateien (Version 4 und 5, Semikolon-getrennt).

Unterstützt die wichtigsten Stammsatz-Arten für Artikel und Preise:
  - Datanorm 4/5 Satzart A (Artikelstammsatz): A;N|A;<ArtNr>;...;<Kurztext1>;<Kurztext2>;...;<Einheit>;<Preis>;...
  - Satzart P (Preissatz): P;...;<ArtNr>;...;<Listenpreis>
Abweichende/unlesbare Zeilen werden übersprungen und als Warnung gemeldet.
"""
from decimal import Decimal, InvalidOperation

EINHEITEN = {
    "STK": "Stück", "ST": "Stück", "PCE": "Stück", "M": "m", "MTR": "m",
    "PA": "Paar", "PK": "Pack", "ROL": "Rolle", "K": "kg", "KG": "kg",
}


class DatanormFehler(ValueError):
    pass


def _dec_preis(wert, faktor=Decimal("1")):
    s = (wert or "").strip().replace(",", ".")
    if not s:
        return None
    try:
        v = Decimal(s)
        return (v / faktor).quantize(Decimal("0.0001"))
    except (InvalidOperation, ValueError):
        return None


def lesen(daten: bytes):
    if not daten or b"\x00" in daten[:200]:
        raise DatanormFehler("Das ist keine Datanorm-Textdatei.")
    text = daten.decode("cp850", errors="replace")
    if "ä" not in text and "ö" not in text and "ü" not in text:
        # Häufig auch CP1252/UTF-8
        t2 = daten.decode("cp1252", errors="replace")
        if any(c in t2 for c in "äöüÄÖÜß"):
            text = t2
    zeilen = [z.rstrip("\r\n") for z in text.splitlines() if z.strip()]
    if not zeilen:
        raise DatanormFehler("Die Datei ist leer.")

    artikel = {}
    warnungen = []
    erkannt = 0
    for nr, z in enumerate(zeilen, 1):
        felder = z.split(";")
        if len(felder) < 4:
            continue
        satz = felder[0].strip().upper()
        if satz == "A":
            # Datanorm 4: A;N|A;ArtNr;Textkz;Kurztext1;Kurztext2;Preiskz;Preiseinh;ME;Preis;Rabattgrp;...
            # Datanorm 5: A;N|A;ArtNr;Kurztext1;Kurztext2;... (oft identisch oder leicht verschoben)
            artnr = (felder[2] if len(felder) > 2 else "").strip()
            if not artnr:
                continue
            erkannt += 1
            if felder[1].strip().upper() == "L":
                continue
            # Heuristik für Text1/Text2/Einheit/Preis
            t1 = (felder[4] if len(felder) > 4 else "").strip()
            t2 = (felder[5] if len(felder) > 5 else "").strip()
            if not t1 and len(felder) > 3:
                t1 = felder[3].strip()
            me_raw = (felder[8] if len(felder) > 8 else "").strip().upper()
            einheit = EINHEITEN.get(me_raw, me_raw[:20] if me_raw else "Stück")
            preis = None
            if len(felder) > 9 and felder[9].strip():
                p_roh = felder[9].strip()
                # In Datanorm 4 stehen Preise oft als ganze Cent (ohne Komma)
                if "," not in p_roh and "." not in p_roh and p_roh.isdigit():
                    pe = (felder[7] if len(felder) > 7 else "").strip()
                    teiler = Decimal("100")
                    if pe == "1":
                        teiler = Decimal("1000")
                    elif pe == "2":
                        teiler = Decimal("10000")
                    preis = _dec_preis(p_roh, teiler)
                else:
                    preis = _dec_preis(p_roh)
            rabatt = (felder[10] if len(felder) > 10 else "").strip()[:30] or None
            artikel[artnr] = {
                "artikelnr": artnr[:100],
                "bezeichnung": (t1 or artnr)[:300],
                "kurztext2": t2[:300] or None,
                "einheit": einheit,
                "listenpreis": preis,
                "rabattgruppe": rabatt,
            }
        elif satz == "P":
            # Preissatz: P;N|A;ArtNr;...;Preis
            artnr = (felder[2] if len(felder) > 2 else "").strip()
            if artnr in artikel:
                for idx in (4, 5, 6, 7):
                    if len(felder) > idx and felder[idx].strip():
                        p = _dec_preis(felder[idx], Decimal("100") if felder[idx].strip().isdigit() else Decimal("1"))
                        if p is not None:
                            artikel[artnr]["listenpreis"] = p
                            break
    if not erkannt or not artikel:
        raise DatanormFehler("Keine gültigen Datanorm-Artikelsätze (Satzart A) gefunden.")
    return {"artikel": list(artikel.values()), "warnungen": warnungen}


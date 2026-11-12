"""Einleser für UGL-Dateien (feste Satzlänge 200, Windows-Zeichensatz).

Der Aufbau wurde aus einer Beispieldatei von Fega & Schmitt (Version 04.00) abgeleitet,
nicht aus einer offiziellen Satzbeschreibung. Abweichende Dateien werden mit Warnungen
gemeldet statt still falsch gelesen.

Satzarten:  RGD = Dateikopf, KOP = Belegkopf, POA = Position, END = Dateiende.
"""
import re
from datetime import date
from decimal import Decimal

UNTERSTUETZT = {"04.00"}


class UglFehler(ValueError):
    pass


def _datum(s):
    s = (s or "").strip()
    if re.fullmatch(r"\d{8}", s) and s != "00000000":
        try:
            return date(int(s[:4]), int(s[4:6]), int(s[6:8]))
        except ValueError:
            return None
    return None


def _norm(artikelnr):
    """Vergleichsform einer Artikelnummer: ohne Leerzeichen und führende Nullen, kleingeschrieben."""
    return (artikelnr or "").strip().replace(" ", "").lstrip("0").casefold()


def normalisiere(artikelnr):
    return _norm(artikelnr)


def lesen(daten: bytes):
    if not daten or b"\x00" in daten[:200]:
        raise UglFehler("Das ist keine UGL-Textdatei.")
    text = daten.decode("cp1252", errors="replace")
    zeilen = [z for z in text.replace("\r\n", "\n").replace("\r", "\n").split("\n") if z.strip()]
    if not zeilen or not zeilen[0].startswith(("RGD", "KOP")):
        raise UglFehler("Die Datei beginnt nicht mit einem UGL-Kopfsatz (RGD/KOP).")

    ergebnis = {"datei": {}, "kopf": {}, "positionen": [], "warnungen": []}
    for nr, z in enumerate(zeilen, 1):
        art = z[:3]
        if len(z) < 190 and art in ("RGD", "KOP", "POA"):
            ergebnis["warnungen"].append(f"Zeile {nr}: ungewöhnliche Länge ({len(z)} statt 200 Zeichen).")
        z = z.ljust(200)
        if art == "RGD":
            ergebnis["datei"] = {
                "nummer": z[3:13].strip(), "kennung": z[13:15].strip(),
                "datum": _datum(z[15:23]), "waehrung": z[23:26].strip(),
            }
        elif art == "KOP":
            ergebnis["kopf"] = {
                "kundennr": z[3:9].strip(), "belegart": z[23:25].strip(), "belegnr": z[90:100].strip(),
                "waehrung": z[113:116].strip(), "version": z[116:121].strip(),
                "datum": _datum(z[161:169]),
            }
        elif art == "POA":
            try:
                pos = int(z[3:13])
                menge = Decimal(int(z[38:49])) / Decimal(1000)
            except ValueError:
                ergebnis["warnungen"].append(f"Zeile {nr}: Position oder Menge nicht lesbar, Zeile übersprungen.")
                continue
            ref = re.search(r"(\d+);(\d+)", z[129:181])
            ergebnis["positionen"].append({
                "pos": pos, "artikelnr": z[23:38].strip(), "menge": menge,
                "text1": z[49:89].strip(), "text2": z[89:129].strip(),
                "einheit": z[183:187].strip(), "verweis": ref.group(0).lstrip("0") if ref else "",
            })
    if not ergebnis["positionen"]:
        raise UglFehler("In der Datei wurden keine Positionen (POA) gefunden.")
    if ergebnis["kopf"].get("version") not in UNTERSTUETZT:
        ergebnis["warnungen"].append(
            f"Dateiversion {ergebnis['kopf'].get('version') or '?'} ist nicht geprüft. Bitte Vorschau genau ansehen.")
    return ergebnis


def abgleichen(positionen, items):
    """Ordnet Dateipositionen den Bestellpositionen über die Artikelnummer zu.

    Rückgabe: (zeilen, fehlend)
      zeilen  – je Dateiposition: Zuordnungen [(item, menge)], 'rest_ueber' (Menge ohne Platz), 'art'
      fehlend – Bestellpositionen mit Rest, die in der Datei nicht vorkommen
    """
    nach_art = {}
    for i in sorted(items, key=lambda x: x.id):
        if i.storniert:
            continue
        nach_art.setdefault(_norm(i.artikelnr), []).append(i)
    frei = {i.id: i.rest for lst in nach_art.values() for i in lst}
    gesehen = set()
    zeilen = []
    for p in positionen:
        key = _norm(p["artikelnr"])
        kandidaten = nach_art.get(key, []) if key else []
        gesehen.add(key)
        zuordnung, rest = [], p["menge"]
        for i in kandidaten:
            if rest <= 0:
                break
            nimm = min(frei[i.id], rest)
            if nimm > 0:
                zuordnung.append((i, nimm))
                frei[i.id] -= nimm
                rest -= nimm
        if not kandidaten:
            art = "unbekannt"
        elif rest > 0 and zuordnung:
            art = "mehr"
        elif rest > 0:
            art = "schon_geliefert"
        elif sum(m for _, m in zuordnung) < sum(i.rest for i in kandidaten):
            art = "weniger"
        else:
            art = "ok"
        zeilen.append({"p": p, "zuordnung": zuordnung, "rest_ueber": rest, "art": art, "kandidaten": kandidaten})
    fehlend = [i for lst in nach_art.values() for i in lst
               if _norm(i.artikelnr) not in gesehen and i.rest > 0]
    return zeilen, sorted(fehlend, key=lambda x: x.id)


def schreiben(order) -> bytes:
    """Erzeugt eine UGL-Bestelldatei (Version 04.00, 200 Zeichen/Zeile, CP1252, CRLF)."""
    def satz(s):
        return s[:200].ljust(200)

    kndnr = ((order.supplier.kundennr or "") if order.supplier else "")[:6].ljust(6)
    belegnr = (order.bestellnr or str(order.id))[:10].ljust(10)
    dat = order.bestelldatum.strftime("%Y%m%d") if order.bestelldatum else date.today().strftime("%Y%m%d")
    lfd = f"{order.id:010d}"[:10]

    zeilen = [
        satz(f"RGD{lfd}BE{dat}EUR"),
        satz("KOP" + kndnr + " " * 14 + "BE" + " " * 65 + belegnr + " " * 13 + "EUR" + "04.00" + " " * 40 + dat),
    ]
    pos_nr = 0
    for item in order.items:
        if item.storniert:
            continue
        pos_nr += 1
        art = (item.artikelnr or "")[:15].ljust(15)
        tausend = int((item.menge * Decimal("1000")).quantize(Decimal("1")))
        menge_str = f"{tausend:011d}"[-11:]
        t1 = (item.bezeichnung or "")[:40].ljust(40)
        t2 = (item.kommission or "")[:40].ljust(40)
        me = (item.einheit or "STK")[:4].upper().ljust(4)
        zeilen.append(satz(f"POA{pos_nr:010d}" + " " * 10 + art + menge_str + t1 + t2 + " " * 54 + me))
    zeilen.append(satz(f"END{pos_nr:010d}"))
    return ("\r\n".join(zeilen) + "\r\n").encode("cp1252", errors="replace")

"""Einleser für Datanorm-Dateien (Version 4 und 5, Semikolon-getrennt).

Unterstützt die wichtigsten Stammsatz-Arten für Artikel und Preise im Elektrohandwerk:
  - Satzart V (Dateikopf): Version 4 oder 5, Datum, Währung, Händler
  - Satzart A (Artikelstammsatz):
      Datanorm 4 (z. B. Rexel): A;N;ArtNr;Textkz;Kurztext1;Kurztext2;Preiskz;Preiseinh;ME;Preis;Rabattgrp;...
      Datanorm 5 (z. B. Fega):  A;N;ArtNr;Kurztext1;Kurztext2;ME;Preiskz;Preiseinh;Preis;Rabattgrp;...;EAN;...
  - Satzart B (Zusatzsatz Datanorm 4):
      B;N;ArtNr;Matchcode;HerstellerNr;...;Kupfermerker;Kupferbasis;Kupfergewicht;EAN;...
  - Satzart P (Preissatz / reine Preis-Datanorm / Preispflege):
      P;ArtNr;Preistyp;Preiseinheit;PreisCent   (Fega-Preissatz)
      P;N;ArtNr;Preistyp;Preiseinheit;PreisCent (Standard-Preissatz)
      P;N;ArtNr;Preiskz;Preiseinh;PreisCent;Rabattgruppe (Datanorm 4 Preissatz)

Preiseinheiten (PE = 1, 10, 100, 1000) werden exakt berücksichtigt, sodass Einzelpreise
immer pro Stück bzw. pro Meter gespeichert werden (kein Faktor-100-Fehler bei Kabeln).
Kupferdaten (Kupfermerker, Kupferbasis z. B. 150 €, Kupfergewicht / Cu-Zahl) werden
gespeichert, um den tagesaktuellen Kupferzuschlag (DEL-Notiz) berechnen zu können.
"""
from decimal import Decimal, InvalidOperation

EINHEITEN = {
    "STK": "Stück", "ST": "Stück", "PCE": "Stück", "STCK": "Stück", "STUECK": "Stück",
    "M": "m", "MTR": "m", "LFM": "m",
    "PA": "Paar", "PK": "Pack", "PAK": "Pack", "PACK": "Pack", "ROL": "Rolle",
    "K": "kg", "KG": "kg", "G": "g", "GRM": "g", "SET": "Set", "BT": "Beutel",
}


class DatanormFehler(ValueError):
    pass


def _pe_faktor(pe_raw: str | None, is_dn5: bool = False) -> int:
    """Gibt den Multiplikator der Preiseinheit zurück (z. B. 1, 10, 100, 1000).

    Sowohl Datanorm 4 Codes (0=1, 2=100, 3=1000) als auch direkte Zahlen (1, 100, 1000)
    werden einheitlich aufgelöst.
    """
    s = (pe_raw or "").strip().upper()
    if not s or s in ("0", "1", "STK", "STCK", "M", "MTR", "1STK"):
        return 1
    if s == "2" or s == "100":
        return 100
    if s == "3" or s == "1000":
        return 1000
    if s == "4" or s == "10000":
        return 10000
    if s == "10":
        return 10
    if s.isdigit():
        v = int(s)
        return v if v > 0 else 1
    return 1


def _dec_preis(wert: str | None, pe: int = 1) -> Decimal | None:
    """Wandelt einen Preisstring um und teilt ihn durch die Preiseinheit.

    Ganzzahlige Werte ohne Dezimaltrennzeichen werden als Cent interpretiert (Standard in Datanorm).
    Dezimalwerte (mit Komma oder Punkt) werden als Euro interpretiert.
    """
    s = (wert or "").strip().replace(",", ".")
    if not s:
        return None
    try:
        v = Decimal(s)
        teiler = Decimal(pe) if pe > 0 else Decimal(1)
        if "." not in s:
            return (v / (Decimal(100) * teiler)).quantize(Decimal("0.0001"))
        else:
            return (v / teiler).quantize(Decimal("0.0001"))
    except (InvalidOperation, ValueError):
        return None


def _dec_zahl(wert: str | None, teiler: Decimal = Decimal(1)) -> Decimal | None:
    s = (wert or "").strip().replace(",", ".")
    if not s:
        return None
    try:
        v = Decimal(s)
        return (v / teiler).quantize(Decimal("0.001"))
    except (InvalidOperation, ValueError):
        return None


def lesen(daten: bytes, modus: str = "auto"):
    if not daten:
        raise DatanormFehler("Die Datei ist leer.")

    # ZIP-Archiv automatisch entpacken
    if daten[:4] == b"PK\x03\x04":
        import io
        import re
        import zipfile
        try:
            with zipfile.ZipFile(io.BytesIO(daten)) as z:
                namen = z.namelist()
                if not namen:
                    raise DatanormFehler("Das ZIP-Archiv enthält keine Dateien.")

                if modus == "nur_preise":
                    preis_datei = next((n for n in namen if "preis" in n.lower() and not n.endswith("/")), None)
                    if preis_datei:
                        return lesen(z.read(preis_datei), modus=modus)
                    stamm_datei = next((n for n in namen if re.search(r"\.(001|701|dat|txt)$", n.lower()) and not n.endswith("/")), namen[0])
                    return lesen(z.read(stamm_datei), modus=modus)

                stamm_datei = next((n for n in namen if re.search(r"(datanorm|\.(001|701))", n.lower()) and "preis" not in n.lower() and not n.endswith("/")), None)
                preis_datei = next((n for n in namen if "preis" in n.lower() and not n.endswith("/")), None)

                if stamm_datei:
                    res = lesen(z.read(stamm_datei), modus=modus)
                    if preis_datei:
                        res_p = lesen(z.read(preis_datei), modus="nur_preise")
                        res["preise"].update(res_p.get("preise", {}))
                        p_map = res_p.get("preise", {})
                        for a in res["artikel"]:
                            pd = p_map.get(a["artikelnr"])
                            if pd:
                                if pd.get("listenpreis") is not None:
                                    a["listenpreis"] = pd["listenpreis"]
                                if pd.get("preiseinheit"):
                                    a["preiseinheit"] = pd["preiseinheit"]
                    return res
                elif preis_datei:
                    return lesen(z.read(preis_datei), modus="nur_preise")
                else:
                    return lesen(z.read(namen[0]), modus=modus)
        except zipfile.BadZipFile:
            raise DatanormFehler("Das ZIP-Archiv ist beschädigt.")

    if not daten or b"\x00" in daten[:200]:
        raise DatanormFehler("Das ist keine Datanorm-Textdatei.")

    text = daten.decode("cp850", errors="replace")
    if "ä" not in text and "ö" not in text and "ü" not in text:
        t2 = daten.decode("cp1252", errors="replace")
        if any(c in t2 for c in "äöüÄÖÜß"):
            text = t2

    zeilen = [z.rstrip("\r\n") for z in text.splitlines() if z.strip()]
    if not zeilen:
        raise DatanormFehler("Die Datei ist leer.")

    # 1. Version ermitteln
    is_dn5 = False
    for z in zeilen[:25]:
        if z.startswith("V;") and ";050;" in z:
            is_dn5 = True
            break

    # Falls kein V-Satz da ist: Heuristik anhand der ersten A-Sätze
    if not is_dn5:
        for z in zeilen:
            if z.startswith("A;"):
                f = z.split(";")
                if len(f) > 15:
                    is_dn5 = True
                break

    artikel = {}
    preise = {}
    loeschungen = set()
    warengruppen = {}
    rabattgruppen = {}
    warnungen = []
    anz_a, anz_p, anz_b, anz_l, anz_s, anz_r = 0, 0, 0, 0, 0, 0

    for nr, z in enumerate(zeilen, 1):
        felder = z.split(";")
        if len(felder) < 2:
            continue
        satz = felder[0].strip().upper()

        if satz == "A":
            if len(felder) < 3:
                continue
            artnr = felder[2].strip()
            if not artnr:
                continue
            v_kz = felder[1].strip().upper()
            if v_kz == "L":
                loeschungen.add(artnr)
                anz_l += 1
                continue

            anz_a += 1
            if is_dn5:
                # Datanorm 5 (Fega)
                # 0: A, 1: N/K, 2: ArtNr, 3: Text1, 4: Text2, 5: ME, 6: Preiskz, 7: PE, 8: Preis, 9: Rabatt, 10: HauptWG, 11: WG, 12: Matchcode, ... 16: HerstNr, 18: EAN
                t1 = felder[3].strip() if len(felder) > 3 else ""
                t2 = felder[4].strip() if len(felder) > 4 else ""
                me_raw = felder[5].strip().upper() if len(felder) > 5 else ""
                pe_raw = felder[7].strip() if len(felder) > 7 else ""
                p_raw = felder[8].strip() if len(felder) > 8 else ""
                rabatt = felder[9].strip()[:30] if len(felder) > 9 else None
                matchcode = felder[12].strip()[:50] if len(felder) > 12 else None
                herst_nr = felder[16].strip()[:100] if len(felder) > 16 else None
                ean = felder[18].strip()[:30] if len(felder) > 18 else None
            else:
                # Datanorm 4 (Rexel)
                # 0: A, 1: N/K, 2: ArtNr, 3: Textkz, 4: Text1, 5: Text2, 6: Preiskz, 7: PE, 8: ME, 9: Preis, 10: Rabatt, 11: HauptWG
                t1 = felder[4].strip() if len(felder) > 4 else ""
                t2 = felder[5].strip() if len(felder) > 5 else ""
                pe_raw = felder[7].strip() if len(felder) > 7 else ""
                me_raw = felder[8].strip().upper() if len(felder) > 8 else ""
                p_raw = felder[9].strip() if len(felder) > 9 else ""
                rabatt = felder[10].strip()[:30] if len(felder) > 10 else None
                matchcode, herst_nr, ean = None, None, None

            einheit = EINHEITEN.get(me_raw, me_raw[:20] if me_raw else "Stück")
            pe = _pe_faktor(pe_raw, is_dn5=is_dn5)
            listenpreis = _dec_preis(p_raw, pe=pe)

            if artnr in artikel:
                a = artikel[artnr]
                a["bezeichnung"] = t1 or a.get("bezeichnung") or artnr
                a["kurztext2"] = t2 or a.get("kurztext2")
                a["einheit"] = einheit
                a["preiseinheit"] = pe
                if listenpreis is not None:
                    a["listenpreis"] = listenpreis
                if rabatt:
                    a["rabattgruppe"] = rabatt
                if matchcode:
                    a["matchcode"] = matchcode
                if herst_nr:
                    a["hersteller_artnr"] = herst_nr
                if ean:
                    a["ean"] = ean
            else:
                artikel[artnr] = {
                    "artikelnr": artnr[:100],
                    "bezeichnung": (t1 or artnr)[:300],
                    "kurztext2": t2[:300] or None,
                    "einheit": einheit,
                    "preiseinheit": pe,
                    "listenpreis": listenpreis,
                    "rabattgruppe": rabatt,
                    "matchcode": matchcode,
                    "hersteller_artnr": herst_nr,
                    "ean": ean,
                    "kupferbasis": None,
                    "kupfergewicht": None,
                    "kupfermerker": None,
                }

        elif satz == "B":
            # Satzart B: Zusatzsatz in Datanorm 4 (Kupfer, EAN, Matchcode, Hersteller-Nr)
            # 0: B, 1: N/K, 2: ArtNr, 3: Matchcode, 4: HerstNr, 6: Cu-Merker, 7: Cu-Basis, 8: Cu-Gewicht, 9: EAN
            if len(felder) < 3:
                continue
            artnr = felder[2].strip()
            if not artnr:
                continue
            anz_b += 1
            matchcode = felder[3].strip()[:50] if len(felder) > 3 else None
            herst_nr = felder[4].strip()[:100] if len(felder) > 4 else None
            cu_merker = int(felder[6].strip()) if (len(felder) > 6 and felder[6].strip().isdigit()) else None
            cu_basis = _dec_zahl(felder[7]) if len(felder) > 7 else None
            cu_gew_raw = felder[8].strip() if len(felder) > 8 else None
            cu_gewicht = None
            if cu_gew_raw:
                try:
                    cu_gewicht = (Decimal(cu_gew_raw) / Decimal(1000)).quantize(Decimal("0.001"))
                except (InvalidOperation, ValueError):
                    pass
            ean = felder[9].strip()[:30] if len(felder) > 9 else None

            if artnr in artikel:
                a = artikel[artnr]
                if matchcode and not a.get("matchcode"):
                    a["matchcode"] = matchcode
                if herst_nr and not a.get("hersteller_artnr"):
                    a["hersteller_artnr"] = herst_nr
                if cu_merker is not None:
                    a["kupfermerker"] = cu_merker
                if cu_basis is not None:
                    a["kupferbasis"] = cu_basis
                if cu_gewicht is not None:
                    a["kupfergewicht"] = cu_gewicht
                if ean and not a.get("ean"):
                    a["ean"] = ean
            else:
                artikel[artnr] = {
                    "artikelnr": artnr[:100],
                    "bezeichnung": artnr,
                    "kurztext2": None,
                    "einheit": "Stück",
                    "preiseinheit": 1,
                    "listenpreis": None,
                    "rabattgruppe": None,
                    "matchcode": matchcode,
                    "hersteller_artnr": herst_nr,
                    "ean": ean,
                    "kupferbasis": cu_basis,
                    "kupfergewicht": cu_gewicht,
                    "kupfermerker": cu_merker,
                }

        elif satz == "P":
            # Satzart P: Preissatz (Preispflege)
            # In Datanorm 4: P;A;ArtNr1;Typ1;Preis1;PE1;RG1;;;;;ArtNr2;Typ2;Preis2;PE2;RG2;;;;;ArtNr3;...
            # In Datanorm 5: P;ArtNr;Preiskz;PE;Preis;RG;...
            if len(felder) < 3:
                continue

            p_bloecke = []
            if felder[1].strip().upper() in ("N", "K", "A", "L"):
                # Datanorm 4: Bis zu 3 Artikelblöcke je Zeile im Abstand von 9 Feldern (2, 11, 20)
                for off in (2, 11, 20):
                    if off < len(felder) and felder[off].strip():
                        artnr = felder[off].strip()
                        ptyp = felder[off + 1].strip() if len(felder) > off + 1 else "1"
                        praw = felder[off + 2].strip() if len(felder) > off + 2 else ""
                        peraw = felder[off + 3].strip() if len(felder) > off + 3 else "0"
                        if praw:
                            p_bloecke.append((artnr, ptyp or "1", praw, peraw or "0"))
            else:
                # Datanorm 5: 0: P, 1: ArtNr, 2: Preiskz, 3: PE, 4: Preis
                artnr = felder[1].strip() if len(felder) > 1 else ""
                ptyp = felder[2].strip() if len(felder) > 2 else "1"
                peraw = felder[3].strip() if len(felder) > 3 else "1"
                praw = felder[4].strip() if len(felder) > 4 else ""
                if artnr and praw:
                    p_bloecke.append((artnr, ptyp or "1", praw, peraw or "1"))

            for artnr, preistyp, p_raw, pe_raw in p_bloecke:
                anz_p += 1
                pe = _pe_faktor(pe_raw, is_dn5=is_dn5)
                preis = _dec_preis(p_raw, pe=pe)
                if preis is not None:
                    if artnr not in preise:
                        preise[artnr] = {
                            "artikelnr": artnr[:100],
                            "listenpreis": preis if preistyp == "1" else None,
                            "ekpreis": preis if preistyp == "2" else None,
                            "preiseinheit": pe,
                            "preistyp": preistyp,
                        }
                    else:
                        if preistyp == "1":
                            preise[artnr]["listenpreis"] = preis
                        elif preistyp == "2":
                            preise[artnr]["ekpreis"] = preis

                    # Falls nur EK-Preis da war, als Listenpreis vorsehen
                    if preise[artnr]["listenpreis"] is None and preise[artnr].get("ekpreis") is not None:
                        preise[artnr]["listenpreis"] = preise[artnr]["ekpreis"]

                    if artnr in artikel:
                        if preistyp == "1" or artikel[artnr].get("listenpreis") is None:
                            artikel[artnr]["listenpreis"] = preis
                            artikel[artnr]["preiseinheit"] = pe

        elif satz == "S":
            # Satzart S: Warengruppen (Datanorm 4/5)
            # z.B. S;;1;Kabel und Leitungen;;; oder S;;10;;01;Ausgleichsleitung;
            anz_s += 1
            wg_code = felder[2].strip() if len(felder) > 2 else ""
            wg_text = felder[3].strip() if len(felder) > 3 and felder[3].strip() else (felder[5].strip() if len(felder) > 5 else "")
            if wg_code and wg_text:
                warengruppen[wg_code] = wg_text[:100]

        elif satz == "R":
            # Satzart R: Rabattgruppen (Datanorm 4/5)
            # z.B. R;;1000;1;1000;;
            anz_r += 1
            rg_code = felder[2].strip() if len(felder) > 2 else ""
            rg_text = felder[4].strip() if len(felder) > 4 and felder[4].strip() else rg_code
            if rg_code:
                rabattgruppen[rg_code] = rg_text[:50]

    if not anz_a and not anz_p and not anz_b and not anz_l and not anz_s and not anz_r:
        raise DatanormFehler("In der Datei wurden keine gültigen Datanorm-Sätze (A, B, P, S oder R) gefunden.")

    ist_reine_preisdatei = (anz_p > 0 and anz_a == 0 and anz_l == 0)
    ist_reine_loeschdatei = (anz_l > 0 and anz_a == 0 and anz_p == 0)
    ist_reine_warengruppendatei = (anz_s > 0 and anz_a == 0 and anz_p == 0 and anz_l == 0)

    return {
        "artikel": list(artikel.values()),
        "preise": preise,
        "loeschungen": list(loeschungen),
        "warengruppen": warengruppen,
        "rabattgruppen": rabattgruppen,
        "is_dn5": is_dn5,
        "ist_reine_preisdatei": ist_reine_preisdatei,
        "ist_reine_loeschdatei": ist_reine_loeschdatei,
        "ist_reine_warengruppendatei": ist_reine_warengruppendatei,
        "anzahl_artikel": anz_a,
        "anzahl_preise": anz_p,
        "anzahl_zusatz": anz_b,
        "anzahl_loeschungen": anz_l,
        "anzahl_warengruppen": anz_s,
        "anzahl_rabattgruppen": anz_r,
        "warnungen": warnungen,
    }

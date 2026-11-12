"""Nummernkreise mit Muster, z. B. P-YYYY-XXXX oder YYMMDDXXXX.

Platzhalter: YYYY = Jahr vierstellig, YY = Jahr zweistellig, MM = Monat, DD = Tag,
X…X = laufende Nummer (Anzahl der X = Stellen, mit Nullen aufgefüllt). Genau eine X-Folge.
Alles andere (Buchstaben, Ziffern, - _ . /) bleibt unverändert. Y, M, D und X sind reserviert.
"""
import re
from datetime import date

from .models import NumberRange

TOKEN = re.compile(r"YYYY|YY|MM|DD|X+")
ERLAUBT = re.compile(r"^[A-Za-z0-9\-_./]+$")
STANDARD = {
    "projekt": {"muster": "P-YYYY-XXXX", "reset": "auto", "start": 1},
    "bestellung": {"muster": "B-YYYY-XXXX", "reset": "auto", "start": 1},
}
TITEL = {"projekt": "Projektnummer", "bestellung": "Bestellnummer"}
RESET = {"auto": "automatisch nach Muster", "nie": "nie", "jahr": "jedes Jahr", "monat": "jeden Monat", "tag": "jeden Tag"}


def pruefen(muster):
    """Gibt eine Fehlermeldung zurück oder None, wenn das Muster passt."""
    if not muster:
        return "Bitte ein Muster eingeben."
    if len(muster) > 40 or not ERLAUBT.match(muster):
        return "Das Muster darf nur Buchstaben, Ziffern und - _ . / enthalten (bis 40 Zeichen)."
    if re.search(r"[YMDX]", TOKEN.sub("", muster)):
        return "Y, M, D und X sind reserviert: YYYY, YY, MM, DD für das Datum und X für die laufende Nummer."
    xs = re.findall(r"X+", muster)
    if len(xs) != 1:
        return "Das Muster braucht genau eine Folge aus X für die laufende Nummer, z. B. XXXX."
    if len(xs[0]) > 10:
        return "Die laufende Nummer darf höchstens 10 Stellen haben."
    return None


def formatieren(muster, n, datum=None):
    datum = datum or date.today()

    def ersetzen(m):
        t = m.group(0)
        if t == "YYYY":
            return f"{datum.year:04d}"
        if t == "YY":
            return f"{datum.year % 100:02d}"
        if t == "MM":
            return f"{datum.month:02d}"
        if t == "DD":
            return f"{datum.day:02d}"
        return str(n).zfill(len(t))

    return TOKEN.sub(ersetzen, muster)


def reset_art(r):
    if r.reset in ("nie", "jahr", "monat", "tag"):
        return r.reset
    m = r.muster or ""
    if "DD" in m:
        return "tag"
    if "MM" in m:
        return "monat"
    if "YY" in m:
        return "jahr"
    return "nie"


def periode(r, datum=None):
    d = datum or date.today()
    return {"nie": "", "jahr": f"{d.year}", "monat": f"{d.year}-{d.month:02d}", "tag": d.isoformat()}[reset_art(r)]


def holen(s, key):
    r = s.get(NumberRange, key)
    if r is None:
        st = STANDARD[key]
        r = NumberRange(key=key, muster=st["muster"], reset=st["reset"], start=st["start"], naechste=st["start"])
        r.periode = periode(r)
        s.add(r)
        s.flush()
    return r


def vorschlag(s, key, vorhanden):
    """Nächste freie Nummer. `vorhanden(nummer)` sagt, ob sie schon vergeben ist."""
    r = holen(s, key)
    p = periode(r)
    if r.periode != p:                      # neue Periode (Jahr/Monat/Tag): Zähler beginnt neu
        r.periode, r.naechste = p, r.start
    n = r.naechste
    for _ in range(100000):
        nr = formatieren(r.muster, n)
        if not vorhanden(nr):
            return nr
        n += 1
    return formatieren(r.muster, r.naechste)


def verbrauchen(s, key, nummer):
    """Zähler nachziehen, wenn die gespeicherte Nummer zum heutigen Muster passt und nicht kleiner ist."""
    if not nummer:
        return
    r = holen(s, key)
    heute = date.today()
    teile, pos = [], 0
    for m in TOKEN.finditer(r.muster):
        teile.append(re.escape(r.muster[pos:m.start()]))
        t = m.group(0)
        teile.append(r"(\d+)" if t.startswith("X") else re.escape(formatieren(t, 0, heute)))
        pos = m.end()
    teile.append(re.escape(r.muster[pos:]))
    treffer = re.fullmatch("".join(teile), nummer)
    if treffer and int(treffer.group(1)) >= r.naechste:
        r.naechste = int(treffer.group(1)) + 1

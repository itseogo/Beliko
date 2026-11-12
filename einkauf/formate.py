"""Anzeige- und Eingabeformate (deutsch)."""
from decimal import Decimal


def qty(v):
    if v is None or v == "":
        return ""
    return format(Decimal(v).normalize(), "f").replace(".", ",")


def money(v):
    """Betrag mit 2 Nachkommastellen und Tausenderpunkt, z. B. 1.234,56 €."""
    if v is None or v == "":
        return ""
    s = f"{Decimal(v):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return s + " €"


def _preis_text(v, tausender):
    q = Decimal(v).quantize(Decimal("0.0001"))
    ganz, _, rest = f"{q:.4f}".partition(".")
    rest = rest.rstrip("0").ljust(2, "0")
    if tausender:
        ganz = f"{int(ganz):,}".replace(",", ".")
    return f"{ganz},{rest}"


def preis(v):
    """Einzelpreis mit mindestens 2 und höchstens 4 Nachkommastellen, z. B. 0,0474 € oder 2,21 €."""
    if v is None or v == "":
        return ""
    return _preis_text(v, True) + " €"


def preis_eingabe(v):
    if v is None or v == "":
        return ""
    return _preis_text(v, False)


def datum(d):
    return d.strftime("%d.%m.%Y") if d else ""

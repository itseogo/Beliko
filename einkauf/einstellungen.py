"""Schlüssel/Wert-Einstellungen in der Datenbank."""
from .models import Setting


def lesen(s, key, default=None):
    row = s.get(Setting, key)
    return row.value if row is not None and row.value is not None else default


def schreiben(s, key, value):
    row = s.get(Setting, key)
    if row is None:
        s.add(Setting(key=key, value=value))
    else:
        row.value = value


def an(s, key, default=False):
    v = lesen(s, key)
    return default if v is None else v == "1"

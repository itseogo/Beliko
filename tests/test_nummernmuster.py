"""Einheitentest für die Nummernmuster (ohne Datenbank)."""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from datetime import date
from types import SimpleNamespace as NS
from einkauf import nummern as n

d = date(2026, 10, 31)
assert n.formatieren("YYMMDDXXXX", 1, d) == "2610310001"                 # das Beispiel aus dem Auftrag
assert n.formatieren("P-YYYY-XXXX", 7, d) == "P-2026-0007"
assert n.formatieren("2265XXXX", 2081, d) == "22652081"
assert n.formatieren("B-XXXXX/YY", 12, d) == "B-00012/26"
assert n.formatieren("XXX", 12345, d) == "12345"                          # Zähler größer als die Stellen läuft über, statt abzuschneiden
for gut in ["YYMMDDXXXX", "P-YYYY-XXXX", "XXXX", "2265XXXX", "A_B.C/XXX"]:
    assert n.pruefen(gut) is None, gut
for schlecht in ["", "P-YYYY", "P-XXXX-XX", "P-YYY-XXXX", "P XXXX", "P!XXXX", "MXXXX", "X" * 11, "A" * 41]:
    assert n.pruefen(schlecht), schlecht
art = lambda m, reset="auto": n.reset_art(NS(muster=m, reset=reset))
assert art("YYMMDDXXXX") == "tag" and art("YYMMXXXX") == "monat" and art("P-YYYY-XXXX") == "jahr" and art("2265XXXX") == "nie"
assert art("YYMMDDXXXX", "nie") == "nie"
print("NUMMERNMUSTER OK")

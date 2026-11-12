"""Erzeugt eine nachgebaute UGL-Datei (Version 04.00) im abgeleiteten Aufbau, für Tests.
Enthält keine echten Lieferantendaten."""
from decimal import Decimal

BEISPIEL = [  # pos, artikelnr, text1, text2, menge, einheit
    (1, "556023", "JUNG Abdeckung A569-2BFPLUAWW", "fuer IAE/UAE", 5, "STK"),
    (2, "056309", "PROT Geraeteschraube PGSKO 3215", "Kombi 15mm", 100, "STK"),
    (3, "057433", "1PROT Kupferband selbstklebend", "Beutel a 20Stk.", 3, "BG"),
    (4, "115418", "KATH Verteiler EBC 03/G", "3fach", 1, "STK"),
    (5, "853346", "KATH F-Stecker EMK 01", "", 10, "STK"),
    (6, "263595", "DOEP FI-Schutzschalter DFS4 063-4/0,03-A", "4polig", 2, "STK"),
    (7, "557607", "JUNG Leitungsauslass AS590AWW", "", 3, "STK"),
    (8, "567465", "WERA Bit-Schraubendreherset", "26-tlg.", 1, "STK"),
    (10, "256019", "JUNG Taster 531U", "1polig Schliesser", 1, "STK"),  # Position 9 fehlt absichtlich
]


def _satz(felder):
    z = bytearray(b" " * 200)
    for start, text in felder:
        z[start:start + len(text)] = text.encode("cp1252")
    return bytes(z)


def beispiel(positionen=BEISPIEL, belegart="AB"):
    zeilen = [
        _satz([(0, "RGD"), (3, "4755816401"), (13, "LS"), (15, "20261027"), (23, "EUR")]),
        _satz([(0, "KOP"), (3, "108690"), (23, belegart), (90, "4755816401"), (113, "EUR"), (116, "04.00"),
               (121, "Max Muster"), (161, "20261025")]),
    ]
    for pos, art, t1, t2, menge, einheit in positionen:
        zeilen.append(_satz([
            (0, "POA"), (3, f"{pos:010d}"), (13, f"{pos:010d}"), (23, art), (38, f"{int(Decimal(menge) * 1000):011d}"),
            (49, t1), (89, t2), (129, "0" * 33 + f"47558164;{pos}"), (181, "H"), (183, einheit), (187, "L"),
        ]))
    zeilen.append(_satz([(0, "END")]))
    return b"\r\n".join(zeilen) + b"\r\n"

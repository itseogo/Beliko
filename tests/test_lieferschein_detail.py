"""Test: Lieferschein-Detailansicht und Verlinkung aus der Bestellung."""
import os, re, sys, tempfile
os.environ["EINKAUF_DATA"] = tempfile.mkdtemp(prefix="einkauf-test-")
HIER = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HIER, ".."))
sys.path.insert(0, HIER)

from einkauf import create_app
app = create_app(); c = app.test_client()
tok = lambda h: re.search(r'name="_csrf" value="([^"]+)"', h).group(1)
def G(url): return c.get(url, follow_redirects=True).get_data(as_text=True)
def P(url, data, page=None):
    t = tok(c.get(page or url).get_data(as_text=True))
    return c.post(url, data=dict(data, _csrf=t), follow_redirects=True).get_data(as_text=True)

P("/setup/", {"type": "sqlite"})
P("/setup/admin", {"username": "chris", "firma": "Elektro Test", "password": "geheim1234", "password2": "geheim1234"})
P("/einstellungen/lieferanten/neu", {"name": "Fega & Schmitt", "active": "1"})
P("/projekte/neu", {"nummer": "P-2026-0011", "name": "TEST-", "status": "aktiv"})

# Bestellung anlegen mit 2 Positionen
P("/bestellungen/neu", {"supplier_id": "1", "bestelldatum": "2026-10-24", "bestellnr": "B-2026-0002", "ab_nr": "47558164", "schon_bestellt": "1"})
P("/bestellungen/1/position", {"artikelnr": "432", "bezeichnung": "test", "menge": "1", "einheit": "Stück", "preis": "200,00", "project_id": "1"}, page="/bestellungen/1")
P("/bestellungen/1/position", {"artikelnr": "9104201", "bezeichnung": "PHOE Elektronikgehäuse", "menge": "1", "einheit": "STK", "preis": "23,10", "project_id": "1"}, page="/bestellungen/1")

# Wareneingang fuer Position 2 buchen (Lieferschein 4755816402)
h_in = P("/bestellungen/1/wareneingang", {
    "lieferschein_nr": "4755816402",
    "datum": "2026-10-30",
    "menge_1": "",
    "menge_2": "1"
}, page="/bestellungen/1")

# 1. Pruefen, dass Lieferschein 4755816402 in der Positionstabelle verlinkt ist
h_best = G("/bestellungen/1")
assert '/lieferscheine/1' in h_best
assert '4755816402' in h_best
assert 'Lfg. 02' in h_best

# 2. Pruefen, dass Lieferschein 4755816402 in /lieferscheine verlinkt ist
h_ls_liste = G("/lieferscheine")
assert '/lieferscheine/1' in h_ls_liste
assert '4755816402' in h_ls_liste

# 3. Lieferschein-Detailseite aufrufen
h_ls_detail = G("/lieferscheine/1")
assert "Lieferschein 4755816402" in h_ls_detail
assert "Teillieferung 02" in h_ls_detail
assert "30.10.2026" in h_ls_detail
assert "Fega" in h_ls_detail and "Schmitt" in h_ls_detail
assert "B-2026-0002" in h_ls_detail
assert "PHOE Elektronikgehäuse" in h_ls_detail
assert "1 STK" in h_ls_detail
assert "P-2026-0011" in h_ls_detail

# 4. Lieferschein loeschen
h_del = P("/lieferscheine/1/loeschen", {}, page="/lieferscheine/1")
assert "gelöscht" in h_del
# Wieder auf der Bestelldetailseite: Mengen wieder offen
h_after_del = G("/bestellungen/1")
assert "4755816402" not in h_after_del
assert "Offen" in h_after_del

print("LIEFERSCHEIN DETAIL TEST OK")

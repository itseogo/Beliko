"""Test: Spaltensortierung (Auf-/Absteigend) fuer Projekttabelle wie Windows Explorer."""
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
P("/setup/admin", {"username": "chris", "password": "geheim1234", "password2": "geheim1234"})

# Drei Testprojekte mit unterschiedlichen Nummern, Namen, Kunden, Budgets
P("/projekte/neu", {"nummer": "P-2026-0001", "name": "Zebra Elektro", "kunde": "Mueller", "status": "aktiv", "materialbudget": "500"})
P("/projekte/neu", {"nummer": "P-2026-0002", "name": "Alpha Klima", "kunde": "Anton", "status": "aktiv", "materialbudget": "1500"})
P("/projekte/neu", {"nummer": "P-2026-0010", "name": "Beta Solar", "kunde": "Berta", "status": "aktiv", "materialbudget": "100"})

def table_attr(html, attr):
    tbody = html.split('<table class="wahl">')[1].split('</table>')[0]
    return re.findall(rf'data-{attr}="([^"]*)"', tbody)

# 1. Standard-Aufruf: Nummer aufsteigend (P-2026-0001 vor P-2026-0002 vor P-2026-0010)
h = G("/projekte")
assert "sortierbar" in h
assert 'data-col="nr"' in h
assert 'data-col="name"' in h
assert 'data-col="kunde"' in h
assert 'data-col="status"' in h
assert 'data-col="offen"' in h
assert 'data-col="bestellt"' in h
assert 'data-col="budget"' in h
assert table_attr(h, "nr") == ["P-2026-0001", "P-2026-0002", "P-2026-0010"], "Standard-Sortierung nach Nr. aufsteigend fehlgeschlagen"
assert "▲" in h

# 2. Nummer absteigend (dir=desc)
h_nr_desc = G("/projekte?sort=nr&dir=desc")
assert table_attr(h_nr_desc, "nr") == ["P-2026-0010", "P-2026-0002", "P-2026-0001"], "Sortierung nach Nr. absteigend fehlgeschlagen"
assert "▼" in h_nr_desc

# 3. Name aufsteigend (Alpha vor Beta vor Zebra)
h_name_asc = G("/projekte?sort=name&dir=asc")
assert table_attr(h_name_asc, "name") == ["Alpha Klima", "Beta Solar", "Zebra Elektro"], "Sortierung nach Name A-Z fehlgeschlagen"

# 4. Name absteigend (Zebra vor Beta vor Alpha)
h_name_desc = G("/projekte?sort=name&dir=desc")
assert table_attr(h_name_desc, "name") == ["Zebra Elektro", "Beta Solar", "Alpha Klima"], "Sortierung nach Name Z-A fehlgeschlagen"

# 5. Kunde aufsteigend (Anton vor Berta vor Mueller)
h_kunde_asc = G("/projekte?sort=kunde&dir=asc")
assert table_attr(h_kunde_asc, "kunde") == ["Anton", "Berta", "Mueller"], "Sortierung nach Kunde A-Z fehlgeschlagen"

# 6. Kunde absteigend (Mueller vor Berta vor Anton)
h_kunde_desc = G("/projekte?sort=kunde&dir=desc")
assert table_attr(h_kunde_desc, "kunde") == ["Mueller", "Berta", "Anton"], "Sortierung nach Kunde Z-A fehlgeschlagen"

# 7. Materialbudget aufsteigend (100 vor 500 vor 1500)
h_bud_asc = G("/projekte?sort=budget&dir=asc")
assert table_attr(h_bud_asc, "nr") == ["P-2026-0010", "P-2026-0001", "P-2026-0002"], "Sortierung nach Budget aufsteigend fehlgeschlagen"

# 8. Materialbudget absteigend (1500 vor 500 vor 100)
h_bud_desc = G("/projekte?sort=budget&dir=desc")
assert table_attr(h_bud_desc, "nr") == ["P-2026-0002", "P-2026-0001", "P-2026-0010"], "Sortierung nach Budget absteigend fehlgeschlagen"

print("SPALTENSORTIERUNG PROJEKTE OK")

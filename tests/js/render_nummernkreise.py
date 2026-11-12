"""Rendert die Seite Nummernkreise als HTML-Datei, damit test_nummernkreise.js die Live-Vorschau prüfen kann."""
import os, re, sys, tempfile
os.environ["EINKAUF_DATA"] = tempfile.mkdtemp(prefix="einkauf-js-")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
from einkauf import create_app
app = create_app(); c = app.test_client()
tok = lambda h: re.search(r'name="_csrf" value="([^"]+)"', h).group(1)
def P(url, data, page=None):
    return c.post(url, data=dict(data, _csrf=tok(c.get(page or url).get_data(as_text=True))), follow_redirects=True)
P("/setup/", {"type": "sqlite"}); P("/setup/admin", {"username": "a", "password": "geheim1234", "password2": "geheim1234"})
open(sys.argv[1] if len(sys.argv) > 1 else "nk.html", "w", encoding="utf-8").write(c.get("/einstellungen/nummernkreise").get_data(as_text=True))
print("Seite gespeichert")

// Prüft das Neu-Menü in der Kopfzeile in einem simulierten Browser (jsdom).
// Aufruf: python tests/js/render_bestellmaske.py tests/js/maske.html && cd tests/js && npm install jsdom && node test_neu_menue.js maske.html
const { JSDOM, VirtualConsole } = require("jsdom");
const fs = require("fs");
const fehler = [];
const html = fs.readFileSync(process.argv[2] || "maske.html", "utf8").replace(/<link[^>]*>/g, "");
const dom = new JSDOM(html, { runScripts: "dangerously", pretendToBeVisual: true, virtualConsole: new VirtualConsole().on("jsdomError", e => fehler.push(String(e))) });
const d = dom.window.document, w = dom.window;
let ok = true; const pruef = (n, ist, soll) => { if (JSON.stringify(ist) !== JSON.stringify(soll)) { ok = false; console.log("FEHLER", n, ist, "erwartet", soll); } };
const m = d.getElementById("neu-menu");
pruef("Menü vorhanden", !!m, true);
pruef("Einträge", [...m.querySelectorAll("a")].map(a => a.textContent.trim()), ["Bestellung", "Lieferschein", "Aus IDS übernehmen", "Projekt anlegen", "Kontakt anlegen"]);
pruef("Ziele", [...m.querySelectorAll("a")].map(a => a.getAttribute("href")), ["/bestellungen/neu", "/lieferscheine/neu", "/ids", "/projekte/neu", "/kontakte/neu"]);
pruef("Zu Beginn zu", m.open, false);
m.open = true;
d.querySelector("main").dispatchEvent(new w.MouseEvent("click", { bubbles: true }));
pruef("Klick daneben schließt", m.open, false);
m.open = true;
m.querySelector("a").dispatchEvent(new w.MouseEvent("click", { bubbles: true, cancelable: true }));
pruef("Klick im Menü schließt nicht vor der Navigation", m.open, true);
d.dispatchEvent(new w.KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
pruef("Escape schließt", m.open, false);
pruef("Fokus zurück auf den Knopf", d.activeElement === m.querySelector("summary"), true);
pruef("keine Skriptfehler", fehler, []);
console.log(ok ? "NEU-MENUE OK" : "NEU-MENUE FEHLERHAFT");

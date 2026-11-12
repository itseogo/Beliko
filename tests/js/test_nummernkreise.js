// Prüft die Live-Vorschau der Nummernkreise in einem simulierten Browser (jsdom).
// Aufruf (im Projektordner): python tests/js/render_nummernkreise.py tests/js/nk.html
//   cd tests/js && npm install jsdom && node test_nummernkreise.js nk.html
const { JSDOM } = require("jsdom");
const fs = require("fs");
const datei = process.argv[2] || "nk.html";
const html = fs.readFileSync(datei, "utf8").replace(/<link[^>]*>/g, "");
const errors = [];
const dom = new JSDOM(html, { runScripts: "dangerously", pretendToBeVisual: true,
  virtualConsole: new (require("jsdom").VirtualConsole)().on("jsdomError", e => errors.push(String(e))) });
const d = dom.window.document;
const heute = new Date(d.getElementById("nk").dataset.heute + "T12:00:00");
const p2 = n => String(n).padStart(2, "0");
const jjmmtt = p2(heute.getFullYear() % 100) + p2(heute.getMonth() + 1) + p2(heute.getDate());
function tippen(k, wert) { const el = d.getElementById(k + "-muster"); el.value = wert; el.dispatchEvent(new dom.window.Event("input", { bubbles: true })); }
function lies(k) { return [d.getElementById(k + "-v1").textContent, d.getElementById(k + "-v2").textContent, d.getElementById(k + "-fehler").textContent, d.getElementById(k + "-muster").classList.contains("ungueltig")]; }
let ok = true; const pruef = (name, ist, soll) => { const gut = JSON.stringify(ist) === JSON.stringify(soll); if (!gut) { ok = false; console.log("FEHLER", name, ist, "erwartet", soll); } };

pruef("Start", lies("projekt").slice(0, 2), ["P-" + heute.getFullYear() + "-0001", "P-" + heute.getFullYear() + "-0002"]);
tippen("projekt", "YYMMDDXXXX");
pruef("Beispiel des Auftrags", lies("projekt"), [jjmmtt + "0001", jjmmtt + "0002", "", false]);
tippen("projekt", "2265XXXX");
pruef("2265XXXX", lies("projekt").slice(0, 2), ["22650001", "22650002"]);
d.querySelector('[name=projekt_naechste]').value = "2081"; d.querySelector('[name=projekt_naechste]').dispatchEvent(new dom.window.Event("input", { bubbles: true }));
pruef("Zähler 2081", lies("projekt").slice(0, 2), ["22652081", "22652082"]);
tippen("projekt", "P-YYYY");
const f = lies("projekt"); pruef("Fehler ohne X", [f[0], f[1], f[2].includes("genau eine Folge"), f[3]], ["–", "", true, true]);
tippen("projekt", "P-YYY-XXXX");
pruef("reserviert", [lies("projekt")[2].includes("reserviert"), lies("projekt")[3]], [true, true]);
tippen("projekt", "P!-XXXX");
pruef("Zeichen", [lies("projekt")[2].includes("Erlaubt sind nur"), lies("projekt")[3]], [true, true]);
// Beispiel-Knopf
d.querySelector('[data-k=bestellung] .bsp-knopf[data-muster="YYMMXXXX"]').click();
pruef("Knopf", [d.getElementById("bestellung-muster").value, lies("bestellung")[0]], ["YYMMXXXX", p2(heute.getFullYear() % 100) + p2(heute.getMonth() + 1) + "0001"]);
// Hilfe-Zeile mit heutigem Datum
pruef("Hilfe", [d.getElementById("h-yyyy").textContent, d.getElementById("h-dd").textContent], [String(heute.getFullYear()), p2(heute.getDate())]);
pruef("keine Skriptfehler", errors, []);
console.log(ok ? "LIVE-VORSCHAU OK" : "LIVE-VORSCHAU FEHLERHAFT");

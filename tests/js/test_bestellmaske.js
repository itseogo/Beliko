// Prüft die Zeilensteuerung der Bestellmaske in einem simulierten Browser (jsdom).
// Aufruf: python tests/js/render_bestellmaske.py tests/js/maske.html && cd tests/js && npm install jsdom && node test_bestellmaske.js maske.html
const { JSDOM, VirtualConsole } = require("jsdom");
const fs = require("fs");
const fehler = [];
const html = fs.readFileSync(process.argv[2] || "maske.html", "utf8").replace(/<link[^>]*>/g, "");
const dom = new JSDOM(html, { runScripts: "dangerously", pretendToBeVisual: true, virtualConsole: new VirtualConsole().on("jsdomError", e => fehler.push(String(e))) });
const d = dom.window.document;
let ok = true; const pruef = (n, ist, soll) => { if (JSON.stringify(ist) !== JSON.stringify(soll)) { ok = false; console.log("FEHLER", n, ist, "erwartet", soll); } };
const zeilen = () => d.querySelectorAll("#zeilen tr").length;
const taste = (el, key) => el.dispatchEvent(new dom.window.KeyboardEvent("keydown", { key, bubbles: true, cancelable: true }));

pruef("Startzeilen", zeilen(), 6);
d.getElementById("zeile-neu").click();
pruef("Zeile hinzufügen", zeilen(), 7);
pruef("Fokus in neuer Zeile", d.activeElement && d.activeElement.name, "row_artikelnr");
// Zeile mit Inhalt entfernen
d.querySelectorAll("#zeilen tr")[0].querySelector("[name=row_bezeichnung]").value = "Test";
d.querySelectorAll("#zeilen tr")[0].querySelector(".entf").click();
pruef("Zeile entfernen", zeilen(), 6);
// Alle bis auf eine entfernen; die letzte wird geleert statt gelöscht
while (zeilen() > 1) d.querySelector("#zeilen tr .entf").click();
const letzte = d.querySelector("#zeilen tr"); letzte.querySelector("[name=row_bezeichnung]").value = "Rest"; letzte.querySelector("[name=row_einheit]").value = "m";
letzte.querySelector(".entf").click();
pruef("Letzte Zeile bleibt, wird geleert", [zeilen(), d.querySelector("#zeilen [name=row_bezeichnung]").value, d.querySelector("#zeilen [name=row_einheit]").value], [1, "", "Stück"]);
// Enter springt in die gleiche Spalte der nächsten Zeile, in der letzten Zeile legt es eine neue an
d.getElementById("zeile-neu").click(); d.getElementById("zeile-neu").click();
const z = () => d.querySelectorAll("#zeilen tr");
const menge0 = z()[0].querySelector("[name=row_menge]"); menge0.focus();
const vorher = zeilen(); taste(menge0, "Enter");
pruef("Enter springt eine Zeile weiter", [zeilen(), d.activeElement === z()[1].querySelector("[name=row_menge]")], [vorher, true]);
const mengeL = z()[zeilen() - 1].querySelector("[name=row_menge]"); mengeL.focus(); taste(mengeL, "Enter");
pruef("Enter in letzter Zeile legt neue an", [zeilen(), d.activeElement === z()[zeilen() - 1].querySelector("[name=row_menge]")], [vorher + 1, true]);
pruef("Alle Felder tragen den Namen row_*", [...d.querySelectorAll("#zeilen input[name], #zeilen select[name]")].every(e => e.name.startsWith("row_")), true);
pruef("keine Skriptfehler", fehler, []);
console.log(ok ? "BESTELLMASKE OK" : "BESTELLMASKE FEHLERHAFT");

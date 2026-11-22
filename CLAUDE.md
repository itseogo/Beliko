# CLAUDE.md – Übergabe für die Weiterarbeit (BeLiKo – BestellLieferKontrolle)

Diese Datei gehört zum Projekt und wird bei **jeder Änderung** mit aktualisiert (Wunsch des Auftraggebers,
damit in einem neuen Chat nahtlos weitergearbeitet werden kann). In einem neuen Chat: `beliko.zip`
hochladen (enthält diese Datei) und sagen „lies die CLAUDE.md und mach weiter“.

**Stand: Version 1.3.1 · Datenbank-Schemaversion 15**

**Name:** Der Auftraggeber nennt das Tool **BeLiKo** (BestellLieferKontrolle). Sichtbar überall als BeLiKo; intern bleiben Paket `einkauf`, Ordner `einkauf-data` und der Dienstname `einkauf` (damit bestehende Installationen weiterlaufen). Auslieferung: `beliko.zip`.

## 1. Worum es geht
Webanwendung für einen Elektro-Handwerksbetrieb: Einkauf überwachen (was ist bestellt, was geliefert),
Material Projekten zuordnen, Rückstand je Projekt/Lieferant/Termin sehen. Sprache der Oberfläche und
Antworten an den Auftraggeber: **Deutsch**. Der Auftraggeber ist kein Entwickler: Schritte einfach erklären,
keine ungefragten Fachbegriffe, immer ein fertig getestetes ZIP liefern.

## 2. Rahmenbedingungen (vom Auftraggeber vorgegeben)
- Läuft auf einem **Raspberry Pi 4 (4 GB), 64-Bit**, Datenbank **MariaDB auf dem NAS**.
- Nur im lokalen Netz, 2–3 gleichzeitige Nutzer.
- **Kein Docker** (Port-Freigaben wären lästig). Installation per `./install.sh`, Autostart per `./install.sh --service`.
- Muss auf ein anderes System kopierbar sein: Programmordner + `einkauf-data/` kopieren, `./install.sh`, fertig.
- Der **erste Benutzer** im Einrichtungsassistenten ist immer Admin.
- Lexoffice (Angebote, Rechnungen, Buchhaltung) ist vorhanden, Anbindung gewünscht (noch nicht gebaut).

## 3. Technik
Python 3.10+, Flask, SQLAlchemy 2, PyMySQL, Waitress, `cryptography` (Fernet). Seiten serverseitig mit
Jinja2, **kein Frontend-Build, fast kein JavaScript**. Siehe `requirements.txt`.

```
run.py                    Start (python run.py) und "install-service" (systemd, nur Linux)
install.sh / install.bat  legt .venv an, installiert Pakete (Linux/Mac bzw. Windows); start.sh / start.bat starten
einkauf/__init__.py       App-Fabrik, Filter (qty, money, datum), Setup-Sperre, Fehlerseiten, VERSION
einkauf/config.py         einkauf-data/config.json (DB-Zugang, secret_key, Port, Firma)
einkauf/db.py             init_db, migrate (Schema-Updates!), SCHEMA_VERSION, daten_kopieren
einkauf/datenbank_kopieren.py  Übertragung aller Daten SQLite ↔ MariaDB (CLI: python -m einkauf.datenbank_kopieren)
einkauf/models.py         Tabellen und Geschäftslogik (Status, Rest, Fälligkeit)
einkauf/security.py       Verschlüsselung, CSRF, Rollen-Dekoratoren, Login-Sperre
einkauf/ugl.py            UGL-Dateileser und Abgleich mit Bestellpositionen
einkauf/lieferantendateien.py  Abruf der Lieferantendateien per FTP/FTPS/Ordner (nur lesend), Verbindungstest
einkauf/planer.py         Hintergrund-Thread für den automatischen Abruf (je Lieferant), `planer.tick(app)` testbar
einkauf/lexoffice.py      Lexoffice-API: Verbindung prüfen, Kontakte einseitig abgleichen (nur lesend)
einkauf/einstellungen.py  Schlüssel/Wert-Einstellungen in der DB (Tabelle settings)
einkauf/ids.py            IDS-Connect: Warenkorb-XML lesen, Rohbytes der Rückgabe zerlegen, Einzelpreis berechnen
einkauf/formate.py        Anzeige-/Eingabeformate (qty, money, preis mit bis zu 4 Nachkommastellen, datum)
einkauf/nummern.py        Nummernkreise mit Muster: pruefen(), formatieren(), vorschlag(), verbrauchen()
einkauf/views.py          alle Routen (Blueprints main, setup)
einkauf/templates/        Jinja-Seiten; _m.html = Formular-Bausteine (immer "with context" importieren)
einkauf/static/style.css  Gestaltung
tests/                    test_basis.py, test_ugl_projekte.py, test_kontakte_nummern.py, test_nummernmuster.py, test_ids_maske_dunkel.py, test_ids_diagnose.py (mit kleinem Schein-Shop im Test), test_neu_lieferschein.py, test_lexoffice.py (mit Schein-Lexoffice), test_ftp.py (Schein-FTP/FTPS-Server, braucht tests/requirements-test.txt), make_ugl.py (nachgebaute UGL-Datei),
                          js/ (Oberflächentests im simulierten Browser: Live-Vorschau der Nummernkreise, Zeilensteuerung der Bestellmaske;
                          Aufruf siehe Kopfzeilen von test_nummernkreise.js / test_bestellmaske.js, braucht node + jsdom)
```

## 4. Datenmodell (Tabellen)
`users` (inkl. `theme` = hell/dunkel/auto) · `suppliers` (inkl. IDS-Felder ids_url, ids_kndnr, ids_benutzer, ids_passwort_enc, ids_version, ids_preis_modus, ids_aufruf; UGL-Felder: verfahren, server, port, pfad_eingang/-ausgang/-zugferd, format,
benutzer, passwort verschlüsselt) · `projects` (nummer, name, kunde, contact_id, status, materialbudget) ·
`contacts` + `contact_persons` (Kontakte, Feldsatz wie Lexoffice, siehe Abschnitt 5b) · `number_ranges` (Nummernkreise) ·
`orders` (status, bestelldatum, bestellnr, ab_nr, wunschtermin, bestellt_am, bezahlt_am) ·
`order_items` (artikelnr, bezeichnung, menge, einheit, preis DECIMAL(12,4) wegen Einzelpreisen wie 0,0474 €, erw_lieferdatum, storniert, kommission, hinweis,
project_id) · `deliveries` · `delivery_items` · `meta` (schema_version).
Die gelieferte Menge wird **immer aus `delivery_items` berechnet**, nie doppelt gespeichert.

**Neue Spalten/Tabellen:** in `models.py` ergänzen, `SCHEMA_VERSION` in `db.py` erhöhen und in `migrate()` einen
Block `if aktuell < N:` mit `_spalten_ergaenzen(...)` (für bestehende Datenbanken) anlegen. `create_all` legt
nur fehlende *Tabellen* an, keine Spalten.

## 5. Fachlogik (wichtig)
**Bestellstatus** (Baum links, je Status Jahr → Monat):
`neu` → `bestellt` → `teilgeliefert` → `komplett` → `abgeschlossen` (= bezahlt).
- Neu → Bestellt: Knopf (oder Haken „Schon bestellt“ beim Erfassen).
- Teillieferung/Komplett: **automatisch** (`Order.status_aktualisieren()`), nach Wareneingang, Positionsänderung, Storno.
- Abgeschlossen: Knopf, nur aus Komplett. Wieder öffnen möglich.
- **Rückstand und Projektsummen zählen erst ab Status „Bestellt“** (Neu = Entwurf).
- Ordnernamen aus der Branchensoftware des Auftraggebers: Gedruckt = Bestellt, Teilweise = Teillieferung,
  Komplett = alles geliefert, Abgeschlossen = bezahlt.

**Rollen:** admin (alles inkl. Einstellungen/Lieferanten/Benutzer), einkaeufer (erfassen, buchen), leser (nur ansehen).
Der letzte aktive Admin ist geschützt.

**Positionen:** Eine Position hat ein Projekt (oder keins) und ein Freitextfeld *Kommission*. Aufteilen auf
mehrere Projekte = zweite Position mit gleicher Artikelnummer (`position_aufteilen`). Der UGL-Import verteilt
gelieferte Mengen automatisch auf mehrere Positionen mit gleicher Artikelnummer.

**Projektansicht:** `/projekte?p=<id>&tab=vorgang|material|uebersicht` – Liste oben, Reiter unten, Wechsel per
Seitenaufruf. Der Reiter **Vorgang** (Standard) fasst die Vorgänge in 3 Blöcken zusammen: **Angebot** (Lexoffice-Angebote/Aufträge),
**Bestellung** (Bestellungen an Lieferanten) und **Rechnung** (Lexoffice-Ausgangs- und Eingangsrechnungen).
Alte Links mit `tab=bestellungen` und `tab=lexoffice` werden automatisch auf `tab=vorgang` abgebildet.
Bestellung öffnet mit `?von=<projekt>` und „Zurück zum Projekt“.

## 5b. Kontakte und Nummernkreise (ab 0.6)
**Kontakte** (Menü/Baum „Kontakte“, Alle/Kunden/Lieferanten): Feldsatz an die Kontakte von Lexoffice/Lexware Office angelehnt
(an der Dokumentation geprüft): Rollen Kunde/Lieferant mit je eigener Nummer; Typ Firma (Firmenname, Steuernummer, USt-IdNr.,
steuerfreie Rechnungen, mehrere Ansprechpartner mit Anrede/Name/E-Mail/Telefon/primär) oder Privatperson (Anrede, Vor-/Nachname);
Rechnungs- und Lieferadresse (Zusatz, Straße, PLZ, Ort, Land); E-Mail (geschäftlich/Büro/privat/sonstige) und Telefon
(geschäftlich/Büro/mobil/privat/Fax/sonstige); XRechnung (Leitweg-ID, Lieferantennr. beim Kunden); Notiz; archiviert.
Lexoffice kennt je Liste mehrere Einträge, die App speichert pro Liste **den ersten**; Ansprechpartner sind mehrfach.
`quelle` = `manuell` oder `lexoffice`; `lexoffice_id`/`lexoffice_version`/`letzter_sync` sind für den Sync vorbereitet.
**Kontakte mit `quelle=lexoffice` sind in der App schreibgeschützt** (Lexoffice ist führend, Sync einseitig), selbst angelegte bleiben bearbeitbar.
**Kunde im Projekt:** Eingabefeld mit Auswahlliste (HTML-`datalist`, kein JavaScript). Stimmt der eingetippte Name mit einem Kontakt überein
(ohne Groß-/Kleinschreibung), wird `projects.contact_id` gesetzt und der Name aus dem Kontakt übernommen; sonst bleibt es freier Text
(`projects.kunde`). Wird ein Kontakt umbenannt, ziehen die verknüpften Projekte den Namen nach.
**Nummernkreise** (Einstellungen → Nummernkreise, nur Admin) für `projekt` und `bestellung`, ab 0.7 per **Muster**:
`YYYY`/`YY` Jahr, `MM` Monat, `DD` Tag, `X…X` laufende Nummer (Anzahl X = Stellen, genau eine Folge), sonst Buchstaben/Ziffern/`- _ . /`;
Y, M, D, X sind reserviert. Beispiele: `P-YYYY-XXXX` → P-2026-0001, `YYMMDDXXXX` → 2610310001, `2265XXXX` → 22652081.
Zähler zurücksetzen: automatisch nach Muster (enthält es `DD` → täglich, `MM` → monatlich, `YY` → jährlich, sonst nie) oder fest gewählt;
danach beginnt er beim „Startwert“. Die Einstellungsseite zeigt die **Live-Vorschau** beim Tippen (JavaScript, gleiche Regeln wie `nummern.pruefen`/`formatieren`
– beide Seiten müssen synchron bleiben). Neue Projekte/Bestellungen bekommen die Nummer **vorgeschlagen** (Feld vorbelegt, überschreibbar).
Beim Speichern zieht der Zähler nach, wenn die Nummer zum heutigen Muster passt und nicht kleiner ist; eigene Nummern lassen ihn stehen.
Belegte Nummern werden beim Vorschlag übersprungen, doppelte Projekt- und Bestellnummern abgewiesen. `number_ranges.praefix/trenner/mit_jahr/stellen/jahr`
stammen aus Schema 5, werden nicht mehr gelesen und bleiben nur wegen bestehender NOT-NULL-Spalten; die Migration schreibt alte Einstellungen in ein Muster um.

## 5c. Darstellung (Dark Mode)
Pro Benutzer unter „Mein Konto → Darstellung“: Hell, Dunkel oder automatisch (folgt dem Gerät). Gespeichert in `users.theme`, ausgeliefert als
`<html data-theme="light|dark|auto">`; abgemeldete Seiten (Login) folgen dem Gerät. Alle Farben sind **CSS-Variablen** in `static/style.css`
(Hell-Palette in `:root`, Dunkel in `:root[data-theme="dark"]`, identisch in `@media (prefers-color-scheme: dark) :root[data-theme="auto"]`).
**Neue Farben nie fest eintragen, sondern als Variable in beiden Paletten ergänzen.** Kontraste beider Paletten wurden mit WCAG-Rechnung geprüft (alle Textpaare ≥ 4,5:1);
im echten Browser noch nicht angesehen. Beim Drucken wird auf Schwarz auf Weiß zurückgestellt.

## 5d. Bestellung erfassen in einer Maske
`/bestellungen/neu` ist **eine Seite**: Kopf (Lieferant, Datum, Bestellnummer aus Nummernkreis, AB-Nr., Wunschtermin, „Projekt für alle Positionen“,
Notiz, schon bestellt) plus Positionsraster (Artikelnr., Bezeichnung, Menge, Einheit, Einzelpreis, Termin, Projekt pro Zeile „wie oben“/„Ohne Projekt“/Projekt,
Kommission). Leere Zeilen werden übersprungen, Fehler zeigen „Zeile n: …“ und behalten alle Eingaben. Zeilenfelder heißen `row_*` (Listen).
JavaScript: „+ Zeile“, Zeile entfernen (die letzte wird nur geleert), Enter springt in die gleiche Spalte der nächsten Zeile bzw. legt eine neue an. Positionen
lassen sich weiterhin später in der Bestellung ergänzen/ändern. Dieselbe Maske wird für die IDS-Übernahme vorbelegt.

## 5e. IDS-Connect (Warenkorb aus dem Shop des Lieferanten übernehmen)
Grundlage: **IDS-Connect 2.5 der ITEK** (Spezifikation öffentlich). Umgesetzt ist die Richtung **Shop → App** (Aktion `WKE`, „Warenkorb empfangen“); das Senden einer
Bestellung an den Shop (`WKS`) ist **nicht** gebaut.
Ablauf: Menü „Bestellwesen → + Aus Shop übernehmen (IDS)“ (`/ids`) → „Shop öffnen“ (`POST /ids/start/<lieferant>`) erzeugt einen einmaligen Token (Datei in
`einkauf-data/ids/`, 8 Stunden gültig, gebunden an den Benutzer) und liefert eine Zwischenseite, die ein **multipart/form-data-Formular** per Browser an `ids_url` des Lieferanten
schickt: `kndnr`, `name_kunde`, `pw_kunde` (sofern eingetragen), `action=WKE`, `hookurl`, `version`. Die `hookurl` ist `<Adresse, mit der der Browser die App aufruft>/ids/rueckgabe/<token>`
(max. 256 Zeichen). Der Anwender wählt im Shop „Warenkorb übertragen“, der Shop schickt das XML **über den Browser** an die hookurl (deshalb funktioniert das im LAN).
`/ids/rueckgabe/<token>` (ohne Login, **von der CSRF-Prüfung ausgenommen**, Schutz = einmaliger Token) sucht das XML in allen Formularteilen/Dateien/Rohdaten (Feldname im Standard nicht festgelegt, `warenkorb`
wird bevorzugt), liest es mit `ids.lesen` und leitet per 303 auf `/bestellungen/neu?ids=<token>` (die Maske ist vorbelegt). Erst „Speichern“ legt die Bestellung an; danach werden Token-Dateien gelöscht.
Übernommen wird: Datum, AB-Nr. (`OrderConfNo`), Lieferdatum (`DeliveryDate`, sonst **Freitag der Lieferwoche**), Kommission/Zusatztext/Versandart als Notiz,
„schon bestellt“ nur bei Rückgabe **mit Bestellung**; je Position Artikelnr., Kurztext, Menge, Einheit (Codeliste PCE→Stück, MTR→m …), Einzelpreis, Shop-Hinweis/-Fehlertext (als `hinweis`).
Alternativ-/Bedarfspositionen (`ItemChara` alternate/provis) werden **nicht** übernommen, aber angezeigt. Warnung bei gleicher AB-Nr. beim selben Lieferanten.
**Einzelpreis:** Laut Spezifikation gilt `NetPrice` für die ganze Anfragemenge (Beispiel 50 m = 522 €) → Einzelpreis = NetPrice / Qty. Pro Lieferant einstellbar „gilt für eine Einheit“
(`ids_preis_modus=einzel`, dann NetPrice / PriceBasis). **Beim ersten echten Shop prüfen.**
Sicherheit: XML mit DOCTYPE/ENTITY wird abgelehnt, max. 5 MB; Rückgabe nur einmal; fremde Benutzer sehen den Warenkorb nicht. Das Shop-Passwort steht beim Öffnen **im Quelltext der Zwischenseite**
(inhärent bei IDS) und wird im LAN unverschlüsselt (http) vom Pi zum Browser übertragen; HTTPS auf dem Pi würde das lösen. Läuft die App per http und der Shop per https,
warnt der Browser eventuell vor dem Senden an eine „unsichere“ Adresse.
**GELÖST (5.11.2026, Rückmeldung des Nutzers):** Ursache war die **falsche Adresse**: Statt der normalen Shop-Adresse muss die **IDS-Einstiegsadresse** eingetragen werden. Mit `https://shop.fega.de/abtest/scripts/clsAIShop.php` erscheint im Fega-Shop der Button „IDS-Daten übertragen“, und die Übertragung nach BeLiKo klappt; ebenso bei **zwei weiteren Lieferanten** (welche, nicht genannt) nach demselben Muster.
Damit sind auch die Hypothesen „https-Hook-URL nötig“ und „eigener IDS-Benutzer nötig“ **nicht bestätigt** (http-Hook im Heimnetz wurde offenbar angenommen; ob ein anderer Benutzer verwendet wurde, ist unbekannt). Ablesen der Adresse: Browser F12 → Netzwerk → „Keep log“ → erste Anfrage (`clsAIShop.php`). Die folgenden Absätze sind die Fehlersuche davor und bleiben als Hintergrund stehen.
**Offen/zu prüfen mit echten Daten:** Stimmen **Einzelpreise** (Einstellung „Nettopreis gilt für ganze Menge / eine Einheit“ je Lieferant), Einheiten, Mengen, Liefertermin nach der Übernahme? Rückmeldung steht aus.
**Gemeldetes Problem (31.10.2026):** Beim Öffnen von Fegas Shop über die App fehlte im Shop der Button „IDS-Daten übertragen“ (der Aufruf aus der App kam im Shop an).
Erkenntnisse aus den Shop-Dokumentationen (Websale, Hoffmann; Fegas eigene IDS-Unterlagen liegen nicht vor): (1) Die Rückgabe-Funktion wird vom Shop **nur angeboten, wenn eine Hook-URL
übergeben und akzeptiert wurde**. (2) Bei Websale-Shops steht der Button **auf der letzten Seite (Bestellübersicht) neben „Bestellen“**, nicht im Warenkorb. (3) Eine **bestehende Shop-Anmeldung**
wird beim IDS-Aufruf nicht zurückgesetzt (Hoffmann: abmelden oder privates Fenster). (4) Websale zeigt den Aufruf als **GET mit Parametern in der Adresszeile** und verlangt **https** für die automatische Anmeldung;
(5) Shops unterstützen nur bestimmte Versionen (Hoffmann: 2.0 und 2.5), erfragbar mit Aktion `SV`, die nötigen Anmeldedaten mit Aktion `LI`.
Gegenmaßnahmen in 0.9.0: **Verbindungstest** je Lieferant (`/einstellungen/lieferanten/<id>/ids-test`, fragt SV und LI vom Pi aus ab, deutet die Antwort, warnt bei nicht unterstützter Version/fehlenden Zugangsdaten/HTML-Antwort),
**Selbsttest** (`/ids/selbsttest/<id>`, spielt einen Testwarenkorb über den Browserweg in die Rückgabe), Einstellung **Aufruf per POST oder GET**, **Version als Auswahl inkl. „keine Version senden“**,
Checkliste auf `/ids` und im Test. **Neuer Befund (Nutzer, 3.11.2026):** Mit seiner Branchensoftware „das Programm“ (Hersteller-App, ruft Fegas Shop ebenfalls per IDS auf) **erscheint der IDS-Button im Shop**, beim Aufruf aus BeLiKo nicht – der Shop
akzeptiert den Zugang also grundsätzlich, die Unterschiede liegen im Aufruf. **Zwischenstand (3.11.2026):** Der Nutzer nannte die Adresse der Shopseite nach dem Aufruf aus „das Programm“: `https://shop.fega.de/abtest/scripts/shop.php?_t=<Zeitstempel>&cmd=Startseite`. Das ist die **Landeseite nach der Weiterleitung**; die IDS-Parameter
sind darin nicht mehr sichtbar. Aufschlussreich nur: Host `shop.fega.de`, Skript `/abtest/scripts/shop.php` (Pfad enthält `abtest`, ggf. eine Testvariante des Shops). Es fehlt der **erste Aufruf** (IDS-Adresse, Parameter, Hook-URL).
Wege dorthin: (a) IDS-Einstellungen in „das Programm“ beim Lieferanten Fega abfragen (IDS-Adresse, Version, Kundennr., Benutzer; ohne Passwort) und mit der IDS-Adresse in BeLiKo vergleichen, (b) Browser F12 → Netzwerk → „Protokoll beibehalten“, den Shop aus „das Programm“ starten, erste Anfrage ansehen
(geht nicht, wenn „das Programm“ einen eingebauten Browser nutzt), (c) bei Fega die IDS-Beschreibung anfordern (Entwurf einer Anfrage wurde dem Nutzer angeboten).
**Befund aus dem Screenshot (4.11.2026):** In „das Programm“ ist beim Lieferanten Fega unter dem Reiter „IDS Connect“ ein **eigener IDS-Benutzer** hinterlegt (Benutzername mit Endung `_ids`, eigenes Passwort, Kundennummer wie bei BeLiKo,
Feld „Angebotspreisermittlung: Berechnen“, Knopf „IDS Connect Konfiguration ändern“ – dahinter vermutlich IDS-Adresse/Version). **Leitende Hypothese:** BeLiKo wurde mit dem normalen Shop-Login betrieben; bei Fega bekommt nur der IDS-Benutzer die Übertragungsfunktion.
Hinweise dazu stehen jetzt im Lieferantenformular und in den Checklisten. **Ergebnis steht aus** (Nutzer soll in BeLiKo den IDS-Benutzer eintragen und die IDS-Adresse aus der Konfiguration von „das Programm“ vergleichen).
**Weiterer Befund (4.11.2026):** Hinter „IDS Connect Konfiguration ändern“ in „das Programm“ steht **keine IDS-Adresse** – man gibt nur Kundennummer, Benutzer und Passwort ein. Grund laut Dokumentationen anderer Handwerkerprogramme: Die **Aufrufadresse des Großhändlers kommt automatisch aus dem
Verzeichnisdienst der ITEK (Open Connect / IDS Connect)**; die Hook-URL setzt die Software selbst. Fegas IDS-Adresse ist öffentlich nicht auffindbar (auch ein Open-Source-Client für Fega nennt sie „unbekannt“). Für BeLiKo muss die Adresse deshalb **von Hand** eingetragen werden;
ist dort die normale Shop-Adresse eingetragen, öffnet sich der Shop ohne IDS-Funktion. Quellen für die Adresse: (a) Browser F12 → Netzwerk → „Protokoll beibehalten“, Shop aus „das Programm“ starten, erste Anfrage an `shop.fega.de` (nur wenn „das Programm“ den Standardbrowser nutzt),
(b) Anfrage an Fega (Entwurf liegt dem Nutzer vor). Der **Verbindungstest** in BeLiKo zeigt, ob eine eingetragene Adresse als IDS-Zugang antwortet.
**Fund (4.11.2026), Löffelhardt:** Viele Großhandels-Shops zeigen die IDS-Adresse im **Kundenbereich unter „IDS Einstellungen“**. Beispiel Löffelhardt (Schorndorf): Profil „Löffelhardt Standard IDS“ (alternativ individuelles Profil für die eigene Software wählbar),
Beispiel-IDS-URL `https://online.loeffelhardt.de/punchout/ids`; der Shop weist darauf hin, dass die Parameter in vielen Systemen schon hinterlegt sind (Standardprofil meist ausreichend), Support über die im Shop genannte Adresse. **Für Fega im Shop-Kundenbereich nach „IDS“/„Schnittstellen“ suchen.**
Löffelhardt eignet sich als **erster echter Test** von BeLiKo (Adresse bekannt; Version/Anmeldedaten per Verbindungstest klären).
**Netzwerkprotokoll aus „das Programm“ (Chrome F12, 5.11.2026):** „Das Programm“ läuft im Browser (app.das-programm.io). Beim Klick auf den Warenkorb-Knopf neben Fega ruft es zuerst seinen eigenen Server auf (`create-ids-connect-session`, fetch, 200),
danach navigiert der Browser zu `https://shop.fega.de/abtest/scripts/clsAIShop.php` (302) → `shop.php?_t=…&cmd=Startseite` (302/200). Die Adresszeile zeigt später `…/abtest/scripts/shop.php?_t=…&bold=&cmd=BasketView/…`. **Der Einstieg ist also `clsAIShop.php`** (Pfad mit `abtest`);
Parameter/Hook-URL stehen vermutlich in der Antwort von `create-ids-connect-session` bzw. in den Formulardaten der Anfrage `clsAIShop.php` (ohne Query im Namen → eher POST). **Im Fega-Shop erscheint die Funktion auf der Warenkorb-Seite in der unteren Leiste: „Warenkorb senden | IDS-Daten übertragen | Zur Bestellung“** (nicht erst auf der Bestellübersicht).
Der Aufruf `create-ids-connect-session` ist ein **POST an `https://app.das-programm.io/api/quotation/create-ids-connect-session`** (Cloud-Dienst des Herstellers, Status 200): Die IDS-Sitzung wird also auf dem **Server des Herstellers** angelegt; die Hook-URL gehört sehr wahrscheinlich zu dessen öffentlicher https-Adresse
(Hypothese: Fega verlangt/bevorzugt eine https-Hook-URL; BeLiKo liefert im Heimnetz http mit interner Adresse). Antwort und Payload dieses Aufrufs sowie die Anfrage `clsAIShop.php` wurden noch nicht mitgeteilt.
Offen: genaue Anfrage (Request URL, Methode, Formularfelder, Hook-URL) – der Nutzer soll die Zeilen `clsAIShop.php` (Headers/Payload) und `create-ids-connect-session` (Payload/Response) auswerten, Passwort/Tokens geschwärzt.
**Nächster Schritt:** vom Nutzer erfragen, wie „das Programm“ den Shop aufruft (Adresszeile der geöffneten Shop-Seite bzw. Browser-Entwicklerwerkzeuge F12 → Netzwerk → Formulardaten, Passwort schwärzen):
Parameternamen und -werte, **Hook-URL-Form (https? Host? Pfad?)**, Version, GET oder POST, Zusatzparameter wie `target`. Danach BeLiKo-Aufruf angleichen (z. B. https-Hook-URL, andere Parameter).
**Ergebnis des Nutzers (Verbindungstest/Selbsttest) steht aus.** Mögliche nächste Schritte je nach Befund: Hook-URL per **https** anbieten (z. B. HTTPS auf dem Pi, selbstsigniertes Zertifikat im Browser bestätigen),
Fegas IDS-Dokumentation anfordern (IDS-Adresse, unterstützte Versionen, Rückgabe-Bedingungen), Parameternamen/Groß-Kleinschreibung gegen deren Beschreibung abgleichen.
**Noch nicht gegen einen echten Shop getestet** (nur mit nachgebautem Warenkorb nach Spezifikation): offen sind die IDS-Adresse und Zugangsdaten von Fega & Schmitt, der tatsächliche
Feldname der Rückgabe, die Preissemantik und das Verhalten von Cookies bei der Weiterleitung (SameSite=Lax; funktioniert nur, weil die Weiterleitung ein GET ist).

## 5f. Neu-Menü, Lieferscheine (ab 1.0)
Kopfzeile: **BeLiKo**, Firmenname klein daneben, Knopf **Neu** (`<details id="neu-menu">`, schließt bei Klick daneben/Escape): Bestellung, Lieferschein, Aus IDS übernehmen, Projekt anlegen, Kontakt anlegen.
Nur für Admin/Einkäufer sichtbar. **Einzelne Anlegen-Knöpfe in Listen/Baum wurden bewusst entfernt** (Wunsch des Auftraggebers); neue Anlege-Funktionen gehören ins Neu-Menü. In den Einstellungen bleiben
„Lieferant anlegen“/„Benutzer anlegen“. **Lieferschein** (`/lieferscheine/neu`, Liste `/lieferscheine`): Lieferant wählen → offene Positionen aller Bestellungen mit Status bestellt/teilgeliefert → Mengen eintragen oder „alles“;
je betroffener Bestellung eine `Delivery` mit derselben Lieferschein-Nr. (pro Lieferant eindeutig, sonst Fehler); Bestellstatus wird abgeleitet. UGL-Dateien weiterhin je Bestellung (zentraler Datei-Import wäre ein späterer Ausbau).

## 5g. Lexoffice (Einstellungen → Lexoffice, ab 1.0, Phase 2 ab 1.2)
Einstellungen in der Tabelle `settings` (`lex_aktiv`, `lex_url` Standard `https://api.lexware.io`, `lex_key_enc` verschlüsselt, `lex_sync_kunden/lieferanten/archiviert/angebote/auftraege/rechnungen`, `lex_letzter_sync` JSON).
Abgleich **einseitig Lexoffice → BeLiKo, nur lesend**, manuell (Einstellungsseite und Kontakte-Seite), Intervall „automatisch“ nicht umgesetzt.
API laut Dokumentation: `Authorization: Bearer <Schlüssel>`, `GET /v1/profile`, `GET /v1/contacts?page=&size=250` (Seiten bis `totalPages`), `GET /v1/voucherlist` (`quotation`, `orderconfirmation`, `invoice`) sowie Detailabruf `/v1/quotations/{id}`, `/v1/order-confirmations/{id}`, `/v1/invoices/{id}` (nur bei neuem/geändertem `updatedDate`). 2 Anfragen/Sekunde (Pause 0,6 s, bei 429 bis zu dreimal Wiederholung).
Kontakte mit `quelle=lexoffice` sind schreibgeschützt; fehlende/ausgeschlossene werden archiviert; Namensänderungen laufen in verknüpfte Projekte durch. Lieferanten (`suppliers.contact_id`) können optional mit einem Lieferanten-Kontakt verknüpft werden.
**Belege & Kostenarten (ab 1.2):** `lex_documents` + `lex_document_items` + `lex_article_rules`. Positionen starten (außer Textzeilen) ohne Kostenart (`unklar`), werden also **nicht** anhand des Lexoffice-Typs erraten. Unter `/lexoffice/belege/<id>` ordnet der Nutzer pro Position die Kostenart zu (`material` = 100 %, `pauschale` = gemischt mit Materialanteil %, `fremdleistung` = 0 %, `arbeit` = 0 %) und kann sie pro Lexoffice-Artikel merken (`lex_article_rules`, wirkt auf künftige Syncs und offene Positionen).
**Materialbudget & Projekt-Reiter:** In der Projektansicht gibt es den Reiter `Angebote / Rechnungen` (`tab=lexoffice`) mit Zuordnung und Summenvergleich (Warensumme vs. Budget vs. Bestellt vs. Rechnungen). Im Projektformular wählbar: `budget_modus` (`manuell` | `warensumme` | `faktor`) und `budget_faktor`. Unklare Angebotspositionen werden als Warnung angezeigt.
**Noch nicht gegen das echte Lexoffice getestet** (nur Schein-Server nach der Dokumentation).

## 5h. FTP-Abruf der Lieferantendateien (ab 1.1)
Je Lieferant (`suppliers.ugl_*`): `ugl_verfahren` (`ftp`/`ftps`/`datei`; `sftp` und `url` **nicht umgesetzt**), `ugl_server`, `ugl_port`, `ugl_pfad_ausgang`, `ugl_benutzer`/`ugl_passwort_enc`, `ugl_auto_min` (15/30/60/240, leer = nur manuell),
`ugl_tls_pruefen`, `ugl_letzter_abruf`, `ugl_abruf_status`. **Nur lesen: nichts auf dem Lieferantenserver löschen oder verändern** (bewusste Vorgabe). Dateien werden unter `einkauf-data/lieferantendateien/<lieferant>/` abgelegt, Metadaten in `supplier_files`
(Status `neu`/`verarbeitet`/`ignoriert`/`fehler`, Belegnr., Belegart, Kennung, Datum, Positionen, `bestell_id`, `sha256`; Dubletten = gleicher Name + gleicher Hash werden übersprungen). Sicherheitsgrenzen: Dateiname `^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$`, max. 5 MB, max. 200 Dateien je Lauf.
Oberfläche: Baum → Bestellwesen → Lieferantendateien (Zähler der neuen), `/dateien`, Detail `/dateien/<id>` mit **Bestellvorschlag** (Treffer = offene Positionen mit gleicher Artikelnummer), „Mit dieser Bestellung prüfen“ nutzt die bestehende UGL-Vorschau (`_ugl_vorschau`, Feld `datei_id`),
`ugl_uebernehmen` setzt die Datei auf `verarbeitet`. Lieferantenformular: „Verbindung testen“ (`ftp_test`, nur Admin) und „Jetzt abrufen“. **Mit dem echten Fega-Server noch nicht getestet** (Pfade `/QDLS/OUT/50/108690/`, vermutlich IBM-System: NLST/SIZE/Binärmodus-Verhalten
könnte abweichen; Verbindungstest nutzen, Servermeldungen im Abrufstatus lesen). Planer: Thread in `run.py` (`planer.starten`), Pause 60 s, Zeitplan je Lieferant; wird in Tests mit `EINKAUF_KEIN_PLANER=1` abgeschaltet.

## 6. UGL-Import (Fega & Schmitt, Version 04.00) – abgeleitet, nicht offiziell
Der Aufbau wurde aus **einer** Beispieldatei (`B0261027.001`) abgeleitet. **Es gibt keine offizielle
Satzbeschreibung**; diese sollte beim Lieferanten angefragt werden. Dateien: 200 Zeichen pro Zeile, CRLF, Windows-1252.
Satzarten `RGD` (Dateikopf), `KOP` (Belegkopf), `POA` (Position), `END`. Positionen in `ugl.py` (0-basiert):

| Satz | Feld | Spalten |
|---|---|---|
| RGD | Nummer / Kennung (`LS`) / Datum / Währung | 3–12 / 13–14 / 15–22 / 23–25 |
| KOP | Kundennr / Belegart (`AB`) / Belegnr / Währung / Version / Datum | 3–8 / 23–24 / 90–99 / 113–115 / 116–120 / 161–168 |
| POA | Pos / Artikelnr / Menge (3 Nachkommastellen) / Text1 / Text2 / Einheit | 3–12 / 23–37 / 38–48 / 49–88 / 89–128 / 183–186 |

Ein Verweis wie `47558164;3` steht im Bereich 129–180. Die Datei enthält **keine Preise und keine Liefertermine**.
**Zweite Beispieldatei (`B0261030.002`, 30.10.2026):** enthält nur Position 9 (Artikel 9104201, 1 STK, Verweis `47558164;9`),
also genau die in „Rückstand genommene“ Position der ersten Datei. Belegnr `4755816402` statt `…401` (fortlaufend je
Teillieferung, vermutlich). Das Datum im Dateikopf (RGD) wechselt (27.10. → 30.10.), das Datum im Belegkopf (KOP, 25.10.)
bleibt gleich: **RGD-Datum = Datei-/Lieferdatum, KOP-Datum = Datum des Auftrags/Belegs.** Spricht stark für Lieferschein-/Lieferavis-Dateien
(Kennung `LS`), endgültig bestätigt ist es nicht. Mit dem Import-Ablauf getestet: erste Datei buchen → Teillieferung, zweite Datei → Komplett,
Hinweis verschwindet, Rückstand 0 (nachgebaute Daten).
Offen/unsicher: ob `AB` wirklich Auftragsbestätigung bedeutet (Kennung `LS` deutet auf Lieferschein), und das
Zusatzzeichen `1` vor „PROT Kupferband“ (kommt auch im Shop des Lieferanten so vor). Deshalb wählt der Nutzer in der
Vorschau selbst: *Als Lieferschein buchen* oder *Als Auftragsbestätigung vermerken*. Abgleich nur über **Artikelnummer**
(führende Nullen egal). Fehlende Positionen bekommen den Hinweis „beim Lieferanten in Rückstand“.
Hochgeladene Dateien liegen bis zur Bestätigung in `einkauf-data/import/` (Token, 1 Tag).

**Lieferant Fega & Schmitt:** FTP-Server `ftp.fega-schmitt.de`, Eingang (Bestellungen hin) `/QDLS/IN/50/108690/`,
Ausgang (Bestätigungen/Lieferscheine her) `/QDLS/OUT/50/108690/`, ZUGFeRD-Rechnungen `/zugferd`, Version 04.00.
Zugangsdaten gehören nur in die App (verschlüsselt), **nie in Chat oder Dateien**. Dass Eingang = Bestellungen hin und
Ausgang = Belege her, ist die übliche Lesart, vom Lieferanten noch nicht bestätigt.

## 7. Entscheidungen, die schon gefallen sind
- Lexoffice nur **lesend** anbinden: Kontakte synchronisieren (Lieferanten/Kunden), Angebot beim Projekt optional wählen,
  Summe netto als Grundlage fürs Materialbudget. Projekte müssen auch **ohne** Angebot funktionieren.
- Im Lexoffice des Auftraggebers gilt: **Service = Positionen mit Stunden, Ware = alles ohne Stunden** (auch Pauschalen wie
  Inbetriebnahme, Kernbohrung, Gerüst). Der Typ sagt also nicht, was echtes Material ist. Geplant: eigene **Kostenart**
  pro Position (Material / Pauschale gemischt mit Materialanteil % / Fremdleistung / Arbeit), die sich die App pro
  Lexoffice-Artikel merkt; Budgetmodus Warensumme, Warensumme × Faktor (Aufschlag) oder manuell. Positionen ohne
  Kostenart als „unklar“ markieren statt still falsch rechnen. Abgleich Angebot ↔ Bestellung nur über Summen, nicht über
  Mengen/Einheiten (in Angeboten unzuverlässig).
- Einzeldatei ohne Docker war gewünscht; geliefert wird ZIP + `install.sh` (Python-venv). Echte Einzeldatei nur mit Bauprozess auf dem Pi möglich.
- Preise netto rechnen.

## 8. Offene Aufgaben (Reihenfolge nach Rücksprache)
(Stand 1.0: Lexoffice-Kontaktabgleich und Lieferschein-Maske sind gebaut; Punkt 2 unten betrifft jetzt Angebote/Aufträge/Rechnungen.)
0. **IDS mit echtem Shop prüfen** (Fega: IDS-Adresse, Kundennr., Benutzer, Passwort erfragen; Preissemantik, Feldname, Browser-Warnung). Danach ggf. `WKS` (Bestellung an den Shop senden).
1. ~~FTP-Abruf~~ (gebaut in 1.1.0; offen: SFTP, Test mit Fega, Abruf des ZUGFeRD-Ordners, Senden von Bestellungen in den Eingang-Ordner). Ursprünglich: **FTP/SFTP-Abruf** der Dateien aus dem Ausgang-Ordner (Felder am Lieferanten sind schon da, Abruf fehlt).
2. ~~Lexoffice-Anbindung Phase 2 & Kostenarten~~ (gebaut in 1.2.0; offen: Test gegen echtes Lexoffice mit API-Schlüssel).
3. ~~Kostenarten und Budgetberechnung~~ (gebaut in 1.2.0).
4. ~~Datanorm-Import~~ (gebaut in 1.3.0: `datanorm.py`, `/artikel`, `/artikel/import`).
5. ~~Bestellung per UGL senden~~ (UGL-Export `ugl.schreiben` + Download auf Bestellseite in 1.3.0; automatischer FTP-Upload in Eingang-Ordner noch offen).
6. ~~ZUGFeRD-Rechnungen~~ (gebaut in 1.3.0: `zugferd.py`, `/rechnungen` mit Abgleich zur Bestellung).
6b. ~~UGL-Vorschau 6b~~ (gebaut in 1.3.0: Dateidatum/Belegdatum getrennt, Duplikat-Warnung bei bereits gebuchter Lieferschein-Nr.).
7. ~~Kleinigkeiten~~ (gebaut in 1.3.0: Bearbeitungssperre + Optimistic Locking `sperre.py`, Änderungsprotokoll `/einstellungen/protokoll`, Rückstand-Zähler im Baum, Hinweise im Dashboard, Datensicherung ZIP `/einstellungen/sicherung`; offen: Barcode-Scan).

## 9. Tests und Entwicklung
```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python tests/test_basis.py            # Grundablauf (SQLite)
.venv/bin/python tests/test_ugl_projekte.py     # Projektansicht, Aufteilen, UGL-Import
TEST_DB=maria .venv/bin/python tests/test_basis.py   # gegen MariaDB (127.0.0.1, DB/Benutzer "einkauf", Passwort siehe Testdatei)
```
Beide Tests müssen vor jeder Auslieferung grün sein, auf SQLite **und** MariaDB. Für Updates ältere Datenbank künstlich
nachbauen (Spalten entfernen, `meta.schema_version` zurücksetzen) und prüfen, dass `init_db` sie hochzieht.
Echte Dateien des Lieferanten nicht ins Paket legen; `tests/make_ugl.py` baut eine nachgebaute Datei.

**Fallstricke, die schon aufgetreten sind**
- Hintergrund-Thread (Planer) braucht `app.app_context()`, sonst scheitert `security.decrypt` (Schlüssel aus der Konfiguration).
- FTP: Einen Download mitten im Transfer abzubrechen, bringt die Steuerverbindung durcheinander (`200 Type set to: Binary` als Fehler) → Größe vorab per `SIZE` prüfen, bei Abbruch neu verbinden (`_FtpVerbindung`).
- Jinja: Ein Dictionary-Schlüssel `items` kollidiert mit der Methode `.items` → anderen Namen nehmen.
- Jinja: Makros aus `_m.html` nur mit `{% from '_m.html' import … with context %}` importieren (sonst fehlt `csrf_token`).
- Jinja: `request.args.get(..., type=int)` geht im Template nicht, stattdessen `(… or 0)|int`.
- SQLAlchemy 2: `Query.get()` vermeiden, `.filter(...).first()` oder `session.get(Modell, id)` nutzen.
- `run.py` darf plattformspezifische Module (`pwd`) nur innerhalb der Linux-Funktion importieren, sonst läuft es nicht unter Windows.
- Beim Testen in der Sandbox niemals `pkill -f "python run.py"` (beendet die eigene Shell).
- Formularfelder aus Fremdsystemen (IDS) **nie über `request.form` lesen**: Werkzeug decodiert als UTF-8, ISO-8859-1-XML verliert Umlaute. Rohbytes über `ids.formular_teile(request.get_data())` holen.
- `/ids/rueckgabe/<token>` ist die einzige POST-Route ohne CSRF-Prüfung (Ausnahme in `__init__.py`); keine weitere ohne Token anlegen.
- Tests mit HTML-Formularen: `<select>` hat kein `value=`-Attribut, Werte dort separat setzen.
- Nummernmuster-Regeln stehen doppelt (Python `nummern.py`, JavaScript in `nummernkreise.html`); bei Änderungen beides anpassen und `tests/js` laufen lassen.
- Spalten in bestehenden Datenbanken nur über `_spalten_ergaenzen` nachziehen (siehe Abschnitt 4).

## 10. Versionsverlauf
- **1.3.1**
  - **Lieferantendateien & Auftragsbestätigung (AB) frei zuweisen (`/dateien/<id>` & `/bestellungen/<id>`):**
    - **Manuelle Bestellauswahl & Zuweisen-Buttons auf `/dateien/<id>`:** Selbst wenn in einer abgerufenen Lieferantendatei keine offene Bestellposition exakt dieselbe Artikelnummer trägt (z. B. bei Zusatz-/Ersatzartikeln oder fehlender AB-Nr. nach einer IDS-Übertragung), bietet `/dateien/<id>` nun immer ein Auswahlmenü aller Bestellungen des Lieferanten (mit Bestellnr., Datum, Projektname, Status und offenen Positionen) sowie zwei direkte Zuweisen-Buttons: **„📦 Bestellung zuweisen & prüfen (Einlieferung / AB)“** und **„📋 Direkt als AB zuweisen“**. Auch in der Dateiliste (`/dateien`) hat jede Zeile direkt einen Button „Zuweisen / Prüfen“.
    - **Auftragsbestätigung (AB) an der Bestellung (`/bestellungen/<id>`):** Da eine IDS-Übertragung noch keine AB ist und eine AB optional ist (aber bei Vorhandensein wichtige Zusatzinfos wie Lieferanten-Auftragsnummer `ab_nr` für Fega-Teillieferungen `01`/`02`, bestätigte Mengen und Liefertermine liefert), gibt es auf `/bestellungen/<id>` nun einen eigenen AB-Infobereich (zeigt `AB-Nr.`, verknüpfte AB-Dateien und ein ausklappbares Formular `POST /bestellungen/<id>/kopf` zum jederzeitigen Zuweisen/Ändern von AB-Nr., Bestellnr., Liefertermin und Notiz) sowie den Schnell-Button **„📋 Direkt als AB zuweisen“** bei den abgerufenen Dateien.
  - **Datanorm Materialübersicht (mit Hersteller & Hersteller-Art.-Nr.) & 3-Spalten Lieferanten-Vergleich über EAN (Schema 14/15):**
    - **Spalten „Hersteller“ und „Hersteller-Art.-Nr.“ (Schema 15):** In der Materialübersicht (`/artikel?ansicht=liste`) und im Vergleich gibt es nun zwei eigene Spalten für **Hersteller** (z. B. *Eaton, Siemens, Phoenix Contact, Hager, OBO Bettermann, Murrplastik, Cimco, Fischer, Weidmüller* – wird automatisch aus den Großhändler-Kürzeln wie `EATO`, `SIEM`, `PHOE`, `MURR` aufgelöst) und **Hersteller-Art.-Nr.** (aus Datanorm-Feld 16 bzw. B-Satz Feld 4 oder Kurztext). Über die Fallback-Properties `hersteller_anzeige` und `hersteller_artnr_anzeige` werden beide Spalten auch für bereits zuvor importierte Artikel sofort ohne Neu-Import angezeigt.
    - **Separate Artikelstämme je Lieferant & Überschneidungsschutz (Schema 14/15):** Das globale `UNIQUE`-Constraint auf `articles.artikelnr` wurde aufgehoben und durch Indizes auf `artikelnr`, `ean`, `hersteller`, `hersteller_artnr` und `supplier_id` ersetzt. Jeder Lieferant führt seinen eigenen Artikelstamm (Pflichtauswahl beim Import); identische Artikelnummern verschiedener Großhändler überschreiben sich nicht und werden weder im Vergleich noch bei der UGL-Positionsübernahme vermischt.
    - **Reiter „Materialübersicht“ (`/artikel?ansicht=liste`):** Zeigt das gesamte eingelesene Datanorm-Material mit Schnellfilter-Pills je Lieferant (inkl. Artikelanzahl), Filter „Nur mit Kupfer“, Suche über Artikelnr./Bezeichnung/EAN/Hersteller/Hersteller-Nr. sowie einem direkten Button **„⚖️ Vergleichen“** in jeder Zeile (zeigt direkt an, wie viele Händler dieselbe EAN führen, z. B. `⚖️ Vergleichen (3)`).
    - **Reiter „Lieferanten-Vergleich (bis zu 3 Spalten)“ (`/artikel?ansicht=vergleich`):** Ermöglicht das Aktivieren von 1, 2 oder **3 Lieferanten-Spalten nebeneinander**. Verknüpft identische Artikel unterschiedlicher Großhändler automatisch über die **EAN-Nummer** (bzw. Hersteller + Hersteller-Artikelnummer als Fallback). Hebt den **günstigsten Anbieter grün (`Günstigster`)** hervor und zeigt bei den anderen Spalten direkt den Mehrpreis in € und % sowie die jeweilige Lieferanten-Artikelnummer, Preiseinheit, Rabattgruppe und Kupferdaten an. Auch eine Suche nach der Artikelnummer nur eines Händlers findet über dessen EAN automatisch die Vergleichspreise der anderen beiden Händler.
  - **Datanorm 4/5, Preiseinheiten, Kupferzuschlag & Preispflege (Schema 13):**
    - **Datanorm 4 & 5 Erkennung:** Datanorm 4 (Rexel, Granzow, Löffelhardt mit separatem B-Satz) und Datanorm 5 (Fega mit erweitertem 29-Feld A-Satz) werden sauber unterschieden; Felder (Kurztext, Einheit, Preise) verschieben sich nicht mehr.
    - **Granzow & Löffelhardt Mehrfach-Preissätze (Datanorm 4 Satzart P):** Datanorm 4 erlaubt bis zu 3 Artikelblöcke je P-Zeile im Abstand von 9 Feldern (z. B. Granzow `datpreis.001` und Löffelhardt `Datanorm.zip`). Da der Datanorm-4-P-Satz kein eigenes Preiseinheit-Feld besitzt (Feld `off+3` ist das Rabattkennzeichen), übernimmt BeLiKo bei der Preisnormierung automatisch die im Artikelstamm (`A`-Satz bzw. Datenbank) hinterlegte Preiseinheit (`PE = 100` / `1000`), sodass auch bei Löffelhardt und Granzow keine Faktor-100-Fehler bei Kabeln oder Kleinmaterial entstehen.
    - **Löschpflege (Satzart A;L & Datanorm.900):** Vollständige Unterstützung für Löschpflege-Dateien (`Datanorm_LöschPflege.Zip`, `Datanorm.900` und `Datanorm_Änderungen.Zip` / `.701`). Entfernt vom Lieferanten abgekündigte/gelöschte Artikel aus dem Artikelstamm.
    - **Warengruppen & Rabattgruppen (Satzart S & R):** Satzarten `S` (Warengruppen z. B. `Datanorm.wrg`) und `R` (Rabattgruppen z. B. `datanorm.rab`) werden sauber erkannt und werfen keinen Fehler mehr.
    - **Direkter ZIP-Archiv-Upload (Fega, Rexel, Granzow, Löffelhardt):** Großhändler liefern Datanorm üblicherweise als ZIP-Archive aus (z. B. Rexel-Gesamtsortiment mit über 650.000 Artikeln oder Fega/Löffelhardt mit `datanorm.001` und `datpreis.001`). ZIP-Dateien können nun ohne vorheriges manuelles Entpacken direkt im Browser hochgeladen werden. BeLiKo entpackt das Archiv im Arbeitsspeicher, wählt die passenden Stamm- und Preispflegedateien aus und führt bei Fega und Löffelhardt automatisch den Preisabgleich durch. Upload-Limit und Puffer wurden dafür auf 150 MB angehoben.
    - **Preiseinheiten (PE = 1, 10, 100, 1000):** Vollständige Berücksichtigung von Preiseinheiten bei Kabeln (PE 100 = 100 m) und Kleinmaterial (PE 100/1000 = 100/1000 Stk) – Cent-Preise werden immer auf den echten Einzelpreis pro Einheit (1 Stück bzw. 1 Meter) heruntergerechnet, wodurch Multiplikationsfehler (Faktor 100) vermieden werden.
    - **Kupferfelder im Artikelstamm:** Speichert Kupferbasis (z. B. 150 €/100kg), Kupfergewicht/Cu-Zahl (z. B. 16,8 kg Cu pro 100m) und Kupfermerker (1=100m, 2=1000m, 3=1 Stk) sowie EAN, Matchcode und Hersteller-Teilenummer.
    - **Reine Preis-Datanorm (Preispflege):** Neue Import-Option unter `/artikel/import` ermöglicht das Einspielen von reinen Preispflege-Dateien (`DATPREIS`, Satzart P). Aktualisiert nur die Listenpreise bereits vorhandener Artikel, ohne Artikeltexte zu verändern oder Fremdartikel anzulegen.
    - **Artikelübersicht (`/artikel`):** Zeigt Kupferdaten (`Cu: 16,8 kg / 100m (Basis 150 €)`), EAN, Hersteller-Teilenummer und Preiseinheiten transparent an.
  - **Tabellarische Positionserfassung in der Bestelldetailansicht (`/bestellungen/<id>`):**
    - Umbau des bisherigen zweizeiligen Kachel-Formulars („Position hinzufügen“ mit `grid4`) in eine kompakte, übersichtliche Zeilentabelle (`table.zeilen`).
    - Spalten: `Artikelnr.`, `Bezeichnung *`, `Menge *`, `Einheit`, `Einzelpreis netto`, `Voraussichtlich`, `Projekt`, `Kommission`.
    - Neuer Button **„+ Zeile“**: Ermöglicht das Anlegen beliebig vieler Positionen auf einmal direkt in der Tabelle (inklusive Zeilen löschen mit `✕` und automatischer Enter-Weiterschaltung).
    - Alle erfassten Zeilen werden mit einem Klick auf „Position hinzufügen“ gebucht.
  - **Spaltensortierung für die Projekttabelle (wie Windows Explorer):**
    - Klick auf einen Spaltenkopf (`Nr.`, `Name`, `Kunde`, `Status`, `Offen`, `Bestellt`, `Materialbudget`) sortiert beim 1. Mausklick aufsteigend (`asc`: hochzählend bzw. A–Z) und beim 2. Mausklick absteigend (`desc`: runterzählend bzw. Z–A).
    - Windows-Explorer-typische natürliche Sortierung (Natural Sort) für Projektnummern (`_nat_key` / `localeCompare` mit `numeric: true`), sodass z. B. `P-2026-0001` vor `P-2026-0010` sortiert wird.
    - Alphabetische Sortierung für Textfelder (`Name`, `Kunde`, `Status`), numerische Sortierung für Zahlen/Währungen (`Offen`, `Bestellt`, `Materialbudget`), leere Felder (z. B. fehlender Kunde oder Budget) sauber am Ende.
    - Visuelle Pfeil-Anzeige (`▲` bzw. `▼`) im Spaltenkopf sowie Hover- und Aktiv-Hervorhebung.
    - Sowohl blitzschnell clientseitig im DOM (ohne Neuladen der Seite) mit URL-Aktualisierung (`history.replaceState`) als auch serverseitig in Python via URL-Parametern (`?sort=...&dir=...`).
    - Filter, Suche und ausgewählte Projekte/Tabs bleiben beim Sortieren erhalten.
  - **Fega Auftrags- & Lieferscheinnummern-Logik (Teillieferungen 01, 02 usw.):** Fega hängt an ihre 8-stellige Auftragsnummer (z. B. `47748835`) je Teillieferung ein zweistelliges Kürzel an (`01` für 1. Lieferung, `02` für 2. Lieferung usw. als 10-stellige Lieferscheinnummer `4774883501`, `4774883502`). BeLiKo erkennt diese Systematik nun vollautomatisch:
    - **Intelligente Zuordnung & Erkennung:** In der Lieferantendatei-Übersicht (`/dateien/<id>`) und auf der Bestelldetailseite (`/bestellungen/<id>`) werden Lieferscheine sofort als passend erkannt (`⭐ Passend (Lieferung 01)`), wenn die Belegnummer zur AB-Nummer der Bestellung passt – egal ob die Bestellung mit der Basis-Auftragsnummer (`47748835`) oder mit Belegsufix hinterlegt ist.
    - **UGL-Prüfungsansicht:** Zeigt bei erkanntem Fega-Lieferschein klar „Fega Teillieferung 01 zu Auftrag 47748835“ an und setzt „Als Lieferschein buchen (Wareneingang)“ als primären Aktionsbutton. Beim Buchen wird die Basis-Auftragsnummer automatisch als `ab_nr` in der Bestellung hinterlegt, sodass nachfolgende Teillieferungen (`4774883502` etc.) sofort gematcht werden.
    - **Anzeige von Teillieferungen:** In der Bestellpositionentabelle („Lieferschein & Lieferdatum“) und unter „Bisherige Lieferungen“ wird das Teillieferungskürzel (z. B. `Lfg. 01`) hervorgehoben. In der Bestellübersicht (`/bestellungen`) wird die AB-Nummer direkt mit angezeigt.
    - **Manuelle Lieferscheinerfassung:** Unter `/lieferscheine/neu` wird für Bestellungen mit AB-Nummer automatisch die nächste fortlaufende Fega-Lieferscheinnummer berechnet (z. B. `4774883502` bei 1 vorhandenen Lieferung) und kann mit einem Klick („... übernehmen“) direkt ins Formular übernommen werden.
  - **Projektname in Bestelllisten & Rückstand:** In der Bestellübersicht (`/bestellungen`, z. B. bei Teillieferung, offenen Bestellungen etc.) sowie in der Positionsliste der Bestelldetailseite (`/bestellungen/<id>`) und im Rückstand wird in der Spalte „Projekt“ nun neben der Projektnummer auch direkt der **Projektname** angezeigt (z. B. `P261113 · Wallbox`) und verlinkt direkt zum jeweiligen Projekt.
  - **Lieferantendatei / UGL – Positionen direkt zur Bestellung hinzufügen:** In der UGL-Prüfungsansicht (`/bestellungen/<id>/ugl`) können Positionen, die der Lieferant zusätzlich geliefert hat („nicht in dieser Bestellung“ oder „schon vollständig geliefert“), jetzt mit einem Klick auf **„Zur Bestellung hinzufügen“** (inkl. Projekt-Auswahl per Dropdown) direkt als neue Bestellposition in die Bestellung übernommen werden. Bei Übermengen („X mehr als offen“) stehen zwei Optionen bereit: **„+ Übermenge anlegen“** (legt eine separate Position für die Mehrmenge an) oder **„Menge anpassen“** (erhöht die bestehende Bestellposition). Die Vorschau aktualisiert sich sofort und die Positionen können direkt als Wareneingang mitgebucht werden.
  - **Neu-Button in der linken Seitenleiste (wie Lexoffice):** Der „Neu ▾“-Button wurde aus der oberen Leiste an die Spitze der linken Seitenleiste (über „Übersicht“) verlegt – analog zum Vorbild in Lexoffice prominent über die gesamte Navigationsbreite mit „+ Neu ▾“ und aufklappbarem Menü (Bestellung, Lieferschein, IDS, Projekt anlegen, Kontakt anlegen).
  - **Projektansicht: Reiter „Vorgang“ mit Blöcken Angebot, Bestellung, Rechnung:** Der bisherige Reiter „Bestellungen“ heißt nun **„Vorgang“** und integriert den früheren separaten Reiter „Angebote / Rechnungen“. Die Projektvorgänge sind nun chronologisch untereinander in 3 Blöcken gegliedert:
    1. **Angebot:** Zugeordnete Lexoffice-Angebote/Aufträge mit Materialwert, Status, Lösen-Button und Schnellauswahl für freie Angebote.
    2. **Bestellung:** Bestellungen an Lieferanten (nach Status gegliedert) mit Button „+ Neue Bestellung“ (mit vorausgewähltem Projekt).
    3. **Rechnung:** Zugeordnete Lexoffice-Rechnungen (Ausgangs- und Eingangsrechnungen) mit Nettosumme, Lösen-Button und Schnellauswahl für freie Rechnungen.
    Volle Abwärtskompatibilität: Aufrufe mit `tab=bestellungen` und `tab=lexoffice` zeigen automatisch den Vorgang-Reiter.
  - **Aktiver Menüpunkt & Reiter:** Aktive Menüpunkte im Navigationsbaum links (`.tree .on`, `summary.on`, `a.on`) und Tabs (`.tabs a.on`) werden nun mit hellerem Hintergrund (`--sel`), 3px blauem Markierungsbalken links (`border-left: 3px solid var(--blue)`) und blauer Fett-Schrift deutlich hervorgehoben (sowohl im Dark- als auch Light-Mode), sodass die aktuelle Position/Seite sofort ersichtlich ist.
  - **Passwörter:** Mindestlänge für Benutzer- und Admin-Passwörter von 8 auf **6 Zeichen** herabgesetzt (in `/setup`, `/konto`, `/einstellungen/benutzer`).
  - **Projekte & Bestellungen löschen:** Stift-Icon (✏️) zum Bearbeiten und rotes Mülleimer-Icon (🗑️) zum Löschen (mit `confirm()`-Sicherheitsabfrage) direkt in den Zeilen von `/projekte` und `/bestellungen`; Lösch-Buttons mit Bestätigung auf Detailseiten.
  - **Datenbank-Migration / Übertragungstool (SQLite → MariaDB):** `datenbank_kopieren.py` (Aufruf `python -m einkauf.datenbank_kopieren` zum Übertragen aller 20 Tabellen mit Foreign-Key-Bypass, `--zurueck-zu-sqlite` für schnellen Rollback) sowie automatische Übertragungs-Checkbox unter `/einstellungen/datenbank`.
  - **Bearbeitungssperren:** Automatische Freigabe beim Schließen des Tabs / Verlassen der Seite via `pagehide` & Beacon (`navigator.sendBeacon` / `fetch keepalive`); verkürztes Timeout von 3 Minuten mit 45s-Heartbeat-Ping; Klick auf „Abbrechen“ oder „Zurück“ gibt Sperre sofort frei; neuer Button „Alle Sperren aufheben“ unter `/einstellungen/protokoll`.
  - **Lieferscheinzuordnung & UGL:** Direktes Zuordnen abgerufener Lieferantendateien (`SupplierFile`) auf `/bestellungen/<id>` per Dropdown und Suchfenster (`🔍 Lieferschein auswählen …`); neue Spalte „Lieferschein & Lieferdatum“ in der Positionentabelle auf der Bestelldetailseite; FTP-Sofortabruf-Button.
  - **Lexoffice:** Eingangsrechnungen (`purchaseinvoice`), Filter nach Jahr und Monat in der Belegliste `/lexoffice/belege`, automatische Vorbelegung von Kostenarten (`material` = 100 %, `service`/Arbeit = 0 %), Lexoffice-Angebot direkt beim Projekt anlegen übernehmbar.
- **1.3.0** Bearbeitungssperre (`sperre.py`, `edit_locks`) mit Benutzer-Benachrichtigung beim Öffnen + Optimistic Locking (`version`) + Admin-Entsperrung; Änderungsprotokoll (`audit_logs`, `/einstellungen/protokoll`); Zähler „Positionen im Rückstand“ im Baum + Hinweise im Dashboard; UGL-Vorschau (Dateidatum/Belegdatum getrennt, Duplikat-Warnung) + UGL-Bestellexport (`ugl.schreiben`); Datanorm-Import (`datanorm.py`, `/artikel`); ZUGFeRD-Rechnungen (`zugferd.py`, `/rechnungen`); Datensicherung als ZIP (`/einstellungen/sicherung`) (Schema 12). Auf SQLite getestet, **nicht auf MariaDB / echtem Browser**.
- **1.2.0** Lexoffice Phase 2: Abruf von Angeboten, Aufträgen und Rechnungen (`/v1/voucherlist` + Detailabruf), Belegübersicht `/lexoffice/belege`, Kostenarten je Position (`material`, `pauschale` mit %, `fremdleistung`, `arbeit`, `unklar`) mit Artikelregeln (`lex_article_rules`), Materialbudget-Modi (`manuell`, `warensumme`, `faktor`), Projekt-Reiter „Angebote / Rechnungen“ mit Summenvergleich, optionale Kontaktverknüpfung am Lieferanten (Schema 11). Mit Schein-Server auf SQLite getestet, **nicht gegen echtes Lexoffice / nicht auf MariaDB**.
- **0.1** Grundgerüst: Einrichtungsassistent, Login, Rollen, Lieferanten, Projekte, Bestellungen, Wareneingang mit Teillieferung, Rückstand, CSV.
- **0.2** Lieferanten-Formular: Server, Pfade Eingang/Ausgang/ZUGFeRD, Version; Update-Migration (Schema 2).
- **0.3** Bestellstatus (Neu … Abgeschlossen) und Navigationsbaum links mit Jahr/Monat (Schema 3).
- **0.4** Geteilte Projektansicht (Liste oben, Reiter unten), Zurück-Link aus der Bestellung.
- **1.1.0** FTP-Abruf der Lieferantendateien (FTP/FTPS/Ordner, nur lesend) mit Dateiliste, Bestellvorschlag, Verbindungstest und automatischem Abruf (Schema 10). Mit Schein-FTP-Server getestet, **nicht mit Fega**.
- **1.0.3** IDS gelöst gemeldet; Hinweise im Lieferantenformular/Checklisten/README auf die Einstiegsadresse mit bekannten Adressen (Fega, Löffelhardt), Hinweis zum IDS-Benutzer abgeschwächt.
- **1.0.2** Hinweis auf „IDS Einstellungen“ im Shop-Kundenbereich (Lieferantenformular, Checklisten, README).
- **1.0.1** IDS-Hinweis zum eigenen IDS-Benutzer (Lieferantenformular, Checklisten, README).
- **1.0.0** Name BeLiKo; Neu-Menü oben statt einzelner Anlegen-Knöpfe; Lieferschein erfassen + Liste; Einstellungen → Lexoffice (API-Schlüssel, Optionen, Verbindungstest, Kontaktabgleich einseitig) (Schema 9). Gegen Schein-Server getestet, nicht gegen echtes Lexoffice.
- **0.9.0** IDS-Diagnose nach Fehlermeldung (Button im Shop fehlte): Verbindungstest (SV/LI), Selbsttest der Rückgabe, Aufruf per GET wählbar, IDS-Version als Auswahl, Checkliste (Schema 8). Mit Schein-Shop im Test geprüft, **nicht am echten Shop**.
- **0.8.0** Dark Mode je Benutzer (Mein Konto), Bestellung in einer Maske mit Positionsraster, IDS-Connect (Warenkorb aus dem Shop übernehmen) mit Lieferanten-Einstellungen, Einzelpreise mit 4 Nachkommastellen (Schema 7). Update von 0.7 auf SQLite und MariaDB geprüft; Zeilensteuerung der Maske im simulierten Browser getestet.
- **0.7.0** Nummernkreise per Muster (YYYY, YY, MM, DD, XXXX), automatischer Zähler-Neustart täglich/monatlich/jährlich, Live-Vorschau mit Beispielknöpfen, Update-Migration von Schema 5 (Schema 6). JS-Vorschau im simulierten Browser getestet.
- **0.6.0** Reiter Kontakte (Feldsatz wie Lexoffice, Ansprechpartner, Archiv, Schreibschutz für Lexoffice-Kontakte), Kunde im Projekt aus Kontakten wählbar oder frei, Nummernkreise für Projekt und Bestellung mit Vorschlag im Formular (Schema 5). Update von 0.5 auf SQLite und MariaDB geprüft.
- **0.5.1** Windows-Probelauf: `run.py` lädt `pwd` erst im Autostart-Zweig (lief unter Windows nicht), `install.bat`/`start.bat` ergänzt, README-Abschnitt „Zur Probe auf dem eigenen Rechner“. **Unter Windows nicht getestet** (nur Import ohne `pwd` simuliert).
- **0.5.0 (Doku-Stand 30.10.)** zweite Beispieldatei ausgewertet, nur Dokumentation ergänzt, Programm unverändert.
- **0.5** UGL-Upload mit Vorschau/Abgleich/Buchung, Kommission, Position aufteilen, Wunschtermin, Hinweis „in Rückstand“ (Schema 4); Tests ins Projekt; diese CLAUDE.md.

## 11. Arbeitsregeln für Claude
1. Vor Änderungen kurz die Absicht nennen, bei größeren Änderungen **erst Antwort/Plan, dann umsetzen**, wenn der Auftraggeber das verlangt.
2. Nach jeder Änderung: Tests (SQLite + MariaDB), Update-Test für Datenbank, `VERSION` und Schemaversion anpassen,
   README und **diese CLAUDE.md aktualisieren** (Stand, Versionsverlauf, offene Aufgaben), ZIP neu bauen und bereitstellen.
3. Ehrlich sagen, was getestet ist und was nicht (z. B. nicht auf echtem Pi/NAS, Oberfläche nicht im Browser gesehen).
4. Keine Zugangsdaten, keine echten Lieferantendateien oder Kundendaten ins Paket.

# BeLiKo – BestellLieferKontrolle

Weboberfläche zur Überwachung von Bestellungen und Lieferungen im Handwerksbetrieb.
Läuft auf einem Raspberry Pi (64-Bit), die Daten liegen in MariaDB auf dem NAS.

**Stand: Version 1.1.0.** Enthalten: Einrichtungsassistent, Benutzer mit Rollen,
Lieferanten (inkl. UGL-Angaben: Server, Pfade Eingang/Ausgang/ZUGFeRD, Version, Zugang), Projekte mit optionalem Materialbudget,
Bestellungen mit Positionen, Wareneingang mit Teillieferungen, Rückstandsübersicht mit CSV-Export,
geteilte Projektansicht, Lieferantendatei (UGL) hochladen mit Vorschau, Kontakte, Nummernkreise, Bestellmaske, Warenkorb-Übernahme aus dem Shop (IDS), Dark Mode, Lieferscheine, Lexoffice-Anbindung (Kontakte), FTP-Abruf der Lieferantendateien.
**Noch nicht enthalten:** automatischer FTP-Abruf, Lexoffice-Anbindung, Datanorm-Import.

## 1. Datenbank auf dem NAS vorbereiten (einmalig)

In MariaDB (z. B. über phpMyAdmin oder die Konsole):

```sql
CREATE DATABASE einkauf CHARACTER SET utf8mb4;
CREATE USER 'einkauf'@'%' IDENTIFIED BY 'EIN-STARKES-PASSWORT';
GRANT ALL ON einkauf.* TO 'einkauf'@'%';
FLUSH PRIVILEGES;
```

Die Tabellen legt die Anwendung selbst an. Prüfe, dass MariaDB im Netzwerk erreichbar ist
(Port 3306, nicht nur lokal auf dem NAS). Bei Synology/QNAP steht das in den MariaDB-Einstellungen.
Statt `'%'` kannst du die IP des Pi eintragen, das ist sicherer.

## Zur Probe auf dem eigenen Rechner (ohne NAS und Pi)

Für einen ersten Test reicht ein normaler Windows-, Mac- oder Linux-Rechner mit **Python 3.10 oder neuer**
(`python --version` im Terminal bzw. in der Eingabeaufforderung prüfen). MariaDB ist dafür nicht nötig.

1. ZIP entpacken.
2. **Windows:** `install.bat` doppelklicken, danach `start.bat`. **Mac/Linux:** `./install.sh`, danach `./start.sh`.
3. Im Browser `http://localhost:8080` öffnen. Die Windows-Firewall fragt eventuell nach, für den Test ist
   „Abbrechen“ in Ordnung, `localhost` funktioniert trotzdem.
4. Im Einrichtungsassistenten **„Lokale Datei (SQLite, nur zum Testen)“** wählen und den Admin anlegen.

Die Testdaten liegen im Ordner `einkauf-data`. Zum Zurücksetzen das Programm beenden und den Ordner löschen.
Wer gegen die MariaDB auf dem NAS testen will, legt dafür besser eine eigene Datenbank an (z. B. `einkauf_test`),
damit keine Testdaten in die spätere echte Datenbank geraten. Für den späteren Betrieb auf dem Pi einen frischen
`einkauf-data`-Ordner verwenden. Unter Windows läuft die Anwendung nur, solange das Fenster offen ist,
und den Autostart-Dienst (`--service`) gibt es nur unter Linux.

## 2. Installation auf dem Pi

Voraussetzung: Python 3.10 oder neuer (bei Raspberry Pi OS Bookworm vorhanden) und das Paket `python3-venv`.

```bash
unzip beliko.zip -d beliko
cd beliko
./install.sh
./start.sh
```

Beim Start steht in der Ausgabe die Adresse, z. B. `http://192.168.1.50:8080`.
Diese öffnest du im Browser. Beim ersten Mal führt der Assistent durch:

1. Datenbankverbindung (Host, Port, Name, Benutzer, Passwort) mit Verbindungstest
2. Admin-Benutzer anlegen (der erste Benutzer ist immer Admin)

## 3. Autostart

```bash
./install.sh --service
```

Richtet den Dienst `einkauf` ein, der nach jedem Neustart automatisch läuft.
Status: `systemctl status einkauf`, Protokoll: `journalctl -u einkauf -f`.
Der Dienst wartet notfalls, bis das NAS erreichbar ist (die Seite zeigt dann eine Hinweismeldung).

Den Port änderst du in `einkauf-data/config.json` (`"port"`). Router-Freigaben sind nicht nötig,
nur bei aktiver Firewall auf dem Pi z. B. `sudo ufw allow 8080`.

## 4. Update

Neue Programmdateien über die alten kopieren (den Ordner `einkauf-data` nicht anfassen), danach
`./install.sh` und Neustart (`sudo systemctl restart einkauf`). Die Datenbank wird beim Start automatisch angepasst (Version 0.2 ergänzt die neuen UGL-Felder, vorhandene Daten bleiben erhalten).

## 5. Umzug auf ein anderes System

1. Programmordner und den Ordner `einkauf-data/` kopieren.
2. Auf dem neuen System `./install.sh` ausführen und starten.

Die Datenbank bleibt auf dem NAS. `einkauf-data/config.json` enthält Datenbankzugang und den
Schlüssel, mit dem Lieferanten-Zugangsdaten verschlüsselt sind. Ohne diese Datei lassen sich die
gespeicherten Zugänge nicht mehr entschlüsseln, deshalb gehört sie in jede Sicherung.
Für ein ganz neues Setup mit bestehender Datenbank startet der Assistent und erkennt die vorhandene Installation.

## 6. Datensicherung

```bash
mysqldump -h NAS-IP -u einkauf -p einkauf > einkauf-sicherung.sql
```

Am besten per Aufgabenplaner des NAS nachts ausführen lassen.

## 7. Bestellstatus und Navigationsbaum

Links steht ein Baum: Projekte (nach Status) und Bestellwesen mit den Ordnern der Bestellungen,
darunter jeweils Jahr und Monat. Jede Bestellung durchläuft diese Stufen:

| Status | Bedeutung | Wie er entsteht |
|---|---|---|
| Neu | angelegt, noch nicht beim Lieferanten bestellt | Standard beim Erfassen |
| Bestellt | beim Lieferanten bestellt | Knopf „Als bestellt markieren“ (oder Haken beim Erfassen) |
| Teillieferung | ein Teil ist angekommen | automatisch beim Buchen eines Wareneingangs |
| Komplett | alles geliefert | automatisch, sobald nichts mehr offen ist |
| Abgeschlossen | bezahlt | Knopf „Als bezahlt abschließen“, nur bei Komplett |

Der Rückstand und die Projektsummen berücksichtigen nur Bestellungen ab Status „Bestellt“.
Abgeschlossene Bestellungen blenden sich aus der Standardliste aus und stehen im Ordner „Abgeschlossen“.
Beim Update von älteren Versionen gelten vorhandene Bestellungen als bestellt, Teillieferung und Komplett werden aus den Wareneingängen abgeleitet.

## 8. Projektansicht

Unter „Projekte“ steht oben die Projektliste (Suche, Filter), unten wechseln die Reiter
**Bestellungen** (nach Status gruppiert), **Material** und **Übersicht**, sobald du ein Projekt anklickst.
Ein Klick auf eine Bestellung öffnet sie, oben steht „Zurück zum Projekt“.

## 9. Lieferantendatei (UGL) hochladen

In der Bestellung den Abschnitt „Lieferantendatei einlesen (UGL)“ öffnen, die Datei aus dem
Ausgang-Ordner des Lieferanten wählen (z. B. `B0261027.001`) und „Datei prüfen“ klicken.
Die Vorschau gleicht die Positionen über die **Artikelnummer** mit der Bestellung ab. Dafür müssen
die Artikelnummern der Bestellpositionen die des Lieferanten sein. Führende Nullen spielen keine Rolle.

- **Als Lieferschein buchen:** bucht die ausgewählten Mengen als Wareneingang. Nicht enthaltene Positionen
  bekommen den Hinweis „beim Lieferanten in Rückstand“ und bleiben im Rückstand.
- **Als Auftragsbestätigung vermerken:** bucht nichts, sondern notiert an den Positionen, was bestätigt wurde.

Der Aufbau der Datei wurde aus einer Beispieldatei (UGL 04.00, Fega & Schmitt) abgeleitet, nicht aus
einer offiziellen Satzbeschreibung. Bei anderem Aufbau oder anderer Version zeigt die Vorschau eine Warnung.
Hochgeladene Dateien liegen bis zur Bestätigung (maximal einen Tag) in `einkauf-data/import/`.

Weitere Hilfen: pro Position ein Feld **Kommission**; eine Position lässt sich über „Bearbeiten“ auf ein
weiteres Projekt **aufteilen** (z. B. 5 Stück, davon 2 für ein anderes Projekt); die Bestellung hat einen **Wunschtermin**.

## 10. Kontakte und Nummernkreise

**Kontakte** (Baum links): Kunden und Lieferanten mit Adressen, E-Mail, Telefon, Steuerangaben und Ansprechpartnern.
Die Felder entsprechen den Kontakten in Lexoffice, damit später der Abgleich passt. Beim Anlegen eines Projekts wählst
du den Kunden aus dieser Liste (beim Tippen erscheinen Vorschläge) oder schreibst einen Namen frei hin, wenn es ihn
dort nicht gibt. Aus Lexoffice synchronisierte Kontakte werden später schreibgeschützt sein.

**Nummernkreise** (Einstellungen → Nummernkreise, nur Admin): Für Projekte und Bestellungen legst du ein **Muster** fest,
während du tippst, zeigt die Seite sofort die nächste Nummer. Platzhalter: `YYYY` Jahr vierstellig, `YY` Jahr zweistellig,
`MM` Monat, `DD` Tag und `XXXX` für die laufende Nummer (die Anzahl der X ist die Stellenzahl). Beispiele:
`P-YYYY-XXXX` → P-2026-0001, `YYMMDDXXXX` → 2610310001, `2265XXXX` → 22652081.
Der Zähler beginnt automatisch neu, wenn das Muster ein Datum enthält (mit Tag täglich, mit Monat monatlich, mit Jahr jährlich);
das lässt sich auch fest einstellen. Neue Projekte und Bestellungen zeigen die nächste Nummer als Vorschlag, den du im Feld überschreiben
kannst. Bereits vergebene Nummern werden übersprungen, doppelte Nummern abgewiesen.

## 11. Bestellung erfassen und Warenkorb aus dem Shop (IDS)

**Neue Bestellung** ist eine einzige Maske: oben der Kopf (Lieferant, Datum, Bestellnummer, AB-Nr., Wunschtermin, Projekt für alle Positionen),
darunter das Raster mit den Positionen. Mit „+ Zeile“ oder Enter kommt eine weitere Zeile dazu, leere Zeilen werden ignoriert.

**Aus dem Shop übernehmen (IDS-Connect):** Beim Lieferanten (Einstellungen → Lieferanten) trägst du die IDS-Adresse, Kundennummer, Benutzername und
Passwort des Shops ein (bekommst du vom Lieferanten). Dann im Baum **Bestellwesen → Aus Shop übernehmen (IDS)** → „Shop öffnen“. Der Shop öffnet sich
in einem neuen Tab und meldet dich an. Nach „Warenkorb übertragen“ im Shop erscheint die Bestellmaske mit allen Positionen, Mengen, Preisen und der
Auftragsbestätigungsnummer. Du ordnest das Projekt zu und speicherst.
Hinweise: Der Browser muss die App unter derselben Adresse erreichen, mit der du sie aufgerufen hast. Bei http-App und https-Shop kann der Browser
vor dem Senden warnen, das kannst du im eigenen Netz bestätigen. Prüfe bei der ersten Übernahme, ob die Einzelpreise stimmen, und stelle sonst beim
Lieferanten um, ob der Nettopreis für die ganze Menge oder eine Einheit gilt. Das Senden von Bestellungen an den Shop ist nicht enthalten.

**Im Shop fehlt der Button zum Übertragen?** Der Shop zeigt ihn nur, wenn er die Rückgabe-Adresse annimmt. Prüfe der Reihe nach:
00. Trage die **IDS-Einstiegsadresse** des Lieferanten ein, nicht die normale Shop-Adresse. Bekannt (laut Rückmeldung des Auftraggebers funktioniert die Übernahme damit): Fega & Schmitt `https://shop.fega.de/abtest/scripts/clsAIShop.php`, Löffelhardt `https://online.loeffelhardt.de/punchout/ids`. Sonst im Kundenbereich des Shops unter „IDS Einstellungen“ suchen oder im Browser ablesen (F12 → Netzwerk, erste Anfrage beim Start aus der Branchensoftware).
0. Verwende den **IDS-Benutzer** des Lieferanten (oft ein eigener Zugang, z. B. mit der Endung „_ids“), nicht den normalen Shop-Login. Er steht in der Branchensoftware beim Lieferanten unter IDS Connect.
1. Im Shop vorher abmelden oder den Shop aus einem privaten Fenster öffnen (eine bestehende Anmeldung überdeckt den IDS-Aufruf).
2. Im Shop bis zur letzten Seite (Bestellübersicht) durchklicken. Der Button steht dort oft neben „Bestellen“, nicht im Warenkorb.
3. Unter Einstellungen → Lieferanten den **Verbindungstest** ausführen: Er zeigt, ob die Adresse ein IDS-Zugang ist, welche Versionen der Shop kennt und welche Anmeldedaten er verlangt.
4. Auf der Seite „Aus Shop übernehmen“ den **Selbsttest** ausführen: Er schickt einen Testwarenkorb ohne den Shop an die App. Klappt das, liegt es am Shop oder an den Einstellungen.
5. Beim Lieferanten die **Version** passend einstellen und es mit dem Aufruf per Adresszeile (GET) versuchen.
6. Manche Shops verlangen eine https-Rückgabe-Adresse. Dann beim Lieferanten nachfragen.

## 12. Darstellung (Dark Mode)

Unter **Mein Konto → Darstellung** wählst du für deinen Benutzer Hell, Dunkel oder „wie das Gerät“.

## 13. Für die Weiterentwicklung

`CLAUDE.md` im Projektordner beschreibt Aufbau, Entscheidungen, offene Aufgaben und Versionsverlauf, damit die Arbeit
in einem neuen Chat nahtlos weitergehen kann (ZIP hochladen und „lies die CLAUDE.md und mach weiter“ sagen).
Die Tests liegen in `tests/` (`.venv/bin/python tests/test_basis.py`). Für den FTP-Test: `pip install -r tests/requirements-test.txt`.

## 14. Neu-Menü und Lieferscheine

Oben in der Kopfzeile steht der Knopf **Neu** mit einem Aufklappmenü: Bestellung, Lieferschein, Aus IDS übernehmen, Projekt anlegen, Kontakt anlegen.
Einzelne „Anlegen“-Knöpfe in den Listen gibt es nicht mehr (in den Einstellungen bleiben „Lieferant anlegen“ und „Benutzer anlegen“).

**Lieferschein erfassen:** Lieferant wählen, dann erscheinen alle offenen Positionen seiner bestellten Bestellungen. Du trägst ein, was geliefert wurde
(oder „Alles als geliefert buchen“), dazu Lieferschein-Nr. und Datum. Ein Lieferschein über mehrere Bestellungen wird je Bestellung gebucht, der Status
(Teillieferung/Komplett) setzt sich selbst. Dieselbe Lieferschein-Nr. kann pro Lieferant nur einmal gebucht werden. Die Liste steht im Baum unter Bestellwesen → Lieferscheine.
Eine Datei des Lieferanten (UGL) liest du weiterhin in der jeweiligen Bestellung ein.

## 15. Lexoffice (Einstellungen → Lexoffice)

Hier schaltest du die Schnittstelle ein, trägst den **API-Schlüssel** ein (in Lexoffice unter Einstellungen → Öffentliche API erzeugt, nur Administratoren; er wird verschlüsselt
gespeichert und nie angezeigt) und wählst, was abgeglichen wird: Kunden, Lieferanten, archivierte Kontakte. Angebote, Aufträge und Rechnungen sind als Optionen vorgesehen,
aber **noch nicht umgesetzt** (gesperrt). Der Abgleich läuft **in eine Richtung (Lexoffice → BeLiKo), nur lesend**, auf Knopfdruck (auch auf der Kontakte-Seite). „Verbindung testen“ prüft den Schlüssel.
Aus Lexoffice übernommene Kontakte sind in BeLiKo schreibgeschützt; Kontakte, die dort fehlen oder durch die Optionen ausgeschlossen sind, werden archiviert, nicht gelöscht.
Projekte, die mit einem solchen Kontakt verknüpft sind, übernehmen Namensänderungen. **Gegen das echte Lexoffice noch nicht ausprobiert**, nur gegen einen nachgebauten Server nach der öffentlichen Dokumentation.

## 16. Lieferantendateien per FTP abrufen

Die Dateien des Lieferanten (Auftragsbestätigungen, Lieferscheine als UGL) holt BeLiKo aus dem **Ausgang-Ordner** des Lieferanten, **nur lesend**: Auf dem Server des Lieferanten wird nichts gelöscht oder verändert.

**Einrichten** (Einstellungen → Lieferanten → Lieferant → UGL-Schnittstelle): Übertragungsweg **FTP** (oder **FTPS**, wenn angeboten, oder **Datei** für einen Ordner/Netzlaufwerk), Server-Adresse, Port (leer = 21), **Pfad Ausgang**, Benutzer und Passwort (verschlüsselt gespeichert). Beispiel Fega & Schmitt: Server `ftp.fega-schmitt.de`, Pfad Ausgang `/QDLS/OUT/50/108690/`.
Dann speichern und **„Verbindung testen“**: Er zeigt, ob die Anmeldung klappt und welche Dateien im Ordner liegen (es wird nichts heruntergeladen). **SFTP ist noch nicht umgesetzt.**

**Abrufen:** unter Bestellwesen → **Lieferantendateien** „Jetzt abrufen“ (je Lieferant oder alle), oder automatisch: beim Lieferanten „Automatisch abrufen“ (alle 15/30/60 Minuten oder 4 Stunden). Schon geholte Dateien werden erkannt und nicht doppelt angelegt. Neue Dateien zeigt der Baum mit einer Zahl und die Übersicht an.
Aus Sicherheitsgründen werden nur Dateien mit einfachen Namen (Buchstaben, Ziffern, `. _ -`) und bis 5 MB geholt. Dateien, die keine lesbare UGL-Datei sind, stehen unter „Nicht lesbar“.

**Verarbeiten:** In der Liste eine Datei öffnen. BeLiKo schlägt die **passende Bestellung** vor (die mit den meisten gleichen Artikelnummern in noch offenen Positionen). Nach „Mit dieser Bestellung prüfen“ siehst du die gewohnte Vorschau und entscheidest, ob die Datei als **Lieferschein** (Wareneingang) gebucht oder als **Auftragsbestätigung** vermerkt wird. Danach steht sie unter „Verarbeitet“. Was nicht gebraucht wird, setzt du auf „Ignoriert“.

**Gut zu wissen:** Normales FTP überträgt Passwort und Dateien **unverschlüsselt** durch das Internet. Nimm FTPS, wenn der Lieferant es anbietet (bei FTPS lässt sich die Zertifikatsprüfung bei Bedarf abschalten). Der automatische Abruf läuft nur, solange BeLiKo läuft. **Mit dem echten Fega-Server noch nicht getestet** (nur mit einem nachgebauten FTP-Server): Fegas Server liegt vermutlich auf einem IBM-System (Pfade mit `/QDLS/`), das sich in Details anders verhalten kann. Der Verbindungstest zeigt das.

## 17. Rollen

| Rolle | Rechte |
|---|---|
| Admin | alles, inkl. Einstellungen, Lieferanten und Benutzer |
| Einkäufer | Bestellungen, Projekte und Wareneingang bearbeiten |
| Nur lesen | alles ansehen, nichts ändern |

Der letzte aktive Admin kann nicht deaktiviert oder herabgestuft werden.

## Hinweise zur Sicherheit

- Die Anwendung ist für das lokale Netz gedacht und spricht HTTP. Nicht ins Internet stellen.
- `einkauf-data/config.json` ist nur für den Besitzer lesbar. Nicht weitergeben.
- Passwörter werden gehasht gespeichert, Anmeldeversuche begrenzt, Formulare gegen CSRF geschützt.

# BeLiKo – BestellLieferKontrolle

Webanwendung zur Überwachung von Einkauf, Bestellungen, Wareneingang und Projekten für einen Elektro-Handwerksbetrieb.
Entwickelt für den Betrieb auf einem **Raspberry Pi 4 (64-Bit)** im lokalen Netzwerk mit Datenbank **MariaDB auf dem NAS** (oder SQLite für lokale Testläufe).

**Stand: Version 1.3.0 · Datenbank-Schemaversion 12**

---

## Funktionen im Überblick

- **Bestellwesen & Wareneingang:**
  - Bestellungen erfassen in einer übersichtlichen Maske (inkl. Positionsraster, Termine, Kommission, Projektzuordnung).
  - Bestellstatus-Ablauf: `Neu` → `Bestellt` → `Teillieferung` → `Komplett geliefert` → `Abgeschlossen` (bezahlt).
  - Wareneingang und Lieferscheine zentral oder je Bestellung erfassen (automatische Statusermittlung).
  - Rückstandsliste mit Filterung nach Projekt, Lieferant oder Datum sowie CSV-Export.
  - Dynamischer Rückstands-Zähler direkt im Navigationsbaum links.
- **Projekte & Materialbudget:**
  - Projekte mit Status, Kundenverknüpfung und Notizen.
  - Reiter: *Bestellungen*, *Material*, *Angebote / Rechnungen* und *Übersicht* mit KPI-Karten und Fortschrittsbalken.
  - Drei Budget-Modi wählbar:
    - **Manuell:** festes Materialbudget in Euro.
    - **Warensumme:** automatische Berechnung aus den Materialwerten verknüpfter Lexoffice-Angebote.
    - **Faktor:** Warensumme × Aufschlags-/Sicherheitsfaktor (z. B. 1,10).
- **Lexoffice-Anbindung (Phase 1 & 2, nur lesend):**
  - Kontakte (Kunden & Lieferanten) einseitig synchronisieren (Lexoffice-Kontakte sind schreibgeschützt, Namensänderungen werden in Projekten nachgezogen).
  - Angebote, Auftragsbestätigungen und Rechnungen abrufen (`/v1/voucherlist` + Details).
  - Zuordnung von Belegen zu Projekten.
  - Kostenarten pro Position festlegen: `Material` (100 %), `Pauschale` (mit % Materialanteil), `Fremdleistung` (0 %), `Arbeit` (0 %) oder `Unklar`.
  - Gemerkte Kostenarten pro Lexoffice-Artikel (`lex_article_rules`) für automatische Übernahme bei künftigen Belegen.
- **Großhändler-Schnittstellen (IDS & UGL):**
  - **IDS-Connect 2.5 (WKE):** Warenkorb per Knopfdruck direkt aus dem Shop des Großhändlers (z. B. Fega & Schmitt, Löffelhardt) in BeLiKo übernehmen.
  - **UGL-Import & FTP-Abruf:** UGL-Dateien manuell hochladen oder per FTP/FTPS automatisch im Hintergrund abholen, mit Vorschau, Dateidatum/Belegdatum-Trennung und Duplikatswarnung bei bereits gebuchten Lieferscheinen.
  - **UGL-Bestellexport:** Bestellungen als standardisierte UGL-Datei (Satzarten RGD, KOP, POA, END) herunterladen.
- **Artikelstamm & Datanorm-Import:**
  - Datanorm-Dateien (Version 4 und 5, Satzarten A und P) einlesen und im Artikelstamm durchsuchen.
- **Rechnungsabgleich (ZUGFeRD / Factur-X):**
  - Elektronische Lieferantenrechnungen (PDF mit eingebettetem XML oder reines XML) einlesen und automatisch mit der zugehörigen Bestellung auf Betragsabweichungen abgleichen.
- **Gleichzeitige Bearbeitung & Sicherheit:**
  - **Bearbeitungssperre (Pessimistic Lock):** Wird ein Datensatz geöffnet, wird er für andere Benutzer gesperrt. Andere Benutzer erhalten eine klare Benachrichtigung, welcher Kollege den Datensatz gerade geöffnet hat und seit wann.
  - **Optimistic Locking:** Schutz vor gegenseitigem Überschreiben durch Versionszähler (`version`).
  - Sperren können von Administratoren bei Bedarf manuell aufgehoben werden.
- **Administration, Protokoll & Sicherung:**
  - Rollenkonzept: `admin` (alles), `einkaeufer` (erfassen und buchen), `leser` (nur ansehen). Letzter Admin ist vor Löschen/Deaktivieren geschützt.
  - Vollständiges Änderungsprotokoll (`audit_logs`) für wichtige Aktionen.
  - Nummernkreise mit frei definierbaren Mustern (`YYYY`, `YY`, `MM`, `DD`, `XXXX`) für Projekte und Bestellungen.
  - Dark Mode / Hell / Automatisch pro Benutzerkonto (WCAG-geprüfte Kontraste).
  - Datensicherung des Datenordners per Knopfdruck als ZIP-Download.

---

## Schnelleinstieg & Test auf dem eigenen Rechner

Für einen schnellen Test genügt ein Rechner mit **Python 3.10 oder neuer** (kein NAS, kein MariaDB nötig):

1. **Repository klonen oder herunterladen:**
   ```bash
   git clone <REPO-URL>
   cd Beliko
   ```
2. **Einrichten und Starten:**
   - **Windows:** `install.bat` doppelklicken, danach `start.bat`.
   - **Linux / Mac:** `./install.sh`, danach `./start.sh`.
3. **Im Browser öffnen:**
   - `http://localhost:8080` aufrufen.
   - Im Assistenten **„Lokale Datei (SQLite, nur zum Testen)“** auswählen und den ersten Admin-Benutzer anlegen.

---

## Installation auf dem Raspberry Pi (Produktionsbetrieb)

### 1. MariaDB auf dem NAS vorbereiten
Auf dem NAS (z. B. Synology, QNAP) in MariaDB via phpMyAdmin oder MySQL-Konsole eine Datenbank und einen Benutzer anlegen:

```sql
CREATE DATABASE einkauf CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'einkauf'@'%' IDENTIFIED BY 'DEIN_SICHERES_PASSWORT';
GRANT ALL ON einkauf.* TO 'einkauf'@'%';
FLUSH PRIVILEGES;
```
*(Hinweis: Statt `'%'` kann für höhere Sicherheit die feste IP-Adresse des Raspberry Pi angegeben werden.)*

### 2. Installation auf dem Pi
```bash
git clone <REPO-URL> beliko
cd beliko
./install.sh
./start.sh
```

Beim ersten Aufruf im Browser (z. B. `http://192.168.1.50:8080`) führt der Einrichtungsassistent durch:
- Eingabe der MariaDB-Zugangsdaten mit Verbindungstest.
- Anlegen des ersten Admin-Benutzers.

### 3. Als Hintergrund-Dienst (Autostart) einrichten
```bash
./install.sh --service
```
Richtet einen `systemd`-Dienst (`einkauf.service`) ein, der BeLiKo nach jedem Neustart automatisch startet.
- Status prüfen: `systemctl status einkauf`
- Live-Logs ansehen: `journalctl -u einkauf -f`

---

## Verzeichnisstruktur

```text
Beliko/
├── einkauf/                  # Hauptanwendung (Flask, SQLAlchemy 2)
│   ├── __init__.py           # App-Fabrik, Filter, Kontextprozessoren
│   ├── models.py             # Datenbank-Modelle & Geschäftslogik
│   ├── views.py              # Alle HTTP-Routen & Controller
│   ├── db.py                 # Schema-Initialisierung & Migrationen
│   ├── config.py             # Konfigurationsverwaltung (config.json)
│   ├── security.py           # Verschlüsselung (Fernet), CSRF, Rollen
│   ├── sperre.py             # Bearbeitungssperren (Pessimistic & Optimistic)
│   ├── lexoffice.py          # Lexoffice Public API (Kontakte & Belege)
│   ├── ugl.py                # UGL-Parser & UGL-Bestellexport
│   ├── lieferantendateien.py  # FTP/FTPS/Ordner-Abruf von UGL-Dateien
│   ├── planer.py             # Hintergrund-Thread für periodischen Dateiabruf
│   ├── datanorm.py           # Datanorm 4/5 Parser
│   ├── zugferd.py            # ZUGFeRD / Factur-X Rechnungsleser
│   ├── ids.py                # IDS-Connect 2.5 (Warenkorbempfang WKE)
│   ├── nummern.py            # Nummernkreis-Engine (Musterformatierung)
│   ├── formate.py            # Deutsche Zahlen-, Währungs- und Datumsformate
│   ├── templates/            # Jinja2-HTML-Vorlagen (inkl. _m.html Makros)
│   └── static/style.css      # CSS-Design (Hell, Dunkel, Druckansicht)
├── tests/                    # Test-Suite (SQLite & MariaDB)
├── install.sh / install.bat  # Installationsskripte (Venv + Abhängigkeiten)
├── start.sh / start.bat      # Startskripte
├── run.py                    # Serverstart (Waitress) & Service-Setup
├── requirements.txt          # Python-Abhängigkeiten
├── CLAUDE.md                 # Projektdokumentation & Entwickler-Übergabe
└── .gitignore                # Git-Ausschlussregeln
```

---

## Tests ausführen

Vor jedem Release oder Commit sollten die Tests ausgeführt werden:

```bash
# Virtuelle Umgebung aktivieren
source .venv/bin/activate       # bzw. .venv\Scripts\Activate.ps1 unter Windows

# Alle Tests laufen lassen
python tests/test_basis.py
python tests/test_kontakte_nummern.py
python tests/test_lexoffice.py
python tests/test_v130.py
python tests/test_ugl_projekte.py
python tests/test_neu_lieferschein.py
python tests/test_nummernmuster.py
python tests/test_ids_diagnose.py
python tests/test_ids_maske_dunkel.py

# Optional: Gegen echte MariaDB testen
TEST_DB=maria python tests/test_basis.py
```

---

## Lizenz & Vertraulichkeit

Dieses Projekt ist für den internen Einsatz in einem Handwerksbetrieb bestimmt. Vertrauliche Zugangsdaten (API-Schlüssel, Datenbank-Passwörter, Shop-Logins) werden verschlüsselt gespeichert und gehören niemals in das Git-Repository.

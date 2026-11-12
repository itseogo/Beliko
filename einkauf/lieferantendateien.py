"""Abruf von Lieferantendateien (UGL) per FTP, FTPS oder aus einem Ordner.

Es wird nur gelesen: Dateien auf dem Server des Lieferanten werden nie gelöscht oder verändert.
SFTP ist noch nicht umgesetzt.
"""
import ftplib
import hashlib
import os
import re
import socket
import ssl
from datetime import datetime
from pathlib import Path

from . import config, security, ugl
from .models import Supplier, SupplierFile

NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._\-]{0,99}$")     # nur harmlose Dateinamen
MAX_BYTES = 5_000_000
MAX_DATEIEN = 200
TIMEOUT = 20
VERFAHREN = ("ftp", "ftps", "datei")


class AbrufFehler(Exception):
    pass


def pruefen(s):
    """Meldung, wenn die Einstellungen des Lieferanten für einen Abruf nicht reichen, sonst None."""
    v = s.ugl_verfahren
    if v == "sftp":
        return "SFTP ist noch nicht umgesetzt. Bitte FTP oder FTPS wählen, falls der Lieferant das anbietet."
    if v not in VERFAHREN:
        return "Für diesen Lieferanten ist kein Abruf per FTP, FTPS oder Ordner eingerichtet (Einstellungen → Lieferanten → UGL-Schnittstelle)."
    if not s.ugl_pfad_ausgang:
        return "Es fehlt der Pfad Ausgang (Ordner, aus dem die Dateien des Lieferanten abgeholt werden)."
    if v in ("ftp", "ftps") and not s.ugl_server:
        return "Es fehlt die Server-Adresse."
    return None


def _fehler_text(e, s):
    if isinstance(e, ssl.SSLCertVerificationError):
        return "Das Zertifikat des Servers ist nicht vertrauenswürdig. Du kannst beim Lieferanten „Zertifikat prüfen“ ausschalten, wenn du dem Server vertraust."
    if isinstance(e, ssl.SSLError):
        return f"Die verschlüsselte Verbindung (FTPS) ist fehlgeschlagen: {e}"
    if isinstance(e, socket.gaierror):
        return f"Der Server {s.ugl_server} wurde nicht gefunden. Stimmt die Adresse, und ist der Pi im Internet?"
    if isinstance(e, (socket.timeout, TimeoutError)):
        return "Der Server antwortet nicht (Zeitüberschreitung). Port und Firewall prüfen."
    if isinstance(e, ConnectionRefusedError):
        return "Der Server hat die Verbindung abgelehnt. Stimmt der Port?"
    if isinstance(e, ftplib.error_perm):
        t = str(e)
        if t.startswith("530"):
            return "Die Anmeldung wurde abgelehnt. Benutzername oder Passwort stimmen nicht."
        if t.startswith("550"):
            return f"Der Ordner {s.ugl_pfad_ausgang} wurde nicht gefunden oder ist nicht lesbar."
        return f"Der Server hat den Befehl abgelehnt: {t}"
    if isinstance(e, ftplib.Error):
        return f"FTP-Fehler: {e}"
    if isinstance(e, OSError):
        return f"Verbindungsproblem: {e}"
    return str(e)


def _verbinden(s):
    ftps = s.ugl_verfahren == "ftps"
    if ftps:
        ctx = ssl.create_default_context()
        if s.ugl_tls_pruefen is False:
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
        ftp = ftplib.FTP_TLS(context=ctx, timeout=TIMEOUT)
    else:
        ftp = ftplib.FTP(timeout=TIMEOUT)
    ftp.connect(s.ugl_server, int(s.ugl_port) if s.ugl_port else 21)
    ftp.login(s.ugl_benutzer or "anonymous", security.decrypt(s.ugl_passwort_enc) if s.ugl_passwort_enc else "")
    if ftps:
        ftp.prot_p()
    ftp.set_pasv(True)
    return ftp


def _ordner_ftp(ftp, pfad):
    ftp.cwd(pfad)
    try:
        namen = ftp.nlst()
    except ftplib.error_perm as e:
        if str(e).startswith("550"):                    # viele Server melden so einen leeren Ordner
            return []
        raise
    erg = []
    for n in namen:
        n = n.replace("\\", "/").rsplit("/", 1)[-1]
        if n and n not in erg:
            erg.append(n)
    return erg


class _ZuGross(Exception):
    pass


class _FtpVerbindung:
    """FTP-Verbindung zum Ausgang-Ordner. Zu große Dateien werden vorab per SIZE erkannt; bricht ein Download ab,
    wird die Verbindung neu aufgebaut (sonst gerät die Steuerverbindung durcheinander)."""

    def __init__(self, s):
        self.s = s
        self.ftp = None
        self._oeffnen()

    def _oeffnen(self):
        self.ftp = _verbinden(self.s)
        self.ftp.cwd(self.s.ugl_pfad_ausgang)

    def namen(self):
        return _ordner_ftp(self.ftp, ".")

    def holen(self, name):
        try:
            self.ftp.voidcmd("TYPE I")
            groesse = self.ftp.size(name)
        except (ftplib.error_perm, ftplib.error_reply):
            groesse = None
        if groesse is not None and groesse > MAX_BYTES:
            raise AbrufFehler("zu groß")
        puffer = bytearray()

        def teil(b):
            puffer.extend(b)
            if len(puffer) > MAX_BYTES:
                raise _ZuGross()
        try:
            self.ftp.retrbinary("RETR " + name, teil)
        except _ZuGross:
            self._neu()
            raise AbrufFehler("zu groß")
        return bytes(puffer)

    def _neu(self):
        try:
            self.ftp.close()
        except Exception:
            pass
        self._oeffnen()

    def schliessen(self):
        try:
            self.ftp.quit()
        except Exception:
            pass


def testen(s):
    """Prüft die Verbindung und listet den Ausgang-Ordner, ohne etwas herunterzuladen."""
    meldung = pruefen(s)
    if meldung:
        raise AbrufFehler(meldung)
    try:
        if s.ugl_verfahren == "datei":
            p = Path(s.ugl_pfad_ausgang)
            if not p.is_dir():
                raise AbrufFehler(f"Der Ordner {p} wurde nicht gefunden.")
            namen = sorted(f.name for f in p.iterdir() if f.is_file())
        else:
            ftp = _verbinden(s)
            try:
                namen = _ordner_ftp(ftp, s.ugl_pfad_ausgang)
            finally:
                try:
                    ftp.quit()
                except Exception:
                    pass
    except AbrufFehler:
        raise
    except Exception as e:
        raise AbrufFehler(_fehler_text(e, s))
    gut = [n for n in namen if NAME.match(n)]
    return {"alle": len(namen), "namen": gut, "ungueltig": len(namen) - len(gut)}


def _speichern(session, s, name, daten):
    """Legt die Datei ab und trägt sie in die Liste ein. Gibt True zurück, wenn sie neu war."""
    sha = hashlib.sha256(daten).hexdigest()
    if session.query(SupplierFile).filter(SupplierFile.supplier_id == s.id, SupplierFile.name == name, SupplierFile.sha256 == sha).first():
        return False
    ordner = config.DATA_DIR / "lieferantendateien" / str(s.id)
    ordner.mkdir(parents=True, exist_ok=True)
    ziel = ordner / name
    if ziel.exists():
        ziel = ordner / f"{sha[:8]}-{name}"
    ziel.write_bytes(daten)
    f = SupplierFile(supplier_id=s.id, name=name, pfad=str(ziel.relative_to(config.DATA_DIR)), groesse=len(daten), sha256=sha)
    try:
        r = ugl.lesen(daten)
        f.belegnr, f.belegart = r["kopf"].get("belegnr") or None, r["kopf"].get("belegart") or None
        f.kennung, f.datei_datum, f.positionen = r["datei"].get("kennung") or None, r["datei"].get("datum"), len(r["positionen"])
        if r["warnungen"]:
            f.hinweis = r["warnungen"][0][:300]
    except ugl.UglFehler as e:
        f.status, f.hinweis = "fehler", f"Keine lesbare UGL-Datei: {e}"[:300]
    session.add(f)
    return True


def _datei_lesen(name, ref):
    if ref.stat().st_size > MAX_BYTES:
        raise AbrufFehler("zu groß")
    return ref.read_bytes()


def abrufen(session, s):
    """Holt neue Dateien aus dem Ausgang-Ordner. Der Aufrufer speichert (commit)."""
    meldung = pruefen(s)
    erg = {"neu": 0, "bekannt": 0, "uebersprungen": 0}
    s.ugl_letzter_abruf = datetime.now()
    if meldung:
        s.ugl_abruf_status = meldung[:300]
        raise AbrufFehler(meldung)
    try:
        if s.ugl_verfahren == "datei":
            p = Path(s.ugl_pfad_ausgang)
            if not p.is_dir():
                raise AbrufFehler(f"Der Ordner {p} wurde nicht gefunden.")
            quelle = [(f.name, f) for f in sorted(p.iterdir()) if f.is_file()]
            holen = _datei_lesen
            verb = None
        else:
            verb = _FtpVerbindung(s)
            quelle = [(n, n) for n in verb.namen()]
            holen = lambda n, ref: verb.holen(n)
        try:
            for name, ref in quelle[:MAX_DATEIEN]:
                if not NAME.match(name):
                    erg["uebersprungen"] += 1
                    continue
                try:
                    daten = holen(name, ref)
                except AbrufFehler:
                    erg["uebersprungen"] += 1
                    continue
                if _speichern(session, s, name, daten):
                    erg["neu"] += 1
                else:
                    erg["bekannt"] += 1
            if len(quelle) > MAX_DATEIEN:
                erg["uebersprungen"] += len(quelle) - MAX_DATEIEN
        finally:
            if verb is not None:
                verb.schliessen()
    except AbrufFehler as e:
        s.ugl_abruf_status = str(e)[:300]
        raise
    except Exception as e:
        text = _fehler_text(e, s)
        s.ugl_abruf_status = text[:300]
        raise AbrufFehler(text)
    s.ugl_abruf_status = f"{erg['neu']} neu, {erg['bekannt']} schon bekannt" + (f", {erg['uebersprungen']} übersprungen" if erg["uebersprungen"] else "")
    return erg


def inhalt(f):
    """Bytes einer abgerufenen Datei (nur innerhalb von einkauf-data)."""
    p = (config.DATA_DIR / f.pfad).resolve()
    if config.DATA_DIR.resolve() not in p.parents:
        raise AbrufFehler("Ungültiger Dateipfad.")
    return p.read_bytes()

import csv
import io
import re
from datetime import datetime
import secrets
import time
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

from flask import (Blueprint, Response, abort, current_app, flash, g, redirect,
                   render_template, request, session, url_for)
from sqlalchemy import extract, func, or_
from sqlalchemy.orm import joinedload, selectinload
from werkzeug.security import check_password_hash, generate_password_hash

import json
import zipfile

from . import config, datanorm, db, einstellungen, formate, ids, lexoffice, lieferantendateien, nummern, security, sperre, ugl, zugferd
from .models import (Article, AuditLog, Contact, ContactPerson, Delivery, DeliveryItem, EditLock,
                     LexArticleRule, LexDocument, LexDocumentItem, Order, OrderItem, Project,
                     Supplier, SupplierFile, SupplierInvoice, User)
from .security import admin_required, edit_required, login_required

main = Blueprint("main", __name__)
setup = Blueprint("setup", __name__, url_prefix="/setup")

THEMEN = {"hell": "Hell", "dunkel": "Dunkel", "auto": "Wie das Gerät (automatisch)"}
ROLLEN = {"admin": "Admin", "einkaeufer": "Einkäufer", "leser": "Nur lesen"}
STATUS = {"planung": "Planung", "aktiv": "Aktiv", "abgeschlossen": "Abgeschlossen"}
BEST_STATUS = {
    "neu": "Neu", "bestellt": "Bestellt", "teilgeliefert": "Teillieferung",
    "komplett": "Komplett geliefert", "abgeschlossen": "Abgeschlossen (bezahlt)",
}
BEST_KURZ = {"neu": "Neu", "bestellt": "Bestellt", "teilgeliefert": "Teillieferung",
             "komplett": "Komplett", "abgeschlossen": "Abgeschlossen"}
BUDGET_MODI = {
    "manuell": "Manuell (festes Materialbudget)",
    "warensumme": "Aus verknüpften Angeboten (Warensumme)",
    "faktor": "Aus verknüpften Angeboten (Warensumme × Faktor)",
}
KOSTENARTEN = {
    "": "Unklar (bitte wählen)",
    "material": "Material (100 %)",
    "pauschale": "Pauschale (gemischt %)",
    "fremdleistung": "Fremdleistung (0 %)",
    "arbeit": "Arbeit (0 %)",
}
BELEG_TYPEN = {
    "angebot": "Angebot",
    "auftrag": "Auftrag / AB",
    "rechnung": "Ausgangsrechnung",
    "eingangsrechnung": "Eingangsrechnung",
}
BELEG_STATUS = {
    "draft": "Entwurf", "open": "Offen", "accepted": "Angenommen", "rejected": "Abgelehnt",
    "paid": "Bezahlt", "paidoff": "Bezahlt", "overdue": "Überfällig", "voided": "Storniert",
}
MONATE = ["", "Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August",
          "September", "Oktober", "November", "Dezember"]
DATEI_STATUS = {"neu": "Neu", "verarbeitet": "Verarbeitet", "ignoriert": "Ignoriert", "fehler": "Nicht lesbar"}


@main.app_context_processor
def _baum():
    """Daten für den Navigationsbaum links (Anzahl je Status, Jahr und Monat)."""
    basis = {"BEST_STATUS": BEST_STATUS, "BEST_KURZ": BEST_KURZ, "MONATE": MONATE, "STATUS_P": STATUS}
    if not getattr(g, "user", None) or g.get("db") is None:
        return basis
    best = {k: {"n": 0, "jahre": {}} for k in BEST_STATUS}
    for st, datum in g.db.query(Order.status, Order.bestelldatum).all():
        if st not in best:
            continue
        b = best[st]
        b["n"] += 1
        j = b["jahre"].setdefault(datum.year, {"n": 0, "monate": {}})
        j["n"] += 1
        j["monate"][datum.month] = j["monate"].get(datum.month, 0) + 1
    for b in best.values():
        b["jahre"] = [(jahr, j["n"], sorted(j["monate"].items(), reverse=True))
                      for jahr, j in sorted(b["jahre"].items(), reverse=True)]
    proj = g.db.query(Project.id, Project.nummer, Project.name, Project.status).order_by(Project.nummer).all()
    kon = g.db.query(Contact.ist_kunde, Contact.ist_lieferant).filter(Contact.archiviert.is_(False)).all()
    kontakt_anz = {"alle": len(kon), "kunden": sum(1 for k in kon if k[0]), "lieferanten": sum(1 for k in kon if k[1])}
    dateien_neu = g.db.query(SupplierFile).filter(SupplierFile.status == "neu").count()
    rueckstand_anz = sum(
        1 for i in g.db.query(OrderItem).join(Order).options(selectinload(OrderItem.delivery_items))
        .filter(Order.status.in_(("bestellt", "teilgeliefert")), OrderItem.storniert.is_(False)).all()
        if i.rest > 0
    )
    return {**basis, "baum_best": best, "baum_proj": proj, "kontakt_anz": kontakt_anz,
            "dateien_neu": dateien_neu, "rueckstand_anz": rueckstand_anz}


def protokoll(aktion, obj_typ, obj_id=None, obj_name=None, details=None):
    """Schreibt einen Eintrag ins Änderungsprotokoll (wird mit dem nächsten commit gespeichert)."""
    u = getattr(g, "user", None)
    g.db.add(AuditLog(
        user_id=u.id if u else None,
        username=u.username if u else "system",
        aktion=aktion[:40],
        obj_typ=obj_typ[:30],
        obj_id=obj_id,
        obj_name=(str(obj_name)[:200] if obj_name else None),
        details=(str(details)[:500] if details else None),
    ))


# ---------------------------------------------------------------- Helfer
def dec(value, default=None):
    s = (value or "").strip().replace(" ", "")
    if not s:
        return default
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    try:
        return Decimal(s)
    except InvalidOperation:
        return default


def parse_date(value, default=None):
    try:
        return date.fromisoformat((value or "").strip())
    except ValueError:
        return default


def text(name):
    return (request.form.get(name) or "").strip() or None


def safe_next(target):
    return target if target and target.startswith("/") and not target.startswith("//") else url_for("main.dashboard")


def offene_positionen(projekt_id=None, lieferant_id=None, suche=None):
    q = (
        g.db.query(OrderItem)
        .join(OrderItem.order)
        .options(
            selectinload(OrderItem.delivery_items),
            joinedload(OrderItem.order).joinedload(Order.supplier),
            joinedload(OrderItem.project),
        )
        .filter(OrderItem.storniert.is_(False), Order.status.in_(("bestellt", "teilgeliefert")))
    )
    if projekt_id == 0:
        q = q.filter(OrderItem.project_id.is_(None))
    elif projekt_id:
        q = q.filter(OrderItem.project_id == projekt_id)
    if lieferant_id:
        q = q.filter(Order.supplier_id == lieferant_id)
    if suche:
        like = f"%{suche}%"
        q = q.filter(or_(OrderItem.bezeichnung.like(like), OrderItem.artikelnr.like(like)))
    return [i for i in q.all() if i.rest > 0]


def sortieren(items, modus):
    def datum(i):
        return (i.erw_lieferdatum is None, i.erw_lieferdatum or date.max)

    def projekt(i):
        return (i.project.nummer if i.project else "~")

    def lieferant(i):
        return i.order.supplier.name.lower()

    if modus == "lieferant":
        return sorted(items, key=lambda i: (lieferant(i),) + datum(i))
    if modus == "datum":
        return sorted(items, key=datum)
    return sorted(items, key=lambda i: (projekt(i),) + datum(i))


def gruppieren(items, modus):
    gruppen = {}
    for i in items:
        if modus == "lieferant":
            key = i.order.supplier.name
        elif modus == "datum":
            key = _datum_key(i.erw_lieferdatum)
        else:
            key = f"{i.project.nummer} · {i.project.name}" if i.project else "Ohne Projekt"
        gruppen.setdefault(key, []).append(i)
    return gruppen


def _datum_key(d):
    return d.strftime("%d.%m.%Y") if d else "Kein Termin"


def aktive_projekte(extra_id=None):
    q = g.db.query(Project).filter(or_(Project.status != "abgeschlossen", Project.id == extra_id))
    return q.order_by(Project.nummer).all()


def letzter_admin(user):
    if user.role != "admin" or not user.active:
        return False
    return g.db.query(User).filter(User.role == "admin", User.active.is_(True), User.id != user.id).count() == 0


# ------------------------------------------------------- Einrichtungsassistent
@setup.route("/", methods=["GET", "POST"])
def db_step():
    form = {"type": "mariadb", "host": "", "port": "3306", "name": "einkauf", "user": "", "password": ""}
    fehler = None
    if request.method == "POST":
        for k in ("type", "host", "port", "name", "user"):
            form[k] = (request.form.get(k) or "").strip()
        form["password"] = request.form.get("password") or ""
        try:
            if form["type"] == "mariadb":
                if not (form["host"] and form["name"] and form["user"]):
                    raise ValueError("Bitte Host, Datenbankname und Benutzer angeben.")
                int(form["port"])
            db.test_connection(form)
            db.init_db(current_app, form)
            cfg = current_app.extensions["cfg"]
            cfg["db"] = form
            config.save(cfg)
            with current_app.extensions["SessionLocal"]() as s:
                if s.query(User).count() > 0:
                    cfg["setup_done"] = True
                    config.save(cfg)
                    flash("Vorhandene Installation gefunden. Bitte anmelden.", "ok")
                    return redirect(url_for("main.login"))
            return redirect(url_for("setup.admin_step"))
        except Exception as e:
            fehler = f"Verbindung fehlgeschlagen: {e}"
    return render_template("setup_db.html", form=form, fehler=fehler)


@setup.route("/admin", methods=["GET", "POST"])
def admin_step():
    maker = current_app.extensions.get("SessionLocal")
    if maker is None:
        return redirect(url_for("setup.db_step"))
    fehler = None
    firma = ""
    name = ""
    if request.method == "POST":
        name = (request.form.get("username") or "").strip()
        firma = (request.form.get("firma") or "").strip()
        pw, pw2 = request.form.get("password", ""), request.form.get("password2", "")
        if not name:
            fehler = "Bitte einen Benutzernamen angeben."
        elif len(pw) < 8:
            fehler = "Das Passwort braucht mindestens 8 Zeichen."
        elif pw != pw2:
            fehler = "Die beiden Passwörter stimmen nicht überein."
        else:
            with maker() as s:
                if s.query(User).count() > 0:
                    return redirect(url_for("setup.db_step"))
                u = User(username=name, password_hash=generate_password_hash(pw), role="admin", active=True)
                s.add(u)
                s.commit()
                uid = u.id
            cfg = current_app.extensions["cfg"]
            cfg["firma"] = firma
            cfg["setup_done"] = True
            config.save(cfg)
            session.clear()
            session["uid"] = uid
            flash("Einrichtung abgeschlossen. Du bist als Admin angemeldet.", "ok")
            return redirect(url_for("main.dashboard"))
    return render_template("setup_admin.html", fehler=fehler, firma=firma, name=name)


# --------------------------------------------------------------- Anmeldung
@main.route("/login", methods=["GET", "POST"])
def login():
    if g.user:
        return redirect(url_for("main.dashboard"))
    fehler = None
    if request.method == "POST":
        ip = request.remote_addr or "?"
        if security.login_blocked(ip):
            fehler = "Zu viele Fehlversuche. Bitte in ein paar Minuten erneut versuchen."
        else:
            name = (request.form.get("username") or "").strip().lower()
            u = g.db.query(User).filter(func.lower(User.username) == name).first()
            if u and u.active and check_password_hash(u.password_hash, request.form.get("password", "")):
                session.clear()
                session["uid"] = u.id
                return redirect(safe_next(request.args.get("next")))
            security.login_failed(ip)
            fehler = "Benutzername oder Passwort stimmt nicht."
    return render_template("login.html", fehler=fehler)


@main.route("/logout", methods=["POST"])
def logout():
    if getattr(g, "user", None) and g.get("db") is not None:
        sperre.freigeben_nutzer(g.db, g.user.id)
        g.db.commit()
    session.clear()
    return redirect(url_for("main.login"))


@main.route("/konto", methods=["GET", "POST"])
@login_required
def konto():
    fehler = None
    if request.method == "POST" and request.form.get("aktion") == "darstellung":
        thema = request.form.get("theme")
        g.user.theme = thema if thema in THEMEN else "hell"
        g.db.merge(g.user)
        g.db.commit()
        flash("Darstellung gespeichert.", "ok")
        return redirect(url_for("main.konto"))
    if request.method == "POST":
        alt, neu, neu2 = request.form.get("alt", ""), request.form.get("neu", ""), request.form.get("neu2", "")
        if not check_password_hash(g.user.password_hash, alt):
            fehler = "Das aktuelle Passwort stimmt nicht."
        elif len(neu) < 8:
            fehler = "Das neue Passwort braucht mindestens 8 Zeichen."
        elif neu != neu2:
            fehler = "Die neuen Passwörter stimmen nicht überein."
        else:
            g.user.password_hash = generate_password_hash(neu)
            g.db.merge(g.user)
            g.db.commit()
            flash("Passwort geändert.", "ok")
            return redirect(url_for("main.konto"))
    return render_template("konto.html", fehler=fehler, themen=THEMEN)


# --------------------------------------------------------------- Dashboard
@main.route("/")
@login_required
def dashboard():
    offen = sortieren(offene_positionen(), "datum")
    heute = date.today()
    ueberfaellig = [i for i in offen if i.faellig == "ueberfaellig"]
    woche = [i for i in offen if i.erw_lieferdatum and heute <= i.erw_lieferdatum <= heute + timedelta(days=7)]
    projekte = g.db.query(Project).filter(Project.status == "aktiv").count()
    neu = g.db.query(Order).filter(Order.status == "neu").count()
    sperre.bereinigen(g.db)
    dateien_neu = g.db.query(SupplierFile).filter(SupplierFile.status == "neu").count()
    unklar_lex = sum(1 for i in g.db.query(LexDocumentItem).filter(LexDocumentItem.kostenart.is_(None)).all() if i.ist_unklar)
    sperren_aktiv = g.db.query(EditLock).count()
    rechnungen_offen = g.db.query(SupplierInvoice).filter(SupplierInvoice.status != "geprueft").count()
    return render_template(
        "dashboard.html", offen=offen, ueberfaellig=ueberfaellig, woche=woche, projekte=projekte, neu=neu,
        hinweise={"dateien_neu": dateien_neu, "unklar_lex": unklar_lex, "sperren_aktiv": sperren_aktiv,
                  "rechnungen_offen": rechnungen_offen},
    )


# ---------------------------------------------------------------- Rückstand
@main.route("/rueckstand")
@login_required
def rueckstand():
    projekt_id = request.args.get("projekt", type=int)
    lieferant_id = request.args.get("lieferant", type=int)
    suche = (request.args.get("suche") or "").strip()
    modus = request.args.get("gruppe", "projekt")
    if modus not in ("projekt", "lieferant", "datum"):
        modus = "projekt"
    items = sortieren(offene_positionen(projekt_id, lieferant_id, suche or None), modus)

    if request.args.get("csv"):
        out = io.StringIO()
        w = csv.writer(out, delimiter=";")
        w.writerow(["Projekt", "Lieferant", "Artikelnr", "Bezeichnung", "Bestellt", "Geliefert", "Rest", "Einheit",
                    "Bestellt am", "Voraussichtlich", "Bestellnr", "Kommission", "Hinweis"])
        for i in items:
            w.writerow([
                i.project.nummer if i.project else "", i.order.supplier.name, i.artikelnr or "", i.bezeichnung,
                str(i.menge).replace(".", ","), str(i.geliefert).replace(".", ","), str(i.rest).replace(".", ","),
                i.einheit or "", i.order.bestelldatum.strftime("%d.%m.%Y"),
                i.erw_lieferdatum.strftime("%d.%m.%Y") if i.erw_lieferdatum else "", i.order.bestellnr or "",
                i.kommission or "", i.hinweis or "",
            ])
        return Response(
            "\ufeff" + out.getvalue(), mimetype="text/csv",
            headers={"Content-Disposition": f"attachment; filename=rueckstand-{date.today().isoformat()}.csv"},
        )

    return render_template(
        "rueckstand.html",
        gruppen=gruppieren(items, modus), anzahl=len(items), modus=modus,
        projekt_id=projekt_id, lieferant_id=lieferant_id, suche=suche,
        projekte=g.db.query(Project).order_by(Project.nummer).all(),
        lieferanten=g.db.query(Supplier).order_by(Supplier.name).all(),
    )


# ---------------------------------------------------------------- Projekte
@main.route("/projekte")
@login_required
def projekte():
    status = request.args.get("status", "laufend")
    suche = (request.args.get("q") or "").strip()
    sel = request.args.get("p", type=int)
    tab = request.args.get("tab", "bestellungen")
    if tab not in ("uebersicht", "bestellungen", "material", "lexoffice"):
        tab = "bestellungen"
    q = g.db.query(Project).options(
        selectinload(Project.items).selectinload(OrderItem.delivery_items),
        selectinload(Project.items).joinedload(OrderItem.order),
        selectinload(Project.lex_documents).selectinload(LexDocument.items))
    if status in STATUS:
        q = q.filter(Project.status == status)
    elif status != "alle":
        q = q.filter(Project.status != "abgeschlossen")
    if suche:
        like = f"%{suche}%"
        q = q.filter(or_(Project.nummer.like(like), Project.name.like(like), Project.kunde.like(like)))
    liste = q.order_by(Project.nummer).all()

    p, gruppen, items, belege_frei = None, {}, [], []
    if sel:
        p = (g.db.query(Project).options(
            selectinload(Project.items).selectinload(OrderItem.delivery_items),
            selectinload(Project.items).joinedload(OrderItem.order).joinedload(Order.supplier),
            selectinload(Project.lex_documents).selectinload(LexDocument.items),
        ).populate_existing().filter(Project.id == sel).first())
        if p:
            items = sorted(p.items, key=lambda i: (i.erw_lieferdatum is None, i.erw_lieferdatum or date.max, i.id))
            gruppen = {k: [] for k in BEST_STATUS}
            je_order = {}
            for i in p.items:
                if not i.storniert:
                    je_order.setdefault(i.order_id, {"o": i.order, "pos": []})["pos"].append(i)
            for e in je_order.values():
                e["summe"] = sum((i.menge * i.preis for i in e["pos"] if i.preis is not None), Decimal(0))
                e["offen"] = sum(1 for i in e["pos"] if i.rest > 0)
                gruppen[e["o"].status].append(e)
            for lst in gruppen.values():
                lst.sort(key=lambda e: (e["o"].bestelldatum, e["o"].id), reverse=True)
            belege_frei = (g.db.query(LexDocument).filter(LexDocument.project_id.is_(None), LexDocument.archiviert.is_(False))
                           .order_by(LexDocument.datum.desc(), LexDocument.id.desc()).all())
            if p.contact_id:
                belege_frei.sort(key=lambda d: (d.contact_id != p.contact_id, -(d.datum.toordinal() if d.datum else 0), -d.id))
    return render_template("projekte.html", projekte=liste, status=status, suche=suche, p=p, tab=tab,
                           gruppen=gruppen, items=items, belege_frei=belege_frei,
                           STATUS=STATUS, BELEG_TYPEN=BELEG_TYPEN, BELEG_STATUS=BELEG_STATUS, BUDGET_MODI=BUDGET_MODI)


def projekt_summen(p):
    alle = [i for i in p.items if not i.storniert]
    aktiv = [i for i in alle if i.order.status != "neu"]
    entwurf = len(alle) - len(aktiv)
    bestellt = sum((i.menge * i.preis for i in aktiv if i.preis is not None), Decimal(0))
    geliefert = sum((min(i.geliefert, i.menge) * i.preis for i in aktiv if i.preis is not None), Decimal(0))
    ohne_preis = sum(1 for i in aktiv if i.preis is None)
    offen = sum(1 for i in aktiv if i.rest > 0)

    angebote = [d for d in p.lex_documents if d.typ == "angebot" and not d.archiviert and d.status != "voided"]
    rechnungen = [d for d in p.lex_documents if d.typ == "rechnung" and not d.archiviert and d.status != "voided"]
    warensumme = sum((d.materialwert for d in angebote), Decimal("0.00"))
    unklar_pos = sum(d.unklar_anzahl for d in angebote)
    rechnungen_summe = sum((d.netto or Decimal("0.00") for d in rechnungen), Decimal("0.00"))
    modus = p.budget_modus or "manuell"
    faktor = p.budget_faktor if p.budget_faktor is not None else Decimal("1.000")

    if modus == "warensumme":
        budget = warensumme if angebote else None
    elif modus == "faktor":
        budget = (warensumme * faktor).quantize(Decimal("0.01")) if angebote else None
    else:
        budget = p.materialbudget

    prozent = None
    if budget and budget > 0:
        prozent = int(bestellt / budget * 100)
    return {
        "bestellt": bestellt, "geliefert": geliefert, "ohne_preis": ohne_preis, "offen": offen, "entwurf": entwurf,
        "prozent": prozent, "rest": (budget - bestellt) if budget is not None else None,
        "budget": budget, "warensumme": warensumme, "unklar_pos": unklar_pos,
        "angebote_n": len(angebote), "rechnungen_summe": rechnungen_summe, "modus": modus,
    }


@main.app_template_global()
def summen(p):
    return projekt_summen(p)


def _kunde_aufloesen(name):
    """Findet zum eingetippten Kundennamen den passenden Kontakt (ohne Groß-/Kleinschreibung)."""
    if not name:
        return None
    kontakte = g.db.query(Contact).filter(Contact.archiviert.is_(False)).order_by(Contact.ist_kunde.desc(), Contact.id).all()
    for c in kontakte:
        if c.name and c.name.casefold() == name.casefold():
            return c
    return None


def _kunden_liste():
    return sorted(g.db.query(Contact).filter(Contact.archiviert.is_(False), Contact.ist_kunde.is_(True)).all(),
                  key=lambda c: c.name.casefold())


def _projekt_nummer_vorhanden(nr):
    return g.db.query(Project.id).filter(Project.nummer == nr).first() is not None


def _bestell_nummer_vorhanden(nr):
    return g.db.query(Order.id).filter(Order.bestellnr == nr).first() is not None


def _projekt_speichern(p):
    nummer, name = text("nummer"), text("name")
    if not nummer or not name:
        return "Nummer und Name sind Pflichtfelder."
    gleiche = g.db.query(Project).filter(Project.nummer == nummer, Project.id != (p.id or 0)).first()
    if gleiche:
        return f"Die Projektnummer {nummer} gibt es schon."
    kunde = text("kunde")
    treffer = _kunde_aufloesen(kunde)
    p.nummer, p.name, p.notiz = nummer, name, text("notiz")
    p.contact_id = treffer.id if treffer else None
    p.kunde = treffer.name if treffer else kunde
    p.status = request.form.get("status") if request.form.get("status") in STATUS else "aktiv"
    p.materialbudget = dec(request.form.get("materialbudget"))
    modus = request.form.get("budget_modus")
    p.budget_modus = modus if modus in BUDGET_MODI else "manuell"
    faktor = dec(request.form.get("budget_faktor"))
    if faktor is not None and faktor > 0:
        p.budget_faktor = faktor
    elif p.budget_faktor is None:
        p.budget_faktor = Decimal("1.000")
    return None


@main.route("/projekte/neu", methods=["GET", "POST"])
@edit_required
def projekt_neu():
    p = Project(status="aktiv", budget_modus="manuell", budget_faktor=Decimal("1.000"))
    fehler = None
    angebote = (g.db.query(LexDocument).options(joinedload(LexDocument.project))
                .filter(LexDocument.typ == "angebot", LexDocument.archiviert.is_(False))
                .order_by(LexDocument.datum.desc(), LexDocument.id.desc())
                .all())
    angebote.sort(key=lambda a: (a.project_id is not None, -(a.datum.toordinal() if a.datum else 0)))
    v_angebot_id = request.values.get("lex_angebot_id", type=int) or request.args.get("angebot_id", type=int) or request.args.get("angebot", type=int)
    gewaehltes_angebot = g.db.get(LexDocument, v_angebot_id) if v_angebot_id else None

    if request.method == "POST":
        fehler = _projekt_speichern(p)
        if not fehler:
            g.db.add(p)
            nummern.verbrauchen(g.db, "projekt", p.nummer)
            g.db.flush()
            protokoll("angelegt", "projekt", p.id, f"{p.nummer} · {p.name}")
            aid = request.form.get("lex_angebot_id", type=int)
            if aid:
                doc = g.db.get(LexDocument, aid)
                if doc and doc.typ == "angebot":
                    doc.project_id = p.id
                    protokoll("zugeordnet", "lex_beleg", doc.id, doc.nummer, details=f"Projekt {p.nummer}")
            g.db.commit()
            flash("Projekt angelegt.", "ok")
            return redirect(url_for("main.projekte", p=p.id, status="alle"))
    else:
        p.nummer = nummern.vorschlag(g.db, "projekt", _projekt_nummer_vorhanden)
        if gewaehltes_angebot:
            if gewaehltes_angebot.titel:
                p.name = gewaehltes_angebot.titel
            elif gewaehltes_angebot.nummer:
                p.name = gewaehltes_angebot.nummer
            if gewaehltes_angebot.kunde_name:
                p.kunde = gewaehltes_angebot.kunde_name
                treffer = _kunde_aufloesen(gewaehltes_angebot.kunde_name)
                p.contact_id = treffer.id if treffer else gewaehltes_angebot.contact_id
            p.budget_modus = "warensumme"
        g.db.commit()
    return render_template("projekt_form.html", p=p, fehler=fehler, status=STATUS, neu=True,
                           kunden=_kunden_liste(), budget_modi=BUDGET_MODI,
                           angebote=angebote, gewaehltes_angebot=gewaehltes_angebot,
                           lex_aktiv=einstellungen.an(g.db, "lex_aktiv"))


@main.route("/projekte/<int:pid>")
@login_required
def projekt_detail(pid):
    return redirect(url_for("main.projekte", p=pid, status="alle"))


@main.route("/projekte/<int:pid>/bearbeiten", methods=["GET", "POST"])
@edit_required
def projekt_bearbeiten(pid):
    p = g.db.get(Project, pid) or abort(404)
    ok, lock = sperre.holen(g.db, "projekt", pid, g.user)
    if not ok:
        flash(sperre.meldung("projekt", lock), "fehler")
        return redirect(url_for("main.projekte", p=p.id, status="alle"))
    g.db.commit()
    fehler = None
    angebote = (g.db.query(LexDocument).options(joinedload(LexDocument.project))
                .filter(LexDocument.typ == "angebot", LexDocument.archiviert.is_(False))
                .filter(or_(LexDocument.project_id.is_(None), LexDocument.project_id == pid))
                .order_by(LexDocument.datum.desc(), LexDocument.id.desc())
                .all())
    angebote.sort(key=lambda a: (a.project_id != pid, -(a.datum.toordinal() if a.datum else 0)))
    gewaehltes_angebot = next((a for a in p.lex_documents if a.typ == "angebot"), None)

    if request.method == "POST":
        form_ver = request.form.get("version", type=int)
        if form_ver is not None and form_ver != (p.version or 1):
            fehler = "Das Projekt wurde inzwischen von einem anderen Benutzer geändert. Bitte neu öffnen."
        else:
            fehler = _projekt_speichern(p)
            if not fehler:
                p.version = (p.version or 1) + 1
                sperre.freigeben(g.db, "projekt", pid, g.user)
                protokoll("geaendert", "projekt", p.id, f"{p.nummer} · {p.name}")
                aid = request.form.get("lex_angebot_id", type=int)
                if aid:
                    doc = g.db.get(LexDocument, aid)
                    if doc and doc.typ == "angebot" and doc.project_id != p.id:
                        doc.project_id = p.id
                        protokoll("zugeordnet", "lex_beleg", doc.id, doc.nummer, details=f"Projekt {p.nummer}")
                g.db.commit()
                flash("Projekt gespeichert.", "ok")
                return redirect(url_for("main.projekte", p=p.id, status="alle"))
    return render_template("projekt_form.html", p=p, fehler=fehler, status=STATUS, neu=False,
                           kunden=_kunden_liste(), budget_modi=BUDGET_MODI,
                           angebote=angebote, gewaehltes_angebot=gewaehltes_angebot,
                           lex_aktiv=einstellungen.an(g.db, "lex_aktiv"))


@main.route("/projekte/<int:pid>/beleg-zuordnen", methods=["POST"])
@edit_required
def projekt_beleg_zuordnen(pid):
    p = g.db.get(Project, pid) or abort(404)
    did = request.form.get("document_id", type=int)
    aktion = request.form.get("aktion", "zuordnen")
    doc = g.db.get(LexDocument, did) if did else None
    if doc:
        if aktion == "loesen":
            if doc.project_id == p.id:
                doc.project_id = None
                flash(f"Beleg {doc.nummer or doc.id} vom Projekt gelöst.", "ok")
        else:
            doc.project_id = p.id
            flash(f"Beleg {doc.nummer or doc.id} zugeordnet.", "ok")
        g.db.commit()
    return redirect(url_for("main.projekte", p=p.id, tab="lexoffice", status="alle"))


@main.route("/projekte/<int:pid>/loeschen", methods=["POST"])
@edit_required
def projekt_loeschen(pid):
    p = g.db.get(Project, pid) or abort(404)
    ok, lock = sperre.holen(g.db, "projekt", pid, g.user)
    if not ok:
        flash(sperre.meldung("projekt", lock), "fehler")
        return redirect(url_for("main.projekte", p=pid, status="alle"))

    nr, name = p.nummer, p.name
    # Zugeordnete Bestellpositionen und Lexoffice-Belege freigeben
    for item in p.items:
        item.project_id = None
    for doc in p.lex_documents:
        doc.project_id = None

    sperre.freigeben(g.db, "projekt", pid, g.user)
    g.db.delete(p)
    protokoll("geloescht", "projekt", pid, f"{nr} · {name}")
    g.db.commit()
    flash(f"Projekt {nr} · {name} gelöscht.", "ok")
    return redirect(url_for("main.projekte"))


# ------------------------------------------------------------- Bestellungen
@main.route("/bestellungen")
@login_required
def bestellungen():
    status = request.args.get("status")
    jahr, monat = request.args.get("jahr", type=int), request.args.get("monat", type=int)
    q = g.db.query(Order).options(
        joinedload(Order.supplier),
        selectinload(Order.items).selectinload(OrderItem.delivery_items),
        selectinload(Order.items).joinedload(OrderItem.project),
    ).order_by(Order.bestelldatum.desc(), Order.id.desc())
    if status in BEST_STATUS:
        q = q.filter(Order.status == status)
    elif status != "alle":
        q = q.filter(Order.status != "abgeschlossen")
    if jahr:
        q = q.filter(extract("year", Order.bestelldatum) == jahr)
        if monat:
            q = q.filter(extract("month", Order.bestelldatum) == monat)
    return render_template("bestellungen.html", bestellungen=q.all(), status=status, jahr=jahr, monat=monat)


ZEILEN_FELDER = ["artikelnr", "bezeichnung", "menge", "einheit", "preis", "termin", "projekt", "kommission", "hinweis"]
LEERE_ZEILE = {"artikelnr": "", "bezeichnung": "", "menge": "", "einheit": "Stück", "preis": "", "termin": "",
               "projekt": "", "kommission": "", "hinweis": ""}


def _zeilen_lesen():
    listen = {f: request.form.getlist(f"row_{f}") for f in ZEILEN_FELDER}
    n = max((len(x) for x in listen.values()), default=0)
    return [{f: (listen[f][i].strip() if i < len(listen[f]) else "") for f in ZEILEN_FELDER} for i in range(n)]


def _zeile_leer(z):
    return not any(z[f] for f in ("artikelnr", "bezeichnung", "menge", "preis", "termin", "kommission"))


def _positionen_aus_formular():
    """Liest die Positionszeilen der Maske. Rückgabe: (Positionen, Fehlertext, Zeilen für die Wiederanzeige)."""
    zeilen = _zeilen_lesen()
    alle = request.form.get("projekt_alle", type=int)
    if alle and not g.db.get(Project, alle):
        alle = None
    positionen = []
    for nr, z in enumerate(zeilen, 1):
        if _zeile_leer(z):
            continue
        menge = dec(z["menge"])
        if not z["bezeichnung"] or menge is None or menge <= 0:
            return [], f"Zeile {nr}: Bezeichnung und eine Menge größer 0 sind Pflicht.", zeilen
        preis = dec(z["preis"])
        if z["preis"] and preis is None:
            return [], f"Zeile {nr}: Der Preis ist keine Zahl.", zeilen
        pid = alle
        if z["projekt"] == "-":
            pid = None
        elif z["projekt"].isdigit() and g.db.get(Project, int(z["projekt"])):
            pid = int(z["projekt"])
        positionen.append(OrderItem(
            artikelnr=z["artikelnr"][:100] or None, bezeichnung=z["bezeichnung"][:300], menge=menge,
            einheit=z["einheit"][:20] or "Stück", preis=preis, erw_lieferdatum=parse_date(z["termin"]),
            project_id=pid, kommission=z["kommission"][:300] or None, hinweis=z["hinweis"][:300] or None))
    return positionen, None, zeilen


@main.route("/bestellungen/neu", methods=["GET", "POST"])
@edit_required
def bestellung_neu():
    lieferanten = g.db.query(Supplier).filter(Supplier.active.is_(True)).order_by(Supplier.name).all()
    fehler, zeilen, ids_info = None, [], None
    ids_token = request.values.get("ids") or request.form.get("ids_token") or ""
    werte = {"supplier_id": "", "bestelldatum": date.today().isoformat(), "bestellnr": "", "ab_nr": "", "wunschtermin": "",
             "notiz": "", "schon_bestellt": False, "projekt_alle": ""}

    if request.method == "POST":
        werte = {k: (request.form.get(k) or "").strip() for k in ("supplier_id", "bestelldatum", "bestellnr", "ab_nr", "wunschtermin", "notiz", "projekt_alle")}
        werte["schon_bestellt"] = request.form.get("schon_bestellt") == "1"
        sid = request.form.get("supplier_id", type=int)
        nr = werte["bestellnr"] or None
        positionen, fehler_pos, zeilen = _positionen_aus_formular()
        if not g.db.get(Supplier, sid or 0):
            fehler = "Bitte einen Lieferanten wählen. Lieferanten legst du unter Einstellungen an."
        elif nr and _bestell_nummer_vorhanden(nr):
            fehler = f"Die Bestellnummer {nr} gibt es schon. Bitte eine andere eintragen."
        elif fehler_pos:
            fehler = fehler_pos
        else:
            o = Order(supplier_id=sid, bestelldatum=parse_date(werte["bestelldatum"], date.today()), bestellnr=nr,
                      ab_nr=werte["ab_nr"] or None, notiz=werte["notiz"] or None, created_by=g.user.id,
                      wunschtermin=parse_date(werte["wunschtermin"]))
            if werte["schon_bestellt"]:
                o.status, o.bestellt_am = "bestellt", o.bestelldatum
            o.items.extend(positionen)
            g.db.add(o)
            nummern.verbrauchen(g.db, "bestellung", nr)
            g.db.commit()
            if ids_token:
                _ids_verwerfen(ids_token)
            flash(f"Bestellung angelegt mit {len(positionen)} Positionen." if positionen else
                  "Bestellung angelegt. Positionen kannst du jetzt ergänzen.", "ok")
            return redirect(url_for("main.bestellung_detail", oid=o.id))
        ids_info = _ids_info(ids_token) if ids_token else None
    else:
        werte["bestellnr"] = nummern.vorschlag(g.db, "bestellung", _bestell_nummer_vorhanden)
        g.db.commit()
        if ids_token:
            vorbelegt = _ids_vorbelegung(ids_token)
            if vorbelegt:
                werte.update(vorbelegt["werte"])
                zeilen, ids_info = vorbelegt["zeilen"], vorbelegt["info"]
            else:
                ids_token = ""
    mind = max(6 - len(zeilen), 3)
    return render_template("bestellung_form.html", lieferanten=lieferanten, fehler=fehler, werte=werte,
                           zeilen=zeilen + [dict(LEERE_ZEILE) for _ in range(mind)], projekte=aktive_projekte(),
                           ids_token=ids_token, ids_info=ids_info)


def _bestellung(oid):
    o = (g.db.query(Order).options(
        joinedload(Order.supplier),
        selectinload(Order.items).selectinload(OrderItem.delivery_items),
        selectinload(Order.items).joinedload(OrderItem.project),
        selectinload(Order.deliveries).selectinload(Delivery.items).joinedload(DeliveryItem.item),
    ).populate_existing().filter(Order.id == oid).first())
    if not o:
        abort(404)
    return o


@main.route("/bestellungen/<int:oid>")
@login_required
def bestellung_detail(oid):
    o = _bestellung(oid)
    von = request.args.get("von", type=int)
    von_projekt = g.db.get(Project, von) if von else None

    # Abgerufene Lieferantendateien dieses Lieferanten laden
    abgerufene_dateien = (g.db.query(SupplierFile)
                          .filter(SupplierFile.supplier_id == o.supplier_id)
                          .filter(or_(SupplierFile.bestell_id.is_(None), SupplierFile.bestell_id == o.id))
                          .filter(SupplierFile.status.in_(("neu", "verarbeitet", "ignoriert")))
                          .order_by(SupplierFile.status == "neu", SupplierFile.abgerufen_am.desc(), SupplierFile.id.desc())
                          .all())
    abgerufene_dateien.sort(key=lambda f: (f.status != "neu", -(f.datei_datum.toordinal() if f.datei_datum else 0)))
    ftp_abrufbar = bool(o.supplier and o.supplier.active and not lieferantendateien.pruefen(o.supplier))

    return render_template("bestellung_detail.html", o=o, projekte=aktive_projekte(), von_projekt=von_projekt,
                           offene=[i for i in o.items if not i.storniert and i.rest > 0],
                           abgerufene_dateien=abgerufene_dateien,
                           ftp_abrufbar=ftp_abrufbar,
                           DATEI_STATUS=DATEI_STATUS)


@main.route("/bestellungen/<int:oid>/datei-zuordnen", methods=["POST"])
@edit_required
def bestellung_datei_zuordnen(oid):
    o = _bestellung(oid)
    fid = request.form.get("datei_id", type=int)
    if not fid:
        flash("Bitte einen abgerufenen Lieferschein auswählen.", "fehler")
        return redirect(url_for("main.bestellung_detail", oid=oid))
    f = g.db.get(SupplierFile, fid) or abort(404)
    if f.supplier_id != o.supplier_id:
        flash("Die Datei gehört zu einem anderen Lieferanten als diese Bestellung.", "fehler")
        return redirect(url_for("main.bestellung_detail", oid=oid))
    try:
        return _ugl_vorschau(o, lieferantendateien.inhalt(f), f.name, datei_id=f.id)
    except (ugl.UglFehler, lieferantendateien.AbrufFehler, OSError) as e:
        flash(f"Die Datei kann nicht gelesen werden: {e}", "fehler")
        return redirect(url_for("main.bestellung_detail", oid=oid))


def status_pruefen(oid):
    o = _bestellung(oid)
    o.status_aktualisieren()
    g.db.commit()


def _position_lesen(i):
    bez = text("bezeichnung")
    menge = dec(request.form.get("menge"))
    if not bez or menge is None or menge <= 0:
        return "Bezeichnung und eine Menge größer 0 sind Pflicht."
    i.bezeichnung, i.menge = bez, menge
    i.artikelnr, i.einheit = text("artikelnr"), text("einheit")
    i.kommission = text("kommission")
    i.preis = dec(request.form.get("preis"))
    i.erw_lieferdatum = parse_date(request.form.get("erw_lieferdatum"))
    pid = request.form.get("project_id", type=int)
    i.project_id = pid if pid and g.db.get(Project, pid) else None
    return None


@main.route("/bestellungen/<int:oid>/position", methods=["POST"])
@edit_required
def position_neu(oid):
    o = g.db.get(Order, oid) or abort(404)
    i = OrderItem(order_id=o.id)
    fehler = _position_lesen(i)
    if fehler:
        flash(fehler, "fehler")
    else:
        g.db.add(i)
        g.db.commit()
        status_pruefen(oid)
        flash("Position hinzugefügt.", "ok")
    return redirect(url_for("main.bestellung_detail", oid=oid) + "#positionen")


@main.route("/positionen/<int:iid>", methods=["GET", "POST"])
@edit_required
def position_bearbeiten(iid):
    i = g.db.get(OrderItem, iid) or abort(404)
    fehler = None
    if request.method == "POST":
        aktion = request.form.get("aktion")
        if aktion == "storno":
            i.storniert = not i.storniert
            g.db.commit()
            status_pruefen(i.order_id)
            return redirect(url_for("main.bestellung_detail", oid=i.order_id))
        if aktion == "loeschen":
            if i.delivery_items:
                fehler = "Es gibt schon Wareneingänge. Bitte stornieren statt löschen."
            else:
                oid = i.order_id
                g.db.delete(i)
                g.db.commit()
                status_pruefen(oid)
                flash("Position gelöscht.", "ok")
                return redirect(url_for("main.bestellung_detail", oid=oid))
        else:
            fehler = _position_lesen(i)
            if not fehler:
                g.db.commit()
                status_pruefen(i.order_id)
                flash("Position gespeichert.", "ok")
                return redirect(url_for("main.bestellung_detail", oid=i.order_id))
    return render_template("position_form.html", i=i, projekte=aktive_projekte(i.project_id), fehler=fehler)


@main.route("/positionen/<int:iid>/aufteilen", methods=["POST"])
@edit_required
def position_aufteilen(iid):
    i = g.db.get(OrderItem, iid) or abort(404)
    menge = dec(request.form.get("menge_neu"))
    pid = request.form.get("project_id", type=int)
    if menge is None or menge <= 0 or menge >= i.menge:
        flash("Die Menge für den neuen Teil muss größer 0 und kleiner als die Gesamtmenge sein.", "fehler")
        return redirect(url_for("main.position_bearbeiten", iid=iid))
    if i.geliefert > i.menge - menge:
        flash("Dafür ist schon zu viel geliefert. Der ursprüngliche Teil müsste mindestens die gelieferte Menge behalten.", "fehler")
        return redirect(url_for("main.position_bearbeiten", iid=iid))
    neu = OrderItem(
        order_id=i.order_id, project_id=pid if pid and g.db.get(Project, pid) else None,
        artikelnr=i.artikelnr, bezeichnung=i.bezeichnung, menge=menge, einheit=i.einheit, preis=i.preis,
        erw_lieferdatum=i.erw_lieferdatum, kommission=text("kommission_neu"), hinweis=i.hinweis)
    i.menge = i.menge - menge
    g.db.add(neu)
    g.db.commit()
    status_pruefen(i.order_id)
    flash(f"Position aufgeteilt: {_qty_text(menge)} gingen in eine neue Position.", "ok")
    return redirect(url_for("main.bestellung_detail", oid=i.order_id))


def _qty_text(v):
    return format(Decimal(v).normalize(), "f").replace(".", ",")


@main.route("/bestellungen/<int:oid>/status", methods=["POST"])
@edit_required
def bestellung_status(oid):
    o = _bestellung(oid)
    aktion = request.form.get("aktion")
    if aktion == "bestellt" and o.status == "neu":
        o.status, o.bestellt_am = "bestellt", date.today()
        o.status_aktualisieren()
        flash("Bestellung als bestellt markiert. Ihre Positionen erscheinen jetzt im Rückstand.", "ok")
    elif aktion == "neu" and o.status == "bestellt":
        o.status, o.bestellt_am = "neu", None
        flash("Bestellung wieder auf Neu gesetzt.", "ok")
    elif aktion == "abschliessen" and o.status == "komplett":
        o.status = "abgeschlossen"
        o.bezahlt_am = parse_date(request.form.get("bezahlt_am"), date.today())
        flash("Bestellung als bezahlt abgeschlossen.", "ok")
    elif aktion == "oeffnen" and o.status == "abgeschlossen":
        o.status, o.bezahlt_am = "bestellt", None
        o.status_aktualisieren()
        flash("Bestellung wieder geöffnet.", "ok")
    else:
        flash("Das ist bei dem aktuellen Status nicht möglich. Abschließen geht erst, wenn alles geliefert ist.", "fehler")
    g.db.commit()
    return redirect(url_for("main.bestellung_detail", oid=oid))


@main.route("/bestellungen/<int:oid>/loeschen", methods=["POST"])
@edit_required
def bestellung_loeschen(oid):
    o = g.db.get(Order, oid) or abort(404)
    ok, lock = sperre.holen(g.db, "bestellung", oid, g.user)
    if not ok:
        flash(sperre.meldung("bestellung", lock), "fehler")
        return redirect(url_for("main.bestellung_detail", oid=oid))

    nr = o.bestellnr or f"Nr. {o.id}"
    sup_name = o.supplier.name if o.supplier else "Lieferant"

    # Verknüpfte Rechnungen und Lieferantendateien lösen
    for inv in g.db.query(SupplierInvoice).filter(SupplierInvoice.order_id == o.id).all():
        inv.order_id = None
        inv.status = "offen"
    for sf in g.db.query(SupplierFile).filter(SupplierFile.bestell_id == o.id).all():
        sf.bestell_id = None

    # Zuerst Lieferungen & Lieferscheinpositionen löschen
    for d in list(o.deliveries):
        g.db.delete(d)
    g.db.flush()

    sperre.freigeben(g.db, "bestellung", oid, g.user)
    g.db.delete(o)
    protokoll("geloescht", "bestellung", oid, f"{nr} · {sup_name}")
    g.db.commit()
    flash(f"Bestellung {nr} ({sup_name}) gelöscht.", "ok")
    return redirect(url_for("main.bestellungen"))


@main.route("/bestellungen/<int:oid>/termin", methods=["POST"])
@edit_required
def termin_setzen(oid):
    o = _bestellung(oid)
    d = parse_date(request.form.get("termin"))
    if not d:
        flash("Bitte ein gültiges Datum wählen.", "fehler")
    else:
        n = 0
        for i in o.items:
            if not i.storniert and i.rest > 0:
                i.erw_lieferdatum = d
                n += 1
        g.db.commit()
        flash(f"Liefertermin {d.strftime('%d.%m.%Y')} für {n} offene Positionen gesetzt.", "ok")
    return redirect(url_for("main.bestellung_detail", oid=oid))


@main.route("/bestellungen/<int:oid>/wareneingang", methods=["POST"])
@edit_required
def wareneingang(oid):
    o = _bestellung(oid)
    d = Delivery(order_id=o.id, lieferschein_nr=text("lieferschein_nr"),
                 datum=parse_date(request.form.get("datum"), date.today()), notiz=text("notiz"), created_by=g.user.id)
    alles = request.form.get("alles") == "1"
    gebucht = 0
    for i in o.items:
        if i.storniert:
            continue
        menge = i.rest if alles else dec(request.form.get(f"menge_{i.id}"), Decimal(0))
        if menge and menge > 0 and (alles and i.rest > 0 or not alles):
            d.items.append(DeliveryItem(item=i, menge=menge))
            gebucht += 1
    if not gebucht:
        flash("Keine Menge eingetragen. Es wurde nichts gebucht.", "fehler")
    else:
        g.db.add(d)
        o.status_aktualisieren()
        g.db.commit()
        flash(f"Wareneingang für {gebucht} Positionen gebucht. Status: {BEST_STATUS[o.status]}.", "ok")
    return redirect(url_for("main.bestellung_detail", oid=oid))


# ------------------------------------------------------------ Einstellungen
@main.route("/einstellungen", endpoint="einstellungen")
@admin_required
def einstellungen_start():
    return redirect(url_for("main.lieferanten"))


@main.route("/einstellungen/lieferanten")
@admin_required
def lieferanten():
    return render_template("lieferanten.html", liste=g.db.query(Supplier).order_by(Supplier.name).all())


def _lieferant_speichern(s):
    name = text("name")
    if not name:
        return "Der Name ist ein Pflichtfeld."
    s.name, s.kundennr, s.ansprechpartner = name, text("kundennr"), text("ansprechpartner")
    s.telefon, s.email, s.notiz = text("telefon"), text("email"), text("notiz")
    s.active = request.form.get("active") == "1"
    s.ugl_verfahren = request.form.get("ugl_verfahren") or None
    s.ugl_server, s.ugl_port = text("ugl_server"), text("ugl_port")
    s.ugl_pfad_eingang, s.ugl_pfad_ausgang = text("ugl_pfad_eingang"), text("ugl_pfad_ausgang")
    s.ugl_pfad_zugferd = text("ugl_pfad_zugferd")
    s.ugl_format, s.ugl_benutzer = text("ugl_format"), text("ugl_benutzer")
    s.ugl_notiz = text("ugl_notiz")
    auto = request.form.get("ugl_auto_min", type=int) or 0
    s.ugl_auto_min = auto if auto in (15, 30, 60, 240) else None
    s.ugl_tls_pruefen = request.form.get("ugl_tls_pruefen", "1") != "0"
    url = text("ids_url")
    if url and not re.match(r"^https?://\S+$", url):
        return "Die IDS-Adresse muss mit http:// oder https:// beginnen."
    s.ids_url, s.ids_kndnr, s.ids_benutzer = url, text("ids_kndnr"), text("ids_benutzer")
    ver = request.form.get("ids_version")
    s.ids_version = ver if ver in ids.VERSIONEN or ver == "" else "2.5"
    s.ids_aufruf = "get" if request.form.get("ids_aufruf") == "get" else "post"
    s.ids_preis_modus = request.form.get("ids_preis_modus") if request.form.get("ids_preis_modus") in ("gesamt", "einzel") else "gesamt"
    if request.form.get("ids_passwort"):
        s.ids_passwort_enc = security.encrypt(request.form["ids_passwort"])
    if request.form.get("ugl_passwort"):
        s.ugl_passwort_enc = security.encrypt(request.form["ugl_passwort"])
    cid = request.form.get("contact_id", type=int)
    s.contact_id = cid if (cid and g.db.get(Contact, cid)) else None
    return None


def _lieferant_kontakte():
    return sorted(g.db.query(Contact).filter(Contact.archiviert.is_(False), Contact.ist_lieferant.is_(True)).all(),
                  key=lambda c: c.name.casefold())


@main.route("/einstellungen/lieferanten/neu", methods=["GET", "POST"])
@admin_required
def lieferant_neu():
    s = Supplier(active=True)
    fehler = None
    if request.method == "POST":
        fehler = _lieferant_speichern(s)
        if not fehler:
            g.db.add(s)
            g.db.commit()
            flash("Lieferant angelegt.", "ok")
            return redirect(url_for("main.lieferanten"))
    return render_template("lieferant_form.html", s=s, fehler=fehler, neu=True, kontakte=_lieferant_kontakte())


@main.route("/einstellungen/lieferanten/<int:sid>", methods=["GET", "POST"])
@admin_required
def lieferant_bearbeiten(sid):
    s = g.db.get(Supplier, sid) or abort(404)
    ok, lock = sperre.holen(g.db, "lieferant", sid, g.user)
    if not ok:
        flash(sperre.meldung("lieferant", lock), "fehler")
        return redirect(url_for("main.lieferanten"))
    g.db.commit()
    fehler = None
    if request.method == "POST":
        form_ver = request.form.get("version", type=int)
        if form_ver is not None and form_ver != (s.version or 1):
            fehler = "Der Lieferant wurde inzwischen von einem anderen Benutzer geändert. Bitte neu öffnen."
        else:
            fehler = _lieferant_speichern(s)
            if not fehler:
                s.version = (s.version or 1) + 1
                sperre.freigeben(g.db, "lieferant", sid, g.user)
                protokoll("geaendert", "lieferant", s.id, s.name)
                g.db.commit()
                flash("Lieferant gespeichert.", "ok")
                return redirect(url_for("main.lieferanten"))
    return render_template("lieferant_form.html", s=s, fehler=fehler, neu=False, kontakte=_lieferant_kontakte())


@main.route("/einstellungen/benutzer")
@admin_required
def benutzer():
    return render_template("benutzer.html", liste=g.db.query(User).order_by(User.username).all(), rollen=ROLLEN)


@main.route("/einstellungen/benutzer/neu", methods=["GET", "POST"])
@admin_required
def benutzer_neu():
    fehler = None
    u = User(role="einkaeufer", active=True)
    if request.method == "POST":
        name, pw = (request.form.get("username") or "").strip(), request.form.get("password", "")
        u.username, u.role = name, request.form.get("role") if request.form.get("role") in ROLLEN else "leser"
        if not name:
            fehler = "Bitte einen Benutzernamen angeben."
        elif g.db.query(User).filter(func.lower(User.username) == name.lower()).first():
            fehler = "Diesen Benutzernamen gibt es schon."
        elif len(pw) < 8:
            fehler = "Das Passwort braucht mindestens 8 Zeichen."
        else:
            u.password_hash = generate_password_hash(pw)
            g.db.add(u)
            g.db.commit()
            flash(f"Benutzer {name} angelegt.", "ok")
            return redirect(url_for("main.benutzer"))
    return render_template("benutzer_form.html", u=u, fehler=fehler, rollen=ROLLEN, neu=True)


@main.route("/einstellungen/benutzer/<int:uid>", methods=["GET", "POST"])
@admin_required
def benutzer_bearbeiten(uid):
    u = g.db.get(User, uid) or abort(404)
    fehler = None
    if request.method == "POST":
        rolle = request.form.get("role") if request.form.get("role") in ROLLEN else u.role
        aktiv = request.form.get("active") == "1"
        pw = request.form.get("password", "")
        if letzter_admin(u) and (rolle != "admin" or not aktiv):
            fehler = "Der letzte aktive Admin kann nicht herabgestuft oder deaktiviert werden."
        elif u.id == g.user.id and not aktiv:
            fehler = "Du kannst dich nicht selbst deaktivieren."
        elif pw and len(pw) < 8:
            fehler = "Das neue Passwort braucht mindestens 8 Zeichen."
        else:
            u.role, u.active = rolle, aktiv
            if pw:
                u.password_hash = generate_password_hash(pw)
            g.db.commit()
            flash("Benutzer gespeichert.", "ok")
            return redirect(url_for("main.benutzer"))
    return render_template("benutzer_form.html", u=u, fehler=fehler, rollen=ROLLEN, neu=False)


# ------------------------------------------------------------- UGL-Import
IMPORT_DIR = config.DATA_DIR / "import"
MAX_UGL = 1_000_000


def _import_pfad(oid, token):
    if not re.fullmatch(r"[0-9a-f]{32}", token or ""):
        abort(400)
    return IMPORT_DIR / f"{oid}-{token}.ugl"


def _import_aufraeumen():
    if IMPORT_DIR.exists():
        for f in IMPORT_DIR.glob("*.ugl"):
            if time.time() - f.stat().st_mtime > 86400:
                f.unlink(missing_ok=True)


def _ugl_vorschau(o, daten, dateiname, datei_id=None):
    """Liest eine UGL-Datei, gleicht sie mit der Bestellung ab und zeigt die Vorschau. UglFehler geht an den Aufrufer."""
    r = ugl.lesen(daten)
    zeilen, fehlend = ugl.abgleichen(r["positionen"], o.items)
    IMPORT_DIR.mkdir(parents=True, exist_ok=True)
    _import_aufraeumen()
    token = secrets.token_hex(16)
    _import_pfad(o.id, token).write_bytes(daten)
    bnr = r["kopf"].get("belegnr")
    duplikat_ls = None
    if bnr:
        duplikat_ls = (g.db.query(Delivery).join(Order)
                       .filter(Order.supplier_id == o.supplier_id, Delivery.lieferschein_nr == bnr).first())
    return render_template("ugl_vorschau.html", o=o, r=r, zeilen=zeilen, fehlend=fehlend, token=token,
                           dateiname=re.sub(r"[^\w.\- ]", "", dateiname)[:80], datei_id=datei_id,
                           duplikat_ls=duplikat_ls)


@main.route("/bestellungen/<int:oid>/ugl-export")
@login_required
def bestellung_ugl_export(oid):
    o = _bestellung(oid)
    daten = ugl.schreiben(o)
    nr = re.sub(r"[^\w.\-]", "_", o.bestellnr or str(o.id))
    return Response(daten, mimetype="text/plain; charset=cp1252",
                    headers={"Content-Disposition": f"attachment; filename=bestellung_{nr}.ugl"})


@main.route("/bestellungen/<int:oid>/ugl", methods=["POST"])
@edit_required
def ugl_hochladen(oid):
    o = _bestellung(oid)
    f = request.files.get("datei")
    if not f or not f.filename:
        flash("Bitte eine Datei auswählen.", "fehler")
        return redirect(url_for("main.bestellung_detail", oid=oid))
    daten = f.read(MAX_UGL + 1)
    if len(daten) > MAX_UGL:
        flash("Die Datei ist zu groß für eine Lieferantendatei.", "fehler")
        return redirect(url_for("main.bestellung_detail", oid=oid))
    try:
        return _ugl_vorschau(o, daten, f.filename)
    except ugl.UglFehler as e:
        flash(f"Datei nicht lesbar: {e}", "fehler")
        return redirect(url_for("main.bestellung_detail", oid=oid))


@main.route("/bestellungen/<int:oid>/ugl/uebernehmen", methods=["POST"])
@edit_required
def ugl_uebernehmen(oid):
    o = _bestellung(oid)
    pfad = _import_pfad(oid, request.form.get("token"))
    if not pfad.exists():
        flash("Die Vorschau ist abgelaufen. Bitte die Datei erneut hochladen.", "fehler")
        return redirect(url_for("main.bestellung_detail", oid=oid))
    r = ugl.lesen(pfad.read_bytes())
    zeilen, fehlend = ugl.abgleichen(r["positionen"], o.items)
    aktion = request.form.get("aktion")
    gewaehlt = set(request.form.getlist("pos"))
    vermerken = request.form.get("vermerken") == "1"
    dat = r["datei"].get("datum") or date.today()
    ds = dat.strftime("%d.%m.%Y")
    dateiname = (request.form.get("dateiname") or "")[:80]

    if aktion == "lieferschein":
        d = Delivery(order_id=o.id, lieferschein_nr=text("lieferschein_nr") or r["kopf"].get("belegnr"),
                     datum=parse_date(request.form.get("datum"), dat), notiz=f"UGL-Datei {dateiname}".strip(),
                     created_by=g.user.id)
        for z in zeilen:
            if str(z["p"]["pos"]) not in gewaehlt or not z["zuordnung"]:
                continue
            for item, menge in z["zuordnung"]:
                d.items.append(DeliveryItem(item=item, menge=menge))
            if z["rest_ueber"] > 0:
                d.items[-1].menge += z["rest_ueber"]
        if not d.items:
            flash("Es wurde nichts gebucht, weil keine Position ausgewählt oder zuordenbar war.", "fehler")
            return redirect(url_for("main.bestellung_detail", oid=oid))
        g.db.add(d)
        g.db.flush()
        for i in o.items:
            if not i.storniert and i.rest <= 0:
                i.hinweis = None
        if vermerken:
            for i in fehlend:
                i.hinweis = f"In Lieferdatei vom {ds} nicht dabei, beim Lieferanten in Rückstand"
            for z in zeilen:
                if z["art"] == "weniger":
                    for item, menge in z["zuordnung"]:
                        if item.rest > 0:
                            item.hinweis = f"Teillieferung vom {ds}, Rest beim Lieferanten in Rückstand"
        o.status_aktualisieren()
        flash(f"Wareneingang gebucht ({len(d.items)} Buchungen). Status: {BEST_STATUS[o.status]}.", "ok")
    elif aktion == "ab":
        for z in zeilen:
            for item, menge in z["zuordnung"]:
                if menge >= item.menge:
                    item.hinweis = f"Vom Lieferanten bestätigt ({ds})"
                else:
                    item.hinweis = f"Bestätigt: {_qty_text(menge)} von {_qty_text(item.menge)} ({ds})"
        if vermerken:
            for i in fehlend:
                i.hinweis = f"In Bestätigung vom {ds} nicht enthalten (nicht lieferbar oder Rückstand)"
        if not o.ab_nr and r["kopf"].get("belegnr"):
            o.ab_nr = r["kopf"]["belegnr"]
        flash("Bestätigung vermerkt. Es wurde nichts als geliefert gebucht.", "ok")
    else:
        abort(400)
    datei = g.db.get(SupplierFile, request.form.get("datei_id", type=int) or 0)
    if datei and datei.supplier_id == o.supplier_id:
        datei.status, datei.bestell_id, datei.aktion = "verarbeitet", o.id, aktion
        datei.verarbeitet_am = datetime.now()
    g.db.commit()
    pfad.unlink(missing_ok=True)
    return redirect(url_for("main.bestellung_detail", oid=oid))


# -------------------------------------------------------------- Nummernkreise
@main.route("/einstellungen/nummernkreise", methods=["GET", "POST"])
@admin_required
def nummernkreise():
    kreise = {k: nummern.holen(g.db, k) for k in nummern.STANDARD}
    fehler = None
    if request.method == "POST":
        neu = {}
        for k in kreise:
            muster = (request.form.get(f"{k}_muster") or "").strip()
            reset = request.form.get(f"{k}_reset") if request.form.get(f"{k}_reset") in nummern.RESET else "auto"
            na, sa = request.form.get(f"{k}_naechste", type=int), request.form.get(f"{k}_start", type=int)
            meldung = nummern.pruefen(muster)
            if meldung:
                fehler = f"{nummern.TITEL[k]}: {meldung}"
            elif na is None or na < 1 or sa is None or sa < 1:
                fehler = f"{nummern.TITEL[k]}: Nächste Nummer und Startwert müssen ganze Zahlen ab 1 sein."
            neu[k] = (muster, reset, na, sa)
        if fehler:                                # Eingaben behalten, damit nichts verloren geht
            kreise = {k: type("Eingabe", (), {"muster": m, "reset": rs, "naechste": na or 1, "start": sa or 1})
                      for k, (m, rs, na, sa) in neu.items()}
        else:
            for k, (muster, reset, na, sa) in neu.items():
                r = kreise[k]
                r.muster, r.reset, r.naechste, r.start = muster, reset, na, sa
                r.periode = nummern.periode(r)
            g.db.commit()
            flash("Nummernkreise gespeichert.", "ok")
            return redirect(url_for("main.nummernkreise"))
    return render_template("nummernkreise.html", kreise=kreise, fehler=fehler, titel=nummern.TITEL, reset=nummern.RESET,
                           bsp={k: nummern.formatieren(r.muster, r.naechste) for k, r in kreise.items()
                                if not nummern.pruefen(r.muster)})


# ----------------------------------------------------------------- Kontakte
KONTAKT_TEXT = [
    "firma", "steuernummer", "ust_idnr", "anrede", "vorname", "nachname", "kunde_nr", "lieferant_nr",
    "re_zusatz", "re_strasse", "re_plz", "re_ort", "re_land", "li_zusatz", "li_strasse", "li_plz", "li_ort", "li_land",
    "email_geschaeft", "email_buero", "email_privat", "email_sonstige",
    "tel_geschaeft", "tel_buero", "tel_mobil", "tel_privat", "tel_fax", "tel_sonstige",
    "leitweg_id", "lieferantennr_beim_kunden", "notiz",
]


def _kontakt_speichern(c):
    c.typ = "person" if request.form.get("typ") == "person" else "firma"
    for f in KONTAKT_TEXT:
        setattr(c, f, text(f))
    c.ist_kunde = request.form.get("ist_kunde") == "1"
    c.ist_lieferant = request.form.get("ist_lieferant") == "1"
    c.steuerfrei = request.form.get("steuerfrei") == "1"
    c.re_land = (c.re_land or "").upper() or None
    c.li_land = (c.li_land or "").upper() or None
    if c.typ == "firma" and not c.firma:
        return "Bei einer Firma ist der Firmenname Pflicht."
    if c.typ == "person" and not c.nachname:
        return "Bei einer Person ist der Nachname Pflicht."
    return None


def _lexoffice_sperre(c):
    if c.quelle == "lexoffice":
        flash("Dieser Kontakt kommt aus Lexoffice und wird von dort synchronisiert. Änderungen bitte in Lexoffice vornehmen.", "warn")
        return redirect(url_for("main.kontakt_detail", cid=c.id))
    return None


@main.route("/kontakte")
@login_required
def kontakte():
    rolle = request.args.get("rolle", "alle")
    suche = (request.args.get("q") or "").strip()
    archiv = request.args.get("archiv") == "1"
    q = g.db.query(Contact)
    if not archiv:
        q = q.filter(Contact.archiviert.is_(False))
    if rolle == "kunden":
        q = q.filter(Contact.ist_kunde.is_(True))
    elif rolle == "lieferanten":
        q = q.filter(Contact.ist_lieferant.is_(True))
    if suche:
        like = f"%{suche}%"
        q = q.filter(or_(*(getattr(Contact, f).like(like) for f in (
            "firma", "vorname", "nachname", "kunde_nr", "lieferant_nr", "re_ort", "li_ort", "email_geschaeft",
            "tel_geschaeft", "tel_mobil"))))
    liste = sorted(q.all(), key=lambda c: c.name.casefold())
    lex_bereit = einstellungen.an(g.db, "lex_aktiv") and bool(einstellungen.lesen(g.db, "lex_key_enc"))
    return render_template("kontakte.html", liste=liste, rolle=rolle, suche=suche, archiv=archiv, lex_bereit=lex_bereit)


@main.route("/kontakte/neu", methods=["GET", "POST"])
@edit_required
def kontakt_neu():
    c = Contact(typ="firma", ist_kunde=True, quelle="manuell")
    fehler = None
    if request.method == "POST":
        fehler = _kontakt_speichern(c)
        if not fehler:
            g.db.add(c)
            g.db.commit()
            flash("Kontakt angelegt. Ansprechpartner kannst du jetzt ergänzen.", "ok")
            return redirect(url_for("main.kontakt_detail", cid=c.id))
    elif request.args.get("rolle") == "lieferanten":
        c.ist_kunde, c.ist_lieferant = False, True
    return render_template("kontakt_form.html", c=c, fehler=fehler, neu=True)


@main.route("/kontakte/<int:cid>")
@login_required
def kontakt_detail(cid):
    c = g.db.get(Contact, cid) or abort(404)
    projekte = g.db.query(Project).filter(Project.contact_id == cid).order_by(Project.nummer).all()
    return render_template("kontakt_detail.html", c=c, projekte=projekte)


@main.route("/kontakte/<int:cid>/bearbeiten", methods=["GET", "POST"])
@edit_required
def kontakt_bearbeiten(cid):
    c = g.db.get(Contact, cid) or abort(404)
    lex_sperre = _lexoffice_sperre(c)
    if lex_sperre:
        return lex_sperre
    ok, lock = sperre.holen(g.db, "kontakt", cid, g.user)
    if not ok:
        flash(sperre.meldung("kontakt", lock), "fehler")
        return redirect(url_for("main.kontakt_detail", cid=c.id))
    g.db.commit()
    fehler = None
    if request.method == "POST":
        form_ver = request.form.get("version", type=int)
        if form_ver is not None and form_ver != (c.version or 1):
            fehler = "Der Kontakt wurde inzwischen von einem anderen Benutzer geändert. Bitte neu öffnen."
        else:
            fehler = _kontakt_speichern(c)
            if not fehler:
                c.version = (c.version or 1) + 1
                for p in g.db.query(Project).filter(Project.contact_id == c.id).all():
                    p.kunde = c.name
                sperre.freigeben(g.db, "kontakt", cid, g.user)
                protokoll("geaendert", "kontakt", c.id, c.name)
                g.db.commit()
                flash("Kontakt gespeichert.", "ok")
                return redirect(url_for("main.kontakt_detail", cid=c.id))
    return render_template("kontakt_form.html", c=c, fehler=fehler, neu=False)


@main.route("/kontakte/<int:cid>/archiv", methods=["POST"])
@edit_required
def kontakt_archiv(cid):
    c = g.db.get(Contact, cid) or abort(404)
    sperre = _lexoffice_sperre(c)
    if sperre:
        return sperre
    c.archiviert = not c.archiviert
    g.db.commit()
    flash("Kontakt archiviert. Er erscheint nicht mehr in der Auswahl." if c.archiviert else "Kontakt wieder aktiviert.", "ok")
    return redirect(url_for("main.kontakt_detail", cid=cid))


@main.route("/kontakte/<int:cid>/person", methods=["POST"])
@edit_required
def kontakt_person_neu(cid):
    c = g.db.get(Contact, cid) or abort(404)
    sperre = _lexoffice_sperre(c)
    if sperre:
        return sperre
    if not (text("vorname") or text("nachname")):
        flash("Bitte mindestens Vor- oder Nachnamen des Ansprechpartners angeben.", "fehler")
    else:
        primaer = request.form.get("primaer") == "1"
        if primaer:
            for p in c.personen:
                p.primaer = False
        c.personen.append(ContactPerson(anrede=text("anrede"), vorname=text("vorname"), nachname=text("nachname"),
                                        email=text("email"), telefon=text("telefon"), primaer=primaer))
        g.db.commit()
        flash("Ansprechpartner hinzugefügt.", "ok")
    return redirect(url_for("main.kontakt_detail", cid=cid))


@main.route("/kontakte/<int:cid>/person/<int:pid>/loeschen", methods=["POST"])
@edit_required
def kontakt_person_loeschen(cid, pid):
    c = g.db.get(Contact, cid) or abort(404)
    sperre = _lexoffice_sperre(c)
    if sperre:
        return sperre
    p = g.db.get(ContactPerson, pid)
    if p and p.contact_id == cid:
        g.db.delete(p)
        g.db.commit()
        flash("Ansprechpartner entfernt.", "ok")
    return redirect(url_for("main.kontakt_detail", cid=cid))


# ------------------------------------------------------- IDS-Connect (Shop)
IDS_DIR = config.DATA_DIR / "ids"
IDS_GUELTIG = 8 * 3600


def _ids_pfad(token, endung):
    if not re.fullmatch(r"[0-9a-f]{32}", token or ""):
        abort(404)
    return IDS_DIR / f"{token}.{endung}"


def _ids_meta(token):
    """Lädt die Angaben zu einem Shop-Aufruf; None, wenn unbekannt oder abgelaufen."""
    import json
    p = _ids_pfad(token, "json")
    if not p.exists():
        return None
    meta = json.loads(p.read_text(encoding="utf-8"))
    if time.time() - meta.get("erstellt", 0) > IDS_GUELTIG:
        _ids_verwerfen(token)
        return None
    return meta


def _ids_meta_speichern(token, meta):
    import json
    IDS_DIR.mkdir(parents=True, exist_ok=True)
    _ids_pfad(token, "json").write_text(json.dumps(meta), encoding="utf-8")


def _ids_verwerfen(token):
    for e in ("json", "xml"):
        _ids_pfad(token, e).unlink(missing_ok=True)


def _ids_aufraeumen():
    if IDS_DIR.exists():
        for f in IDS_DIR.glob("*"):
            if time.time() - f.stat().st_mtime > 2 * IDS_GUELTIG:
                f.unlink(missing_ok=True)


def _ids_warenkorb(token):
    """(meta, Warenkorb) für den angemeldeten Benutzer oder (None, None)."""
    meta = _ids_meta(token)
    xml = _ids_pfad(token, "xml")
    if not meta or not meta.get("empfangen") or not xml.exists():
        return None, None
    if meta.get("user") != g.user.id:
        return None, None
    try:
        return meta, ids.lesen(xml.read_bytes())
    except ids.IdsFehler:
        return None, None


def _ids_info(token):
    meta, r = _ids_warenkorb(token)
    return {"warnungen": r["warnungen"]} if r else None


def _ids_vorbelegung(token):
    meta, r = _ids_warenkorb(token)
    if not r:
        flash("Dieser Warenkorb ist nicht mehr verfügbar (abgelaufen, schon übernommen oder von einem anderen Benutzer).", "fehler")
        return None
    lief = g.db.get(Supplier, meta.get("supplier") or 0)
    modus = (lief.ids_preis_modus if lief else None) or "gesamt"
    zeilen, uebersprungen, ohne_preis = [], [], 0
    for p in r["positionen"]:
        if p["art"] in ("alternate", "provis"):
            uebersprungen.append(p)
            continue
        pr = ids.einzelpreis(p, modus)
        ohne_preis += pr is None
        hinweis = " ".join(x for x in (p["hinweis"], p["fehlertext"]) if x)
        zeilen.append({
            "artikelnr": p["artikelnr"], "bezeichnung": p["kurztext"] or p["langtext"][:100] or p["artikelnr"],
            "menge": formate.qty(p["menge"]) if p["menge"] is not None else "", "einheit": p["einheit"] or "Stück",
            "preis": formate.preis_eingabe(pr) if pr is not None else "",
            "termin": r["lieferdatum"].isoformat() if r["lieferdatum"] else "", "projekt": "", "kommission": "",
            "hinweis": f"Shop: {hinweis}"[:300] if hinweis else ""})
    notiz = " · ".join(x for x in (f"Kommission im Shop: {r['kommission']}" if r["kommission"] else "",
                                   r["zusatztext"], f"Versandart: {r['versandart']}" if r["versandart"] else "") if x)
    doppelt = None
    if r["ab_nr"] and lief:
        doppelt = g.db.query(Order).filter(Order.supplier_id == lief.id, Order.ab_nr == r["ab_nr"]).first()
    mit_bestellung = "mit bestellung" in r["rueckgabe"].lower()
    return {
        "werte": {"supplier_id": str(meta.get("supplier") or ""), "ab_nr": r["ab_nr"],
                  "bestelldatum": (r["datum"] or date.today()).isoformat(), "notiz": notiz[:1000],
                  "schon_bestellt": mit_bestellung},
        "zeilen": zeilen,
        "info": {"lieferant": lief.name if lief else "", "anzahl": len(zeilen), "rueckgabe": r["rueckgabe"],
                 "uebersprungen": uebersprungen, "ohne_preis": ohne_preis, "modus": modus,
                 "lieferdatum": r["lieferdatum"], "lieferwoche": r["lieferwoche"], "warnungen": r["warnungen"],
                 "doppelt": doppelt, "mit_bestellung": mit_bestellung},
    }


@main.route("/ids")
@edit_required
def ids_seite():
    lieferanten = g.db.query(Supplier).filter(Supplier.active.is_(True)).order_by(Supplier.name).all()
    offen = []
    if IDS_DIR.exists():
        for f in sorted(IDS_DIR.glob("*.json")):
            meta = _ids_meta(f.stem)
            if meta and meta.get("empfangen") and meta.get("user") == g.user.id and _ids_pfad(f.stem, "xml").exists():
                lief = g.db.get(Supplier, meta.get("supplier") or 0)
                offen.append({"token": f.stem, "lieferant": lief.name if lief else "?",
                              "zeit": time.strftime("%d.%m.%Y %H:%M", time.localtime(meta.get("empfangen_am", meta["erstellt"])))})
    return render_template("ids.html", lieferanten=lieferanten, offen=offen)


@main.route("/ids/start/<int:sid>", methods=["POST"])
@edit_required
def ids_start(sid):
    s = g.db.get(Supplier, sid) or abort(404)
    if not s.ids_url:
        flash("Für diesen Lieferanten ist keine IDS-Adresse eingetragen (Einstellungen → Lieferanten).", "fehler")
        return redirect(url_for("main.ids_seite"))
    IDS_DIR.mkdir(parents=True, exist_ok=True)
    _ids_aufraeumen()
    token = secrets.token_hex(16)
    hook = request.host_url.rstrip("/") + url_for("main.ids_rueckgabe", token=token)
    if len(hook) > 256:
        flash("Die Rückgabe-Adresse wäre länger als die erlaubten 256 Zeichen.", "fehler")
        return redirect(url_for("main.ids_seite"))
    _ids_meta_speichern(token, {"user": g.user.id, "supplier": s.id, "erstellt": time.time(), "empfangen": False})
    felder = []
    if s.ids_kndnr:
        felder.append(("kndnr", s.ids_kndnr))
    if s.ids_benutzer:
        felder.append(("name_kunde", s.ids_benutzer))
    if s.ids_passwort_enc:
        felder.append(("pw_kunde", security.decrypt(s.ids_passwort_enc)))
    felder += [("action", "WKE"), ("hookurl", hook)]
    version = s.ids_version if s.ids_version is not None else "2.5"
    if version:
        felder.append(("version", version))
    if s.ids_aufruf == "get":      # manche Shops lesen die Parameter nur aus der Adresszeile (Passwort steht dann im Verlauf des Browsers)
        from urllib.parse import urlencode
        ziel = s.ids_url + ("&" if "?" in s.ids_url else "?") + urlencode(felder)
        return redirect(ziel, code=303)
    return render_template("ids_start.html", s=s, felder=felder)


@main.route("/ids/rueckgabe/<token>", methods=["GET", "POST"])
def ids_rueckgabe(token):
    """Hier schickt der Shop den Warenkorb hin (Hook-URL). Geschützt durch den einmaligen Token in der Adresse."""
    meta = _ids_meta(token)
    if request.method == "GET":
        return render_template("fehler.html", titel="IDS-Rückgabe",
                               text="Diese Adresse nimmt Warenkörbe aus dem Shop entgegen. Bitte den Shop über die App öffnen: Bestellwesen → Aus Shop übernehmen."), 200
    if not meta or meta.get("empfangen"):
        return render_template("fehler.html", titel="Warenkorb nicht angenommen",
                               text="Diese Rückgabe ist abgelaufen oder wurde schon verwendet. Bitte den Shop erneut über die App öffnen."), 410
    body = request.get_data(cache=True)
    teile = ids.formular_teile(request.content_type, body)
    xml = ids.finde_xml(teile, body if request.mimetype in ("application/xml", "text/xml") else b"")
    if not xml:
        return render_template("fehler.html", titel="Kein Warenkorb gefunden",
                               text="Der Shop hat keine Warenkorb-Daten mitgeschickt. Bitte im Shop nochmals „Warenkorb übertragen“ wählen."), 400
    try:
        ids.lesen(xml)
    except ids.IdsFehler as e:
        return render_template("fehler.html", titel="Warenkorb nicht lesbar", text=str(e)), 400
    _ids_pfad(token, "xml").write_bytes(xml)
    meta.update(empfangen=True, empfangen_am=time.time())
    _ids_meta_speichern(token, meta)
    return redirect(url_for("main.bestellung_neu", ids=token), code=303)


# --------------------------------------------- IDS: Diagnose und Selbsttest
def _ids_grundfelder(s):
    felder = []
    if s.ids_kndnr:
        felder.append(("kndnr", s.ids_kndnr))
    if s.ids_benutzer:
        felder.append(("name_kunde", s.ids_benutzer))
    if s.ids_passwort_enc:
        felder.append(("pw_kunde", security.decrypt(s.ids_passwort_enc)))
    return felder


@main.route("/einstellungen/lieferanten/<int:sid>/ids-test", methods=["POST"])
@admin_required
def ids_test(sid):
    s = g.db.get(Supplier, sid) or abort(404)
    if not s.ids_url:
        flash("Bitte zuerst die IDS-Adresse eintragen und speichern.", "fehler")
        return redirect(url_for("main.lieferant_bearbeiten", sid=sid))
    ergebnisse = []
    for action, titel in (("SV", "Welche Schnittstellenversionen unterstützt der Shop? (SV)"),
                          ("LI", "Welche Anmeldedaten verlangt der Shop? (LI)")):
        felder = _ids_grundfelder(s) + [("action", action)]
        antwort = ids.abfrage(s.ids_url, felder)
        ergebnisse.append({"titel": titel, "action": action, "antwort": antwort, "deutung": ids.deuten(antwort)})
    version = s.ids_version if s.ids_version is not None else "2.5"
    versionen = next((e["deutung"]["werte"] for e in ergebnisse if e["deutung"]["art"] == "versionen"), None)
    login = next((e["deutung"]["werte"] for e in ergebnisse if e["deutung"]["art"] == "login"), None)
    gesendet = [(n, "••••••••" if n == "pw_kunde" else w) for n, w in _ids_grundfelder(s)] + [
        ("action", "WKE"), ("hookurl", request.host_url.rstrip("/") + "/ids/rueckgabe/<einmaliger Code>")] + (
        [("version", version)] if version else [])
    return render_template("ids_test.html", s=s, ergebnisse=ergebnisse, versionen=versionen, login=login,
                           version=version, gesendet=gesendet,
                           ist_ids=any(e["deutung"]["art"] in ("versionen", "login") for e in ergebnisse))


@main.route("/ids/selbsttest/<int:sid>", methods=["POST"])
@edit_required
def ids_selbsttest(sid):
    """Spielt einen Warenkorb über denselben Weg ein wie der Shop (Browser → Rückgabe-Adresse), ohne den Shop zu benutzen."""
    s = g.db.get(Supplier, sid) or abort(404)
    IDS_DIR.mkdir(parents=True, exist_ok=True)
    token = secrets.token_hex(16)
    _ids_meta_speichern(token, {"user": g.user.id, "supplier": s.id, "erstellt": time.time(), "empfangen": False})
    hook = request.host_url.rstrip("/") + url_for("main.ids_rueckgabe", token=token)
    return render_template("ids_selbsttest.html", s=s, hook=hook,
                           xml=ids.BEISPIEL_WARENKORB.format(datum=date.today().isoformat()))


# ------------------------------------------------------------ Lieferscheine
@main.route("/lieferscheine")
@login_required
def lieferscheine():
    suche = (request.args.get("q") or "").strip()
    lieferant_id = request.args.get("lieferant", type=int)
    q = (g.db.query(Delivery).join(Delivery.order)
         .options(joinedload(Delivery.order).joinedload(Order.supplier), selectinload(Delivery.items))
         .order_by(Delivery.datum.desc(), Delivery.id.desc()))
    if suche:
        q = q.filter(Delivery.lieferschein_nr.like(f"%{suche}%"))
    if lieferant_id:
        q = q.filter(Order.supplier_id == lieferant_id)
    return render_template("lieferscheine.html", liste=q.limit(500).all(), suche=suche, lieferant_id=lieferant_id,
                           lieferanten=g.db.query(Supplier).order_by(Supplier.name).all())


def _offene_positionen_je_bestellung(lieferant_id):
    orders = (g.db.query(Order).options(
        selectinload(Order.items).selectinload(OrderItem.delivery_items),
        selectinload(Order.items).joinedload(OrderItem.project))
        .filter(Order.supplier_id == lieferant_id, Order.status.in_(("bestellt", "teilgeliefert")))
        .order_by(Order.bestelldatum, Order.id).all())
    erg = []
    for o in orders:
        pos = [i for i in o.items if not i.storniert and i.rest > 0]
        if pos:
            erg.append((o, pos))
    return erg


@main.route("/lieferscheine/neu", methods=["GET", "POST"])
@edit_required
def lieferschein_neu():
    lieferanten = g.db.query(Supplier).filter(Supplier.active.is_(True)).order_by(Supplier.name).all()
    sid = request.values.get("lieferant", type=int)
    if sid and not g.db.get(Supplier, sid):
        sid = None
    offene = _offene_positionen_je_bestellung(sid) if sid else []
    fehler = None
    if request.method == "POST" and sid:
        nr = text("lieferschein_nr")
        datum = parse_date(request.form.get("datum"), date.today())
        alles = request.form.get("alles") == "1"
        mengen = {}
        for o, pos in offene:
            for i in pos:
                roh = (request.form.get(f"menge_{i.id}") or "").strip()
                m = i.rest if alles else dec(roh, Decimal(0))
                if roh and not alles and dec(roh) is None:
                    fehler = f"„{roh}“ ist keine Zahl (Position {i.bezeichnung})."
                elif m and m < 0:
                    fehler = f"Negative Menge bei {i.bezeichnung}."
                elif m and m > 0:
                    mengen[i.id] = m
        if not fehler and nr:
            doppelt = (g.db.query(Delivery).join(Delivery.order)
                       .filter(Order.supplier_id == sid, Delivery.lieferschein_nr == nr).first())
            if doppelt:
                fehler = f"Den Lieferschein {nr} gibt es für diesen Lieferanten schon (vom {doppelt.datum.strftime('%d.%m.%Y')}). Bitte eine andere Nummer eintragen."
        if not fehler and not mengen:
            fehler = "Es ist keine gelieferte Menge eingetragen. Gib Mengen ein oder wähle „Alles als geliefert buchen“."
        if not fehler:
            n_pos, n_best = 0, 0
            for o, pos in offene:
                d = Delivery(order_id=o.id, lieferschein_nr=nr, datum=datum, notiz=text("notiz"), created_by=g.user.id)
                for i in pos:
                    if i.id in mengen:
                        d.items.append(DeliveryItem(item=i, menge=mengen[i.id]))
                        n_pos += 1
                if d.items:
                    g.db.add(d)
                    o.status_aktualisieren()
                    n_best += 1
            g.db.commit()
            flash(f"Lieferschein gebucht: {n_pos} Positionen in {n_best} Bestellungen.", "ok")
            return redirect(url_for("main.lieferscheine"))
    return render_template("lieferschein_form.html", lieferanten=lieferanten, sid=sid, offene=offene, fehler=fehler,
                           form=request.form if request.method == "POST" else {})


# -------------------------------------------------------- Lexoffice (Einstellungen)
LEX_OPTIONEN = [  # (Schlüssel, Titel, umgesetzt, Standard)
    ("lex_sync_kunden", "Kontakte: Kunden", True, True),
    ("lex_sync_lieferanten", "Kontakte: Lieferanten", True, True),
    ("lex_sync_archiviert", "Auch archivierte Kontakte übernehmen", True, False),
    ("lex_sync_angebote", "Angebote (für das Materialbudget im Projekt)", True, False),
    ("lex_sync_auftraege", "Aufträge / Auftragsbestätigungen", True, False),
    ("lex_sync_rechnungen", "Ausgangsrechnungen", True, False),
    ("lex_sync_eingangsrechnungen", "Eingangsrechnungen (Lieferantenbelege)", True, False),
]


def _lex_zugang():
    key_enc = einstellungen.lesen(g.db, "lex_key_enc")
    return einstellungen.lesen(g.db, "lex_url", lexoffice.BASIS), (security.decrypt(key_enc) if key_enc else "")


def _lex_zeitraum(jahr_str, monat_str, ab_str, bis_str):
    """Berechnet datum_ab und datum_bis aus Jahr/Monat oder freien Datumsgrenzen."""
    import calendar
    datum_ab = (ab_str or "").strip() or None
    datum_bis = (bis_str or "").strip() or None
    if jahr_str and str(jahr_str).isdigit():
        j = int(jahr_str)
        if monat_str and str(monat_str).isdigit() and 1 <= int(monat_str) <= 12:
            m = int(monat_str)
            last_day = calendar.monthrange(j, m)[1]
            datum_ab = f"{j:04d}-{m:02d}-01"
            datum_bis = f"{j:04d}-{m:02d}-{last_day:02d}"
        else:
            datum_ab = f"{j:04d}-01-01"
            datum_bis = f"{j:04d}-12-31"
    return datum_ab, datum_bis


@main.route("/einstellungen/lexoffice", methods=["GET", "POST"], endpoint="lexoffice")
@admin_required
def lexoffice_seite():
    fehler = None
    if request.method == "POST":
        url = (request.form.get("lex_url") or "").strip() or lexoffice.BASIS
        if not re.match(r"^https?://\S+$", url):
            fehler = "Die API-Adresse muss mit https:// beginnen."
        else:
            einstellungen.schreiben(g.db, "lex_url", url.rstrip("/"))
            einstellungen.schreiben(g.db, "lex_aktiv", "1" if request.form.get("lex_aktiv") == "1" else "0")
            neu = (request.form.get("lex_key") or "").strip()
            if neu:
                einstellungen.schreiben(g.db, "lex_key_enc", security.encrypt(neu))
            elif request.form.get("lex_key_loeschen") == "1":
                einstellungen.schreiben(g.db, "lex_key_enc", None)
            for schluessel, _titel, umgesetzt, _std in LEX_OPTIONEN:
                if umgesetzt:
                    einstellungen.schreiben(g.db, schluessel, "1" if request.form.get(schluessel) == "1" else "0")
            ab = (request.form.get("lex_belege_ab") or "").strip()
            einstellungen.schreiben(g.db, "lex_belege_ab", ab if re.match(r"^\d{4}-\d{2}-\d{2}$", ab) else "")
            bis = (request.form.get("lex_belege_bis") or "").strip()
            einstellungen.schreiben(g.db, "lex_belege_bis", bis if re.match(r"^\d{4}-\d{2}-\d{2}$", bis) else "")
            fj = (request.form.get("lex_filter_jahr") or "").strip()
            einstellungen.schreiben(g.db, "lex_filter_jahr", fj if re.match(r"^\d{4}$", fj) else "")
            fm = (request.form.get("lex_filter_monat") or "").strip()
            einstellungen.schreiben(g.db, "lex_filter_monat", fm if fm in [str(i) for i in range(1, 13)] else "")
            g.db.commit()
            flash("Lexoffice-Einstellungen gespeichert.", "ok")
            return redirect(url_for("main.lexoffice"))
    letzter = None
    try:
        letzter = json.loads(einstellungen.lesen(g.db, "lex_letzter_sync") or "null")
    except ValueError:
        pass
    optionen = [{"key": k, "titel": t, "umgesetzt": u, "an": einstellungen.an(g.db, k, std) if u else False}
                for k, t, u, std in LEX_OPTIONEN]
    belege_anz = {t: g.db.query(LexDocument).filter(LexDocument.typ == t).count() for t in BELEG_TYPEN}
    aktuelles_jahr = date.today().year
    jahre = list(range(aktuelles_jahr + 1, aktuelles_jahr - 7, -1))
    return render_template(
        "lexoffice.html", fehler=fehler, aktiv=einstellungen.an(g.db, "lex_aktiv"),
        url=einstellungen.lesen(g.db, "lex_url", lexoffice.BASIS), hat_key=bool(einstellungen.lesen(g.db, "lex_key_enc")),
        optionen=optionen, letzter=letzter,
        filter_jahr=einstellungen.lesen(g.db, "lex_filter_jahr", ""),
        filter_monat=einstellungen.lesen(g.db, "lex_filter_monat", ""),
        belege_ab=einstellungen.lesen(g.db, "lex_belege_ab", ""),
        belege_bis=einstellungen.lesen(g.db, "lex_belege_bis", ""),
        jahre=jahre, MONATE=MONATE,
        anzahl=g.db.query(Contact).filter(Contact.quelle == "lexoffice").count(),
        belege_anz=belege_anz)


@main.route("/einstellungen/lexoffice/test", methods=["POST"], endpoint="lexoffice_test")
@admin_required
def lexoffice_testen():
    basis, key = _lex_zugang()
    if not key:
        flash("Bitte zuerst den API-Schlüssel eintragen und speichern.", "fehler")
    else:
        try:
            p = lexoffice.profil(basis, key)
            flash(f"Verbindung in Ordnung. Verbunden mit: {p.get('companyName') or p.get('organizationId') or 'Lexoffice'}.", "ok")
        except lexoffice.LexFehler as e:
            flash(str(e), "fehler")
    return redirect(url_for("main.lexoffice"))


@main.route("/einstellungen/lexoffice/sync", methods=["POST"], endpoint="lexoffice_sync")
@admin_required
def lexoffice_abgleichen():
    basis, key = _lex_zugang()
    if not einstellungen.an(g.db, "lex_aktiv") or not key:
        flash("Die Schnittstelle ist nicht eingeschaltet oder es fehlt der API-Schlüssel.", "fehler")
        return redirect(url_for("main.lexoffice"))
    jetzt = time.strftime("%d.%m.%Y %H:%M")
    try:
        erg = lexoffice.synchronisieren(
            g.db, basis, key, kunden=einstellungen.an(g.db, "lex_sync_kunden", True),
            lieferanten=einstellungen.an(g.db, "lex_sync_lieferanten", True),
            archivierte=einstellungen.an(g.db, "lex_sync_archiviert", False))
        ang = einstellungen.an(g.db, "lex_sync_angebote", False)
        auf = einstellungen.an(g.db, "lex_sync_auftraege", False)
        rech = einstellungen.an(g.db, "lex_sync_rechnungen", False)
        eingang = einstellungen.an(g.db, "lex_sync_eingangsrechnungen", False)
        belege_erg = None
        if ang or auf or rech or eingang:
            ab_datum, bis_datum = _lex_zeitraum(
                einstellungen.lesen(g.db, "lex_filter_jahr", ""),
                einstellungen.lesen(g.db, "lex_filter_monat", ""),
                einstellungen.lesen(g.db, "lex_belege_ab", ""),
                einstellungen.lesen(g.db, "lex_belege_bis", ""),
            )
            belege_erg = lexoffice.belege_synchronisieren(
                g.db, basis, key, angebote=ang, auftraege=auf, rechnungen=rech,
                eingangsrechnungen=eingang, datum_ab=ab_datum, datum_bis=bis_datum)
        einstellungen.schreiben(g.db, "lex_letzter_sync", json.dumps({
            "zeit": jetzt, "ergebnis": erg, "belege": belege_erg, "fehler": None}))
        g.db.commit()
        msg = (f"Abgleich fertig: {erg['neu']} neu, {erg['aktualisiert']} aktualisiert, "
               f"{erg['unveraendert']} unverändert, {erg['archiviert']} archiviert.")
        if belege_erg:
            msg += (f" Belege: {belege_erg['neu']} neu, {belege_erg['aktualisiert']} aktualisiert, "
                    f"{belege_erg['unveraendert']} unverändert.")
        flash(msg, "ok")
    except lexoffice.LexFehler as e:
        g.db.rollback()
        einstellungen.schreiben(g.db, "lex_letzter_sync", json.dumps({"zeit": jetzt, "ergebnis": None, "fehler": str(e)}))
        g.db.commit()
        flash(f"Der Abgleich ist fehlgeschlagen: {e}", "fehler")
    return redirect(url_for("main.lexoffice"))


# ------------------------------------------------- Lexoffice-Belege & Kostenarten
@main.route("/lexoffice/belege")
@login_required
def lex_belege():
    typ = request.args.get("typ", "alle")
    projekt = request.args.get("projekt", "alle")
    suche = (request.args.get("q") or "").strip()
    jahr = request.args.get("jahr", "alle")
    monat = request.args.get("monat", "alle")
    q = g.db.query(LexDocument).options(
        joinedload(LexDocument.project),
        selectinload(LexDocument.items),
    ).order_by(LexDocument.datum.desc(), LexDocument.id.desc())
    if typ in BELEG_TYPEN:
        q = q.filter(LexDocument.typ == typ)
    if projekt == "ohne":
        q = q.filter(LexDocument.project_id.is_(None))
    elif projekt == "mit":
        q = q.filter(LexDocument.project_id.isnot(None))
    if jahr.isdigit():
        q = q.filter(extract("year", LexDocument.datum) == int(jahr))
    if monat.isdigit() and 1 <= int(monat) <= 12:
        q = q.filter(extract("month", LexDocument.datum) == int(monat))
    if suche:
        like = f"%{suche}%"
        q = q.filter(or_(LexDocument.nummer.like(like), LexDocument.kunde_name.like(like), LexDocument.titel.like(like)))
    aktuelles_jahr = date.today().year
    jahre = list(range(aktuelles_jahr + 1, aktuelles_jahr - 7, -1))
    return render_template("lex_belege.html", belege=q.all(), typ=typ, projekt=projekt, suche=suche,
                           jahr=jahr, monat=monat, jahre=jahre, MONATE=MONATE,
                           BELEG_TYPEN=BELEG_TYPEN, BELEG_STATUS=BELEG_STATUS)


@main.route("/lexoffice/belege/<int:did>", methods=["GET", "POST"])
@login_required
def lex_beleg_detail(did):
    doc = (g.db.query(LexDocument).options(
        joinedload(LexDocument.project),
        joinedload(LexDocument.contact),
        selectinload(LexDocument.items),
    ).filter(LexDocument.id == did).first()) or abort(404)
    gesperrt_von = None
    if g.user.role != "leser":
        ok, lock = sperre.holen(g.db, "lex_beleg", did, g.user)
        if not ok:
            gesperrt_von = lock
        else:
            g.db.commit()
    if request.method == "POST":
        if g.user.role == "leser":
            abort(403)
        if gesperrt_von:
            flash(sperre.meldung("lex_beleg", gesperrt_von), "fehler")
            return redirect(url_for("main.lex_beleg_detail", did=doc.id, von=request.args.get("von", type=int)))
        form_ver = request.form.get("version", type=int)
        if form_ver is not None and form_ver != (doc.version or 1):
            flash("Der Beleg wurde inzwischen von einem anderen Benutzer geändert. Bitte neu laden.", "fehler")
            return redirect(url_for("main.lex_beleg_detail", did=doc.id, von=request.args.get("von", type=int)))
        pid = request.form.get("project_id", type=int)
        doc.project_id = pid if (pid and g.db.get(Project, pid)) else None
        merken = request.form.get("merken") == "1"
        angewendet = 0
        for item in doc.items:
            if item.lex_typ == "text":
                continue
            ka = request.form.get(f"ka_{item.id}", "")
            item.kostenart = ka if ka in ("material", "pauschale", "fremdleistung", "arbeit") else None
            if item.kostenart == "material":
                item.materialanteil = Decimal("100.00")
            elif item.kostenart in ("fremdleistung", "arbeit"):
                item.materialanteil = Decimal("0.00")
            elif item.kostenart == "pauschale":
                ant = dec(request.form.get(f"anteil_{item.id}"))
                if ant is None:
                    ant = Decimal("50.00")
                item.materialanteil = max(Decimal("0.00"), min(Decimal("100.00"), ant))
            if merken and item.kostenart:
                angewendet += lexoffice.regel_speichern(g.db, item, item.kostenart, item.materialanteil, auch_offene=True)
        doc.version = (doc.version or 1) + 1
        sperre.freigeben(g.db, "lex_beleg", did, g.user)
        protokoll("geaendert", "lex_beleg", doc.id, doc.nummer or f"Beleg #{doc.id}")
        g.db.commit()
        hinweis = f" ({angewendet} offene Positionen in anderen Belegen mitgeändert)" if angewendet else ""
        flash(f"Beleg gespeichert{hinweis}.", "ok")
        von = request.args.get("von", type=int)
        return redirect(url_for("main.lex_beleg_detail", did=doc.id, von=von))

    projekte_liste = g.db.query(Project).order_by(Project.nummer).all()
    von = request.args.get("von", type=int)
    return render_template("lex_beleg_detail.html", doc=doc, projekte=projekte_liste, von=von,
                           gesperrt_von=gesperrt_von, sperre_text=(sperre.meldung("lex_beleg", gesperrt_von) if gesperrt_von else None),
                           BELEG_TYPEN=BELEG_TYPEN, BELEG_STATUS=BELEG_STATUS, KOSTENARTEN=KOSTENARTEN)


# ------------------------------------------------- Sperren, Protokoll, Sicherung, Artikel, Rechnungen
@main.route("/sperre/freigeben/<obj_typ>/<int:obj_id>", methods=["POST"])
@admin_required
def sperre_freigeben(obj_typ, obj_id):
    sperre.freigeben(g.db, obj_typ, obj_id, force=True)
    protokoll("entsperrt", obj_typ, obj_id, details="Bearbeitungssperre durch Admin aufgehoben")
    g.db.commit()
    flash("Bearbeitungssperre aufgehoben.", "ok")
    return redirect(request.referrer or url_for("main.dashboard"))


@main.route("/artikel")
@login_required
def artikel():
    suche = (request.args.get("q") or "").strip()
    q = g.db.query(Article).options(joinedload(Article.supplier)).order_by(Article.artikelnr)
    if suche:
        like = f"%{suche}%"
        q = q.filter(or_(Article.artikelnr.like(like), Article.bezeichnung.like(like)))
    return render_template("artikel.html", artikel=q.limit(500).all(), suche=suche, gesamt=g.db.query(Article).count())


@main.route("/artikel/import", methods=["GET", "POST"])
@edit_required
def artikel_import():
    if request.method == "POST":
        f = request.files.get("datei")
        sid = request.form.get("supplier_id", type=int)
        if not f or not f.filename:
            flash("Bitte eine Datanorm-Datei auswählen.", "fehler")
            return redirect(url_for("main.artikel_import"))
        daten = f.read(10 * 1024 * 1024 + 1)
        if len(daten) > 10 * 1024 * 1024:
            flash("Die Datei ist größer als 10 MB.", "fehler")
            return redirect(url_for("main.artikel_import"))
        try:
            r = datanorm.lesen(daten)
        except datanorm.DatanormFehler as e:
            flash(f"Datanorm-Datei nicht lesbar: {e}", "fehler")
            return redirect(url_for("main.artikel_import"))
        bestehende = {a.artikelnr: a for a in g.db.query(Article).all()}
        neu, akt = 0, 0
        for d in r["artikel"]:
            a = bestehende.get(d["artikelnr"])
            if a is None:
                a = Article(artikelnr=d["artikelnr"], bezeichnung=d["bezeichnung"])
                g.db.add(a)
                bestehende[d["artikelnr"]] = a
                neu += 1
            else:
                akt += 1
            a.bezeichnung = d["bezeichnung"]
            a.kurztext2 = d["kurztext2"]
            a.einheit = d["einheit"]
            a.listenpreis = d["listenpreis"]
            a.rabattgruppe = d["rabattgruppe"]
            if sid:
                a.supplier_id = sid
            a.updated_at = datetime.now()
        protokoll("import", "artikel", details=f"Datanorm: {neu} neu, {akt} aktualisiert")
        g.db.commit()
        flash(f"Datanorm-Import fertig: {neu} neue Artikel, {akt} aktualisiert.", "ok")
        return redirect(url_for("main.artikel"))
    lieferanten = g.db.query(Supplier).filter(Supplier.active.is_(True)).order_by(Supplier.name).all()
    return render_template("artikel_import.html", lieferanten=lieferanten)


@main.route("/rechnungen", methods=["GET", "POST"])
@login_required
def rechnungen():
    if request.method == "POST":
        if g.user.role == "leser":
            abort(403)
        f = request.files.get("datei")
        if not f or not f.filename:
            flash("Bitte eine ZUGFeRD-PDF oder XML-Datei auswählen.", "fehler")
            return redirect(url_for("main.rechnungen"))
        daten = f.read(10 * 1024 * 1024 + 1)
        if len(daten) > 10 * 1024 * 1024:
            flash("Die Datei ist größer als 10 MB.", "fehler")
            return redirect(url_for("main.rechnungen"))
        try:
            r = zugferd.lesen(daten)
        except zugferd.ZugferdFehler as e:
            flash(f"ZUGFeRD-Datei nicht lesbar: {e}", "fehler")
            return redirect(url_for("main.rechnungen"))
        sid = request.form.get("supplier_id", type=int)
        oid = request.form.get("order_id", type=int)
        status = "offen"
        if oid:
            o = g.db.get(Order, oid)
            if o and r["netto"] is not None:
                diff = abs((o.summe or Decimal(0)) - r["netto"])
                status = "geprueft" if diff <= Decimal("0.05") else "abweichung"
        inv = SupplierInvoice(
            supplier_id=sid if sid else None,
            order_id=oid if oid else None,
            rechnungsnr=r["rechnungsnr"],
            datum=r["datum"],
            lieferant_name=r["lieferant_name"],
            netto=r["netto"],
            brutto=r["brutto"],
            waehrung=r["waehrung"],
            dateiname=re.sub(r"[^\w.\- ]", "", f.filename)[:200],
            status=status,
        )
        g.db.add(inv)
        g.db.flush()
        protokoll("import", "rechnung", inv.id, inv.rechnungsnr, details=f"Netto {inv.netto}")
        g.db.commit()
        flash(f"Rechnung {inv.rechnungsnr} eingelesen.", "ok")
        return redirect(url_for("main.rechnungen"))
    liste = g.db.query(SupplierInvoice).options(
        joinedload(SupplierInvoice.supplier),
        joinedload(SupplierInvoice.order).selectinload(Order.items),
    ).order_by(SupplierInvoice.datum.desc(), SupplierInvoice.id.desc()).all()
    lieferanten = g.db.query(Supplier).filter(Supplier.active.is_(True)).order_by(Supplier.name).all()
    bestellungen = g.db.query(Order).options(joinedload(Order.supplier)).order_by(Order.bestelldatum.desc(), Order.id.desc()).limit(100).all()
    return render_template("rechnungen.html", rechnungen=liste, lieferanten=lieferanten, bestellungen=bestellungen)


@main.route("/rechnungen/<int:rid>/zuordnen", methods=["POST"])
@edit_required
def rechnung_zuordnen(rid):
    inv = g.db.get(SupplierInvoice, rid) or abort(404)
    oid = request.form.get("order_id", type=int)
    inv.order_id = oid if (oid and g.db.get(Order, oid)) else None
    if inv.order_id:
        o = g.db.get(Order, inv.order_id)
        if o and inv.netto is not None:
            diff = abs((o.summe or Decimal(0)) - inv.netto)
            inv.status = "geprueft" if diff <= Decimal("0.05") else "abweichung"
        else:
            inv.status = "offen"
    else:
        inv.status = "offen"
    g.db.commit()
    flash("Rechnungszuordnung aktualisiert.", "ok")
    return redirect(url_for("main.rechnungen"))


@main.route("/einstellungen/datenbank", methods=["GET", "POST"])
@admin_required
def einstellungen_datenbank():
    cfg = current_app.extensions["cfg"]
    db_aktuell = cfg.get("db") or {"type": "sqlite"}
    form = {
        "type": db_aktuell.get("type", "mariadb"),
        "host": db_aktuell.get("host", ""),
        "port": str(db_aktuell.get("port") or "3306"),
        "name": db_aktuell.get("name", "einkauf"),
        "user": db_aktuell.get("user", ""),
        "hat_password": bool(db_aktuell.get("password")),
    }
    fehler = None
    if request.method == "POST":
        neu_typ = request.form.get("type") or "mariadb"
        neu_form = {
            "type": neu_typ,
            "host": (request.form.get("host") or "").strip(),
            "port": (request.form.get("port") or "3306").strip(),
            "name": (request.form.get("name") or "").strip(),
            "user": (request.form.get("user") or "").strip(),
            "password": request.form.get("password") or (db_aktuell.get("password") if neu_typ == db_aktuell.get("type") else ""),
        }
        try:
            if neu_typ == "mariadb":
                if not (neu_form["host"] and neu_form["name"] and neu_form["user"]):
                    raise ValueError("Bitte Host, Datenbankname und Benutzer angeben.")
                int(neu_form["port"])
            db.test_connection(neu_form)
            # Verbindung erfolgreich -> initialisieren & Engine/Session neu anlegen
            db.init_db(current_app, neu_form)
            cfg["db"] = neu_form
            config.save(cfg)
            protokoll("geaendert", "system", details=f"Datenbankverbindung geändert auf {neu_typ}")
            with current_app.extensions["SessionLocal"]() as s:
                s.commit()
            flash("Datenbankverbindung erfolgreich geprüft und gespeichert.", "ok")
            return redirect(url_for("main.einstellungen_datenbank"))
        except Exception as e:
            fehler = f"Verbindung fehlgeschlagen: {e}"
            form = {
                "type": neu_typ,
                "host": neu_form["host"],
                "port": neu_form["port"],
                "name": neu_form["name"],
                "user": neu_form["user"],
                "hat_password": bool(neu_form["password"]),
            }
    return render_template("datenbank.html", form=form, fehler=fehler,
                           sqlite_pfad=str(config.DATA_DIR / "einkauf.db"))


@main.route("/einstellungen/protokoll")
@admin_required
def einstellungen_protokoll():
    eintraege = g.db.query(AuditLog).order_by(AuditLog.zeit.desc(), AuditLog.id.desc()).limit(200).all()
    sperren = g.db.query(EditLock).order_by(EditLock.seit.desc()).all()
    return render_template("protokoll.html", eintraege=eintraege, sperren=sperren)


@main.route("/einstellungen/sicherung")
@admin_required
def einstellungen_sicherung():
    return render_template("sicherung.html", daten_dir=str(config.DATA_DIR))


@main.route("/einstellungen/sicherung/download", methods=["POST"])
@admin_required
def einstellungen_sicherung_download():
    ddir = config.DATA_DIR
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in ddir.rglob("*"):
            if p.is_file():
                zf.write(p, p.relative_to(ddir))
    buf.seek(0)
    protokoll("sicherung", "system", details="Datensicherung (ZIP) heruntergeladen")
    g.db.commit()
    name = f"beliko-sicherung-{date.today().isoformat()}.zip"
    return Response(buf.getvalue(), mimetype="application/zip",
                    headers={"Content-Disposition": f"attachment; filename={name}"})


# ------------------------------------------------- Lieferantendateien (Abruf)
DATEI_STATUS = {"neu": "Neu", "verarbeitet": "Verarbeitet", "ignoriert": "Ignoriert", "fehler": "Nicht lesbar"}


def _bestell_kandidaten(f, daten):
    """Passende Bestellungen zu einer Lieferantendatei: je mehr offene Positionen mit gleicher Artikelnummer, desto besser."""
    r = ugl.lesen(daten)
    arts = {ugl.normalisiere(p["artikelnr"]) for p in r["positionen"] if p["artikelnr"]}
    orders = (g.db.query(Order).options(selectinload(Order.items).selectinload(OrderItem.delivery_items))
              .filter(Order.supplier_id == f.supplier_id, Order.status.in_(("neu", "bestellt", "teilgeliefert")))
              .order_by(Order.bestelldatum.desc(), Order.id.desc()).all())
    erg = []
    for o in orders:
        treffer = sum(1 for i in o.items if not i.storniert and i.rest > 0 and ugl.normalisiere(i.artikelnr) in arts)
        if treffer:
            erg.append({"o": o, "treffer": treffer, "gesamt": len(r["positionen"]),
                        "offen": sum(1 for i in o.items if not i.storniert and i.rest > 0)})
    erg.sort(key=lambda e: (-e["treffer"], -e["o"].id))
    return r, erg


@main.route("/dateien")
@login_required
def dateien():
    status = request.args.get("status", "neu")
    lieferant_id = request.args.get("lieferant", type=int)
    q = (g.db.query(SupplierFile).options(joinedload(SupplierFile.supplier))
         .order_by(SupplierFile.abgerufen_am.desc(), SupplierFile.id.desc()))
    if status in DATEI_STATUS:
        q = q.filter(SupplierFile.status == status)
    if lieferant_id:
        q = q.filter(SupplierFile.supplier_id == lieferant_id)
    lieferanten = g.db.query(Supplier).order_by(Supplier.name).all()
    return render_template("dateien.html", liste=q.limit(300).all(), status=status, lieferant_id=lieferant_id,
                           lieferanten=lieferanten, abrufbar=[s for s in lieferanten if s.active and not lieferantendateien.pruefen(s)],
                           DATEI_STATUS=DATEI_STATUS)


@main.route("/dateien/abrufen", methods=["POST"])
@edit_required
def dateien_abrufen():
    sid = request.form.get("lieferant", type=int)
    q = g.db.query(Supplier).filter(Supplier.active.is_(True))
    if sid:
        q = q.filter(Supplier.id == sid)
    ziele = q.order_by(Supplier.name).all()
    gemeldet = 0
    for s in ziele:
        meldung = lieferantendateien.pruefen(s)
        if meldung:
            if sid:
                flash(f"{s.name}: {meldung}", "fehler")
            continue
        try:
            erg = lieferantendateien.abrufen(g.db, s)
            flash(f"{s.name}: {erg['neu']} neue Dateien, {erg['bekannt']} schon bekannt"
                  + (f", {erg['uebersprungen']} übersprungen" if erg["uebersprungen"] else "") + ".", "ok")
        except lieferantendateien.AbrufFehler as e:
            flash(f"{s.name}: {e}", "fehler")
        g.db.commit()
        gemeldet += 1
    if not gemeldet and not sid:
        flash("Kein Lieferant hat einen Abruf eingerichtet (Einstellungen → Lieferanten → UGL-Schnittstelle).", "warn")
    weiter = request.form.get("weiter")
    if weiter:
        return redirect(weiter)
    return redirect(url_for("main.dateien"))


@main.route("/dateien/<int:fid>")
@login_required
def datei_detail(fid):
    f = g.db.get(SupplierFile, fid) or abort(404)
    r, kandidaten = None, []
    try:
        r, kandidaten = _bestell_kandidaten(f, lieferantendateien.inhalt(f))
    except (ugl.UglFehler, lieferantendateien.AbrufFehler, OSError) as e:
        flash(f"Die Datei kann nicht gelesen werden: {e}", "fehler")
    return render_template("datei_detail.html", f=f, r=r, kandidaten=kandidaten, DATEI_STATUS=DATEI_STATUS)


@main.route("/dateien/<int:fid>/pruefen", methods=["POST"])
@edit_required
def datei_pruefen(fid):
    f = g.db.get(SupplierFile, fid) or abort(404)
    oid = request.form.get("bestellung", type=int)
    if not oid:
        flash("Bitte eine Bestellung wählen.", "fehler")
        return redirect(url_for("main.datei_detail", fid=fid))
    o = _bestellung(oid)
    if o.supplier_id != f.supplier_id:
        flash("Die Datei gehört zu einem anderen Lieferanten als die gewählte Bestellung.", "fehler")
        return redirect(url_for("main.datei_detail", fid=fid))
    try:
        return _ugl_vorschau(o, lieferantendateien.inhalt(f), f.name, datei_id=f.id)
    except (ugl.UglFehler, lieferantendateien.AbrufFehler, OSError) as e:
        flash(f"Die Datei kann nicht gelesen werden: {e}", "fehler")
        return redirect(url_for("main.datei_detail", fid=fid))


@main.route("/dateien/<int:fid>/status", methods=["POST"])
@edit_required
def datei_status(fid):
    f = g.db.get(SupplierFile, fid) or abort(404)
    aktion = request.form.get("aktion")
    if aktion == "ignorieren" and f.status in ("neu", "fehler"):
        f.status, f.aktion, f.verarbeitet_am = "ignoriert", "ignoriert", datetime.now()
        flash("Datei ignoriert. Sie steht weiter unter „Ignoriert“.", "ok")
    elif aktion == "neu" and f.status == "ignoriert":
        f.status, f.aktion, f.verarbeitet_am = "neu", None, None
        flash("Datei wieder auf „Neu“ gesetzt.", "ok")
    else:
        flash("Das ist bei dem aktuellen Status nicht möglich.", "fehler")
    g.db.commit()
    return redirect(url_for("main.dateien"))


@main.route("/einstellungen/lieferanten/<int:sid>/ftp-test", methods=["POST"])
@admin_required
def ftp_test(sid):
    s = g.db.get(Supplier, sid) or abort(404)
    ergebnis, fehler = None, None
    try:
        ergebnis = lieferantendateien.testen(s)
    except lieferantendateien.AbrufFehler as e:
        fehler = str(e)
    return render_template("ftp_test.html", s=s, ergebnis=ergebnis, fehler=fehler)

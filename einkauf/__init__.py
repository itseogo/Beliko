from datetime import date
from decimal import Decimal

from flask import Flask, g, redirect, render_template, request, session, url_for

from . import config, db, formate, security
from .models import User

VERSION = "1.3.1"


def create_app():
    cfg = config.load()
    app = Flask(__name__)
    app.secret_key = cfg["secret_key"]
    app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax")
    app.extensions["cfg"] = cfg
    app.extensions["SessionLocal"] = None

    app.jinja_env.filters.update(qty=formate.qty, money=formate.money, moneyinp=formate.preis_eingabe,
                                 preis=formate.preis, datum=formate.datum)
    app.config.update(MAX_CONTENT_LENGTH=8 * 1024 * 1024)

    @app.context_processor
    def _ctx():
        nutzer = getattr(g, "user", None)
        thema = {"hell": "light", "dunkel": "dark", "auto": "auto"}.get((nutzer.theme if nutzer else "auto") or "hell", "light")
        return {
            "theme": thema,
            "csrf_token": security.csrf_token,
            "firma": cfg.get("firma", ""),
            "heute": date.today(),
            "version": VERSION,
        }

    from .views import main, setup
    app.register_blueprint(main)
    app.register_blueprint(setup)

    @app.before_request
    def _before():
        if request.endpoint in (None, "static"):
            return
        g.db = None
        g.user = None
        if cfg["setup_done"]:
            if app.extensions["SessionLocal"] is None:
                try:
                    db.init_db(app, cfg["db"])
                except Exception as e:  # z. B. NAS beim Start noch nicht erreichbar
                    return render_template("dberror.html", error=str(e)), 503
            g.db = app.extensions["SessionLocal"]()
            uid = session.get("uid")
            if uid:
                u = g.db.get(User, uid)
                if u and u.active:
                    g.user = u
                else:
                    session.pop("uid", None)
            if request.endpoint.startswith("setup."):
                return redirect(url_for("main.dashboard"))
        elif not request.endpoint.startswith("setup."):
            return redirect(url_for("setup.db_step"))
        if request.endpoint != "main.ids_rueckgabe":      # kommt vom Shop (anderer Absender), geschützt durch einmaligen Token
            security.check_csrf()

    @app.teardown_request
    def _teardown(exc):
        s = g.pop("db", None)
        if s is not None:
            if exc:
                s.rollback()
            s.close()

    @app.errorhandler(403)
    def _403(e):
        return render_template("fehler.html", titel="Kein Zugriff", text="Dafür fehlt deinem Benutzer die Berechtigung."), 403

    @app.errorhandler(404)
    def _404(e):
        return render_template("fehler.html", titel="Nicht gefunden", text="Diese Seite oder dieser Eintrag existiert nicht."), 404

    @app.errorhandler(400)
    def _400(e):
        return render_template("fehler.html", titel="Ungültige Anfrage", text=getattr(e, "description", "")), 400

    return app

import functools
import secrets
import time

from cryptography.fernet import Fernet, InvalidToken
from flask import abort, current_app, g, redirect, request, session, url_for


def _fernet():
    from . import config
    return Fernet(config.fernet_key(current_app.extensions["cfg"]["secret_key"]))


def encrypt(text):
    return _fernet().encrypt(text.encode()).decode() if text else None


def decrypt(token):
    try:
        return _fernet().decrypt(token.encode()).decode() if token else ""
    except InvalidToken:
        return ""


def csrf_token():
    if "_csrf" not in session:
        session["_csrf"] = secrets.token_hex(16)
    return session["_csrf"]


def check_csrf():
    if request.method == "POST":
        sent = request.form.get("_csrf", "")
        if not sent or not secrets.compare_digest(sent, session.get("_csrf", "")):
            abort(400, "Ungültiges Formular. Seite neu laden und erneut versuchen.")


def login_required(f):
    @functools.wraps(f)
    def wrapper(*a, **kw):
        if not g.user:
            return redirect(url_for("main.login", next=request.full_path.rstrip("?")))
        return f(*a, **kw)
    return wrapper


def roles(*allowed):
    def deco(f):
        @functools.wraps(f)
        def wrapper(*a, **kw):
            if not g.user:
                return redirect(url_for("main.login", next=request.full_path.rstrip("?")))
            if g.user.role not in allowed:
                abort(403)
            return f(*a, **kw)
        return wrapper
    return deco


edit_required = roles("admin", "einkaeufer")
admin_required = roles("admin")

_fails = {}


def login_blocked(ip):
    now = time.time()
    _fails[ip] = [t for t in _fails.get(ip, []) if now - t < 300]
    return len(_fails[ip]) >= 10


def login_failed(ip):
    _fails.setdefault(ip, []).append(time.time())

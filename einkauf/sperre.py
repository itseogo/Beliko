"""Bearbeitungssperre (Pessimistic Lock) + Versionsprüfung (Optimistic Locking).

Wenn ein Benutzer einen Datensatz zum Bearbeiten öffnet, wird eine zeitlich begrenzte
Sperre hinterlegt. Andere Benutzer erhalten beim Öffnen eine klare Benachrichtigung,
welcher Benutzer den Datensatz gerade geöffnet hat / bearbeitet und seit wann.
"""
from datetime import datetime, timedelta

from .models import EditLock

SPERR_MINUTEN = 3

TYPEN_NAMEN = {
    "projekt": "Das Projekt",
    "bestellung": "Die Bestellung",
    "kontakt": "Der Kontakt",
    "lieferant": "Der Lieferant",
    "lex_beleg": "Der Lexoffice-Beleg",
}


def alle_freigeben(session):
    """Gibt alle aktiven Bearbeitungssperren frei."""
    return session.query(EditLock).delete()


def verlaengern(session, obj_typ, obj_id, user, minuten=SPERR_MINUTEN):
    """Verlängert die Sperre für den aktuellen Benutzer (Heartbeat)."""
    bereinigen(session)
    jetzt = datetime.now()
    ablauf = jetzt + timedelta(minutes=minuten)
    lock = session.query(EditLock).filter(
        EditLock.obj_typ == obj_typ, EditLock.obj_id == obj_id, EditLock.user_id == user.id
    ).first()
    if lock:
        lock.ablauf = ablauf
        session.flush()
        return True
    return False


def bereinigen(session):
    """Entfernt abgelaufene Sperren."""
    jetzt = datetime.now()
    session.query(EditLock).filter(EditLock.ablauf < jetzt).delete()


def pruefen(session, obj_typ, obj_id, user):
    """Gibt eine aktive Sperre eines anderen Benutzers zurück, sonst None."""
    bereinigen(session)
    lock = session.query(EditLock).filter(
        EditLock.obj_typ == obj_typ, EditLock.obj_id == obj_id
    ).first()
    if lock and lock.user_id != user.id:
        return lock
    return None


def holen(session, obj_typ, obj_id, user, minuten=SPERR_MINUTEN):
    """Versucht eine Sperre für `user` zu setzen/zu verlängern.

    Rückgabe: (ok: bool, lock: EditLock)
      ok=True  -> Sperre gehört `user`
      ok=False -> ein anderer Benutzer hält die Sperre (`lock.username`)
    """
    bereinigen(session)
    jetzt = datetime.now()
    ablauf = jetzt + timedelta(minutes=minuten)
    lock = session.query(EditLock).filter(
        EditLock.obj_typ == obj_typ, EditLock.obj_id == obj_id
    ).first()
    if lock:
        if lock.user_id != user.id:
            return False, lock
        lock.ablauf = ablauf
        lock.username = user.username
        session.flush()
        return True, lock
    lock = EditLock(
        obj_typ=obj_typ, obj_id=obj_id, user_id=user.id,
        username=user.username, seit=jetzt, ablauf=ablauf,
    )
    session.add(lock)
    session.flush()
    return True, lock


def freigeben(session, obj_typ, obj_id, user=None, force=False):
    """Gibt eine Sperre wieder frei (nur eigene, oder beliebig mit force=True)."""
    q = session.query(EditLock).filter(EditLock.obj_typ == obj_typ, EditLock.obj_id == obj_id)
    if not force and user is not None:
        q = q.filter(EditLock.user_id == user.id)
    return q.delete()


def freigeben_nutzer(session, user_id):
    """Gibt alle Sperren eines Benutzers frei (z. B. beim Abmelden)."""
    return session.query(EditLock).filter(EditLock.user_id == user_id).delete()


def meldung(obj_typ, lock):
    """Verständliche Benachrichtigung, warum nicht geöffnet/gespeichert werden kann."""
    was = TYPEN_NAMEN.get(obj_typ, "Der Eintrag")
    seit = lock.seit.strftime("%H:%M") if lock.seit else "?"
    bis = lock.ablauf.strftime("%H:%M") if lock.ablauf else "?"
    return (f"{was} ist gesperrt: Wird gerade von Benutzer „{lock.username}“ "
            f"(seit {seit} Uhr, gültig bis {bis} Uhr) bearbeitet und kann derzeit nicht geöffnet werden.")


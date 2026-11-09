"""Contrasenyes (Argon2id) i segon factor TOTP."""
import hmac
import os
import threading
import time

import pyotp
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

_ph = PasswordHasher()


class Overloaded(Exception):
    """Massa verificacions Argon2 alhora: el servidor respon 503 en lloc d'esgotar la memòria."""


# Argon2 gasta ~64 MiB per verificació: sense límit, N peticions en paral·lel són un DoS de memòria/CPU.
_gate = threading.BoundedSemaphore(int(os.environ.get("CLUB_ARGON_CONCURRENCY", "4")))
GATE_WAIT_SECONDS = 10


def _gated(fn, *a):
    if not _gate.acquire(timeout=GATE_WAIT_SECONDS):
        raise Overloaded()
    try:
        return fn(*a)
    finally:
        _gate.release()
MIN_PASSWORD_LEN = 12
MAX_PASSWORD_LEN = 200  # Argon2 amb entrades enormes seria una via de DoS


def hash_password(password: str) -> str:
    if len(password) < MIN_PASSWORD_LEN:
        raise ValueError(f"La contrasenya ha de tenir almenys {MIN_PASSWORD_LEN} caràcters")
    if len(password) > MAX_PASSWORD_LEN:
        raise ValueError(f"La contrasenya no pot passar de {MAX_PASSWORD_LEN} caràcters")
    return _gated(_ph.hash, password)


_dummy = None


def dummy_hash() -> str:
    """Hash de mentida per fer la mateixa feina quan l'usuari no existeix (evita deduir usuaris pel temps de resposta)."""
    global _dummy
    if _dummy is None:
        _dummy = _ph.hash("contrasenya-de-mentida-que-no-coincideix-mai")
    return _dummy


def hash_secret(text: str) -> str:
    """Hash Argon2 d'un valor curt (p. ex. un PIN ja barrejat amb pebre). No aplica la longitud mínima de les contrasenyes."""
    return _gated(_ph.hash, text)


def verify_password(password: str, hashed: str) -> bool:
    try:
        return _gated(_ph.verify, hashed, password)
    except VerifyMismatchError:
        return False


def new_totp_secret() -> str:
    return pyotp.random_base32()


def totp_step(secret: str, code: str) -> int | None:
    """Pas de temps (30 s) del codi si és vàlid (finestra ±1), o None."""
    t = pyotp.TOTP(secret)
    ara = time.time()
    for off in (-1, 0, 1):
        pas = int(ara // t.interval) + off
        if hmac.compare_digest(t.at(pas * t.interval), str(code or "")):
            return pas
    return None


def verify_totp(secret: str, code: str) -> bool:
    return totp_step(secret, code) is not None


def totp_replay_enabled() -> bool:
    return os.environ.get("CLUB_TOTP_REPLAY", "1") != "0"


def totp_consume(db, user_id: int, step: int) -> bool:
    """Antireutilització persistent: l'últim pas TOTP consumit viu a users.last_totp_step. L'UPDATE condicional és
    atòmic (dos intents simultanis amb el mateix codi: només un canvia la fila) i sobreviu a reinicis i a diversos workers.
    True si el pas és nou per a l'usuari; False si ja s'havia fet servir o és anterior. El canvi es confirma amb el
    commit del login."""
    if not totp_replay_enabled():
        return True
    from sqlalchemy import or_, update
    from .models import User
    r = db.execute(update(User).where(User.id == user_id, or_(User.last_totp_step.is_(None), User.last_totp_step < step))
                   .values(last_totp_step=step))
    return r.rowcount == 1

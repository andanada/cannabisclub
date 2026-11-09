"""Contrasenyes (Argon2id) i segon factor TOTP."""
import os
import threading

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


def verify_totp(secret: str, code: str) -> bool:
    return pyotp.TOTP(secret).verify(code, valid_window=1)

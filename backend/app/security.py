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


# Antireutilització del codi TOTP. LIMITACIÓ: no hi ha columna per desar l'últim pas per usuari (no es pot tocar
# models.py), així que es guarda en memòria del procés amb TTL: es perd en reiniciar i cada worker té el seu mapa.
# El TTL (>= 90 s) cobreix tota la finestra de validesa d'un codi (3 passos de 30 s).
TOTP_REPLAY_TTL = 120
_totp_usats: dict[int, tuple[int, float]] = {}
_totp_lock = threading.Lock()


def totp_replay_enabled() -> bool:
    return os.environ.get("CLUB_TOTP_REPLAY", "1") != "0"


def totp_consume(user_id: int, step: int) -> bool:
    """True si el pas és nou per a l'usuari (i el marca com a usat); False si ja s'havia fet servir o és anterior."""
    if not totp_replay_enabled():
        return True
    ara = time.monotonic()
    with _totp_lock:
        for k in [k for k, (_, exp) in _totp_usats.items() if exp < ara]:
            del _totp_usats[k]
        previ = _totp_usats.get(user_id)
        if previ and step <= previ[0]:
            return False
        _totp_usats[user_id] = (step, ara + TOTP_REPLAY_TTL)
        return True

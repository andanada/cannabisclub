"""Contrasenyes (Argon2id) i segon factor TOTP."""
import pyotp
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

_ph = PasswordHasher()
MIN_PASSWORD_LEN = 12


def hash_password(password: str) -> str:
    if len(password) < MIN_PASSWORD_LEN:
        raise ValueError(f"La contrasenya ha de tenir almenys {MIN_PASSWORD_LEN} caràcters")
    return _ph.hash(password)


_dummy = None


def dummy_hash() -> str:
    """Hash de mentida per fer la mateixa feina quan l'usuari no existeix (evita deduir usuaris pel temps de resposta)."""
    global _dummy
    if _dummy is None:
        _dummy = _ph.hash("contrasenya-de-mentida-que-no-coincideix-mai")
    return _dummy


def hash_secret(text: str) -> str:
    """Hash Argon2 d'un valor curt (p. ex. un PIN ja barrejat amb pebre). No aplica la longitud mínima de les contrasenyes."""
    return _ph.hash(text)


def verify_password(password: str, hashed: str) -> bool:
    try:
        return _ph.verify(hashed, password)
    except VerifyMismatchError:
        return False


def new_totp_secret() -> str:
    return pyotp.random_base32()


def verify_totp(secret: str, code: str) -> bool:
    return pyotp.TOTP(secret).verify(code, valid_window=1)

"""Xifrat de camps sensibles (Fernet). La clau ve de l'entorn, mai del repo ni de la base de dades."""
import os
from cryptography.fernet import Fernet, InvalidToken


class KeyMissing(RuntimeError):
    pass


def _fernet() -> Fernet:
    key = os.environ.get("CLUB_FIELD_KEY")
    if not key:
        raise KeyMissing("Falta CLUB_FIELD_KEY (genera-la amb generate_key() i desa-la fora del repo)")
    return Fernet(key.encode())


def generate_key() -> str:
    return Fernet.generate_key().decode()


def encrypt(text: str | None) -> str | None:
    if text is None:
        return None
    return _fernet().encrypt(text.encode()).decode()


def decrypt(token: str | None) -> str | None:
    if token is None:
        return None
    try:
        return _fernet().decrypt(token.encode()).decode()
    except InvalidToken as exc:
        raise ValueError("Camp xifrat il·legible: clau incorrecta o dada alterada") from exc

"""Text informatiu de protecció de dades, versionat. Cada versió viu a textos/<versio>/<idioma>.txt i no es modifica
mai un cop publicada: un canvi de text és una versió nova (v2…). El consentiment desa la versió i el SHA-256 del text."""
import hashlib
from functools import lru_cache
from pathlib import Path

VERSIO_ACTUAL = "v2"
IDIOMES = ("ca", "es", "en")
FINALITATS = ("basic", "foto", "contacte", "consum")
_ARREL = Path(__file__).resolve().parent


def versions() -> list[str]:
    return sorted(p.name for p in _ARREL.iterdir() if p.is_dir() and not p.name.startswith("_"))


@lru_cache(maxsize=None)
def text(versio: str, idioma: str = "ca") -> str:
    if idioma not in IDIOMES or versio not in versions():
        raise ValueError("Text informatiu inexistent")
    return (_ARREL / versio / f"{idioma}.txt").read_text(encoding="utf-8")


def sha256(versio: str, idioma: str = "ca") -> str:
    return hashlib.sha256(text(versio, idioma).encode("utf-8")).hexdigest()


def hashes(versio: str) -> dict[str, str]:
    return {i: sha256(versio, i) for i in IDIOMES}


def idioma_del_hash(versio: str, h: str) -> str | None:
    return next((i for i, x in hashes(versio).items() if x == h), None)

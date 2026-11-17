"""Versió desplegada: el primer mot del fitxer VERSION de l'arrel del programa (l'escriu scripts/deploy.sh).
/salut la porta perquè el desplegament pugui comprovar que respon el codi NOU (i no el vell, que encara no s'ha reiniciat)."""
from pathlib import Path

ARREL = Path(__file__).resolve().parents[2]


def actual(arrel: Path = ARREL) -> str:
    try:
        mots = (arrel / "VERSION").read_text(encoding="utf-8").split()
    except OSError:
        return "desconeguda"
    return mots[0][:40] if mots and mots[0].isalnum() else "desconeguda"

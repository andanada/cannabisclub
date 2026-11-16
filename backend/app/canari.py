"""Canari de claus.

Tres claus de l'entorn (CLUB_FIELD_KEY, CLUB_INDEX_KEY i la d'auditoria) han de ser SEMPRE les mateixes que van crear les dades.
Si el servei arrenca amb unes altres (el `app.env` de proves que passa a producció, una clau copiada malament, una restauració
sense les claus bones), passa en silenci el pitjor: llegir dóna 422 «camp il·legible», escriure barreja claus dins la BD,
els duplicats de document no es detecten i la cadena d'auditoria es trenca per sempre.

Aquí la BD recorda la «marca» de cada clau la primera vegada que arrenca el servei (taula d'afegir, `config_canari`). A partir
d'aquí, cada arrencada la comprova i, si no quadra, **s'atura amb un missatge clar** abans de tocar res.
"""
import hashlib
import hmac

from sqlalchemy import select

from . import audit, crypto, service
from .models import ConfigCanari

TEXT = "club-canari"


def _marques() -> dict[str, str]:
    """Valors esperats segons les claus de l'entorn ARA. Falla (RuntimeError) si en falta alguna."""
    try:
        camp = crypto.encrypt(TEXT)
    except crypto.KeyMissing as e:
        raise RuntimeError(str(e)) from e
    return {
        "field": camp,   # no és comparable (Fernet és aleatori): es comprova desxifrant el que hi ha desat
        "index": hmac.new(service._index_key(), b"canari|index", hashlib.sha256).hexdigest(),
        "audit": hmac.new(audit.audit_key(), b"canari|audit", hashlib.sha256).hexdigest(),
    }


NOM_CLAU = {"field": "CLUB_FIELD_KEY", "index": "CLUB_INDEX_KEY", "audit": "CLUB_AUDIT_KEY (o CLUB_INDEX_KEY, de la qual es deriva)"}


def comprova(factory) -> str:
    """'creat' si és la primera vegada (es desa la marca), 'ok' si les claus quadren. Si no quadren, RuntimeError."""
    ara = _marques()
    with factory() as s:
        desades = {c.clau: c.valor for c in s.scalars(select(ConfigCanari))}
        if not desades:
            for clau, valor in ara.items():
                s.add(ConfigCanari(clau=clau, valor=valor))
            s.commit()
            return "creat"
        malament = []
        if "field" not in desades or not _camp_quadra(desades["field"]):
            malament.append("field")
        for clau in ("index", "audit"):
            if desades.get(clau) != ara[clau]:
                malament.append(clau)
    if malament:
        noms = ", ".join(NOM_CLAU[c] for c in malament)
        raise RuntimeError(
            f"Les claus de l'entorn NO són les amb què es va crear aquesta base de dades: {noms}. El servei no arrenca perquè "
            "barrejaria claus a les dades (camps il·legibles, duplicats sense detectar, auditoria trencada). Restaura les claus "
            "correctes (paquet de claus de la còpia, docs/COPIES.md) o apunta a la base de dades que toca.")
    return "ok"


def _camp_quadra(token: str) -> bool:
    try:
        return crypto.decrypt(token) == TEXT
    except (ValueError, crypto.KeyMissing):
        return False

"""Ajustos opcionals per local (taula clau/valor). Tot té un valor per defecte: un local sense ajustos
es comporta com abans."""
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import service
from .models import LocalSetting, User

DEFECTES = {"quota_obligatoria": False, "quota_cent": None, "quota_mesos": 1}
MAX_QUOTA_CENT = 1_000_000


def _parse(clau: str, valor: str):
    if clau == "quota_obligatoria":
        return valor == "1"
    return int(valor)


def get(db: Session, local_id: int) -> dict:
    out = dict(DEFECTES)
    for r in db.scalars(select(LocalSetting).where(LocalSetting.local_id == local_id)):
        if r.clau in DEFECTES:
            out[r.clau] = _parse(r.clau, r.valor)
    return out


def _validate(clau: str, valor) -> None:
    if clau == "quota_cent" and valor is not None and not 0 < valor <= MAX_QUOTA_CENT:
        raise ValueError("L'import de la quota ha d'estar entre 0,01 € i 10.000 €")
    if clau == "quota_mesos" and not 1 <= valor <= 24:
        raise ValueError("Els mesos de la quota han d'estar entre 1 i 24")


def set_(db: Session, actor: User, local_id: int, canvis: dict) -> dict:
    """Desa els ajustos indicats (els que valen None es deixen com estan, excepte quota_cent que s'esborra amb 0)."""
    aplicats = {}
    for clau, valor in canvis.items():
        if clau not in DEFECTES or valor is None:
            continue
        if clau == "quota_cent" and valor == 0:
            fila = db.get(LocalSetting, (local_id, clau))
            if fila:
                db.delete(fila)
            aplicats[clau] = None
            continue
        _validate(clau, valor)
        text = ("1" if valor else "0") if clau == "quota_obligatoria" else str(int(valor))
        fila = db.get(LocalSetting, (local_id, clau))
        if fila:
            fila.valor = text
        else:
            db.add(LocalSetting(local_id=local_id, clau=clau, valor=text))
        aplicats[clau] = valor
    if not aplicats:
        raise ValueError("No hi ha cap ajust per desar")
    service.audit_append(db, {"accio": "canvi_ajustos", "local": local_id, "ajustos": aplicats, "per": actor.id})
    db.commit()
    return get(db, local_id)

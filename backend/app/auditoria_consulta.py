"""Consulta de l'auditoria filtrada i paginada (només administradors) i «qui ha accedit a les dades d'aquest soci».
Les entrades no contenen dades personals en clar; el filtre per soci/usuari/acció es fa sobre el JSON canònic."""
import json
from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from .csvutil import to_csv
from .models import AuditLog, User
from .stock import TZ


def _dia_local(d: date) -> datetime:
    return datetime.combine(d, time.min, tzinfo=TZ).astimezone(timezone.utc)

MAX_LIMIT = 500
# accions que són un ACCÉS a dades personals d'un soci (lectura o exportació)
ACCIONS_ACCES = ("consulta_soci", "consulta_quotes", "consulta_consum", "consulta_foto", "consulta_signatura",
                 "exporta_soci", "exporta_consum_soci", "cerca_soci", "cerca_carnet")


def _num(clau: str, n: int):
    return or_(AuditLog.payload.like(f'%"{clau}":{int(n)},%'), AuditLog.payload.like(f'%"{clau}":{int(n)}}}%'))


def _cond(soci: int | None, usuari: int | None, accio: str | None, des: date | None, fins: date | None):
    c = []
    if soci is not None:
        c.append(_num("soci", soci))
    if usuari is not None:
        c.append(_num("per", usuari))
    if accio:
        if not accio.replace("_", "").isalnum():
            raise ValueError("Acció no vàlida")
        c.append(AuditLog.payload.like(f'%"accio":"{accio}"%'))
    # Dies en hora local (Europe/Madrid), com a caixa, informes i llibres.
    if des:
        c.append(AuditLog.ts >= _dia_local(des))
    if fins:
        c.append(AuditLog.ts < _dia_local(fins + timedelta(days=1)))
    return c


def _row(r: AuditLog, noms: dict[int, str]) -> dict:
    p = json.loads(r.payload)
    return {"seq": r.seq, "ts": r.ts.isoformat(), "accio": p.get("accio"), "soci": p.get("soci"), "per": p.get("per"),
            "per_usuari": noms.get(p.get("per")), "detall": {k: v for k, v in p.items() if k not in ("accio", "soci", "per", "_alg")}}


def query(db: Session, soci=None, usuari=None, accio=None, des=None, fins=None, limit: int = 100, offset: int = 0) -> dict:
    limit = max(1, min(int(limit), MAX_LIMIT))
    c = _cond(soci, usuari, accio, des, fins)
    q = select(AuditLog).order_by(AuditLog.seq.desc())
    if c:
        q = q.where(and_(*c))
    files = db.scalars(q.offset(max(0, int(offset))).limit(limit + 1)).all()
    noms = {i: n for i, n in db.execute(select(User.id, User.username))}
    return {"entrades": [_row(f, noms) for f in files[:limit]], "limit": limit, "offset": max(0, int(offset)), "hi_ha_mes": len(files) > limit}


def entrades_del_soci(db: Session, member_id: int, limit: int = 5000) -> list[dict]:
    noms = {i: n for i, n in db.execute(select(User.id, User.username))}
    return [_row(f, noms) for f in db.scalars(select(AuditLog).where(_num("soci", member_id)).order_by(AuditLog.seq).limit(limit))]


def accessos_al_soci(db: Session, member_id: int) -> list[dict]:
    """Qui ha consultat o exportat les dades del soci (usuari, acció i data)."""
    return [e for e in entrades_del_soci(db, member_id) if e["accio"] in ACCIONS_ACCES]


def accessos_csv(files: list[dict]) -> str:
    return to_csv(["seq", "data", "accio", "usuari_id", "usuari"], [[f["seq"], f["ts"], f["accio"], f["per"], f["per_usuari"]] for f in files])

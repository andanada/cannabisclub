"""Política de retenció: llista els socis candidats a supressió i purga el que ha vençut (fotos velles, intents de
login, sessions caducades). No fa res destructiu si no es demana `aplicar=True` (script: scripts/club-retencio.py --aplicar)."""
import os
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from . import service, supressio
from .models import LoginAttempt, Member, MemberPhoto, SessionToken


def _dies(nom: str, defecte: int) -> int:
    v = os.environ.get(nom, "").strip()
    return int(v) if v.isdigit() else defecte


def config() -> dict:
    return {"min_dies_baixa": supressio.retencio_min_dies(), "fotos_velles_dies": _dies("CLUB_RETENCIO_FOTOS_DIES", 365),
            "intents_login_dies": _dies("CLUB_RETENCIO_INTENTS_DIES", 30)}


def candidates(db: Session, local_id: int | None = None) -> list[dict]:
    """Socis de baixa encara no suprimits. Només ids i dates (cap dada personal)."""
    ara = datetime.now(timezone.utc)
    q = select(Member).where(Member.estat == "baixa", Member.suprimit_en.is_(None)).order_by(Member.id)
    if local_id is not None:
        q = q.where(Member.local_id == local_id)
    out = []
    for m in db.scalars(q):
        baixa = supressio.baixa_date(db, m)
        b = supressio.bloqueig(db, m, ara)
        out.append({"soci": m.id, "local": m.local_id, "baixa": baixa.isoformat() if baixa else None,
                    "dies_des_de_la_baixa": (ara - baixa).days if baixa else None, "suprimible": b is None, "bloqueig": b})
    return out


def _fotos_velles(db: Session, tall: datetime) -> int:
    ultimes = {m: i for m, i in db.execute(select(MemberPhoto.member_id, func.max(MemberPhoto.id)).group_by(MemberPhoto.member_id))}
    return sum(1 for fid, mid, ts, enc in db.execute(select(MemberPhoto.id, MemberPhoto.member_id, MemberPhoto.ts, MemberPhoto.img_enc)).all()
               if enc != "" and supressio._aware(ts) < tall and ultimes[mid] > fid)


def run(db: Session, actor_id: int | None = None, aplicar: bool = False, local_id: int | None = None) -> dict:
    cfg = config()
    ara = datetime.now(timezone.utc)
    cands = candidates(db, local_id)
    tall_fotos = ara - timedelta(days=cfg["fotos_velles_dies"])
    tall_intents = ara - timedelta(days=cfg["intents_login_dies"])
    fotos = _fotos_velles(db, tall_fotos)
    intents = db.scalar(select(func.count()).select_from(LoginAttempt).where(LoginAttempt.ts < tall_intents)) or 0
    sessions = db.scalar(select(func.count()).select_from(SessionToken).where(SessionToken.expires_at < ara)) or 0
    informe = {"aplicat": aplicar, "config": cfg, "candidats": cands, "suprimibles": sum(1 for c in cands if c["suprimible"]),
               "fotos_velles": fotos, "intents_login": intents, "sessions_caducades": sessions, "suprimits": []}
    if not aplicar:
        return informe
    for c in cands:
        if c["suprimible"]:
            informe["suprimits"].append(supressio.pseudonymize(db, actor_id, db.get(Member, c["soci"]), "retencio"))
    informe["fotos_velles"] = supressio.buida_binaris(db, 0, "fotos_velles", tall_fotos) if fotos else 0
    informe["intents_login"] = db.execute(delete(LoginAttempt).where(LoginAttempt.ts < tall_intents)).rowcount or 0
    informe["sessions_caducades"] = db.execute(delete(SessionToken).where(SessionToken.expires_at < ara)).rowcount or 0
    service.audit_append(db, {"accio": "retencio", "suprimits": len(informe["suprimits"]), "fotos": informe["fotos_velles"],
                              "intents": informe["intents_login"], "sessions": informe["sessions_caducades"], "per": actor_id})
    db.commit()
    return informe

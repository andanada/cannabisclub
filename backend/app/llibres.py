"""Llibres exportables i signats (CSV): llibre de socis (altes/baixes) i llibre d'entrades/sortides de producte.
Cada exportació calcula el SHA-256 del contingut exacte i el deixa a l'auditoria, de manera que es pot comprovar més
endavant que un fitxer no ha estat alterat (`verify`). Els camps lliures (nota, concepte, motiu) passen per
`csvutil.cell`, que neutralitza les fórmules de full de càlcul. Cap llibre porta dades personals del soci: només el seu id."""
import hashlib
import json
import re
from datetime import date, datetime, time, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import service
from .csvutil import to_csv
from .models import AuditLog, Batch, Member, MovementBatch, Product, StockMovement, User

ACCIONS_SOCI = ("alta_soci", "canvi_estat_soci", "aprova_soci", "supressio_soci")


def _lim(des: date, fins: date):
    return (datetime.combine(des, time.min, tzinfo=timezone.utc), datetime.combine(fins, time.max, tzinfo=timezone.utc))


def members_book(db: Session, local_id: int, des: date, fins: date) -> str:
    a, b = _lim(des, fins)
    noms = {i: n for i, n in db.execute(select(User.id, User.username))}
    locals_ = {i: l for i, l in db.execute(select(Member.id, Member.local_id))}
    rows = []
    for r in db.scalars(select(AuditLog).where(AuditLog.ts >= a, AuditLog.ts <= b).order_by(AuditLog.seq)):
        p = json.loads(r.payload)
        if p.get("accio") not in ACCIONS_SOCI or locals_.get(p.get("soci")) != local_id:
            continue
        esdeveniment = {"alta_soci": "alta", "aprova_soci": "aprovacio", "supressio_soci": "supressio",
                        "canvi_estat_soci": f"estat {p.get('de')} -> {p.get('a')}"}[p["accio"]]
        rows.append([r.seq, r.ts.isoformat(), p["soci"], esdeveniment, noms.get(p.get("per")), p.get("motiu") or ""])
    return to_csv(["seq_auditoria", "data", "soci_id", "esdeveniment", "usuari", "motiu"], rows)


def stock_book(db: Session, local_id: int, des: date, fins: date) -> str:
    a, b = _lim(des, fins)
    noms = {i: n for i, n in db.execute(select(User.id, User.username))}
    lots = {}
    for mb, bt in db.execute(select(MovementBatch, Batch).join(Batch, Batch.id == MovementBatch.batch_id)):
        lots.setdefault(mb.movement_id, []).append(f"{bt.codi}:{mb.mg}")
    q = (select(StockMovement, Product.nom).join(Product, Product.id == StockMovement.product_id)
         .where(StockMovement.local_id == local_id, StockMovement.ts >= a, StockMovement.ts <= b).order_by(StockMovement.id))
    rows = [[m.id, m.ts.isoformat(), m.tipus, nom, m.delta_mg, ";".join(lots.get(m.id, [])), m.member_id or "", m.corregeix_id or "",
             noms.get(m.user_id), m.nota or ""] for m, nom in db.execute(q)]
    return to_csv(["moviment", "data", "tipus", "producte", "delta_mg", "lots(codi:mg)", "soci_id", "corregeix_id", "usuari", "nota"], rows)


def sign_and_log(db: Session, actor: User, llibre: str, local_id: int, des: date, fins: date, csv_text: str) -> str:
    h = hashlib.sha256(csv_text.encode("utf-8")).hexdigest()
    service.audit_append(db, {"accio": "exporta_llibre", "llibre": llibre, "local": local_id, "des": des.isoformat(),
                              "fins": fins.isoformat(), "sha256": h, "files": max(0, csv_text.count("\n") - 1), "per": actor.id})
    db.commit()
    return h


def verify(db: Session, sha256: str) -> list[dict]:
    """Exportacions registrades amb aquest hash (buit = ningú l'ha generat: contingut desconegut o alterat)."""
    if not re.fullmatch(r"[0-9a-f]{64}", sha256 or ""):
        return []
    out = []
    for r in db.scalars(select(AuditLog).where(AuditLog.payload.like('%"accio":"exporta_llibre"%'), AuditLog.payload.like(f'%"sha256":"{sha256}"%'))):
        p = json.loads(r.payload)
        out.append({"seq": r.seq, "ts": r.ts.isoformat(), "llibre": p["llibre"], "local": p["local"], "des": p["des"], "fins": p["fins"], "per": p["per"]})
    return out

"""Informes de socis: evolució del club (altes, baixes, renovacions), demografia i historial de consum.
Només sortida agregada o de moviments: cap nom ni document de cap soci."""
import json
from collections import defaultdict
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import crypto
from .cash import _range
from .csvutil import to_csv
from .models import AuditLog, Member, Product, Quota, StockMovement
from .stock import TZ

FRANGES = [(18, 24), (25, 34), (35, 44), (45, 54), (55, 64), (65, 200)]


def _mes(ts: datetime) -> str:
    return ts.replace(tzinfo=ts.tzinfo or timezone.utc).astimezone(TZ).strftime("%Y-%m")


def _g(mg: int) -> str:
    return str(Decimal(mg) / 1000)


def evolution(db: Session, local_id: int, des: date, fins: date, usuari=None) -> dict:
    a, b = _range(des, fins)
    mesos: dict[str, dict] = defaultdict(lambda: {"altes": 0, "baixes": 0, "quotes_noves": 0, "renovacions": 0})
    socis = {m.id: m for m in db.scalars(select(Member).where(Member.local_id == local_id))}
    for m in socis.values():
        if a <= m.creat.replace(tzinfo=m.creat.tzinfo or timezone.utc) < b:
            mesos[_mes(m.creat)]["altes"] += 1
    # Baixes: el canvi d'estat a «baixa» queda a l'auditoria (només d'afegir) amb la data real.
    for fila in db.scalars(select(AuditLog).where(AuditLog.ts >= a, AuditLog.ts < b).order_by(AuditLog.seq)):
        try:
            p = json.loads(fila.payload)
        except ValueError:
            continue
        if p.get("accio") == "canvi_estat_soci" and p.get("a") == "baixa" and p.get("soci") in socis:
            mesos[_mes(fila.ts)]["baixes"] += 1
    # Quotes: la primera quota d'un soci és «nova»; les següents, renovacions.
    vistos: set[int] = set()
    for q in db.scalars(select(Quota).where(Quota.local_id == local_id).order_by(Quota.ts, Quota.id)):
        ts = q.ts.replace(tzinfo=q.ts.tzinfo or timezone.utc)
        nova = q.member_id not in vistos
        vistos.add(q.member_id)
        if a <= ts < b:
            mesos[_mes(q.ts)]["quotes_noves" if nova else "renovacions"] += 1
    files = [{"mes": k, **v} for k, v in sorted(mesos.items())]
    total = {c: sum(f[c] for f in files) for c in ("altes", "baixes", "quotes_noves", "renovacions")}
    estat = {"actiu": 0, "suspes": 0, "baixa": 0}
    for m in socis.values():
        estat[m.estat] = estat.get(m.estat, 0) + 1
    return {"des": des.isoformat(), "fins": fins.isoformat(), "mesos": files, "total": total, "estat_actual": estat}


def evolution_csv(r: dict) -> str:
    return to_csv(["mes", "altes", "baixes", "quotes_noves", "renovacions"],
                  [[f["mes"], f["altes"], f["baixes"], f["quotes_noves"], f["renovacions"]] for f in r["mesos"]])


def _edat(naixement: date, avui: date) -> int:
    return avui.year - naixement.year - ((avui.month, avui.day) < (naixement.month, naixement.day))


def demographics(db: Session, local_id: int) -> dict:
    """Franges d'edat dels socis que no són de baixa. Es desxifra la data de naixement en memòria i només se'n torna el recompte."""
    avui = datetime.now(TZ).date()
    edats = []
    for m in db.scalars(select(Member).where(Member.local_id == local_id, Member.estat != "baixa")):
        try:
            edats.append(_edat(date.fromisoformat(crypto.decrypt(m.naixement_enc)), avui))
        except ValueError:
            continue
    franges = [{"franja": f"{a}-{b}" if b < 100 else f"{a}+", "socis": sum(1 for e in edats if a <= e <= b)} for a, b in FRANGES]
    return {"total": len(edats), "edat_mitjana": round(sum(edats) / len(edats), 1) if edats else 0, "franges": franges}


def demographics_csv(r: dict) -> str:
    return to_csv(["franja", "socis"], [[f["franja"], f["socis"]] for f in r["franges"]])


def consumption(db: Session, member: Member, des: date, fins: date) -> dict:
    """Dispensacions d'un soci en un rang (les corregides surten marcades i no compten als totals)."""
    a, b = _range(des, fins)
    rows = db.execute(
        select(StockMovement, Product.nom).join(Product, Product.id == StockMovement.product_id)
        .where(StockMovement.member_id == member.id, StockMovement.tipus.in_(["dispensacio", "correccio"]),
               StockMovement.ts >= a, StockMovement.ts < b).order_by(StockMovement.id.desc())).all()
    corregides = {m.corregeix_id for m, _ in rows if m.tipus == "correccio"}
    llista, per_producte = [], defaultdict(lambda: {"mg": 0, "cent": 0})
    mg_t = cent_t = n = 0
    for m, nom in rows:
        if m.tipus == "dispensacio":
            corregida = m.id in corregides
            llista.append({"id": m.id, "ts": m.ts.replace(tzinfo=m.ts.tzinfo or timezone.utc).isoformat(), "producte": nom,
                           "grams": _g(-m.delta_mg), "import_cent": m.import_cent or 0, "corregida": corregida})
            if not corregida:
                per_producte[nom]["mg"] += -m.delta_mg
                per_producte[nom]["cent"] += m.import_cent or 0
                mg_t, cent_t, n = mg_t + -m.delta_mg, cent_t + (m.import_cent or 0), n + 1
    return {"des": des.isoformat(), "fins": fins.isoformat(), "dispensacions": llista,
            "productes": [{"producte": k, "grams": _g(v["mg"]), "import_cent": v["cent"]} for k, v in sorted(per_producte.items())],
            "total": {"grams": _g(mg_t), "import_cent": cent_t, "dispensacions": n}}

from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import service
from .csvutil import to_csv
from .models import CashEntry, CashSession, Product, StockMovement, User
from .stock import TZ

METODES = {"efectiu", "targeta"}


def open_session(db: Session, actor: User, local_id: int, opening_cent: int) -> CashSession:
    if opening_cent < 0:
        raise ValueError("L'import d'obertura no pot ser negatiu")
    if current_session(db, local_id):
        raise ValueError("Ja hi ha una caixa oberta en aquest local")
    cs = CashSession(local_id=local_id, opened_by=actor.id, opening_cent=opening_cent)
    db.add(cs)
    db.flush()
    service.audit_append(db, {"accio": "obrir_caixa", "sessio": cs.id, "local": local_id, "cent": opening_cent, "per": actor.id})
    db.commit()
    return cs


def current_session(db: Session, local_id: int) -> CashSession | None:
    return db.scalar(select(CashSession).where(CashSession.local_id == local_id, CashSession.closed_at.is_(None)))


def _require_open(db: Session, local_id: int) -> CashSession:
    cs = current_session(db, local_id)
    if not cs:
        raise ValueError("No hi ha cap caixa oberta en aquest local")
    return cs


def expected_cash(db: Session, cs: CashSession) -> int:
    return cs.opening_cent + db.scalar(select(func.coalesce(func.sum(CashEntry.import_cent), 0)).where(
        CashEntry.session_id == cs.id, CashEntry.metode == "efectiu"))


def close_session(db: Session, actor: User, local_id: int, counted_cent: int) -> CashSession:
    cs = _require_open(db, local_id)
    if counted_cent < 0:
        raise ValueError("L'import comptat no pot ser negatiu")
    cs.expected_cent = expected_cash(db, cs)
    cs.counted_cent = counted_cent
    cs.diff_cent = counted_cent - cs.expected_cent
    cs.closed_at = datetime.now(timezone.utc)
    cs.closed_by = actor.id
    service.audit_append(db, {"accio": "tancar_caixa", "sessio": cs.id, "esperat": cs.expected_cent,
                              "comptat": counted_cent, "diferencia": cs.diff_cent, "per": actor.id})
    db.commit()
    return cs


def charge(db: Session, actor: User, movement_id: int, metode: str) -> CashEntry:
    if metode not in METODES:
        raise ValueError("Mètode de pagament no vàlid")
    mv = db.get(StockMovement, movement_id)
    if not mv or mv.tipus != "dispensacio":
        raise ValueError("Només es poden cobrar dispensacions")
    if db.scalar(select(StockMovement.id).where(StockMovement.corregeix_id == mv.id)):
        raise ValueError("La dispensació està corregida")
    cs = _require_open(db, mv.local_id)
    if db.scalar(select(CashEntry.id).where(CashEntry.movement_id == mv.id)):
        raise ValueError("Aquesta dispensació ja està cobrada")
    e = CashEntry(local_id=mv.local_id, session_id=cs.id, tipus="cobrament", metode=metode,
                  import_cent=mv.import_cent or 0, movement_id=mv.id, user_id=actor.id)
    db.add(e)
    db.flush()
    service.audit_append(db, {"accio": "cobrament", "apunt": e.id, "moviment": mv.id, "cent": e.import_cent, "metode": metode, "per": actor.id})
    db.commit()
    return e


def expense(db: Session, actor: User, local_id: int, cent: int, metode: str, categoria: str, concepte: str) -> CashEntry:
    if cent <= 0:
        raise ValueError("L'import de la despesa ha de ser positiu")
    if metode not in METODES:
        raise ValueError("Mètode de pagament no vàlid")
    cs = _require_open(db, local_id)
    e = CashEntry(local_id=local_id, session_id=cs.id, tipus="despesa", metode=metode, import_cent=-cent,
                  categoria=categoria, concepte=concepte, user_id=actor.id)
    db.add(e)
    db.flush()
    service.audit_append(db, {"accio": "despesa", "apunt": e.id, "cent": cent, "categoria": categoria, "per": actor.id})
    db.commit()
    return e


def correct_entry(db: Session, actor: User, entry_id: int, concepte: str) -> CashEntry:
    orig = db.get(CashEntry, entry_id)
    if not orig:
        raise ValueError("Apunt inexistent")
    if orig.tipus == "correccio":
        raise ValueError("Una correcció no es pot corregir")
    if db.scalar(select(CashEntry.id).where(CashEntry.corregeix_id == orig.id)):
        raise ValueError("Aquest apunt ja està corregit")
    cs = _require_open(db, orig.local_id)
    e = CashEntry(local_id=orig.local_id, session_id=cs.id, tipus="correccio", metode=orig.metode,
                  import_cent=-orig.import_cent, categoria=orig.categoria, concepte=concepte,
                  corregeix_id=orig.id, user_id=actor.id)
    db.add(e)
    db.flush()
    service.audit_append(db, {"accio": "correccio_caixa", "apunt": e.id, "corregeix": orig.id, "per": actor.id})
    db.commit()
    return e


def _range(des: date, fins: date) -> tuple[datetime, datetime]:
    a = datetime.combine(des, time.min, tzinfo=TZ).astimezone(timezone.utc)
    b = datetime.combine(fins + timedelta(days=1), time.min, tzinfo=TZ).astimezone(timezone.utc)
    return a, b


def report(db: Session, local_id: int, des: date, fins: date, usuari: int | None = None) -> dict:
    a, b = _range(des, fins)
    q = select(CashEntry).where(CashEntry.local_id == local_id, CashEntry.ts >= a, CashEntry.ts < b)
    if usuari is not None:
        q = q.where(CashEntry.user_id == usuari)
    entries = db.scalars(q).all()
    per_dia = defaultdict(lambda: {"ingressos_cent": 0, "despeses_cent": 0})
    despeses = defaultdict(int)
    ingressos = despeses_total = 0
    for e in entries:
        dia = e.ts.replace(tzinfo=e.ts.tzinfo or timezone.utc).astimezone(TZ).date().isoformat()
        if e.categoria is None:  # cobrament, o correcció d'un cobrament (import negatiu)
            per_dia[dia]["ingressos_cent"] += e.import_cent
            ingressos += e.import_cent
        else:  # despesa, o correcció d'una despesa (import positiu, resta de la despesa)
            per_dia[dia]["despeses_cent"] += -e.import_cent
            despeses_total += -e.import_cent
            despeses[e.categoria] += -e.import_cent
    qm = select(func.coalesce(func.sum(-StockMovement.delta_mg), 0)).where(
        StockMovement.local_id == local_id, StockMovement.tipus.in_(["dispensacio", "correccio"]),
        StockMovement.member_id.is_not(None), StockMovement.ts >= a, StockMovement.ts < b)
    if usuari is not None:
        qm = qm.where(StockMovement.user_id == usuari)
    mg = db.scalar(qm)
    return {"des": des.isoformat(), "fins": fins.isoformat(), "ingressos_cent": ingressos,
            "despeses_cent": despeses_total, "resultat_cent": ingressos - despeses_total,
            "despeses_per_categoria": dict(despeses), "dispensat_mg": mg,
            "per_dia": {k: per_dia[k] for k in sorted(per_dia)}}


def entries_list(db: Session, local_id: int, des: date, fins: date, limit: int = 100) -> list[dict]:
    """Apunts de caixa del rang, del més recent al més antic, amb qui els va fer i si han estat corregits."""
    a, b = _range(des, fins)
    corregits = set(db.scalars(select(CashEntry.corregeix_id).where(CashEntry.local_id == local_id, CashEntry.corregeix_id.is_not(None))))
    noms = {i: n for i, n in db.execute(select(User.id, User.username))}
    q = (select(CashEntry).where(CashEntry.local_id == local_id, CashEntry.ts >= a, CashEntry.ts < b)
         .order_by(CashEntry.id.desc()).limit(limit))
    return [{"id": e.id, "ts": e.ts.replace(tzinfo=e.ts.tzinfo or timezone.utc).isoformat(), "tipus": e.tipus, "metode": e.metode,
             "import_cent": e.import_cent, "categoria": e.categoria, "concepte": e.concepte, "usuari": noms.get(e.user_id),
             "corregeix_id": e.corregeix_id, "corregit": e.id in corregits} for e in db.scalars(q)]


def entries_csv(db: Session, local_id: int, des: date, fins: date) -> str:
    a, b = _range(des, fins)
    rows = [[e.id, e.ts.isoformat(), e.tipus, e.metode, e.import_cent, e.categoria or "", e.concepte or "",
             e.movement_id or "", e.corregeix_id or ""]
            for e in db.scalars(select(CashEntry).where(CashEntry.local_id == local_id, CashEntry.ts >= a, CashEntry.ts < b).order_by(CashEntry.id))]
    # to_csv neutralitza el text que un full de càlcul executaria com a fórmula (el concepte l'escriu l'usuari)
    return to_csv(["id", "data_hora_utc", "tipus", "metode", "import_cent", "categoria", "concepte", "moviment", "corregeix"], rows)

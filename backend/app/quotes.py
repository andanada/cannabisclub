"""Quotes de soci: cobrament (entra a la caixa) i estat «al dia»."""
import calendar
from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import cash, service
from .models import CashEntry, Member, Quota, User
from .stock import TZ

MAX_MESOS = 24
MAX_IMPORT_CENT = 1_000_000


def avui() -> date:
    return datetime.now(TZ).date()


def add_months(d: date, n: int) -> date:
    """Suma n mesos; si el dia no existeix al mes de destí, es queda a l'últim dia del mes."""
    idx = d.year * 12 + (d.month - 1) + n
    y, m = divmod(idx, 12)
    return date(y, m + 1, min(d.day, calendar.monthrange(y, m + 1)[1]))


def _valides(db: Session, member_id: int):
    """Quotes del soci que no han estat anul·lades (l'apunt de caixa corregit les anul·la)."""
    corregit = select(CashEntry.id).where(CashEntry.corregeix_id == Quota.cash_entry_id).exists()
    return select(Quota).where(Quota.member_id == member_id, ~corregit)


def status(db: Session, member_id: int, dia: date | None = None) -> dict:
    dia = dia or avui()
    q = db.scalar(_valides(db, member_id).order_by(Quota.valid_fins.desc(), Quota.id.desc()).limit(1))
    fins = q.valid_fins if q else None
    return {"al_dia": bool(fins and fins >= dia), "valid_fins": fins.isoformat() if fins else None}


def ultimes_quotes(db: Session, local_id: int) -> dict[int, date]:
    """Per a cada soci del local, la data fins a la qual és vàlida la seva última quota no anul·lada (una sola consulta)."""
    from sqlalchemy import func
    corregit = select(CashEntry.id).where(CashEntry.corregeix_id == Quota.cash_entry_id).exists()
    q = select(Quota.member_id, func.max(Quota.valid_fins)).where(Quota.local_id == local_id, ~corregit).group_by(Quota.member_id)
    return {m: fins for m, fins in db.execute(q)}


def charge(db: Session, actor: User, member: Member, import_cent: int, metode: str, mesos: int,
           dia: date | None = None) -> Quota:
    if member.estat == "baixa":
        raise ValueError("El soci està de baixa")
    if not 0 < import_cent <= MAX_IMPORT_CENT:
        raise ValueError("L'import de la quota ha d'estar entre 0,01 € i 10.000 €")
    if not 1 <= mesos <= MAX_MESOS:
        raise ValueError(f"Els mesos han d'estar entre 1 i {MAX_MESOS}")
    if metode not in cash.METODES:
        raise ValueError("Mètode de pagament no vàlid")
    cs = cash._require_open(db, member.local_id)
    dia = dia or avui()
    actual = db.scalar(_valides(db, member.id).order_by(Quota.valid_fins.desc(), Quota.id.desc()).limit(1))
    des = actual.valid_fins + timedelta(days=1) if actual and actual.valid_fins >= dia else dia
    fins = add_months(des, mesos) - timedelta(days=1)
    e = CashEntry(local_id=member.local_id, session_id=cs.id, tipus="quota", metode=metode, import_cent=import_cent, user_id=actor.id)
    db.add(e)
    db.flush()
    q = Quota(local_id=member.local_id, member_id=member.id, cash_entry_id=e.id, valid_des=des, valid_fins=fins,
              mesos=mesos, user_id=actor.id)
    db.add(q)
    db.flush()
    service.audit_append(db, {"accio": "cobrament_quota", "apunt": e.id, "quota": q.id, "soci": member.id,
                              "cent": import_cent, "metode": metode, "des": des.isoformat(), "fins": fins.isoformat(), "per": actor.id})
    db.commit()
    return q


def history(db: Session, member_id: int) -> list[dict]:
    corregides = set(db.scalars(select(CashEntry.corregeix_id).where(CashEntry.corregeix_id.is_not(None))))
    out = []
    for q in db.scalars(select(Quota).where(Quota.member_id == member_id).order_by(Quota.id.desc())):
        e = db.get(CashEntry, q.cash_entry_id)
        out.append({"id": q.id, "ts": q.ts.isoformat(), "valid_des": q.valid_des.isoformat(), "valid_fins": q.valid_fins.isoformat(),
                    "mesos": q.mesos, "import_cent": e.import_cent, "metode": e.metode, "anulada": q.cash_entry_id in corregides})
    return out

"""Quotes de soci: cobrament (entra a la caixa) i estat «al dia»."""
import calendar
from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import ajustos, cash, service
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


def _comprova_tarifa(db: Session, actor: User, local_id: int, import_cent: int, mesos: int, nota: str | None) -> int | None:
    """Regla de tarifa. Rols no gestors (dispensador): l'import ha de ser exactament quota_cent x mesos i els mesos
    no poden passar de quota_mesos; sense tarifa configurada no cobren. Gestors (admin, encarregat): amb tarifa configurada poden cobrar un
    altre import o més mesos, però només amb una nota (>= 3 caràcters) i l'import esperat queda a l'auditoria.
    Retorna l'import esperat segons la tarifa (None si no n'hi ha)."""
    aj = ajustos.get(db, local_id)
    tarifa, max_mesos = aj["quota_cent"], aj["quota_mesos"]
    esperat = tarifa * mesos if tarifa else None
    gestor = actor.role in ("admin", "encarregat")
    quadra = esperat is not None and import_cent == esperat and mesos <= max_mesos
    if quadra:
        return esperat
    if not gestor:
        if tarifa is None:
            raise ValueError("Aquest local no té la quota configurada: la cobra un encarregat o un administrador")
        if mesos > max_mesos:
            raise ValueError(f"Només es poden cobrar fins a {max_mesos} mesos de quota de cop")
        raise ValueError("L'import ha de ser la quota del local per aquests mesos")
    if tarifa is None:
        return None  # sense tarifa configurada no hi ha res amb què comparar: el gestor cobra l'import indicat
    if len((nota or "").strip()) < 3:
        raise ValueError("Un import o uns mesos diferents de la tarifa del local necessiten una nota que ho justifiqui")
    return esperat


def charge(db: Session, actor: User, member: Member, import_cent: int, metode: str, mesos: int,
           dia: date | None = None, nota: str | None = None) -> Quota:
    if member.estat == "baixa":
        raise ValueError("El soci està de baixa")
    if not 0 < import_cent <= MAX_IMPORT_CENT:
        raise ValueError("L'import de la quota ha d'estar entre 0,01 € i 10.000 €")
    if not 1 <= mesos <= MAX_MESOS:
        raise ValueError(f"Els mesos han d'estar entre 1 i {MAX_MESOS}")
    if metode not in cash.METODES:
        raise ValueError("Mètode de pagament no vàlid")
    esperat = _comprova_tarifa(db, actor, member.local_id, import_cent, mesos, nota)
    # Ordre global de bloquejos: soci -> producte -> sessió de caixa (igual que les dispensacions; si no, interbloqueig).
    # Es bloqueja el soci abans de llegir la quota vigent: dos cobraments simultanis (doble clic, dos llocs) es posen
    # en cua i el segon veu el primer, en lloc de cobrar dues vegades el mateix període.
    db.scalar(select(Member.id).where(Member.id == member.id).with_for_update())
    cs = cash._require_open(db, member.local_id, actor)
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
    registre = {"accio": "cobrament_quota", "apunt": e.id, "quota": q.id, "soci": member.id, "cent": import_cent, "metode": metode,
                "des": des.isoformat(), "fins": fins.isoformat(), "mesos": mesos, "esperat_cent": esperat, "per": actor.id}
    if nota and nota.strip():
        registre["nota"] = nota.strip()
    service.audit_append(db, registre)
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

from datetime import date, datetime, time, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import service
from .models import CashEntry, Local, Member, Product, StockMovement, User

TZ = ZoneInfo("Europe/Madrid")


def grams_to_mg(g: Decimal) -> int:
    mg = (Decimal(g) * 1000).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    if mg <= 0:
        raise ValueError("La quantitat ha de ser positiva")
    return int(mg)


def stock_mg(db: Session, product_id: int) -> int:
    return db.scalar(select(func.coalesce(func.sum(StockMovement.delta_mg), 0))
                     .where(StockMovement.product_id == product_id))


def _lock_product(db: Session, product_id: int) -> Product:
    p = db.scalar(select(Product).where(Product.id == product_id).with_for_update())
    if not p or not p.actiu:
        raise ValueError("Producte inexistent o inactiu")
    return p


def _window_start(period: str, now: datetime) -> datetime:
    local = now.astimezone(TZ)
    d = local.date() if period == "dia" else local.date().replace(day=1)
    return datetime.combine(d, time.min, tzinfo=TZ).astimezone(timezone.utc)


def dispensed_mg(db: Session, member_id: int, period: str, now: datetime) -> int:
    """Total net dispensat al soci en el període (les correccions hi resten)."""
    start = _window_start(period, now)
    total = db.scalar(select(func.coalesce(func.sum(-StockMovement.delta_mg), 0)).where(
        StockMovement.member_id == member_id, StockMovement.ts >= start,
        StockMovement.tipus.in_(["dispensacio", "correccio"])))
    return total


def add_product(db: Session, actor: User, local_id: int, nom: str, categoria: str, preu_cent_per_g: int) -> Product:
    p = Product(local_id=local_id, nom=nom, categoria=categoria, preu_cent_per_g=preu_cent_per_g)
    db.add(p)
    db.flush()
    service.audit_append(db, {"accio": "alta_producte", "producte": p.id, "local": local_id, "per": actor.id})
    db.commit()
    return p


def receive(db: Session, actor: User, product_id: int, grams: Decimal, nota: str | None) -> StockMovement:
    p = _lock_product(db, product_id)
    m = StockMovement(local_id=p.local_id, product_id=p.id, tipus="entrada",
                      delta_mg=grams_to_mg(grams), user_id=actor.id, nota=nota)
    db.add(m)
    db.flush()
    service.audit_append(db, {"accio": "entrada_estoc", "moviment": m.id, "producte": p.id, "mg": m.delta_mg, "per": actor.id})
    db.commit()
    return m


def dispense(db: Session, actor: User, member_id: int, product_id: int, grams: Decimal,
             pes_bascula_g: Decimal | None, now: datetime | None = None) -> StockMovement:
    now = now or datetime.now(timezone.utc)
    p = _lock_product(db, product_id)
    member = db.get(Member, member_id)
    if not member or member.local_id != p.local_id:
        raise ValueError("Soci inexistent o d'un altre local")
    if member.estat != "actiu":
        raise ValueError("El soci no està actiu")
    mg = grams_to_mg(grams)
    if stock_mg(db, p.id) < mg:
        raise ValueError("Estoc insuficient")
    local = db.get(Local, p.local_id)
    if pes_bascula_g is not None and local.tolerancia_bascula_mg is not None:
        if abs(grams_to_mg(pes_bascula_g) - mg) > local.tolerancia_bascula_mg:
            raise ValueError("El pes de la bàscula no coincideix amb la quantitat dispensada")
    for period, limit in (("dia", local.limit_diari_mg), ("mes", local.limit_mensual_mg)):
        if limit is not None and dispensed_mg(db, member_id, period, now) + mg > limit:
            raise ValueError(f"Supera el límit {'diari' if period == 'dia' else 'mensual'} del soci")
    m = StockMovement(
        ts=now, local_id=p.local_id, product_id=p.id, tipus="dispensacio", delta_mg=-mg, member_id=member_id,
        pes_bascula_mg=grams_to_mg(pes_bascula_g) if pes_bascula_g is not None else None,
        import_cent=int((Decimal(mg) * p.preu_cent_per_g / 1000).quantize(Decimal("1"), rounding=ROUND_HALF_UP)),
        user_id=actor.id)
    db.add(m)
    db.flush()
    service.audit_append(db, {"accio": "dispensacio", "moviment": m.id, "soci": member_id, "producte": p.id,
                              "mg": mg, "import_cent": m.import_cent, "per": actor.id})
    db.commit()
    return m


def correct(db: Session, actor: User, movement_id: int, nota: str) -> StockMovement:
    orig = db.get(StockMovement, movement_id)
    if not orig:
        raise ValueError("Moviment inexistent")
    if orig.tipus == "correccio":
        raise ValueError("Una correcció no es pot corregir")
    if db.scalar(select(StockMovement.id).where(StockMovement.corregeix_id == orig.id)):
        raise ValueError("Aquest moviment ja està corregit")
    pagat = db.scalar(select(CashEntry).where(CashEntry.movement_id == orig.id))
    if pagat and not db.scalar(select(CashEntry.id).where(CashEntry.corregeix_id == pagat.id)):
        raise ValueError("La dispensació està cobrada: corregeix primer el cobrament")
    _lock_product(db, orig.product_id)
    if stock_mg(db, orig.product_id) - orig.delta_mg < 0:
        raise ValueError("La correcció deixaria l'estoc negatiu")
    m = StockMovement(local_id=orig.local_id, product_id=orig.product_id, tipus="correccio",
                      delta_mg=-orig.delta_mg, member_id=orig.member_id, import_cent=-orig.import_cent if orig.import_cent else None,
                      corregeix_id=orig.id, user_id=actor.id, nota=nota)
    db.add(m)
    db.flush()
    service.audit_append(db, {"accio": "correccio", "moviment": m.id, "corregeix": orig.id, "per": actor.id})
    db.commit()
    return m


def shrink(db: Session, actor: User, product_id: int, grams: Decimal, nota: str) -> StockMovement:
    p = _lock_product(db, product_id)
    mg = grams_to_mg(grams)
    if stock_mg(db, p.id) < mg:
        raise ValueError("La merma supera l'estoc")
    m = StockMovement(local_id=p.local_id, product_id=p.id, tipus="merma", delta_mg=-mg, user_id=actor.id, nota=nota)
    db.add(m)
    db.flush()
    service.audit_append(db, {"accio": "merma", "moviment": m.id, "producte": p.id, "mg": mg, "per": actor.id})
    db.commit()
    return m


def adjust(db: Session, actor: User, product_id: int, grams_reals: Decimal, nota: str) -> StockMovement:
    """Ajust d'inventari: deixa l'estoc exactament en `grams_reals` (>= 0)."""
    p = _lock_product(db, product_id)
    real = int((Decimal(grams_reals) * 1000).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    if real < 0:
        raise ValueError("L'inventari real no pot ser negatiu")
    delta = real - stock_mg(db, p.id)
    if delta == 0:
        raise ValueError("L'estoc ja coincideix amb l'inventari")
    m = StockMovement(local_id=p.local_id, product_id=p.id, tipus="ajust", delta_mg=delta, user_id=actor.id, nota=nota)
    db.add(m)
    db.flush()
    service.audit_append(db, {"accio": "ajust_inventari", "moviment": m.id, "producte": p.id, "delta_mg": delta, "per": actor.id})
    db.commit()
    return m

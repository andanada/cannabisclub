"""Sessions d'inventari: recompte guiat de l'estoc amb ajust final en una sola transacció."""
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import service, stock
from .models import InventoryCount, InventorySession, Product, StockMovement, User

MAX_MG = 1_000_000_000


def _g(mg: int) -> str:
    return str(Decimal(mg) / 1000)


def obrir(db: Session, actor: User, local_id: int, nom: str | None) -> InventorySession:
    if db.scalar(select(InventorySession.id).where(InventorySession.local_id == local_id, InventorySession.estat == "obert")):
        raise ValueError("Ja hi ha un inventari obert en aquest local: tanca'l o cancel·la'l primer")
    nom = (nom or "").strip() or "Inventari " + datetime.now(stock.TZ).strftime("%d/%m/%Y")
    s = InventorySession(local_id=local_id, nom=nom[:60], user_id=actor.id)
    db.add(s)
    db.flush()
    service.audit_append(db, {"accio": "obre_inventari", "inventari": s.id, "local": local_id, "per": actor.id})
    db.commit()
    return s


def llista(db: Session, local_id: int) -> list[dict]:
    comptats = {sid: n for sid, n in db.execute(select(InventoryCount.session_id, func.count()).group_by(InventoryCount.session_id))}
    q = select(InventorySession).where(InventorySession.local_id == local_id).order_by(InventorySession.id.desc()).limit(50)
    return [{"id": s.id, "nom": s.nom, "estat": s.estat, "ts_obert": s.ts_obert.isoformat(),
             "ts_tancat": s.ts_tancat.isoformat() if s.ts_tancat else None, "comptats": comptats.get(s.id, 0)} for s in db.scalars(q)]


def detall(db: Session, s: InventorySession) -> dict:
    prods = list(db.scalars(select(Product).where(Product.local_id == s.local_id, Product.actiu.is_(True)).order_by(Product.categoria, Product.nom)))
    esperat = stock.stock_by_product(db, [p.id for p in prods])
    comptat = {c.product_id: c.counted_mg for c in db.scalars(select(InventoryCount).where(InventoryCount.session_id == s.id))}
    linies = []
    for p in prods:
        c = comptat.get(p.id)
        linies.append({"product_id": p.id, "nom": p.nom, "categoria": p.categoria, "esperat_g": _g(esperat[p.id]),
                       "comptat_g": _g(c) if c is not None else None,
                       "diferencia_g": _g(c - esperat[p.id]) if c is not None else None})
    return {"id": s.id, "nom": s.nom, "estat": s.estat, "total": len(prods), "comptats": sum(1 for l in linies if l["comptat_g"] is not None),
            "linies": linies}


def _obert(s: InventorySession) -> None:
    if s.estat != "obert":
        raise ValueError("Aquest inventari ja no està obert")


def comptar(db: Session, actor: User, s: InventorySession, product_id: int, grams: Decimal) -> None:
    _obert(s)
    p = db.get(Product, product_id)
    if not p or p.local_id != s.local_id or not p.actiu:
        raise ValueError("Producte inexistent o inactiu en aquest local")
    mg = int((Decimal(grams) * 1000).quantize(Decimal("1")))
    if mg < 0 or mg > MAX_MG:
        raise ValueError("Quantitat no vàlida")
    fila = db.get(InventoryCount, (s.id, product_id))
    if fila:
        fila.counted_mg, fila.user_id, fila.ts = mg, actor.id, datetime.now(timezone.utc)
    else:
        db.add(InventoryCount(session_id=s.id, product_id=product_id, counted_mg=mg, user_id=actor.id))
    db.commit()


def tancar(db: Session, actor: User, s: InventorySession) -> dict:
    """Ajusta cada producte comptat a la quantitat comptada. Tot o res: una sola transacció."""
    _obert(s)
    ajustos = sense = 0
    for c in db.scalars(select(InventoryCount).where(InventoryCount.session_id == s.id).order_by(InventoryCount.product_id)):
        p = stock._lock_product(db, c.product_id)
        delta = c.counted_mg - stock.stock_mg(db, p.id)
        if delta == 0:
            sense += 1
            continue
        m = StockMovement(local_id=p.local_id, product_id=p.id, tipus="ajust", delta_mg=delta, user_id=actor.id, nota=f"Inventari #{s.id}")
        db.add(m)
        db.flush()
        service.audit_append(db, {"accio": "ajust_inventari", "moviment": m.id, "producte": p.id, "delta_mg": delta, "inventari": s.id, "per": actor.id})
        ajustos += 1
    total = db.scalar(select(func.count()).select_from(Product).where(Product.local_id == s.local_id, Product.actiu.is_(True)))
    pendents = total - ajustos - sense
    s.estat, s.ts_tancat = "tancat", datetime.now(timezone.utc)
    service.audit_append(db, {"accio": "tanca_inventari", "inventari": s.id, "ajustos": ajustos, "per": actor.id})
    db.commit()
    return {"ajustos": ajustos, "sense_canvis": sense, "pendents": max(0, pendents)}


def cancellar(db: Session, actor: User, s: InventorySession) -> None:
    _obert(s)
    s.estat, s.ts_tancat = "cancel·lat", datetime.now(timezone.utc)
    service.audit_append(db, {"accio": "cancella_inventari", "inventari": s.id, "per": actor.id})
    db.commit()

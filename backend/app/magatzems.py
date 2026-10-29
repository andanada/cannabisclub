"""Magatzems: el principal és implícit (on es dispensa); els altres guarden estoc que es mou amb traspassos."""
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import service, stock
from .models import MovementWarehouse, Product, StockMovement, User, Warehouse

RESERVAT = "principal"


def _g(mg: int) -> str:
    return str(Decimal(mg) / 1000)


def llista(db: Session, local_id: int) -> list[dict]:
    out = [{"id": None, "nom": "Principal", "principal": True, "actiu": True}]
    out += [{"id": w.id, "nom": w.nom, "principal": False, "actiu": w.actiu}
            for w in db.scalars(select(Warehouse).where(Warehouse.local_id == local_id).order_by(Warehouse.nom))]
    return out


def check_active(db: Session, local_id: int, warehouse_id: int | None) -> None:
    if warehouse_id is None:
        return
    w = db.get(Warehouse, warehouse_id)
    if not w or w.local_id != local_id or not w.actiu:
        raise ValueError("Magatzem inexistent o desactivat en aquest local")


def _nom(db: Session, local_id: int, nom, excepte_id=None) -> str:
    nom = (nom or "").strip()
    if not 1 <= len(nom) <= 60:
        raise ValueError("El nom ha de tenir entre 1 i 60 caràcters")
    if nom.lower() == RESERVAT:
        raise ValueError("El nom «Principal» està reservat")
    q = select(Warehouse.id).where(Warehouse.local_id == local_id, Warehouse.nom == nom)
    if excepte_id:
        q = q.where(Warehouse.id != excepte_id)
    if db.scalar(q):
        raise ValueError("Ja existeix un magatzem amb aquest nom en aquest local")
    return nom


def create(db: Session, actor: User, local_id: int, nom) -> Warehouse:
    w = Warehouse(local_id=local_id, nom=_nom(db, local_id, nom))
    db.add(w)
    db.flush()
    service.audit_append(db, {"accio": "alta_magatzem", "magatzem": w.id, "local": local_id, "per": actor.id})
    db.commit()
    return w


def update(db: Session, actor: User, w: Warehouse, nom: str | None, actiu: bool | None) -> None:
    canvis = {}
    if nom is not None and nom.strip() != w.nom:
        canvis["nom"] = _nom(db, w.local_id, nom, w.id)
    if actiu is not None and actiu != w.actiu:
        if not actiu:
            net = db.scalar(select(func.coalesce(func.sum(StockMovement.delta_mg), 0))
                            .join(MovementWarehouse, MovementWarehouse.movement_id == StockMovement.id)
                            .where(MovementWarehouse.warehouse_id == w.id))
            if net != 0:
                raise ValueError("El magatzem encara té estoc: traspassa'l abans de desactivar-lo")
        canvis["actiu"] = actiu
    if not canvis:
        raise ValueError("No hi ha cap canvi")
    for k, v in canvis.items():
        setattr(w, k, v)
    service.audit_append(db, {"accio": "edita_magatzem", "magatzem": w.id, "camps": sorted(canvis), "per": actor.id})
    db.commit()


def estoc(db: Session, local_id: int) -> list[dict]:
    """Per producte actiu, l'estoc a cada magatzem (principal primer; els desactivats no hi surten)."""
    prods = list(db.scalars(select(Product).where(Product.local_id == local_id, Product.actiu.is_(True)).order_by(Product.nom)))
    magatzems = [w for w in db.scalars(select(Warehouse).where(Warehouse.local_id == local_id, Warehouse.actiu.is_(True)).order_by(Warehouse.nom))]
    principal = stock.stock_by_product(db, [p.id for p in prods])
    per_mag = {(pid, wid): int(mg) for pid, wid, mg in db.execute(
        select(StockMovement.product_id, MovementWarehouse.warehouse_id, func.sum(StockMovement.delta_mg))
        .join(MovementWarehouse, MovementWarehouse.movement_id == StockMovement.id)
        .where(StockMovement.local_id == local_id).group_by(StockMovement.product_id, MovementWarehouse.warehouse_id))}
    return [{"product_id": p.id, "nom": p.nom, "categoria": p.categoria,
             "estocs": [{"magatzem_id": None, "g": _g(principal[p.id])}] + [{"magatzem_id": w.id, "g": _g(per_mag.get((p.id, w.id), 0))} for w in magatzems]}
            for p in prods]


def transfer(db: Session, actor: User, product: Product, de: int | None, a: int | None, grams: Decimal) -> None:
    """Mou estoc d'un magatzem a un altre amb dos moviments (surt -mg, entra +mg), tot en una transacció."""
    if de == a:
        raise ValueError("L'origen i el destí han de ser diferents")
    mg = stock.grams_to_mg(grams)
    check_active(db, product.local_id, a)
    if de is not None:
        w = db.get(Warehouse, de)
        if not w or w.local_id != product.local_id:
            raise ValueError("Magatzem d'origen inexistent")
    if stock.stock_in_mg(db, product.id, de) < mg:
        raise ValueError("No hi ha prou estoc al magatzem d'origen")
    sortida = StockMovement(local_id=product.local_id, product_id=product.id, tipus="traspas", delta_mg=-mg, user_id=actor.id)
    entrada = StockMovement(local_id=product.local_id, product_id=product.id, tipus="traspas", delta_mg=mg, user_id=actor.id)
    db.add_all([sortida, entrada])
    db.flush()
    if de is not None:
        db.add(MovementWarehouse(movement_id=sortida.id, warehouse_id=de))
    if a is not None:
        db.add(MovementWarehouse(movement_id=entrada.id, warehouse_id=a))
    service.audit_append(db, {"accio": "traspas_estoc", "producte": product.id, "de": de, "a": a, "mg": mg, "per": actor.id})
    db.commit()

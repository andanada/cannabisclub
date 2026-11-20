"""Magatzems: el principal és implícit (on es dispensa); els altres guarden estoc que es mou amb traspassos."""
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import service, stock, unitats
from .races import flush_or_error
from .models import MovementWarehouse, Product, StockMovement, User, Warehouse

RESERVAT = "principal"


_g = unitats.mg_to_g


def llista(db: Session, local_id: int) -> list[dict]:
    out = [{"id": None, "nom": "Principal", "principal": True, "actiu": True}]
    out += [{"id": w.id, "nom": w.nom, "principal": False, "actiu": w.actiu}
            for w in db.scalars(select(Warehouse).where(Warehouse.local_id == local_id).order_by(Warehouse.nom))]
    return out


NOM_MAGATZEM = "Magatzem"  # «Almacén»: el dispensari és el magatzem principal; aquest és l'únic altre lloc on hi ha estoc


def magatzem_unic(db: Session, local_id: int) -> Warehouse:
    """El magatzem del local (el primer actiu); si no n'hi ha cap, es crea. Així hi ha sempre dos llocs: Magatzem i Dispensari."""
    w = db.scalar(select(Warehouse).where(Warehouse.local_id == local_id, Warehouse.actiu.is_(True)).order_by(Warehouse.id))
    if w is None:
        w = Warehouse(local_id=local_id, nom=NOM_MAGATZEM)
        db.add(w)
        db.commit()
    return w


def existencies(db: Session, local_id: int) -> dict:
    """Llista d'existències: per producte actiu, el que hi ha al dispensari i al magatzem (pesos reals, sense tara) i un avís quan
    s'acaba o està a punt d'acabar-se (límit: ajust `estoc_baix_mg`)."""
    from . import ajustos
    w = magatzem_unic(db, local_id)
    baix = ajustos.get(db, local_id)["estoc_baix_mg"]
    prods = list(db.scalars(select(Product).where(Product.local_id == local_id, Product.actiu.is_(True)).order_by(Product.categoria, Product.nom)))
    ids = [p.id for p in prods]
    dispensari = stock.stock_by_product(db, ids)
    total = stock.stock_by_product(db, ids, total=True)
    out = []
    for p in prods:
        d, t = dispensari[p.id], total[p.id]
        estat = "esgotat" if t <= 0 else ("baix" if baix and d < baix else "ok")
        out.append({"id": p.id, "nom": p.nom, "categoria": p.categoria, "es_genetic": p.es_genetic, "unitat": p.unitat,
                    "dispensari_g": _g(d), "magatzem_g": _g(t - d), "estat": estat, "preu_entrada_cent": p.preu_entrada_cent})
    return {"magatzem_id": w.id, "baix_g": _g(baix), "productes": out}


def moviments_producte(db: Session, product: Product, limit: int = 10) -> list[dict]:
    """Els darrers moviments d'un producte (de qualsevol lloc), del més recent al més antic."""
    noms = {i: n for i, n in db.execute(select(User.id, User.username))}
    llocs = {wid: nom for wid, nom in db.execute(select(Warehouse.id, Warehouse.nom).where(Warehouse.local_id == product.local_id))}
    rows = db.execute(select(StockMovement, MovementWarehouse.warehouse_id)
                      .outerjoin(MovementWarehouse, MovementWarehouse.movement_id == StockMovement.id)
                      .where(StockMovement.product_id == product.id).order_by(StockMovement.id.desc()).limit(limit)).all()
    return [{"id": m.id, "ts": m.ts.isoformat(), "tipus": m.tipus, "grams": _g(m.delta_mg), "cost_cent": m.cost_cent, "nota": m.nota, "usuari": noms.get(m.user_id),
             "lloc": llocs.get(wid) if wid is not None else "Dispensari"} for m, wid in rows]


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
    flush_or_error(db, "Ja existeix un magatzem amb aquest nom en aquest local")
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
    product = stock._lock_product(db, product.id)  # el mateix bloqueig que dispensar: no es pot creuar amb una dispensació
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

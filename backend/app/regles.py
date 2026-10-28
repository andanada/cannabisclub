"""Regles de dispensació: límit de gramatge per soci i període (dia, setmana o mes)."""
from datetime import datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import service, stock
from .models import Product, Regla, StockMovement, User

PERIODES = {"dia": "diari", "setmana": "setmanal", "mes": "mensual"}
AMBITS = {"tot", "categoria", "producte"}
MAX_MG = 10_000_000


def _aplica(r: Regla, p: Product) -> bool:
    if r.ambit == "tot":
        return True
    if r.ambit == "categoria":
        return (p.categoria or "") == r.categoria
    return r.product_id == p.id


def view(r: Regla) -> dict:
    return {"id": r.id, "nom": r.nom, "ambit": r.ambit, "categoria": r.categoria, "product_id": r.product_id,
            "periode": r.periode, "max_g": str(Decimal(r.max_mg) / 1000), "actiu": r.actiu}


def list_rules(db: Session, local_id: int) -> list[dict]:
    return [view(r) for r in db.scalars(select(Regla).where(Regla.local_id == local_id).order_by(Regla.nom))]


def _consumit_mg(db: Session, r: Regla, member_id: int, now: datetime) -> int:
    """Gramatge net dispensat al soci dins la finestra de la regla (les correccions hi resten)."""
    q = (select(func.coalesce(func.sum(-StockMovement.delta_mg), 0))
         .join(Product, Product.id == StockMovement.product_id)
         .where(StockMovement.member_id == member_id, StockMovement.local_id == r.local_id,
                StockMovement.ts >= stock._window_start(r.periode, now),
                StockMovement.tipus.in_(["dispensacio", "correccio"])))
    if r.ambit == "categoria":
        q = q.where(func.coalesce(Product.categoria, "") == r.categoria)
    elif r.ambit == "producte":
        q = q.where(StockMovement.product_id == r.product_id)
    return db.scalar(q)


def check(db: Session, member_id: int, product: Product, mg: int, now: datetime) -> None:
    """Llança ValueError si dispensar `mg` supera alguna regla activa que afecti el producte."""
    for r in db.scalars(select(Regla).where(Regla.local_id == product.local_id, Regla.actiu.is_(True)).order_by(Regla.id)):
        if _aplica(r, product) and _consumit_mg(db, r, member_id, now) + mg > r.max_mg:
            raise ValueError(f"Supera la regla «{r.nom}»: màxim {Decimal(r.max_mg) / 1000} g per soci {PERIODES[r.periode]}")


def _valida(db: Session, local_id: int, nom, ambit, categoria, product_id, periode, max_mg, excepte_id=None) -> str:
    nom = (nom or "").strip()
    if not 1 <= len(nom) <= 60:
        raise ValueError("El nom ha de tenir entre 1 i 60 caràcters")
    if ambit not in AMBITS:
        raise ValueError("Àmbit no vàlid (tot, categoria o producte)")
    if periode not in PERIODES:
        raise ValueError("Període no vàlid (dia, setmana o mes)")
    if not isinstance(max_mg, int) or not 1 <= max_mg <= MAX_MG:
        raise ValueError("El màxim ha de ser un gramatge positiu")
    if ambit == "categoria" and not (categoria or "").strip():
        raise ValueError("Cal indicar la categoria")
    if ambit == "producte":
        p = db.get(Product, product_id) if product_id else None
        if not p or p.local_id != local_id:
            raise ValueError("Cal triar un producte d'aquest local")
    q = select(Regla.id).where(Regla.local_id == local_id, Regla.nom == nom)
    if excepte_id:
        q = q.where(Regla.id != excepte_id)
    if db.scalar(q):
        raise ValueError("Ja existeix una regla amb aquest nom en aquest local")
    return nom


def create(db: Session, actor: User, local_id: int, nom, ambit, categoria, product_id, periode, max_g) -> Regla:
    max_mg = stock.grams_to_mg(max_g)
    nom = _valida(db, local_id, nom, ambit, categoria, product_id, periode, max_mg)
    r = Regla(local_id=local_id, nom=nom, ambit=ambit, periode=periode, max_mg=max_mg,
              categoria=(categoria or "").strip() or None if ambit == "categoria" else None,
              product_id=product_id if ambit == "producte" else None)
    db.add(r)
    db.flush()
    service.audit_append(db, {"accio": "alta_regla", "regla": r.id, "local": local_id, "per": actor.id})
    db.commit()
    return r


def update(db: Session, actor: User, r: Regla, actiu: bool | None, nom: str | None, max_g: Decimal | None) -> None:
    canvis = {}
    if actiu is not None and actiu != r.actiu:
        canvis["actiu"] = actiu
    if nom is not None and nom.strip() != r.nom:
        canvis["nom"] = _valida(db, r.local_id, nom, r.ambit, r.categoria, r.product_id, r.periode, r.max_mg, r.id)
    if max_g is not None:
        mg = stock.grams_to_mg(max_g)
        if mg != r.max_mg:
            _valida(db, r.local_id, r.nom, r.ambit, r.categoria, r.product_id, r.periode, mg, r.id)
            canvis["max_mg"] = mg
    if not canvis:
        raise ValueError("No hi ha cap canvi")
    for k, v in canvis.items():
        setattr(r, k, v)
    service.audit_append(db, {"accio": "edita_regla", "regla": r.id, "camps": sorted(canvis), "per": actor.id})
    db.commit()

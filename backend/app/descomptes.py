"""Descomptes: configuració per local i càlcul en dispensar."""
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import service
from .models import Discount, Product, User

TIPUS = {"percent", "import_g"}
AMBITS = {"tot", "categoria", "producte"}


def _vigent(d: Discount, dia: date) -> bool:
    return d.actiu and (d.inici is None or d.inici <= dia) and (d.fi is None or dia <= d.fi)


def _aplica(d: Discount, p: Product) -> bool:
    if d.ambit == "tot":
        return True
    if d.ambit == "categoria":
        return (p.categoria or "") == d.categoria
    return d.product_id == p.id


def view(d: Discount) -> dict:
    return {"id": d.id, "nom": d.nom, "tipus": d.tipus, "valor": d.valor, "ambit": d.ambit, "categoria": d.categoria,
            "product_id": d.product_id, "inici": d.inici.isoformat() if d.inici else None, "fi": d.fi.isoformat() if d.fi else None, "actiu": d.actiu}


def list_discounts(db: Session, local_id: int, dia: date, product: Product | None = None, tots: bool = False) -> list[dict]:
    out = []
    for d in db.scalars(select(Discount).where(Discount.local_id == local_id).order_by(Discount.nom)):
        if tots or (_vigent(d, dia) and (product is None or _aplica(d, product))):
            out.append(view(d))
    return out


def _valida(db: Session, local_id: int, nom, tipus, valor, ambit, categoria, product_id, inici, fi, excepte_id=None) -> str:
    nom = (nom or "").strip()
    if not 1 <= len(nom) <= 60:
        raise ValueError("El nom ha de tenir entre 1 i 60 caràcters")
    if tipus not in TIPUS:
        raise ValueError("Tipus de descompte no vàlid (percent o import_g)")
    if not isinstance(valor, int) or valor < 1 or (tipus == "percent" and valor > 100) or valor > 1_000_000:
        raise ValueError("El valor ha d'estar entre 1 i 100 (%) o ser un import positiu en cèntims per gram")
    if ambit not in AMBITS:
        raise ValueError("Àmbit no vàlid (tot, categoria o producte)")
    if ambit == "categoria" and not (categoria or "").strip():
        raise ValueError("Cal indicar la categoria")
    if ambit == "producte":
        p = db.get(Product, product_id) if product_id else None
        if not p or p.local_id != local_id:
            raise ValueError("Cal triar un producte d'aquest local")
    if inici and fi and fi < inici:
        raise ValueError("La data final no pot ser anterior a la inicial")
    q = select(Discount.id).where(Discount.local_id == local_id, Discount.nom == nom)
    if excepte_id:
        q = q.where(Discount.id != excepte_id)
    if db.scalar(q):
        raise ValueError("Ja existeix un descompte amb aquest nom en aquest local")
    return nom


def create(db: Session, actor: User, local_id: int, nom, tipus, valor, ambit, categoria=None, product_id=None, inici=None, fi=None) -> Discount:
    nom = _valida(db, local_id, nom, tipus, valor, ambit, categoria, product_id, inici, fi)
    d = Discount(local_id=local_id, nom=nom, tipus=tipus, valor=valor, ambit=ambit, inici=inici, fi=fi,
                 categoria=(categoria or "").strip() or None if ambit == "categoria" else None, product_id=product_id if ambit == "producte" else None)
    db.add(d)
    db.flush()
    service.audit_append(db, {"accio": "alta_descompte", "descompte": d.id, "local": local_id, "per": actor.id})
    db.commit()
    return d


def update(db: Session, actor: User, d: Discount, actiu: bool | None, nom: str | None, valor: int | None, inici, fi, canvia_dates: bool) -> None:
    canvis = {}
    if actiu is not None and actiu != d.actiu:
        canvis["actiu"] = actiu
    if nom is not None and nom.strip() != d.nom:
        canvis["nom"] = _valida(db, d.local_id, nom, d.tipus, d.valor, d.ambit, d.categoria, d.product_id, d.inici, d.fi, d.id)
    if valor is not None and valor != d.valor:
        _valida(db, d.local_id, d.nom, d.tipus, valor, d.ambit, d.categoria, d.product_id, d.inici, d.fi, d.id)
        canvis["valor"] = valor
    if canvia_dates:
        _valida(db, d.local_id, d.nom, d.tipus, d.valor, d.ambit, d.categoria, d.product_id, inici, fi, d.id)
        canvis["inici"], canvis["fi"] = inici, fi
    if not canvis:
        raise ValueError("No hi ha cap canvi")
    for k, v in canvis.items():
        setattr(d, k, v)
    service.audit_append(db, {"accio": "edita_descompte", "descompte": d.id, "camps": sorted(canvis), "per": actor.id})
    db.commit()


def apply(db: Session, discount_id: int, product: Product, import_cent: int, mg: int, dia: date) -> tuple[Discount, int]:
    """Valida el descompte per a aquest producte i dia i retorna (descompte, import descomptat en cèntims)."""
    d = db.get(Discount, discount_id)
    if not d or d.local_id != product.local_id:
        raise ValueError("Descompte inexistent")
    if not _vigent(d, dia):
        raise ValueError("El descompte no està vigent")
    if not _aplica(d, product):
        raise ValueError("El descompte no es pot aplicar a aquest producte")
    if d.tipus == "percent":
        rebaixa = int((Decimal(import_cent) * d.valor / 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    else:
        rebaixa = int((Decimal(mg) * d.valor / 1000).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    return d, min(import_cent, max(0, rebaixa))

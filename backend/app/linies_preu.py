"""Línies de preu: preus per gram alternatius per producte, assignables a socis."""
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import service
from .models import Member, MemberPriceLine, PriceLine, Product, ProductPrice, User

MAX_PREU = 10_000_000


def price_for(db: Session, member_id: int, product: Product) -> int:
    """Preu per gram efectiu: el de la línia activa del soci si té preu per al producte; si no, el base."""
    fila = db.execute(
        select(ProductPrice.preu_cent_per_g)
        .join(PriceLine, PriceLine.id == ProductPrice.price_line_id)
        .join(MemberPriceLine, MemberPriceLine.price_line_id == PriceLine.id)
        .where(MemberPriceLine.member_id == member_id, ProductPrice.product_id == product.id, PriceLine.actiu.is_(True))).first()
    return fila[0] if fila else product.preu_cent_per_g


def effective_prices(db: Session, member_id: int, products: list[Product]) -> dict[int, int]:
    base = {p.id: p.preu_cent_per_g for p in products}
    rows = db.execute(
        select(ProductPrice.product_id, ProductPrice.preu_cent_per_g)
        .join(PriceLine, PriceLine.id == ProductPrice.price_line_id)
        .join(MemberPriceLine, MemberPriceLine.price_line_id == PriceLine.id)
        .where(MemberPriceLine.member_id == member_id, PriceLine.actiu.is_(True)))
    base.update({pid: cent for pid, cent in rows if pid in base})
    return base


def llista(db: Session, local_id: int) -> list[dict]:
    socis = {lid: n for lid, n in db.execute(select(MemberPriceLine.price_line_id, func.count()).group_by(MemberPriceLine.price_line_id))}
    prods = {lid: n for lid, n in db.execute(select(ProductPrice.price_line_id, func.count()).group_by(ProductPrice.price_line_id))}
    return [{"id": l.id, "nom": l.nom, "actiu": l.actiu, "socis": socis.get(l.id, 0), "productes": prods.get(l.id, 0)}
            for l in db.scalars(select(PriceLine).where(PriceLine.local_id == local_id).order_by(PriceLine.nom))]


def detall(db: Session, l: PriceLine) -> dict:
    prods = list(db.scalars(select(Product).where(Product.local_id == l.local_id, Product.actiu.is_(True)).order_by(Product.nom)))
    preus = {pid: cent for pid, cent in db.execute(select(ProductPrice.product_id, ProductPrice.preu_cent_per_g).where(ProductPrice.price_line_id == l.id))}
    return {"id": l.id, "nom": l.nom, "actiu": l.actiu,
            "preus": [{"product_id": p.id, "nom": p.nom, "base_cent": p.preu_cent_per_g, "preu_cent": preus.get(p.id)} for p in prods]}


def _nom(db: Session, local_id: int, nom, excepte_id=None) -> str:
    nom = (nom or "").strip()
    if not 1 <= len(nom) <= 60:
        raise ValueError("El nom ha de tenir entre 1 i 60 caràcters")
    q = select(PriceLine.id).where(PriceLine.local_id == local_id, PriceLine.nom == nom)
    if excepte_id:
        q = q.where(PriceLine.id != excepte_id)
    if db.scalar(q):
        raise ValueError("Ja existeix una línia de preu amb aquest nom en aquest local")
    return nom


def create(db: Session, actor: User, local_id: int, nom) -> PriceLine:
    l = PriceLine(local_id=local_id, nom=_nom(db, local_id, nom))
    db.add(l)
    db.flush()
    service.audit_append(db, {"accio": "alta_linia_preu", "linia": l.id, "local": local_id, "per": actor.id})
    db.commit()
    return l


def update(db: Session, actor: User, l: PriceLine, nom: str | None, actiu: bool | None) -> None:
    canvis = {}
    if nom is not None and nom.strip() != l.nom:
        canvis["nom"] = _nom(db, l.local_id, nom, l.id)
    if actiu is not None and actiu != l.actiu:
        canvis["actiu"] = actiu
    if not canvis:
        raise ValueError("No hi ha cap canvi")
    for k, v in canvis.items():
        setattr(l, k, v)
    service.audit_append(db, {"accio": "edita_linia_preu", "linia": l.id, "camps": sorted(canvis), "per": actor.id})
    db.commit()


def set_price(db: Session, actor: User, l: PriceLine, product_id: int, cent: int) -> None:
    p = db.get(Product, product_id)
    if not p or p.local_id != l.local_id:
        raise ValueError("Producte inexistent en aquest local")
    if not 0 <= cent <= MAX_PREU:
        raise ValueError("Preu no vàlid")
    fila = db.get(ProductPrice, (l.id, product_id))
    antic = fila.preu_cent_per_g if fila else None
    if fila:
        fila.preu_cent_per_g = cent
    else:
        db.add(ProductPrice(price_line_id=l.id, product_id=product_id, preu_cent_per_g=cent))
    service.audit_append(db, {"accio": "preu_linia", "linia": l.id, "producte": product_id, "abans": antic, "ara": cent, "per": actor.id})
    db.commit()


def remove_price(db: Session, actor: User, l: PriceLine, product_id: int) -> bool:
    fila = db.get(ProductPrice, (l.id, product_id))
    if not fila:
        return False
    db.delete(fila)
    service.audit_append(db, {"accio": "esborra_preu_linia", "linia": l.id, "producte": product_id, "per": actor.id})
    db.commit()
    return True


def member_line(db: Session, member_id: int) -> dict:
    fila = db.get(MemberPriceLine, member_id)
    l = db.get(PriceLine, fila.price_line_id) if fila else None
    return {"price_line_id": l.id if l else None, "nom": l.nom if l else None}


def assign(db: Session, actor: User, member: Member, line_id: int | None) -> None:
    if line_id is not None:
        l = db.get(PriceLine, line_id)
        if not l or l.local_id != member.local_id:
            raise ValueError("Línia de preu inexistent en aquest local")
    fila = db.get(MemberPriceLine, member.id)
    if line_id is None:
        if fila:
            db.delete(fila)
    elif fila:
        fila.price_line_id = line_id
    else:
        db.add(MemberPriceLine(member_id=member.id, price_line_id=line_id))
    service.audit_append(db, {"accio": "assigna_linia_preu", "soci": member.id, "linia": line_id, "per": actor.id})
    db.commit()

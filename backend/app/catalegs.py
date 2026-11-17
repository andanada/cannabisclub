"""Catàlegs auxiliars: aspecte (icona i color) de les categories de producte i monedes del club."""
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import service
from .models import Currency, Product, ProductCategory, User

ICONES = ["🌿", "🍃", "🔥", "💧", "🍬", "🍪", "🥤", "☕", "🧴", "🎁", "📦", "⭐"]
COLORS = ["verd", "blau", "roig", "groc", "lila", "taronja", "rosa", "gris"]


def categories(db: Session, local_id: int) -> list[dict]:
    """Categories del local: les dels productes més les que ja tenen aspecte propi, amb quants productes té cada una."""
    comptes = {c: n for c, n in db.execute(select(Product.categoria, func.count()).where(Product.local_id == local_id, Product.categoria != "")
                                           .group_by(Product.categoria))}
    aspecte = {c.nom: c for c in db.scalars(select(ProductCategory).where(ProductCategory.local_id == local_id))}
    return [{"nom": n, "icona": aspecte[n].icona if n in aspecte else "", "color": aspecte[n].color if n in aspecte else "", "productes": comptes.get(n, 0)}
            for n in sorted(set(comptes) | set(aspecte), key=str.casefold)]


def desa_categoria(db: Session, actor: User, local_id: int, nom: str, icona: str, color: str) -> None:
    nom = (nom or "").strip()
    if not nom:
        raise ValueError("El nom de la categoria no pot estar buit")
    if icona and icona not in ICONES:
        raise ValueError("Icona no vàlida")
    if color and color not in COLORS:
        raise ValueError("Color no vàlid")
    fila = db.scalar(select(ProductCategory).where(ProductCategory.local_id == local_id, ProductCategory.nom == nom))
    if fila:
        fila.icona, fila.color = icona, color
    else:
        db.add(ProductCategory(local_id=local_id, nom=nom, icona=icona, color=color))
    service.audit_append(db, {"accio": "aspecte_categoria", "local": local_id, "categoria": nom, "per": actor.id})
    db.commit()


def monedes(db: Session, local_id: int) -> list[dict]:
    return [{"id": c.id, "nom": c.nom, "codi": c.codi} for c in db.scalars(select(Currency).where(Currency.local_id == local_id).order_by(Currency.codi))]


def crea_moneda(db: Session, actor: User, local_id: int, nom: str, codi: str) -> int:
    nom, codi = (nom or "").strip(), (codi or "").strip().upper()
    if not nom or not codi:
        raise ValueError("Cal indicar el nom i el codi de la moneda")
    if not codi.isalnum() or len(codi) > 8:
        raise ValueError("El codi de la moneda ha de ser alfanumèric (màxim 8 caràcters)")
    if db.scalar(select(Currency.id).where(Currency.local_id == local_id, Currency.codi == codi)):
        raise ValueError("Ja existeix una moneda amb aquest codi")
    c = Currency(local_id=local_id, nom=nom, codi=codi)
    db.add(c)
    db.flush()
    service.audit_append(db, {"accio": "alta_moneda", "moneda": c.id, "local": local_id, "per": actor.id})
    db.commit()
    return c.id

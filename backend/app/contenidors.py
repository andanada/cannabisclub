"""Contenidors i tipus de contenidor: tara, producte contingut i pes net."""
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import service, stock
from .models import Container, ContainerType, Product, User

MAX_MG = 50_000_000  # 50 kg


def _g(mg: int | None) -> str | None:
    return None if mg is None else str(Decimal(mg) / 1000)


def _mg(g, nul_ok=False) -> int | None:
    if g is None and nul_ok:
        return None
    mg = int((Decimal(g) * 1000).quantize(Decimal("1")))
    if mg < 0 or mg > MAX_MG:
        raise ValueError("Pes no vàlid")
    return mg


def _nom(db: Session, model, local_id: int, camp, valor, excepte_id=None, maxlen=60) -> str:
    valor = (valor or "").strip()
    if not 1 <= len(valor) <= maxlen:
        raise ValueError(f"El text ha de tenir entre 1 i {maxlen} caràcters")
    q = select(model.id).where(model.local_id == local_id, getattr(model, camp) == valor)
    if excepte_id:
        q = q.where(model.id != excepte_id)
    if db.scalar(q):
        raise ValueError("Ja existeix un element amb aquest nom o codi en aquest local")
    return valor


def llista_tipus(db: Session, local_id: int) -> list[dict]:
    return [{"id": t.id, "nom": t.nom, "tara_g": _g(t.tara_mg), "actiu": t.actiu}
            for t in db.scalars(select(ContainerType).where(ContainerType.local_id == local_id).order_by(ContainerType.nom))]


def create_type(db: Session, actor: User, local_id: int, nom, tara_g) -> ContainerType:
    nom = _nom(db, ContainerType, local_id, "nom", nom)
    t = ContainerType(local_id=local_id, nom=nom, tara_mg=_mg(tara_g))
    db.add(t)
    db.flush()
    service.audit_append(db, {"accio": "alta_tipus_contenidor", "tipus": t.id, "local": local_id, "per": actor.id})
    db.commit()
    return t


def update_type(db: Session, actor: User, t: ContainerType, nom, tara_g, actiu) -> None:
    canvis = {}
    if nom is not None and nom.strip() != t.nom:
        canvis["nom"] = _nom(db, ContainerType, t.local_id, "nom", nom, t.id)
    if tara_g is not None and _mg(tara_g) != t.tara_mg:
        canvis["tara_mg"] = _mg(tara_g)
    if actiu is not None and actiu != t.actiu:
        canvis["actiu"] = actiu
    if not canvis:
        raise ValueError("No hi ha cap canvi")
    for k, v in canvis.items():
        setattr(t, k, v)
    service.audit_append(db, {"accio": "edita_tipus_contenidor", "tipus": t.id, "camps": sorted(canvis), "per": actor.id})
    db.commit()


def llista(db: Session, local_id: int) -> list[dict]:
    tipus = {t.id: t for t in db.scalars(select(ContainerType).where(ContainerType.local_id == local_id))}
    prods = {p.id: p.nom for p in db.scalars(select(Product).where(Product.local_id == local_id))}
    out = []
    for c in db.scalars(select(Container).where(Container.local_id == local_id).order_by(Container.codi)):
        t = tipus[c.type_id]
        net = None if c.brut_mg is None else c.brut_mg - t.tara_mg
        out.append({"id": c.id, "codi": c.codi, "type_id": t.id, "tipus": t.nom, "tara_g": _g(t.tara_mg), "product_id": c.product_id,
                    "producte": prods.get(c.product_id), "brut_g": _g(c.brut_mg), "net_g": _g(net), "actiu": c.actiu})
    return out


def _producte(db: Session, local_id: int, product_id):
    if product_id is None:
        return None
    p = db.get(Product, product_id)
    if not p or p.local_id != local_id:
        raise ValueError("Producte inexistent en aquest local")
    return p.id


def _tipus_valid(db: Session, local_id: int, type_id) -> ContainerType:
    t = db.get(ContainerType, type_id) if type_id else None
    if not t or t.local_id != local_id or not t.actiu:
        raise ValueError("Tipus de contenidor inexistent o desactivat")
    return t


def create(db: Session, actor: User, local_id: int, codi, type_id, product_id, brut_g) -> Container:
    codi = _nom(db, Container, local_id, "codi", codi, maxlen=40)
    t = _tipus_valid(db, local_id, type_id)
    brut = _mg(brut_g, nul_ok=True)
    if brut is not None and brut < t.tara_mg:
        raise ValueError("El pes brut no pot ser inferior a la tara del tipus")
    c = Container(local_id=local_id, codi=codi, type_id=t.id, product_id=_producte(db, local_id, product_id), brut_mg=brut)
    db.add(c)
    db.flush()
    service.audit_append(db, {"accio": "alta_contenidor", "contenidor": c.id, "local": local_id, "per": actor.id})
    db.commit()
    return c


def update(db: Session, actor: User, c: Container, camps: dict) -> None:
    """`camps` només porta els camps enviats (None és un valor vàlid per buidar producte o pes)."""
    if not camps:
        raise ValueError("No hi ha cap canvi")
    canvis = {}
    if "codi" in camps and (camps["codi"] or "").strip() != c.codi:
        canvis["codi"] = _nom(db, Container, c.local_id, "codi", camps["codi"], c.id, maxlen=40)
    if "type_id" in camps and camps["type_id"] != c.type_id:
        canvis["type_id"] = _tipus_valid(db, c.local_id, camps["type_id"]).id
    if "product_id" in camps:
        canvis["product_id"] = _producte(db, c.local_id, camps["product_id"])
    if "brut_g" in camps:
        canvis["brut_mg"] = _mg(camps["brut_g"], nul_ok=True)
    if "actiu" in camps and camps["actiu"] is not None:
        canvis["actiu"] = camps["actiu"]
    tara = db.get(ContainerType, canvis.get("type_id", c.type_id)).tara_mg
    brut = canvis.get("brut_mg", c.brut_mg)
    if brut is not None and brut < tara:
        raise ValueError("El pes brut no pot ser inferior a la tara del tipus")
    for k, v in canvis.items():
        setattr(c, k, v)
    service.audit_append(db, {"accio": "edita_contenidor", "contenidor": c.id, "camps": sorted(canvis), "per": actor.id})
    db.commit()

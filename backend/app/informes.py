"""Informes: vendes per producte, estoc valorat, assistència de socis i hores del personal."""
from collections import defaultdict
from datetime import date, timezone
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from . import personal
from .cash import _range
from .csvutil import to_csv
from .models import CheckIn, MovementDiscount, Product, StockMovement, User
from .stock import TZ, stock_by_product


def _g(mg: int) -> str:
    return str(Decimal(int(mg)) / 1000)


def sales(db: Session, local_id: int, des: date, fins: date, usuari: int | None = None) -> dict:
    """Vendes netes (les correccions hi resten) per producte i per categoria."""
    a, b = _range(des, fins)
    dispensat = case((StockMovement.tipus == "dispensacio", 1), else_=-1)
    q = (select(Product.nom, Product.categoria, func.sum(-StockMovement.delta_mg), func.sum(func.coalesce(StockMovement.import_cent, 0)),
                func.sum(dispensat))
         .join(Product, Product.id == StockMovement.product_id)
         .where(StockMovement.local_id == local_id, StockMovement.member_id.is_not(None),
                StockMovement.tipus.in_(["dispensacio", "correccio"]), StockMovement.ts >= a, StockMovement.ts < b))
    if usuari is not None:
        q = q.where(StockMovement.user_id == usuari)
    rows = db.execute(q.group_by(Product.id, Product.nom, Product.categoria).order_by(Product.nom))
    productes, per_cat = [], defaultdict(lambda: {"mg": 0, "import_cent": 0})
    tot_mg = tot_cent = tot_n = 0
    for nom, cat, mg, cent, n in rows:
        mg, cent, n = int(mg or 0), int(cent or 0), int(n or 0)
        if mg == 0 and cent == 0 and n == 0:
            continue  # totalment corregit: no apareix
        productes.append({"nom": nom, "categoria": cat, "grams": _g(mg), "import_cent": cent, "dispensacions": n})
        per_cat[cat or "(sense categoria)"]["mg"] += mg
        per_cat[cat or "(sense categoria)"]["import_cent"] += cent
        tot_mg, tot_cent, tot_n = tot_mg + mg, tot_cent + cent, tot_n + n
    qd = (select(func.coalesce(func.sum(MovementDiscount.descompte_cent), 0)).join(StockMovement, StockMovement.id == MovementDiscount.movement_id)
          .where(StockMovement.local_id == local_id, StockMovement.ts >= a, StockMovement.ts < b))
    if usuari is not None:
        qd = qd.where(StockMovement.user_id == usuari)
    descomptes = int(db.scalar(qd) or 0)
    return {"des": des.isoformat(), "fins": fins.isoformat(), "productes": productes,
            "categories": [{"categoria": k, "grams": _g(v["mg"]), "import_cent": v["import_cent"]} for k, v in sorted(per_cat.items())],
            "total": {"grams": _g(tot_mg), "import_cent": tot_cent, "dispensacions": tot_n, "descomptes_cent": descomptes}}


def sales_csv(r: dict) -> str:
    return to_csv(["producte", "categoria", "grams", "import_cent", "dispensacions"],
                  [[p["nom"], p["categoria"], p["grams"], p["import_cent"], p["dispensacions"]] for p in r["productes"]])


def valued_stock(db: Session, local_id: int) -> dict:
    """Estoc actual de cada producte actiu i el seu valor al preu de venda vigent."""
    productes, tot_mg, tot_cent = [], 0, 0
    prods = db.scalars(select(Product).where(Product.local_id == local_id, Product.actiu.is_(True)).order_by(Product.nom)).all()
    per_producte = stock_by_product(db, [p.id for p in prods])
    for p in prods:
        mg = per_producte[p.id]
        valor = int((Decimal(mg) * p.preu_cent_per_g / 1000).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        productes.append({"nom": p.nom, "categoria": p.categoria, "estoc_g": _g(mg), "preu_cent_per_g": p.preu_cent_per_g, "valor_cent": valor})
        tot_mg, tot_cent = tot_mg + mg, tot_cent + valor
    return {"productes": productes, "total_g": _g(tot_mg), "total_cent": tot_cent}


def stock_csv(r: dict) -> str:
    return to_csv(["producte", "categoria", "estoc_g", "preu_cent_per_g", "valor_cent"],
                  [[p["nom"], p["categoria"], p["estoc_g"], p["preu_cent_per_g"], p["valor_cent"]] for p in r["productes"]])


def attendance(db: Session, local_id: int, des: date, fins: date, usuari: int | None = None) -> dict:
    """Entrades de socis per dia (hora local) i socis diferents."""
    a, b = _range(des, fins)
    per_dia = defaultdict(lambda: {"entrades": 0, "socis": set()})
    tots = set()
    q = select(CheckIn).where(CheckIn.local_id == local_id, CheckIn.ts >= a, CheckIn.ts < b)
    if usuari is not None:
        q = q.where(CheckIn.user_id == usuari)
    for c in db.scalars(q):
        dia = c.ts.replace(tzinfo=c.ts.tzinfo or timezone.utc).astimezone(TZ).date().isoformat()
        per_dia[dia]["entrades"] += 1
        per_dia[dia]["socis"].add(c.member_id)
        tots.add(c.member_id)
    return {"des": des.isoformat(), "fins": fins.isoformat(),
            "per_dia": [{"dia": d, "entrades": v["entrades"], "socis": len(v["socis"])} for d, v in sorted(per_dia.items())],
            "total_entrades": sum(v["entrades"] for v in per_dia.values()), "socis_diferents": len(tots)}


def attendance_csv(r: dict) -> str:
    return to_csv(["dia", "entrades", "socis"], [[d["dia"], d["entrades"], d["socis"]] for d in r["per_dia"]])


def staff_hours(db: Session, local_id: int, des: date, fins: date, usuari: int | None = None) -> dict:
    """Hores treballades per persona (amb el nom d'usuari) en el rang."""
    brut = personal.hours(db, local_id, des, fins)
    if usuari is not None:
        brut = {k: v for k, v in brut.items() if k == str(usuari)}
    noms = {str(i): n for i, n in db.execute(select(User.id, User.username))}
    persones = [{"usuari": noms.get(uid, uid), "hores": round(v["segons_treballats"] / 3600, 2), "torns": v["torns"], "torn_obert": v["torn_obert"]}
                for uid, v in brut.items()]
    persones.sort(key=lambda p: p["usuari"])
    return {"des": des.isoformat(), "fins": fins.isoformat(), "persones": persones, "total_hores": round(sum(p["hores"] for p in persones), 2)}


def hours_csv(r: dict) -> str:
    return to_csv(["usuari", "hores", "torns", "torn_obert"], [[p["usuari"], p["hores"], p["torns"], p["torn_obert"]] for p in r["persones"]])

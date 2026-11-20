"""Consultes agrupades (SQL) compartides per rendibilitat, resum mensual i dispensari. Només lectura.

Quantitats: un diccionari {"g": text, "ud": text} (grams per als productes en grams, unitats per als altres), perquè sumar
grams i unitats no té sentit. Diners en cèntims."""
from collections import defaultdict
from datetime import date

from sqlalchemy import case, exists, func, select
from sqlalchemy.orm import Session, aliased

from .cash import _range
from .models import CashEntry, Expense, ExpenseCategory, Product, StockMovement
from .unitats import mg_to_g


def clau_unitat(p) -> str:
    return "g" if p.unitat == "g" else "ud"


def qtat(mgs: dict) -> dict:
    return {"g": mg_to_g(mgs.get("g", 0)), "ud": mg_to_g(mgs.get("ud", 0))}


def productes(db: Session, local_id: int) -> dict[int, Product]:
    return {p.id: p for p in db.scalars(select(Product).where(Product.local_id == local_id))}


def entrades(db: Session, local_id: int, des: date, fins: date) -> dict[int, dict]:
    """Entrades d'estoc no corregides del rang, per producte: {mg, cost_cent, estimat}. El cost és el pagat (cost_cent de cada
    entrada); si una entrada no en té, s'estima amb el preu d'entrada del producte i es marca com a estimat."""
    a, b = _range(des, fins)
    corr = aliased(StockMovement)
    q = (select(StockMovement.product_id, StockMovement.cost_cent.is_(None), func.sum(StockMovement.delta_mg), func.sum(StockMovement.cost_cent))
         .where(StockMovement.local_id == local_id, StockMovement.tipus == "entrada", StockMovement.ts >= a, StockMovement.ts < b,
                ~exists().where(corr.corregeix_id == StockMovement.id))
         .group_by(StockMovement.product_id, StockMovement.cost_cent.is_(None)))
    prods = productes(db, local_id)
    out: dict[int, dict] = defaultdict(lambda: {"mg": 0, "cost_cent": 0, "estimat": False})
    for pid, sense_cost, mg, cost in db.execute(q):
        p = prods.get(pid)
        if p is None:
            continue
        r = out[pid]
        r["mg"] += int(mg or 0)
        if sense_cost:
            r["estimat"] = True
            r["cost_cent"] += round((p.preu_entrada_cent or 0) * int(mg or 0) / 1000)
        else:
            r["cost_cent"] += int(cost or 0)
    return dict(out)


def dispensat(db: Session, local_id: int, des: date, fins: date) -> dict[int, dict]:
    """Dispensacions netes (amb correccions) per producte: {mg, import_cent, regal_mg}. Un regal (o la correcció d'un regal) va a part."""
    a, b = _range(des, fins)
    orig = aliased(StockMovement)
    es_regal = case((StockMovement.regal.is_(True), 1), (orig.regal.is_(True), 1), else_=0)
    q = (select(StockMovement.product_id, es_regal, func.sum(-StockMovement.delta_mg), func.sum(func.coalesce(StockMovement.import_cent, 0)))
         .outerjoin(orig, orig.id == StockMovement.corregeix_id)
         .where(StockMovement.local_id == local_id, StockMovement.tipus.in_(["dispensacio", "correccio"]),
                StockMovement.member_id.is_not(None), StockMovement.ts >= a, StockMovement.ts < b)
         .group_by(StockMovement.product_id, es_regal))
    out: dict[int, dict] = defaultdict(lambda: {"mg": 0, "import_cent": 0, "regal_mg": 0})
    for pid, regal, mg, cent in db.execute(q):
        r = out[pid]
        if regal:
            r["regal_mg"] += int(mg or 0)
        else:
            r["mg"] += int(mg or 0)
        r["import_cent"] += int(cent or 0)
    return dict(out)


def estoc_actual(db: Session, local_id: int) -> dict[int, int]:
    q = select(StockMovement.product_id, func.sum(StockMovement.delta_mg)).where(StockMovement.local_id == local_id).group_by(StockMovement.product_id)
    return {pid: int(mg or 0) for pid, mg in db.execute(q)}


def despeses(db: Session, local_id: int, des: date, fins: date, pendents: set[int] | None = None) -> dict:
    """Despeses del rang per categoria, separades en «caixa» (surten de la caixa del dia) i «final de mes» (sense apunt de caixa:
    sous, lloguer, compres d'estoc automàtiques, avançaments no de caixa...). Les anul·lacions resten. `pendent_cent` = part
    de les despeses automàtiques d'estoc encara pendents de revisió. Inclou els apunts de caixa antics sense fila a «expenses»."""
    out = {"caixa": defaultdict(int), "final_mes": defaultdict(int), "pendent": defaultdict(int)}
    noms = {c.id: c.nom for c in db.scalars(select(ExpenseCategory).where(ExpenseCategory.local_id == local_id))}
    for e in db.scalars(select(Expense).where(Expense.local_id == local_id, Expense.data >= des, Expense.data <= fins)):
        cent = -e.import_cent if e.corregeix_id is not None else e.import_cent
        cat = noms.get(e.category_id, "")
        ref = e.cash_entry_id
        if e.corregeix_id is not None:  # una anul·lació es classifica segons l'original (caixa o final de mes)
            original = db.get(Expense, e.corregeix_id)
            ref = original.cash_entry_id if original is not None else None
        out["caixa" if ref is not None else "final_mes"][cat] += cent
        if pendents and e.id in pendents:
            out["pendent"][cat] += cent
    a, b = _range(des, fins)
    enl = aliased(Expense)
    q = (select(CashEntry.categoria, func.sum(-CashEntry.import_cent))
         .where(CashEntry.local_id == local_id, CashEntry.categoria.is_not(None), CashEntry.ts >= a, CashEntry.ts < b,
                ~exists().where(enl.cash_entry_id == CashEntry.id), ~exists().where(enl.cash_entry_id == CashEntry.corregeix_id))
         .group_by(CashEntry.categoria))
    for cat, cent in db.execute(q):
        out["caixa"][cat] += int(cent or 0)
    return {k: dict(v) for k, v in out.items()}


def total_despeses(d: dict) -> int:
    return sum(d["caixa"].values()) + sum(d["final_mes"].values())

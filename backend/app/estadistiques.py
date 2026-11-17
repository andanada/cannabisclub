"""Estadístiques per a responsables: socis, dispensari i bar, i finances. Només lectura.

«Dispensari» = productes genètics; «bar» = la resta (begudes, accessoris…). Les vendes són els moviments de dispensació
(les correccions hi resten): és el que s'ha dispensat, estigui cobrat o no. Els agregats demogràfics respecten el llindar
d'anonimat (informes_socis.anonimitza); els «top 10» porten noms de soci i la consulta queda a l'auditoria."""
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import crypto, informes_socis, service
from .models import CheckIn, Expense, Member, Product, Quota, StockMovement, User
from .stock import TZ

TOP = 10


def _dia(ts: datetime) -> date:
    return ts.replace(tzinfo=ts.tzinfo or timezone.utc).astimezone(TZ).date()


def _g(mg: int) -> str:
    return str(Decimal(mg) / 1000)


def _vendes(db: Session, local_id: int, des: date | None = None) -> list[dict]:
    """Dispensacions netes (amb correccions) amb producte i data local. Una fila per moviment."""
    q = (select(StockMovement, Product).join(Product, Product.id == StockMovement.product_id)
         .where(StockMovement.local_id == local_id, StockMovement.tipus.in_(["dispensacio", "correccio"]), StockMovement.member_id.is_not(None)))
    if des is not None:
        q = q.where(StockMovement.ts >= datetime(des.year, des.month, des.day, tzinfo=TZ).astimezone(timezone.utc))
    return [{"dia": _dia(m.ts), "mg": -m.delta_mg, "cent": m.import_cent or 0, "soci": m.member_id, "producte": p.nom,
             "genetic": p.es_genetic} for m, p in db.execute(q)]


def _suma(files: list[dict], des: date, fins: date) -> int:
    return sum(f["cent"] for f in files if des <= f["dia"] <= fins)


def _variacio(actual: int, anterior: int) -> float | None:
    return None if anterior == 0 else round((actual - anterior) * 100 / anterior, 1)


def _mesos(fins: date, n: int) -> list[str]:
    """Els n mesos (YYYY-MM) acabats al de `fins`, del més antic al més recent."""
    out, y, m = [], fins.year, fins.month
    for _ in range(n):
        out.append(f"{y}-{m:02d}")
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    return out[::-1]


def _top(files: list[dict], genetic: bool, per: str) -> list[dict]:
    acc: dict[str, dict] = defaultdict(lambda: {"mg": 0, "cent": 0})
    for f in files:
        if f["genetic"] == genetic:
            acc[f["producte"]]["mg"] += f["mg"]
            acc[f["producte"]]["cent"] += f["cent"]
    cla = "mg" if per == "grams" else "cent"
    return [{"producte": k, "grams": _g(v["mg"]), "import_cent": v["cent"]}
            for k, v in sorted(acc.items(), key=lambda kv: -kv[1][cla])[:TOP] if v[cla] > 0]


def membres(db: Session, actor: User, local_id: int) -> dict:
    avui = datetime.now(TZ).date()
    socis = list(db.scalars(select(Member).where(Member.local_id == local_id)))
    actius = [m for m in socis if m.estat != "baixa"]
    # gènere (dada de perfil xifrada): mateix llindar d'anonimat que l'edat
    comptes = {"home": 0, "dona": 0, "altre": 0, "": 0}
    for m in actius:
        comptes[service.llegeix_perfil(m)["genere"]] += 1
    noms_genere = {"home": "Home", "dona": "Dona", "altre": "Altre", "": "Sense dada"}
    genere = informes_socis.anonimitza({"total": len(actius), "edat_mitjana": 0,
                                        "franges": [{"franja": noms_genere[k], "socis": v} for k, v in comptes.items()]})
    # nous socis per mes (12 mesos)
    mesos = _mesos(avui, 12)
    nous = defaultdict(int)
    for m in socis:
        nous[informes_socis._mes(m.creat)] += 1
    # comptadors dels darrers 30 dies
    fa30 = datetime.now(timezone.utc) - timedelta(days=30)
    from . import ajustos
    dies_inactiu = ajustos.get(db, local_id)["inactivitat_dies"]
    amb_visita = set(db.scalars(select(CheckIn.member_id).where(
        CheckIn.local_id == local_id, CheckIn.ts >= datetime.now(timezone.utc) - timedelta(days=dies_inactiu))))
    primera: dict[int, int] = {}   # id de la primera quota de cada soci: les següents són renovacions
    renovats = set()
    for q in db.scalars(select(Quota).where(Quota.local_id == local_id).order_by(Quota.ts, Quota.id)):
        if q.member_id not in primera:
            primera[q.member_id] = q.id
        elif q.ts.replace(tzinfo=q.ts.tzinfo or timezone.utc) >= fa30:
            renovats.add(q.member_id)
    nous30 = [m for m in socis if m.creat.replace(tzinfo=m.creat.tzinfo or timezone.utc) >= fa30]
    # tops de l'any en curs
    files = _vendes(db, local_id, date(avui.year, 1, 1))
    per_soci: dict[int, dict] = defaultdict(lambda: {"mg": 0, "cent": 0})
    for f in files:
        per_soci[f["soci"]]["mg"] += f["mg"]
        per_soci[f["soci"]]["cent"] += f["cent"]
    noms = {m.id: crypto.decrypt(m.nom_enc) for m in socis if m.id in per_soci}

    def top(cla):
        return [{"soci": noms[i], "grams": _g(v["mg"]), "import_cent": v["cent"]}
                for i, v in sorted(per_soci.items(), key=lambda kv: -kv[1][cla])[:TOP] if v[cla] > 0 and i in noms]
    service.audit_append(db, {"accio": "consulta_estadistiques", "tipus": "membres", "local": local_id, "per": actor.id})
    db.commit()
    return {"edat": informes_socis.demographics(db, local_id), "genere": genere,
            "nous_per_mes": [{"mes": k, "socis": nous.get(k, 0)} for k in mesos],
            "comptadors": {"dies_inactivitat": dies_inactiu, "sense_visites": sum(1 for m in actius if m.estat == "actiu" and m.id not in amb_visita),
                           "nous_30d": len(nous30), "renovats_30d": len(renovats)},
            "top_grams": top("mg"), "top_import": top("cent"), "any": avui.year}


def dispensari(db: Session, actor: User, local_id: int) -> dict:
    avui = datetime.now(TZ).date()
    files = _vendes(db, local_id, avui - timedelta(days=200))
    totals = {g: {"mg": 0, "cent": 0} for g in (True, False)}
    for f in files:
        totals[f["genetic"]]["mg"] += f["mg"]
        totals[f["genetic"]]["cent"] += f["cent"]
    total_cent = totals[True]["cent"] + totals[False]["cent"]

    def periodes(genetic):
        sel = [f for f in files if f["genetic"] == genetic]
        return {"avui": _suma(sel, avui, avui), "ahir": _suma(sel, avui - timedelta(days=1), avui - timedelta(days=1)),
                "setmana": _suma(sel, avui - timedelta(days=6), avui),
                "mesos": [{"mes": m, "import_cent": sum(f["cent"] for f in sel if f["dia"].strftime("%Y-%m") == m)} for m in _mesos(avui, 6)]}
    service.audit_append(db, {"accio": "consulta_estadistiques", "tipus": "dispensari", "local": local_id, "per": actor.id})
    db.commit()
    return {"percentatge_genetics": None if total_cent == 0 else round(totals[True]["cent"] * 100 / total_cent, 1),
            "preu_mitja_genetics_cent_per_g": round(totals[True]["cent"] * 1000 / totals[True]["mg"]) if totals[True]["mg"] > 0 else None,
            "preu_mitja_no_genetics_cent": round(totals[False]["cent"] / max(1, sum(1 for f in files if not f["genetic"] and f["cent"] > 0))) if totals[False]["cent"] else None,
            "dispensari": periodes(True), "bar": periodes(False),
            "top_genetics_grams": _top(files, True, "grams"), "top_genetics_import": _top(files, True, "cent"),
            "top_no_genetics_import": _top(files, False, "cent")}


def finances(db: Session, actor: User, local_id: int, any_: int | None = None) -> dict:
    avui = datetime.now(TZ).date()
    any_ = any_ or avui.year
    files = _vendes(db, local_id, date(min(any_, avui.year) - 1, 1, 1))
    ingressos = {"avui": _suma(files, avui, avui), "ahir": _suma(files, avui - timedelta(days=1), avui - timedelta(days=1)),
                 "setmana": _suma(files, avui - timedelta(days=6), avui), "setmana_anterior": _suma(files, avui - timedelta(days=13), avui - timedelta(days=7))}
    ingressos["variacio_dia_pct"] = _variacio(ingressos["avui"], ingressos["ahir"])
    ingressos["variacio_setmana_pct"] = _variacio(ingressos["setmana"], ingressos["setmana_anterior"])
    despeses_mes: dict[str, int] = defaultdict(int)
    for e in db.scalars(select(Expense).where(Expense.local_id == local_id, Expense.data >= date(any_, 1, 1), Expense.data <= date(any_, 12, 31))):
        despeses_mes[e.data.strftime("%Y-%m")] += -e.import_cent if e.corregeix_id is not None else e.import_cent
    mesos, grams_total, dies_amb_venda = [], 0, set()
    for n in range(1, 13):
        k = f"{any_}-{n:02d}"
        sel = [f for f in files if f["dia"].strftime("%Y-%m") == k]
        vendes = sum(f["cent"] for f in sel)
        mg = sum(f["mg"] for f in sel if f["genetic"])
        dies = {f["dia"] for f in sel if f["genetic"] and f["mg"] > 0}
        grams_total += mg
        dies_amb_venda |= dies
        mesos.append({"mes": k, "vendes_cent": vendes, "despeses_cent": despeses_mes.get(k, 0), "benefici_cent": vendes - despeses_mes.get(k, 0),
                      "grams": _g(mg), "mitjana_diaria_g": _g(mg // len(dies)) if dies else "0"})
    service.audit_append(db, {"accio": "consulta_estadistiques", "tipus": "finances", "local": local_id, "per": actor.id})
    db.commit()
    return {"any": any_, "ingressos": ingressos, "mesos": mesos, "grams_any": _g(grams_total),
            "mitjana_diaria_g": _g(grams_total // len(dies_amb_venda)) if dies_amb_venda else "0"}

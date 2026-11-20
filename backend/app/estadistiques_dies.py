"""Finances dia a dia (8.3), dispensari per categories (8.2) i top de visites (8.1). Només lectura.

Torns: cada ingrés es classifica pel moment en què s'ha apuntat, segons la franja de la configuració d'horaris del local
(horaris.torns_del_dia): abans de l'inici del torn de tarda = matí; des de l'inici = tarda. Els dies de torn únic tot compta
com a tarda. Billets i monedes: l'efectiu que es retira en tancar cada caixa (sortida_billets/monedes_cent) el dia del tancament."""
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import crypto, horaris, service
from . import estadistiques_comu as C
from .cash import _range
from .models import CashEntry, CashSession, CheckIn, Member, User
from .stock import TZ

TOP = 10
MAX_DIES = 366


def _dia(ts: datetime) -> date:
    return ts.replace(tzinfo=ts.tzinfo or timezone.utc).astimezone(TZ).date()


def _limit_tarda(cfg: dict, d: date, cache: dict) -> str | None:
    if d not in cache:
        torns = horaris.torns_del_dia(cfg, d)
        cache[d] = torns["tarda"][0] if "tarda" in torns else None
    return cache[d]


def finances_dies(db: Session, actor: User, local_id: int, des: date, fins: date) -> dict:
    if fins < des:
        raise ValueError("Rang de dates invàlid")
    if (fins - des).days >= MAX_DIES:
        raise ValueError("El rang no pot passar d'un any")
    a, b = _range(des, fins)
    cfg, cache = horaris.get_config(db, local_id), {}
    dies: dict[date, dict] = {}
    d = des
    while d <= fins:
        dies[d] = {"dia": d.isoformat(), "mati_cent": 0, "tarda_cent": 0, "billets_cent": 0, "monedes_cent": 0, "efectiu_cent": 0,
                   "targeta_cent": 0, "bizum_cent": 0, "total_cent": 0, "despeses_caixa_cent": 0}
        d += timedelta(days=1)
    for ts, metode, categoria, cent in db.execute(select(CashEntry.ts, CashEntry.metode, CashEntry.categoria, CashEntry.import_cent).where(
            CashEntry.local_id == local_id, CashEntry.ts >= a, CashEntry.ts < b)):
        if metode == "monedero":
            continue
        local = ts.replace(tzinfo=ts.tzinfo or timezone.utc).astimezone(TZ)
        r = dies[local.date()]
        if categoria is not None:
            r["despeses_caixa_cent"] += -cent
            continue
        r[metode + "_cent"] += cent
        r["total_cent"] += cent
        lim = _limit_tarda(cfg, local.date(), cache)
        r["mati_cent" if lim and local.strftime("%H:%M") < lim else "tarda_cent"] += cent
    for tanc, bil, mon in db.execute(select(CashSession.closed_at, CashSession.sortida_billets_cent, CashSession.sortida_monedes_cent).where(
            CashSession.local_id == local_id, CashSession.closed_at >= a, CashSession.closed_at < b)):
        r = dies[_dia(tanc)]
        r["billets_cent"] += bil or 0
        r["monedes_cent"] += mon or 0
    files = list(dies.values())
    tots = {k: sum(f[k] for f in files) for k in files[0] if k != "dia"} if files else {}
    vendes = sum(v["import_cent"] for v in C.dispensat(db, local_id, des, fins).values())
    service.audit_append(db, {"accio": "consulta_estadistiques", "tipus": "finances_dies", "local": local_id, "per": actor.id})
    db.commit()
    return {"des": des.isoformat(), "fins": fins.isoformat(), "dies": files, "totals": tots, "vendes_cent": vendes,
            "despeses_cent": C.total_despeses(C.despeses(db, local_id, des, fins))}


def categories_dispensari(db: Session, local_id: int, des: date, fins: date) -> dict:
    """Categoria més dispensada i top 10 productes per quantitat dins de cada categoria (dispensacions netes, sense regals)."""
    prods = C.productes(db, local_id)
    per_cat: dict[str, dict] = defaultdict(lambda: {"mg": defaultdict(int), "cent": 0, "productes": []})
    for pid, r in C.dispensat(db, local_id, des, fins).items():
        p = prods.get(pid)
        if p is None or (r["mg"] <= 0 and r["import_cent"] <= 0):
            continue
        c = per_cat[p.categoria or ""]
        c["mg"][C.clau_unitat(p)] += r["mg"]
        c["cent"] += r["import_cent"]
        c["productes"].append({"producte": p.nom, "unitat": C.clau_unitat(p), "mg": r["mg"], "import_cent": r["import_cent"]})
    cats = []
    for nom, c in per_cat.items():
        top = sorted(c["productes"], key=lambda x: -x["mg"])[:TOP]
        cats.append({"categoria": nom, "quantitat": C.qtat(c["mg"]), "mg_g": c["mg"].get("g", 0), "import_cent": c["cent"],
                     "top": [{"producte": t["producte"], "unitat": t["unitat"], "quantitat": C.mg_to_g(t["mg"]), "import_cent": t["import_cent"]} for t in top]})
    cats.sort(key=lambda c: (-c["mg_g"], -c["import_cent"], c["categoria"]))
    for c in cats:
        del c["mg_g"]
    return {"des": des.isoformat(), "fins": fins.isoformat(), "categoria_top": cats[0]["categoria"] if cats else None, "categories": cats}


def top_visites(db: Session, local_id: int, des: date, fins: date) -> list[dict]:
    """Els 10 socis amb més entrades al local. Només nom i nombre de visites (dada mínima); s'agrupa en SQL i es desxifren 10 noms."""
    a, b = _range(des, fins)
    q = (select(CheckIn.member_id, func.count()).where(CheckIn.local_id == local_id, CheckIn.tipus == "entrada", CheckIn.ts >= a, CheckIn.ts < b)
         .group_by(CheckIn.member_id).order_by(func.count().desc(), CheckIn.member_id).limit(TOP))
    files = list(db.execute(q))
    noms = {m.id: crypto.decrypt(m.nom_enc) for m in db.scalars(select(Member).where(Member.id.in_([i for i, _ in files])))} if files else {}
    return [{"soci": noms.get(i, ""), "visites": n} for i, n in files]

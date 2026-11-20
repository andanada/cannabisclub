"""Rendibilitat per producte (8.4) i resum mensual (8.5). Només lectura; la consulta queda a l'auditoria.

Benefici = ingressat - pagat (diners reals del període). Els regals no ingressen res: el seu cost ja és dins el pagat i es
mostra a part (regal_cost_cent, estimat amb el cost mitjà per unitat). Benefici potencial = benefici + valor de l'estoc restant
al preu de dispensació (l'estoc és l'actual, no el de la data final)."""
import calendar
from collections import defaultdict
from datetime import date, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session, aliased

from . import estadistiques_comu as C
from . import gastos, service
from .cash import _range
from .csvutil import to_csv
from .models import CashEntry, CashSession, User, WalletMovement
from .unitats import mg_to_g


def _fila(p, ent, dis, estoc_mg) -> dict:
    u = C.clau_unitat(p)
    mg_ent, pagat = (ent or {}).get("mg", 0), (ent or {}).get("cost_cent", 0)
    cost_mg = pagat / mg_ent if mg_ent else (p.preu_entrada_cent or 0) / 1000
    d = dis or {"mg": 0, "import_cent": 0, "regal_mg": 0}
    valor = round(estoc_mg * p.preu_cent_per_g / 1000)
    return {"id": p.id, "nom": p.nom, "categoria": p.categoria or "", "genetic": bool(p.es_genetic), "u": u,
            "ent": mg_ent, "pagat": pagat, "estimat": bool((ent or {}).get("estimat")), "dis": d["mg"], "ing": d["import_cent"],
            "regal": d["regal_mg"], "regal_cost": round(d["regal_mg"] * cost_mg), "estoc": estoc_mg, "valor": valor}


def _plega(files: list[dict]) -> dict:
    s = {k: defaultdict(int) for k in ("ent", "dis", "regal", "estoc")}
    t = {"pagat": 0, "ing": 0, "regal_cost": 0, "valor": 0}
    estimat = False
    for f in files:
        for k in s:
            s[k][f["u"]] += f[k]
        for k in t:
            t[k] += f[k]
        estimat = estimat or f["estimat"]
    ben = t["ing"] - t["pagat"]
    return {"entrat": C.qtat(s["ent"]), "pagat_cent": t["pagat"], "pagat_estimat": estimat, "dispensat": C.qtat(s["dis"]),
            "ingressat_cent": t["ing"], "regal": C.qtat(s["regal"]), "regal_cost_cent": t["regal_cost"], "estoc": C.qtat(s["estoc"]),
            "valor_potencial_cent": t["valor"], "benefici_cent": ben, "benefici_potencial_cent": ben + t["valor"]}


def rendibilitat(db: Session, actor: User, local_id: int, des: date, fins: date) -> dict:
    prods = C.productes(db, local_id)
    ent, dis, estoc = C.entrades(db, local_id, des, fins), C.dispensat(db, local_id, des, fins), C.estoc_actual(db, local_id)
    files = [_fila(p, ent.get(pid), dis.get(pid), estoc.get(pid, 0)) for pid, p in prods.items()
             if pid in ent or pid in dis or estoc.get(pid, 0) != 0]
    files.sort(key=lambda f: (f["categoria"].lower(), f["nom"].lower()))
    per_cat: dict[str, list] = defaultdict(list)
    for f in files:
        per_cat[f["categoria"]].append(f)
    service.audit_append(db, {"accio": "consulta_estadistiques", "tipus": "rendibilitat", "local": local_id, "per": actor.id})
    db.commit()
    return {"des": des.isoformat(), "fins": fins.isoformat(),
            "productes": [{"id": f["id"], "nom": f["nom"], "categoria": f["categoria"], "genetic": f["genetic"], **_plega([f])} for f in files],
            "per_categoria": [{"categoria": k, **_plega(v)} for k, v in sorted(per_cat.items())],
            "genetics": _plega([f for f in files if f["genetic"]]), "no_genetics": _plega([f for f in files if not f["genetic"]]),
            "total": _plega(files)}


def rendibilitat_csv(r: dict) -> str:
    cap = ["producte", "categoria", "genetic", "entrat_g", "entrat_ud", "pagat_cent", "pagat_estimat", "dispensat_g", "dispensat_ud",
           "ingressat_cent", "regal_g", "regal_ud", "regal_cost_cent", "estoc_g", "estoc_ud", "valor_potencial_cent", "benefici_cent", "benefici_potencial_cent"]

    def fila(nom, cat, gen, x):
        return [nom, cat, gen, x["entrat"]["g"], x["entrat"]["ud"], x["pagat_cent"], "si" if x["pagat_estimat"] else "no", x["dispensat"]["g"],
                x["dispensat"]["ud"], x["ingressat_cent"], x["regal"]["g"], x["regal"]["ud"], x["regal_cost_cent"], x["estoc"]["g"], x["estoc"]["ud"],
                x["valor_potencial_cent"], x["benefici_cent"], x["benefici_potencial_cent"]]
    rows = [fila(p["nom"], p["categoria"], "si" if p["genetic"] else "no", p) for p in r["productes"]]
    rows += [fila("TOTAL categoria", c["categoria"], "", c) for c in r["per_categoria"]]
    rows += [fila("TOTAL genetiques", "", "si", r["genetics"]), fila("TOTAL no genetiques", "", "no", r["no_genetics"]), fila("TOTAL", "", "", r["total"])]
    return to_csv(cap, rows)


# ---------- resum mensual ----------

def _mes(mes: str) -> tuple[date, date]:
    try:
        a = datetime.strptime(mes, "%Y-%m").date()
    except ValueError:
        raise ValueError("Mes no vàlid (format AAAA-MM)")
    return a, date(a.year, a.month, calendar.monthrange(a.year, a.month)[1])


def _grups(files: list[dict], camps: tuple[str, ...]) -> dict:
    """Plega per genètics / no genètics i per categoria (suma només els camps indicats, en mg per unitat)."""
    def plega(sel):
        out = {c: defaultdict(int) for c in camps if c != "cent"}
        cent = 0
        for f in sel:
            for c in out:
                out[c][f["u"]] += f[c]
            cent += f.get("cent", 0)
        return {**{c: C.qtat(v) for c, v in out.items()}, "cent": cent}
    per_cat: dict[str, list] = defaultdict(list)
    for f in files:
        per_cat[f["categoria"]].append(f)
    return {"genetics": plega([f for f in files if f["genetic"]]), "no_genetics": plega([f for f in files if not f["genetic"]]),
            "per_categoria": [{"categoria": k, "genetic": v[0]["genetic"], **plega(v)} for k, v in sorted(per_cat.items())],
            "total": plega(files)}


def _ingressos(db: Session, local_id: int, des: date, fins: date) -> dict:
    a, b = _range(des, fins)
    orig = aliased(CashEntry)
    tipus = func.coalesce(orig.tipus, CashEntry.tipus)
    q = (select(tipus, CashEntry.metode, func.sum(CashEntry.import_cent)).outerjoin(orig, orig.id == CashEntry.corregeix_id)
         .where(CashEntry.local_id == local_id, CashEntry.categoria.is_(None), CashEntry.metode != "monedero", CashEntry.ts >= a, CashEntry.ts < b)
         .group_by(tipus, CashEntry.metode))
    don, quo = defaultdict(int), defaultdict(int)
    for t, metode, cent in db.execute(q):
        (quo if t == "quota" else don)[metode] += int(cent or 0)
    sessions = db.execute(select(func.coalesce(func.sum(CashSession.sortida_billets_cent), 0), func.coalesce(func.sum(CashSession.sortida_monedes_cent), 0))
                          .where(CashSession.local_id == local_id, CashSession.closed_at >= a, CashSession.closed_at < b)).one()

    def bloc(d):
        return {"efectiu_cent": d["efectiu"], "targeta_cent": d["targeta"], "bizum_cent": d["bizum"], "total_cent": d["efectiu"] + d["targeta"] + d["bizum"]}
    donacions, quotes = bloc(don), bloc(quo)
    return {"donacions": donacions, "quotes": quotes, "billets_cent": int(sessions[0]), "monedes_cent": int(sessions[1]),
            "total_cent": donacions["total_cent"] + quotes["total_cent"]}


def _credit(db: Session, local_id: int, fins_exclusiu: date) -> int:
    _, b = _range(fins_exclusiu, fins_exclusiu)
    a = _range(fins_exclusiu, fins_exclusiu)[0]
    return int(db.scalar(select(func.coalesce(func.sum(WalletMovement.import_cent), 0)).where(WalletMovement.local_id == local_id, WalletMovement.ts < a)))


def resum_mensual(db: Session, actor: User, local_id: int, mes: str) -> dict:
    des, fins = _mes(mes)
    prods = C.productes(db, local_id)
    ent, dis = C.entrades(db, local_id, des, fins), C.dispensat(db, local_id, des, fins)
    f_ent = [{"u": C.clau_unitat(prods[i]), "categoria": prods[i].categoria or "", "genetic": bool(prods[i].es_genetic),
              "mg": r["mg"], "cent": r["cost_cent"], "estimat": r["estimat"]} for i, r in ent.items()]
    f_dis = [{"u": C.clau_unitat(prods[i]), "categoria": prods[i].categoria or "", "genetic": bool(prods[i].es_genetic),
              "mg": r["mg"], "regal_mg": r["regal_mg"], "cent": r["import_cent"]} for i, r in dis.items() if i in prods]
    pend = {p.id for p in gastos._pendents_exp(db, local_id)}
    desp = C.despeses(db, local_id, des, fins, pend)
    ingressos = _ingressos(db, local_id, des, fins)
    total_desp = C.total_despeses(desp)
    credit_fi = _credit(db, local_id, fins + timedelta(days=1))
    credit_ini = _credit(db, local_id, des)
    service.audit_append(db, {"accio": "consulta_estadistiques", "tipus": "resum_mensual", "local": local_id, "per": actor.id})
    db.commit()
    return {"mes": mes, "des": des.isoformat(), "fins": fins.isoformat(),
            "entrades": {**_grups(f_ent, ("mg", "cent")), "estimat": any(f["estimat"] for f in f_ent)},
            "dispensat": _grups(f_dis, ("mg", "cent")),
            "regals": _grups([{**f, "mg": f["regal_mg"], "cent": 0} for f in f_dis if f["regal_mg"]], ("mg",)),
            "ingressos": ingressos,
            "despeses": {"caixa": _llista(desp["caixa"], desp["pendent"]), "final_mes": _llista(desp["final_mes"], desp["pendent"]),
                         "caixa_cent": sum(desp["caixa"].values()), "final_mes_cent": sum(desp["final_mes"].values()),
                         "pendent_cent": sum(desp["pendent"].values()), "total_cent": total_desp},
            "credit": {"final_cent": credit_fi, "inici_cent": credit_ini, "diferencia_cent": credit_fi - credit_ini},
            "total_net_cent": ingressos["total_cent"] - total_desp}


def _llista(d: dict, pendent: dict) -> list[dict]:
    return [{"categoria": k, "import_cent": v, "pendent_cent": pendent.get(k, 0) if v else 0} for k, v in sorted(d.items()) if v]


def resum_csv(r: dict) -> str:
    rows = []
    for nom, bloc in (("Entrades d'estoc", r["entrades"]), ("Dispensat", r["dispensat"])):
        for k, t in (("Genetiques", bloc["genetics"]), ("No genetiques", bloc["no_genetics"])):
            rows.append([nom, k, "", t["mg"]["g"], t["mg"]["ud"], t["cent"]])
        for c in bloc["per_categoria"]:
            rows.append([nom, "Categoria", c["categoria"], c["mg"]["g"], c["mg"]["ud"], c["cent"]])
    for c in r["regals"]["per_categoria"]:
        rows.append(["Regals", "Categoria", c["categoria"], c["mg"]["g"], c["mg"]["ud"], 0])
    i = r["ingressos"]
    for nom, b in (("Donacions", i["donacions"]), ("Quotes", i["quotes"])):
        for m in ("efectiu", "targeta", "bizum"):
            rows.append(["Diners entrats", nom, m, "", "", b[m + "_cent"]])
    rows += [["Diners entrats", "Efectiu retirat", "billets", "", "", i["billets_cent"]], ["Diners entrats", "Efectiu retirat", "monedes", "", "", i["monedes_cent"]]]
    for grup in ("caixa", "final_mes"):
        for d in r["despeses"][grup]:
            rows.append(["Despeses", grup, d["categoria"] + (" (pendent de revisio)" if d["pendent_cent"] else ""), "", "", d["import_cent"]])
    rows += [["Credit no dispensat", "final de mes", "", "", "", r["credit"]["final_cent"]], ["Credit no dispensat", "diferencia amb mes anterior", "", "", "", r["credit"]["diferencia_cent"]],
             ["Total net", "diners entrats - despeses", "", "", "", r["total_net_cent"]]]
    return to_csv(["bloc", "concepte", "categoria", "quantitat_g", "quantitat_ud", "import_cent"], rows)

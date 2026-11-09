"""Migració única del camp `es_genetic`.

Les bases de dades anteriors a aquest camp tenen tots els productes amb es_genetic = FALSE i, en canvi, els límits
de dispensació només compten productes genètics: sense aquesta migració els límits deixarien d'aplicar-se.
Per a cada local, UNA sola vegada (marca a `local_settings`), marca com a genètics els productes la categoria
dels quals és de flor, hash, extracte, clon o llavor, i retorna la llista de la resta perquè una persona la revisi.
Si el local ja té algun producte genètic (algú ja l'ha classificat), no es toca res: només es desa la marca."""
import re
import unicodedata
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import service
from .models import Local, LocalSetting, Product

MARCA = "es_genetic_migrat"
GENETIC_RE = re.compile(r"\b(flor|flors|flores|flower|flowers|cogoll\w*|buds?|hash\w*|haix\w*|hachis\w*|extract\w*|resin\w*|rosin|"
                        r"shatter|clon\w*|esqueix\w*|llavor\w*|semill\w*|seeds?|cannabis|marihuana|marijuana)\b")


def _norm(text: str) -> str:
    return unicodedata.normalize("NFKD", (text or "").lower()).encode("ascii", "ignore").decode()


def es_genetic_per_categoria(categoria: str) -> bool:
    return bool(GENETIC_RE.search(_norm(categoria)))


def migra(db: Session) -> dict:
    """Retorna {"marcats": [...], "pendents": [...], "locals_ja_fets": n}. Cada llista té {local, id, nom, categoria, pista}."""
    marcats, pendents, ja_fets = [], [], 0
    for loc in db.scalars(select(Local).order_by(Local.id)):
        if db.get(LocalSetting, (loc.id, MARCA)):
            ja_fets += 1
            continue
        prods = list(db.scalars(select(Product).where(Product.local_id == loc.id).order_by(Product.nom)))
        classificat = any(p.es_genetic for p in prods)
        for p in prods:
            fila = {"local": loc.id, "id": p.id, "nom": p.nom, "categoria": p.categoria}
            if p.es_genetic:
                continue
            if not classificat and es_genetic_per_categoria(p.categoria):
                p.es_genetic = True
                marcats.append(fila)
            else:
                pendents.append({**fila, "pista": es_genetic_per_categoria(p.nom)})
        db.add(LocalSetting(local_id=loc.id, clau=MARCA, valor=date.today().isoformat()))
        if prods:
            service.audit_append(db, {"accio": "migracio_es_genetic", "local": loc.id,
                                      "marcats": [f["id"] for f in marcats if f["local"] == loc.id],
                                      "classificat_abans": classificat})
    db.commit()
    return {"marcats": marcats, "pendents": pendents, "locals_ja_fets": ja_fets}


def informe(r: dict) -> str:
    out = [f"Productes marcats com a genètics: {len(r['marcats'])}"]
    out += [f"  + local {f['local']} #{f['id']} {f['nom']} ({f['categoria'] or 'sense categoria'})" for f in r["marcats"]]
    out.append(f"Productes NO genètics pendents de revisar: {len(r['pendents'])}"
               + (" (els límits per soci NOMÉS compten productes genètics: revisa'ls a Estoc > Productes)" if r["pendents"] else ""))
    out += [f"  ? local {f['local']} #{f['id']} {f['nom']} ({f['categoria'] or 'sense categoria'})" + ("  <- el nom sembla genètic" if f["pista"] else "")
            for f in r["pendents"][:300]]
    if len(r["pendents"]) > 300:
        out.append(f"  … i {len(r['pendents']) - 300} més")
    return "\n".join(out)

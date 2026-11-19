"""Inventaris: control de l'estoc comptant pesos reals.

Tres àmbits: dispensari (productes genètics del dispensari, amb la tara del pot restada del pes), magatzem (genètics del magatzem) i
no genètics (per unitats, a tot el local). Dos tipus de control: complet (tots els productes de l'àmbit) o d'un sol producte.

El recompte NO toca l'estoc: es desa amb el botó «Guardar» i els resultats els consulta la gerència, amb avisos quan una
diferència supera el límit (ajust `perdua_maxima_mg`). La gerència pot, després, ajustar l'estoc al comptat."""
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import lots, service, stock, unitats
from .races import flush_or_error
from .models import InventoryCount, InventorySession, MovementWarehouse, Product, StockMovement, User

MAX_MG = 1_000_000_000
TIPUS = ("dispensari", "magatzem", "no_genetiques")
CONTROLS = ("complet", "producte")

_g = unitats.mg_to_g


def _abast(db: Session, s: InventorySession) -> list[Product]:
    q = select(Product).where(Product.local_id == s.local_id, Product.actiu.is_(True))
    q = q.where(Product.es_genetic.is_(False) if s.tipus == "no_genetiques" else Product.es_genetic.is_(True))
    if s.control == "producte":
        q = q.where(Product.id == s.product_id)
    return list(db.scalars(q.order_by(Product.categoria, Product.nom)))


def _esperat(db: Session, s: InventorySession, ids: list[int]) -> dict[int, int]:
    """Estoc del sistema a l'àmbit de l'inventari (mg)."""
    principal = stock.stock_by_product(db, ids)
    if s.tipus == "dispensari":
        return principal
    total = stock.stock_by_product(db, ids, total=True)
    return total if s.tipus == "no_genetiques" else {i: total[i] - principal[i] for i in ids}


def _tara(s: InventorySession, p: Product) -> int:
    return p.tara_mg if s.tipus == "dispensari" else 0


def obrir(db: Session, actor: User, local_id: int, nom: str | None, tipus: str = "dispensari", control: str = "complet",
          product_id: int | None = None) -> InventorySession:
    if tipus not in TIPUS:
        raise ValueError("Inventari no vàlid: dispensari, magatzem o no genètics")
    if control not in CONTROLS:
        raise ValueError("Tipus de control no vàlid: complet o d'un sol producte")
    if db.scalar(select(InventorySession.id).where(InventorySession.local_id == local_id, InventorySession.estat == "obert")):
        raise ValueError("Ja hi ha un inventari obert en aquest local: guarda'l o cancel·la'l primer")
    if control == "producte":
        p = db.get(Product, product_id) if product_id else None
        if not p or p.local_id != local_id or not p.actiu or p.es_genetic != (tipus != "no_genetiques"):
            raise ValueError("El producte no és d'aquest inventari o està desactivat")
    else:
        product_id = None
    etiqueta = {"dispensari": "Dispensari", "magatzem": "Magatzem", "no_genetiques": "No genètics"}[tipus]
    nom = (nom or "").strip() or f"{etiqueta} {datetime.now(stock.TZ).strftime('%d/%m/%Y %H:%M')}"
    s = InventorySession(local_id=local_id, nom=nom[:60], user_id=actor.id, tipus=tipus, control=control, product_id=product_id)
    db.add(s)
    flush_or_error(db, "Ja hi ha un inventari obert en aquest local: guarda'l o cancel·la'l primer")
    service.audit_append(db, {"accio": "obre_inventari", "inventari": s.id, "local": local_id, "tipus": tipus, "control": control, "per": actor.id})
    db.commit()
    return s


def llista(db: Session, local_id: int) -> list[dict]:
    comptats = {sid: n for sid, n in db.execute(select(InventoryCount.session_id, func.count()).group_by(InventoryCount.session_id))}
    noms = {i: n for i, n in db.execute(select(User.id, User.username))}
    q = select(InventorySession).where(InventorySession.local_id == local_id).order_by(InventorySession.id.desc()).limit(50)
    return [{"id": s.id, "nom": s.nom, "estat": s.estat, "tipus": s.tipus, "control": s.control, "ajustat": s.ajustat,
             "ts_obert": s.ts_obert.isoformat(), "ts_tancat": s.ts_tancat.isoformat() if s.ts_tancat else None,
             "comptats": comptats.get(s.id, 0), "usuari": noms.get(s.user_id)} for s in db.scalars(q)]


def detall(db: Session, s: InventorySession, veure: bool = True) -> dict:
    """`veure` = pot veure l'estoc del sistema i les diferències (gerència o permís de resultats). Si no, l'inventari és a cegues:
    qui pesa no sap quant «hauria de» haver-hi (si no, podria escriure just aquesta xifra)."""
    prods = _abast(db, s)
    esperat = _esperat(db, s, [p.id for p in prods])
    files = {c.product_id: c for c in db.scalars(select(InventoryCount).where(InventoryCount.session_id == s.id))}
    linies = []
    for p in prods:
        c = files.get(p.id)
        # Si el recompte va guardar l'estoc teòric d'aquell moment, la diferència es compara amb aquest (no amb l'actual)
        teoric = c.expected_mg if c is not None and c.expected_mg is not None else esperat[p.id]
        linia = {"product_id": p.id, "nom": p.nom, "categoria": p.categoria, "unitat": p.unitat, "tara_g": _g(_tara(s, p)),
                 "pes_g": _g(c.brut_mg) if c is not None and c.brut_mg is not None else None,
                 "comptat_g": _g(c.counted_mg) if c is not None else None, "nota": c.nota if c is not None else None}
        if veure:
            linia.update({"esperat_g": _g(teoric), "diferencia_g": _g(c.counted_mg - teoric) if c is not None else None})
        linies.append(linia)
    return {"id": s.id, "nom": s.nom, "estat": s.estat, "tipus": s.tipus, "control": s.control, "ajustat": s.ajustat,
            "total": len(prods), "comptats": sum(1 for l in linies if l["comptat_g"] is not None), "linies": linies}


def _obert(s: InventorySession) -> None:
    if s.estat != "obert":
        raise ValueError("Aquest inventari ja no està obert")


def _lock_session(db: Session, s: InventorySession) -> None:
    """Bloqueja la sessió (ordre: sessió -> productes) i en refresca l'estat: guardar i comptar no es creuen."""
    db.execute(select(InventorySession).where(InventorySession.id == s.id).with_for_update().execution_options(populate_existing=True))


def comptar(db: Session, actor: User, s: InventorySession, product_id: int, grams: Decimal, nota: str | None = None, veure: bool = True) -> dict:
    """Desa el pes d'un producte. `grams` és el pes que marca la bàscula (o escrit); al dispensari se'n resta la tara del pot.
    Torna el comptat net, el del sistema i la diferència perquè la pantalla ho comprovi a l'instant."""
    _lock_session(db, s)
    _obert(s)
    p = stock._lock_product_row(db, product_id)
    if not p or p.local_id != s.local_id or not p.actiu or p.id not in {x.id for x in _abast(db, s)}:
        raise ValueError("Aquest producte no és d'aquest inventari")
    brut = unitats.g_to_mg(grams)
    if brut < 0 or brut > MAX_MG:
        raise ValueError("Quantitat no vàlida")
    if p.unitat == "u" and brut % 1000:
        raise ValueError("Aquest producte es compta per unitats senceres")
    tara = _tara(s, p)
    if brut < tara:
        raise ValueError(f"El pes és inferior a la tara del pot ({_g(tara)} g)")
    net = brut - tara
    esperat = _esperat(db, s, [p.id])[p.id]
    nota = (nota or "").strip()[:300] or None
    fila = db.get(InventoryCount, (s.id, product_id))
    if fila:
        fila.counted_mg, fila.brut_mg, fila.expected_mg, fila.nota, fila.user_id, fila.ts = net, brut, esperat, nota, actor.id, datetime.now(timezone.utc)
    else:
        db.add(InventoryCount(session_id=s.id, product_id=product_id, counted_mg=net, brut_mg=brut, expected_mg=esperat, nota=nota, user_id=actor.id))
    db.commit()
    if not veure:
        return {"comptat_g": _g(net), "a_cegues": True}
    return {"comptat_g": _g(net), "esperat_g": _g(esperat), "diferencia_g": _g(net - esperat), "coincideix": net == esperat}


def _alertes(db: Session, s: InventorySession, comptes: list[InventoryCount]) -> list[dict]:
    from . import ajustos
    maxim = ajustos.get(db, s.local_id)["perdua_maxima_mg"]
    if not maxim:
        return []
    noms = {i: n for i, n in db.execute(select(Product.id, Product.nom).where(Product.id.in_([c.product_id for c in comptes] or [0])))}
    return [{"producte": noms.get(c.product_id), "diferencia_mg": c.counted_mg - (c.expected_mg or 0)}
            for c in comptes if c.expected_mg is not None and abs(c.counted_mg - c.expected_mg) > maxim]


def guardar(db: Session, actor: User, s: InventorySession) -> dict:
    """Guarda els resultats (no ajusta l'estoc). Cal haver pesat almenys un producte."""
    _lock_session(db, s)
    _obert(s)
    comptes = list(db.scalars(select(InventoryCount).where(InventoryCount.session_id == s.id)))
    if not comptes:
        raise ValueError("Encara no has pesat cap producte")
    total = len(_abast(db, s))
    diferents = sum(1 for c in comptes if c.expected_mg is not None and c.counted_mg != c.expected_mg)
    alertes = _alertes(db, s, comptes)
    s.estat, s.ts_tancat = "tancat", datetime.now(timezone.utc)
    service.audit_append(db, {"accio": "guarda_inventari", "inventari": s.id, "comptats": len(comptes), "diferencies": diferents,
                              "alertes": len(alertes), "per": actor.id})
    db.commit()
    return {"comptats": len(comptes), "pendents": max(0, total - len(comptes)), "diferencies": diferents, "alertes": alertes}


def resultats(db: Session, local_id: int, limit: int = 30) -> list[dict]:
    """Inventaris guardats amb el detall de cada línia i els avisos de diferència gran (només gerència)."""
    noms = {i: n for i, n in db.execute(select(User.id, User.username))}
    sessions = list(db.scalars(select(InventorySession).where(InventorySession.local_id == local_id, InventorySession.estat == "tancat")
                               .order_by(InventorySession.id.desc()).limit(limit)))
    out = []
    for s in sessions:
        comptes = list(db.scalars(select(InventoryCount).where(InventoryCount.session_id == s.id).order_by(InventoryCount.product_id)))
        productes = {p.id: p for p in db.scalars(select(Product).where(Product.id.in_([c.product_id for c in comptes] or [0])))}
        alerta = {a["producte"] for a in _alertes(db, s, comptes)}
        out.append({"id": s.id, "nom": s.nom, "tipus": s.tipus, "control": s.control, "ajustat": s.ajustat, "ts": s.ts_tancat.isoformat() if s.ts_tancat else None,
                    "usuari": noms.get(s.user_id), "alertes": len(alerta),
                    "linies": [{"producte": productes[c.product_id].nom if c.product_id in productes else "?", "unitat": productes[c.product_id].unitat if c.product_id in productes else "g",
                                "esperat_g": _g(c.expected_mg or 0), "comptat_g": _g(c.counted_mg), "diferencia_g": _g(c.counted_mg - (c.expected_mg or 0)),
                                "nota": c.nota, "alerta": productes[c.product_id].nom in alerta if c.product_id in productes else False} for c in comptes]})
    return out


def ajustar(db: Session, actor: User, s: InventorySession) -> dict:
    """Només gerència: deixa l'estoc de l'àmbit exactament com s'ha comptat (un moviment d'ajust per producte amb diferència).
    Tot o res; mai deixa l'estoc negatiu (si després del recompte hi ha hagut vendes, no s'esborren). Al magatzem se suposa un de sol
    (el que crea `magatzem_unic`); en no genètics, una falta surt primer del dispensari i després del magatzem."""
    from . import magatzems
    magatzem_id = magatzems.magatzem_unic(db, s.local_id).id   # abans de bloquejar res: pot fer commit
    _lock_session(db, s)
    if s.estat != "tancat":
        raise ValueError("Primer cal guardar l'inventari")
    if s.ajustat:
        raise ValueError("Aquest inventari ja s'ha ajustat")
    comptes = list(db.scalars(select(InventoryCount).where(InventoryCount.session_id == s.id).order_by(InventoryCount.product_id)))
    productes = {c.product_id: stock._lock_product_row(db, c.product_id) for c in comptes}
    ajustos = 0
    for c in comptes:
        p = productes[c.product_id]
        if not p:
            continue
        principal = stock.stock_mg(db, p.id)
        total = stock.stock_total_mg(db, p.id)
        actual = {"dispensari": principal, "magatzem": total - principal, "no_genetiques": total}[s.tipus]
        esperat = c.expected_mg if c.expected_mg is not None else actual
        delta = max(c.counted_mg - esperat, -actual)
        if delta == 0:
            continue
        # repartiment per lloc: [(warehouse_id|None, delta)]
        if s.tipus == "dispensari":
            parts = [(None, delta)]
        elif s.tipus == "magatzem":
            parts = [(magatzem_id, delta)]
        elif delta > 0:
            parts = [(None, delta)]
        else:
            del_principal = min(-delta, principal)
            parts = [(None, -del_principal)] + ([(magatzem_id, -(-delta - del_principal))] if -delta - del_principal else [])
        for wid, d in parts:
            m = StockMovement(local_id=p.local_id, product_id=p.id, tipus="ajust", delta_mg=d, user_id=actor.id, nota=f"Inventari #{s.id}")
            db.add(m)
            db.flush()
            if wid is not None:
                db.add(MovementWarehouse(movement_id=m.id, warehouse_id=wid))
            pla = lots.attach_outflow(db, m, p, -d) if (d < 0 and wid is None) else []
            service.audit_append(db, {"accio": "ajust_inventari", "moviment": m.id, "producte": p.id, "delta_mg": d, "inventari": s.id,
                                      **({"lots": [[b, x] for b, x in pla]} if pla else {}), "per": actor.id})
        ajustos += 1
    s.ajustat = True
    service.audit_append(db, {"accio": "ajusta_inventari", "inventari": s.id, "ajustos": ajustos, "per": actor.id})
    db.commit()
    return {"ajustos": ajustos}


def cancellar(db: Session, actor: User, s: InventorySession) -> None:
    _lock_session(db, s)
    _obert(s)
    s.estat, s.ts_tancat = "cancel·lat", datetime.now(timezone.utc)
    service.audit_append(db, {"accio": "cancella_inventari", "inventari": s.id, "per": actor.id})
    db.commit()

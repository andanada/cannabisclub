from datetime import date, datetime, time, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import exists, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, aliased

from . import service, unitats
from .races import flush_or_error
from .models import CashEntry, Local, Member, MovementWarehouse, Product, StockMovement, User

TZ = ZoneInfo("Europe/Madrid")


def grams_to_mg(g: Decimal) -> int:
    mg = unitats.g_to_mg(g)
    if mg <= 0:
        raise ValueError("La quantitat ha de ser positiva")
    return mg


def _del_principal():
    """Condició SQL: el moviment és del magatzem principal (no té magatzem addicional assignat)."""
    return ~exists().where(MovementWarehouse.movement_id == StockMovement.id)


def stock_mg(db: Session, product_id: int) -> int:
    """Estoc del magatzem principal, que és el que es pot dispensar."""
    return db.scalar(select(func.coalesce(func.sum(StockMovement.delta_mg), 0))
                     .where(StockMovement.product_id == product_id, _del_principal()))


def stock_total_mg(db: Session, product_id: int) -> int:
    """Estoc a tots els magatzems del local."""
    return db.scalar(select(func.coalesce(func.sum(StockMovement.delta_mg), 0)).where(StockMovement.product_id == product_id))


def stock_in_mg(db: Session, product_id: int, warehouse_id: int | None) -> int:
    if warehouse_id is None:
        return stock_mg(db, product_id)
    return db.scalar(select(func.coalesce(func.sum(StockMovement.delta_mg), 0))
                     .join(MovementWarehouse, MovementWarehouse.movement_id == StockMovement.id)
                     .where(StockMovement.product_id == product_id, MovementWarehouse.warehouse_id == warehouse_id))


def stock_by_product(db: Session, product_ids, total: bool = False) -> dict[int, int]:
    """Estoc (mg) de molts productes amb UNA sola consulta (evita una consulta per producte).
    Per defecte, el del magatzem principal; amb total=True, el de tots els magatzems."""
    ids = list(product_ids)
    if not ids:
        return {}
    q = select(StockMovement.product_id, func.coalesce(func.sum(StockMovement.delta_mg), 0)).where(StockMovement.product_id.in_(ids)).group_by(StockMovement.product_id)
    if not total:
        q = q.where(_del_principal())
    out = {i: 0 for i in ids}
    out.update({p: int(mg) for p, mg in db.execute(q)})
    return out


def _lock_product_row(db: Session, product_id: int) -> Product | None:
    return db.scalar(select(Product).where(Product.id == product_id).with_for_update().execution_options(populate_existing=True))


def _lock_product(db: Session, product_id: int) -> Product:
    p = _lock_product_row(db, product_id)
    if not p or not p.actiu:
        raise ValueError("Producte inexistent o inactiu")
    return p


def _lock_member(db: Session, member_id: int | None) -> Member | None:
    """Bloqueja la fila del soci. ORDRE FIX DE BLOQUEIGS: soci -> producte -> (sessió de caixa). Qui bloquegi
    el producte i després el soci pot interbloquejar-se; qui vulgui els dos, sempre en aquest ordre."""
    if member_id is None:
        return None
    return db.scalar(select(Member).where(Member.id == member_id).with_for_update().execution_options(populate_existing=True))


def _window_start(period: str, now: datetime) -> datetime:
    local = now.astimezone(TZ)
    if period == "dia":
        d = local.date()
    elif period == "setmana":
        d = local.date() - timedelta(days=local.weekday())
    else:
        d = local.date().replace(day=1)
    return datetime.combine(d, time.min, tzinfo=TZ).astimezone(timezone.utc)


def net_consumed_query(member_id: int, since: datetime):
    """Consulta del gramatge net (mg) dispensat a un soci des de `since`, només de productes genètics.
    Una correcció compta en el període de la dispensació que corregeix (no en el dia en què es fa)."""
    orig = aliased(StockMovement)
    ts_efectiu = func.coalesce(orig.ts, StockMovement.ts)
    q = (select(func.coalesce(func.sum(-StockMovement.delta_mg), 0))
         .select_from(StockMovement)
         .join(Product, Product.id == StockMovement.product_id)
         .outerjoin(orig, orig.id == StockMovement.corregeix_id)
         .where(StockMovement.member_id == member_id, ts_efectiu >= since,
                StockMovement.tipus.in_(["dispensacio", "correccio"]), Product.es_genetic.is_(True)))
    return q


def dispensed_mg(db: Session, member_id: int, period: str, now: datetime) -> int:
    """Total net dispensat al soci en el període, només productes genètics (les correccions hi resten,
    al període de la dispensació original)."""
    return db.scalar(net_consumed_query(member_id, _window_start(period, now)))


def _nom_lliure(db: Session, local_id: int, nom: str, excepte_id: int | None = None) -> bool:
    q = select(Product.id).where(Product.local_id == local_id, Product.nom == nom)
    if excepte_id is not None:
        q = q.where(Product.id != excepte_id)
    return db.scalar(q) is None


def movements_list(db: Session, local_id: int, des: date, fins: date, limit: int = 100) -> list[dict]:
    """Moviments d'estoc del rang, del més recent al més antic. Del soci només hi surt l'identificador (cap dada personal)."""
    from .cash import _range
    a, b = _range(des, fins)
    corregits = set(db.scalars(select(StockMovement.corregeix_id).where(StockMovement.local_id == local_id, StockMovement.corregeix_id.is_not(None))))
    noms = {i: n for i, n in db.execute(select(User.id, User.username))}
    q = (select(StockMovement, Product.nom).join(Product, Product.id == StockMovement.product_id)
         .where(StockMovement.local_id == local_id, StockMovement.ts >= a, StockMovement.ts < b)
         .order_by(StockMovement.id.desc()).limit(limit))
    return [{"id": m.id, "ts": m.ts.replace(tzinfo=m.ts.tzinfo or timezone.utc).isoformat(), "tipus": m.tipus, "producte": nom,
             "grams": unitats.mg_to_g(m.delta_mg), "import_cent": m.import_cent, "soci_id": m.member_id,
             "usuari": noms.get(m.user_id), "nota": m.nota, "corregeix_id": m.corregeix_id, "corregit": m.id in corregits}
            for m, nom in db.execute(q)]


UNITATS = {"g", "u"}


def _valida_unitat(unitat: str, es_genetic: bool) -> None:
    if unitat not in UNITATS:
        raise ValueError("La unitat ha de ser g (grams) o u (unitats)")
    if unitat == "u" and es_genetic:
        raise ValueError("Un producte genètic es dispensa en grams (els límits per soci són de pes)")


def add_product(db: Session, actor: User, local_id: int, nom: str, categoria: str, preu_cent_per_g: int, es_genetic: bool = False,
                regalable: bool = False, unitat: str = "g", granel: bool = True) -> Product:
    _valida_unitat(unitat, es_genetic)
    nom = nom.strip()
    if not nom:
        raise ValueError("El nom del producte no pot estar buit")
    if not _nom_lliure(db, local_id, nom):
        raise ValueError("Ja existeix un producte amb aquest nom en aquest local")
    p = Product(local_id=local_id, nom=nom, categoria=categoria, preu_cent_per_g=preu_cent_per_g, es_genetic=es_genetic, regalable=regalable,
                unitat=unitat, granel=granel)
    db.add(p)
    flush_or_error(db, "Ja existeix un producte amb aquest nom en aquest local")
    service.audit_append(db, {"accio": "alta_producte", "producte": p.id, "local": local_id, "per": actor.id})
    db.commit()
    return p


def update_product(db: Session, actor: User, product_id: int, nom: str | None = None, categoria: str | None = None,
                   preu_cent_per_g: int | None = None, actiu: bool | None = None, es_genetic: bool | None = None,
                   regalable: bool | None = None, unitat: str | None = None, granel: bool | None = None) -> Product:
    """Canvia el nom, la categoria, el preu o l'estat d'un producte. El preu només afecta les dispensacions
    noves: les antigues guarden el seu import. Per desactivar, l'estoc ha de ser zero (sinó quedaria encallat)."""
    p = db.scalar(select(Product).where(Product.id == product_id).with_for_update())
    if not p:
        raise ValueError("Producte inexistent")
    canvis: dict[str, list] = {}
    if nom is not None and nom.strip() != p.nom:
        nom = nom.strip()
        if not nom:
            raise ValueError("El nom del producte no pot estar buit")
        if not _nom_lliure(db, p.local_id, nom, p.id):
            raise ValueError("Ja existeix un producte amb aquest nom en aquest local")
        canvis["nom"] = [p.nom, nom]
    if categoria is not None and categoria != p.categoria:
        canvis["categoria"] = [p.categoria, categoria]
    if preu_cent_per_g is not None and preu_cent_per_g != p.preu_cent_per_g:
        if preu_cent_per_g < 0:
            raise ValueError("El preu no pot ser negatiu")
        canvis["preu_cent_per_g"] = [p.preu_cent_per_g, preu_cent_per_g]
    if es_genetic is not None and es_genetic != p.es_genetic:
        canvis["es_genetic"] = [p.es_genetic, es_genetic]
    if unitat is not None and unitat != p.unitat:
        _valida_unitat(unitat, es_genetic if es_genetic is not None else p.es_genetic)
        if db.scalar(select(StockMovement.id).where(StockMovement.product_id == p.id).limit(1)):
            raise ValueError("No es pot canviar la unitat d'un producte que ja té moviments d'estoc: crea'n un de nou")
        canvis["unitat"] = [p.unitat, unitat]
    elif es_genetic and p.unitat == "u":
        raise ValueError("Un producte en unitats no pot ser genètic")
    if granel is not None and granel != p.granel:
        canvis["granel"] = [p.granel, granel]
    if regalable is not None and regalable != p.regalable:
        canvis["regalable"] = [p.regalable, regalable]
    if actiu is not None and actiu != p.actiu:
        if not actiu and stock_total_mg(db, p.id) != 0:
            raise ValueError("Per desactivar el producte l'estoc ha de ser zero: registra una merma o un ajust d'inventari")
        canvis["actiu"] = [p.actiu, actiu]
    if not canvis:
        raise ValueError("No hi ha cap canvi")
    if "es_genetic" in canvis or "categoria" in canvis:
        # El consum passat es recalcula amb el valor ACTUAL (net_consumed_query, regles per categoria): canviar-los amb consum
        # en curs buidaria o inflaria el que ja compta per als límits (dia/setmana/mes) i les regles per soci.
        des = min(_window_start("setmana", datetime.now(timezone.utc)), _window_start("mes", datetime.now(timezone.utc)))
        if db.scalar(select(StockMovement.id).where(StockMovement.product_id == p.id, StockMovement.tipus == "dispensacio",
                                                    StockMovement.ts >= des).limit(1)):
            raise ValueError("No es pot canviar si és genètic ni la categoria: hi ha dispensacions d'aquest producte en el període "
                             "dels límits per soci (setmana o mes en curs) i el seu consum canviaria. Espera al període següent.")
    for camp, (_, nou) in canvis.items():
        setattr(p, camp, nou)
    service.audit_append(db, {"accio": "edita_producte", "producte": p.id, "local": p.local_id, "canvis": canvis, "per": actor.id})
    db.commit()
    return p


def receive(db: Session, actor: User, product_id: int, grams: Decimal, nota: str | None, warehouse_id: int | None = None,
            batch_id: int | None = None) -> StockMovement:
    p = _lock_product(db, product_id)
    from . import lots
    lot = lots.check_receive(db, p, batch_id)
    from . import magatzems
    magatzems.check_active(db, p.local_id, warehouse_id)
    m = StockMovement(local_id=p.local_id, product_id=p.id, tipus="entrada",
                      delta_mg=grams_to_mg(grams), user_id=actor.id, nota=nota)
    db.add(m)
    db.flush()
    if warehouse_id is not None:
        db.add(MovementWarehouse(movement_id=m.id, warehouse_id=warehouse_id))
    lots.attach_entry(db, m, lot)
    service.audit_append(db, {"accio": "entrada_estoc", "moviment": m.id, "producte": p.id, "mg": m.delta_mg,
                              **({"lot": lot.id} if lot else {}), "per": actor.id})
    db.commit()
    return m


def dispense(db: Session, actor: User, member_id: int, product_id: int, grams: Decimal,
             pes_bascula_g: Decimal | None, now: datetime | None = None, discount_id: int | None = None,
             metode: str | None = None, batch_id: int | None = None, regal: bool = False) -> StockMovement:
    """Dispensa. Amb `metode` (efectiu/targeta/bizum) també cobra en la mateixa transacció: o es fa tot o res.
    Amb `regal` l'import és 0 (cal que el producte sigui regalable); no es pot combinar amb cobrament ni descompte."""
    if regal and (metode is not None or discount_id is not None):
        raise ValueError("Un regal no es cobra ni porta descompte")
    now = now or datetime.now(timezone.utc)
    member = _lock_member(db, member_id)  # primer el soci, després el producte (ordre fix, evita interbloqueigs)
    p = _lock_product(db, product_id)
    if not member or member.local_id != p.local_id:
        raise ValueError("Soci inexistent o d'un altre local")
    if regal and not p.regalable:
        raise ValueError("Aquest producte no es pot dispensar com a regal")
    if metode is not None:
        # Ordre global de bloquejos: soci -> producte -> sessió de caixa -> auditoria. Tancar la caixa, una despesa o una quota
        # agafen la sessió i després l'auditoria; si aquí s'escrivís l'auditoria abans de bloquejar la sessió, s'interbloquejarien.
        from . import cash
        if metode not in cash.COBRAMENTS:
            raise ValueError("Mètode de pagament no vàlid")
        sessio_caixa = cash._require_open(db, p.local_id, actor)
    from . import controls
    controls.check_dispense(db, member, p, now)  # espera, aval, pendent d'aprovació (vegeu controls.py)
    if member.estat != "actiu":
        raise ValueError("El soci no està actiu")
    from . import ajustos, consentiments, quotes
    if ajustos.get(db, p.local_id)["consum_exigit"] and not consentiments.vigent(db, member_id, "consum"):
        raise ValueError("El soci no ha donat (o ha retirat) el consentiment explícit per al registre de consum")  # import local: quotes depèn d'aquest mòdul
    if ajustos.get(db, p.local_id)["quota_obligatoria"] and not quotes.status(db, member_id, now.astimezone(TZ).date())["al_dia"]:
        raise ValueError("La quota del soci no està al dia: cal cobrar-la abans de dispensar")
    decimals = 0 if (p.unitat == "u" or not p.granel) else ajustos.get(db, p.local_id)["decimals_dispensacio"]
    if -Decimal(grams).normalize().as_tuple().exponent > decimals:
        raise ValueError("La quantitat admet com a màxim " + (f"{decimals} decimals" if decimals else ("unitats senceres" if p.unitat == "u" else "grams sencers")))
    mg = grams_to_mg(grams)
    # Caixa registradora amb magatzem propi: la dispensació en descompta l'estoc d'aquell magatzem (no del principal).
    from . import cash as _cash
    if metode is not None:
        wid = _cash.register_warehouse(db, sessio_caixa)
    else:
        wid = _cash.register_warehouse(db, _cash.current_session(db, p.local_id, actor=actor))  # ambigua: error, no estoc a mig repartir
    if wid is not None:
        if stock_in_mg(db, p.id, wid) < mg:
            raise ValueError("Estoc insuficient al magatzem de la caixa")
    elif stock_mg(db, p.id) < mg:
        raise ValueError("Estoc insuficient")
    local = db.get(Local, p.local_id)
    if pes_bascula_g is not None and local.tolerancia_bascula_mg is not None:
        if abs(grams_to_mg(pes_bascula_g) - mg) > local.tolerancia_bascula_mg:
            raise ValueError("El pes de la bàscula no coincideix amb la quantitat dispensada")
    if p.es_genetic:  # els límits només afecten productes genètics (flor, clons…)
        for period, limit in (("dia", local.limit_diari_mg), ("mes", local.limit_mensual_mg)):
            limit = controls.limit_for(db, member_id, period, limit)  # excepció per soci
            if limit is not None and dispensed_mg(db, member_id, period, now) + mg > limit:
                raise ValueError(f"Supera el límit {'diari' if period == 'dia' else 'mensual'} del soci")
    from . import linies_preu, regles
    regles.check(db, member_id, p, mg, now)
    from . import lots
    pla_lots = lots.plan_dispense(db, p, mg, batch_id)  # lot manual o FIFO (buit si el producte no té lots)
    original = int((Decimal(mg) * linies_preu.price_for(db, member_id, p) / 1000).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    descompte, rebaixa = None, 0
    if discount_id is not None:
        from . import descomptes
        descompte, rebaixa = descomptes.apply(db, discount_id, p, original, mg, now.astimezone(TZ).date())
    rebaixa_chosen = rebaixa
    if member.descompte_pct and not regal:  # descompte permanent del soci, sumat al triat (mai per sobre de l'import)
        rebaixa = min(original, rebaixa + int((Decimal(original) * member.descompte_pct / 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP)))
    m = StockMovement(
        ts=now, local_id=p.local_id, product_id=p.id, tipus="dispensacio", delta_mg=-mg, member_id=member_id,
        pes_bascula_mg=grams_to_mg(pes_bascula_g) if pes_bascula_g is not None else None,
        import_cent=0 if regal else original - rebaixa, user_id=actor.id, regal=regal)
    db.add(m)
    db.flush()
    if wid is not None:
        db.add(MovementWarehouse(movement_id=m.id, warehouse_id=wid))
    if descompte is not None:
        from .models import MovementDiscount
        db.add(MovementDiscount(movement_id=m.id, discount_id=descompte.id, nom=descompte.nom, original_cent=original, descompte_cent=rebaixa_chosen))
    m.descompte_cent = rebaixa  # només per a la resposta (no és una columna)
    lots.attach_dispense(db, m, pla_lots)
    service.audit_append(db, {"accio": "dispensacio", "moviment": m.id, "soci": member_id, "producte": p.id,
                              "mg": mg, "import_cent": m.import_cent, "descompte": descompte.id if descompte else None,
                              **({"descompte_soci_pct": member.descompte_pct} if member.descompte_pct and not regal else {}),
                              **({"regal": True} if regal else {}),
                              **({"lots": [[b, x] for b, x in pla_lots]} if pla_lots else {}), "per": actor.id})
    if metode is not None:
        from . import cash
        cash.charge_in_tx(db, actor, m, metode)
    db.commit()
    return m


def correct(db: Session, actor: User, movement_id: int, nota: str, commit: bool = True) -> StockMovement:
    orig = db.get(StockMovement, movement_id)
    if not orig:
        raise ValueError("Moviment inexistent")
    if orig.tipus == "correccio":
        raise ValueError("Una correcció no es pot corregir")
    if orig.tipus == "traspas":
        raise ValueError("Un traspàs no es pot corregir: fes un traspàs en sentit contrari")
    _lock_member(db, orig.member_id)  # ordre fix: soci -> producte
    _lock_product(db, orig.product_id)
    if db.scalar(select(StockMovement.id).where(StockMovement.corregeix_id == orig.id)):
        raise ValueError("Aquest moviment ja està corregit")
    from . import cash
    if cash._live_charge(db, orig.id):
        raise ValueError("La dispensació està cobrada: corregeix primer el cobrament")
    wid = db.scalar(select(MovementWarehouse.warehouse_id).where(MovementWarehouse.movement_id == orig.id))
    if stock_in_mg(db, orig.product_id, wid) - orig.delta_mg < 0:
        raise ValueError("La correcció deixaria l'estoc negatiu")
    m = StockMovement(local_id=orig.local_id, product_id=orig.product_id, tipus="correccio",
                      delta_mg=-orig.delta_mg, member_id=orig.member_id, import_cent=-orig.import_cent if orig.import_cent else None,
                      corregeix_id=orig.id, user_id=actor.id, nota=nota)
    db.add(m)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise ValueError("Aquest moviment ja està corregit")
    if wid is not None:
        db.add(MovementWarehouse(movement_id=m.id, warehouse_id=wid))
    from . import lots
    lots.mirror_correction(db, orig, m)
    service.audit_append(db, {"accio": "correccio", "moviment": m.id, "corregeix": orig.id, "per": actor.id})
    if commit:
        db.commit()
    return m


def refund(db: Session, actor: User, movement_id: int, nota: str) -> dict:
    """Devolució d'una dispensació, tot o res: anul·la el cobrament vigent (si n'hi ha, cal caixa oberta: surt de la caixa
    pel mètode amb què es va cobrar), torna el producte a l'estoc (al mateix lot i magatzem) i ho deixa a l'auditoria."""
    orig = db.get(StockMovement, movement_id)
    if not orig or orig.tipus != "dispensacio":
        raise ValueError("Només es poden retornar dispensacions")
    _lock_member(db, orig.member_id)  # ordre fix: soci -> producte -> sessió de caixa -> auditoria
    _lock_product(db, orig.product_id)
    from . import cash
    cobrament = cash._live_charge(db, orig.id)
    if cobrament is not None:
        cash._require_open(db, orig.local_id, actor)
        cash.correct_entry(db, actor, cobrament.id, "Devolució: " + nota, commit=False)
    corr = correct(db, actor, movement_id, nota, commit=False)
    service.audit_append(db, {"accio": "devolucio", "moviment": orig.id, "correccio": corr.id,
                              "cent": orig.import_cent or 0, "cobrada": cobrament is not None, "per": actor.id})
    db.commit()
    return {"correccio": corr.id, "retornat_cent": (orig.import_cent or 0) if cobrament is not None else 0}


def shrink(db: Session, actor: User, product_id: int, grams: Decimal, nota: str) -> StockMovement:
    p = _lock_product(db, product_id)
    mg = grams_to_mg(grams)
    if stock_mg(db, p.id) < mg:
        raise ValueError("La merma supera l'estoc")
    m = StockMovement(local_id=p.local_id, product_id=p.id, tipus="merma", delta_mg=-mg, user_id=actor.id, nota=nota)
    db.add(m)
    db.flush()
    from . import lots
    pla = lots.attach_outflow(db, m, p, mg)
    service.audit_append(db, {"accio": "merma", "moviment": m.id, "producte": p.id, "mg": mg,
                              **({"lots": [[b, x] for b, x in pla]} if pla else {}), "per": actor.id})
    db.commit()
    return m


def adjust(db: Session, actor: User, product_id: int, grams_reals: Decimal, nota: str) -> StockMovement:
    """Ajust d'inventari: deixa l'estoc exactament en `grams_reals` (>= 0)."""
    p = _lock_product(db, product_id)
    real = unitats.g_to_mg(grams_reals)
    if real < 0:
        raise ValueError("L'inventari real no pot ser negatiu")
    delta = real - stock_mg(db, p.id)
    if delta == 0:
        raise ValueError("L'estoc ja coincideix amb l'inventari")
    m = StockMovement(local_id=p.local_id, product_id=p.id, tipus="ajust", delta_mg=delta, user_id=actor.id, nota=nota)
    db.add(m)
    db.flush()
    from . import lots
    pla = lots.attach_outflow(db, m, p, -delta) if delta < 0 else []   # a l'alça no se sap de quin lot és: queda sense lot
    service.audit_append(db, {"accio": "ajust_inventari", "moviment": m.id, "producte": p.id, "delta_mg": delta,
                              **({"lots": [[b, x] for b, x in pla]} if pla else {}), "per": actor.id})
    db.commit()
    return m


# ---------- miniatures de producte ----------

MAX_IMAGE_BYTES = 30_000  # és una miniatura (uns 96 px); les fotos grans no hi caben
IMAGE_MIN_BYTES = 100


def _image_mime(img: bytes) -> str:
    if img.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if img.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    raise ValueError("La imatge ha de ser JPEG o PNG")


def set_image(db: Session, actor: User, product: Product, image_b64: str) -> None:
    import base64
    import binascii
    from .models import ProductImage
    try:
        img = base64.b64decode(image_b64, validate=True)
    except (binascii.Error, ValueError):
        raise ValueError("La imatge no és vàlida")
    mime = _image_mime(img)
    if len(img) > MAX_IMAGE_BYTES:
        raise ValueError("La imatge és massa gran (màxim 30 KB: es redueix sola a la pantalla)")
    if len(img) < IMAGE_MIN_BYTES:
        raise ValueError("La imatge està buida")
    fila = db.get(ProductImage, product.id)
    if fila:
        fila.mime, fila.data, fila.user_id = mime, image_b64, actor.id
    else:
        db.add(ProductImage(product_id=product.id, mime=mime, data=image_b64, user_id=actor.id))
    service.audit_append(db, {"accio": "imatge_producte", "producte": product.id, "per": actor.id})
    db.commit()


def remove_image(db: Session, actor: User, product: Product) -> None:
    from .models import ProductImage
    fila = db.get(ProductImage, product.id)
    if not fila:
        raise ValueError("El producte no té imatge")
    db.delete(fila)
    service.audit_append(db, {"accio": "esborra_imatge_producte", "producte": product.id, "per": actor.id})
    db.commit()


def images_for(db: Session, product_ids) -> dict[int, dict]:
    """Miniatures de molts productes amb una sola consulta: {id: {mime, image_base64}}."""
    from .models import ProductImage
    ids = list(product_ids)
    if not ids:
        return {}
    return {i.product_id: {"mime": i.mime, "image_base64": i.data} for i in db.scalars(select(ProductImage).where(ProductImage.product_id.in_(ids)))}

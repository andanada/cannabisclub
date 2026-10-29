from datetime import date, datetime, time, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import exists, func, select
from sqlalchemy.orm import Session

from . import service
from .models import CashEntry, Local, Member, MovementWarehouse, Product, StockMovement, User

TZ = ZoneInfo("Europe/Madrid")


def grams_to_mg(g: Decimal) -> int:
    mg = (Decimal(g) * 1000).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    if mg <= 0:
        raise ValueError("La quantitat ha de ser positiva")
    return int(mg)


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


def _lock_product(db: Session, product_id: int) -> Product:
    p = db.scalar(select(Product).where(Product.id == product_id).with_for_update())
    if not p or not p.actiu:
        raise ValueError("Producte inexistent o inactiu")
    return p


def _window_start(period: str, now: datetime) -> datetime:
    local = now.astimezone(TZ)
    if period == "dia":
        d = local.date()
    elif period == "setmana":
        d = local.date() - timedelta(days=local.weekday())
    else:
        d = local.date().replace(day=1)
    return datetime.combine(d, time.min, tzinfo=TZ).astimezone(timezone.utc)


def dispensed_mg(db: Session, member_id: int, period: str, now: datetime) -> int:
    """Total net dispensat al soci en el període (les correccions hi resten)."""
    start = _window_start(period, now)
    total = db.scalar(select(func.coalesce(func.sum(-StockMovement.delta_mg), 0)).where(
        StockMovement.member_id == member_id, StockMovement.ts >= start,
        StockMovement.tipus.in_(["dispensacio", "correccio"])))
    return total


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
             "grams": str(Decimal(m.delta_mg) / 1000), "import_cent": m.import_cent, "soci_id": m.member_id,
             "usuari": noms.get(m.user_id), "nota": m.nota, "corregeix_id": m.corregeix_id, "corregit": m.id in corregits}
            for m, nom in db.execute(q)]


def add_product(db: Session, actor: User, local_id: int, nom: str, categoria: str, preu_cent_per_g: int) -> Product:
    nom = nom.strip()
    if not nom:
        raise ValueError("El nom del producte no pot estar buit")
    if not _nom_lliure(db, local_id, nom):
        raise ValueError("Ja existeix un producte amb aquest nom en aquest local")
    p = Product(local_id=local_id, nom=nom, categoria=categoria, preu_cent_per_g=preu_cent_per_g)
    db.add(p)
    db.flush()
    service.audit_append(db, {"accio": "alta_producte", "producte": p.id, "local": local_id, "per": actor.id})
    db.commit()
    return p


def update_product(db: Session, actor: User, product_id: int, nom: str | None = None, categoria: str | None = None,
                   preu_cent_per_g: int | None = None, actiu: bool | None = None) -> Product:
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
    if actiu is not None and actiu != p.actiu:
        if not actiu and stock_total_mg(db, p.id) != 0:
            raise ValueError("Per desactivar el producte l'estoc ha de ser zero: registra una merma o un ajust d'inventari")
        canvis["actiu"] = [p.actiu, actiu]
    if not canvis:
        raise ValueError("No hi ha cap canvi")
    for camp, (_, nou) in canvis.items():
        setattr(p, camp, nou)
    service.audit_append(db, {"accio": "edita_producte", "producte": p.id, "local": p.local_id, "canvis": canvis, "per": actor.id})
    db.commit()
    return p


def receive(db: Session, actor: User, product_id: int, grams: Decimal, nota: str | None, warehouse_id: int | None = None) -> StockMovement:
    p = _lock_product(db, product_id)
    from . import magatzems
    magatzems.check_active(db, p.local_id, warehouse_id)
    m = StockMovement(local_id=p.local_id, product_id=p.id, tipus="entrada",
                      delta_mg=grams_to_mg(grams), user_id=actor.id, nota=nota)
    db.add(m)
    db.flush()
    if warehouse_id is not None:
        db.add(MovementWarehouse(movement_id=m.id, warehouse_id=warehouse_id))
    service.audit_append(db, {"accio": "entrada_estoc", "moviment": m.id, "producte": p.id, "mg": m.delta_mg, "per": actor.id})
    db.commit()
    return m


def dispense(db: Session, actor: User, member_id: int, product_id: int, grams: Decimal,
             pes_bascula_g: Decimal | None, now: datetime | None = None, discount_id: int | None = None) -> StockMovement:
    now = now or datetime.now(timezone.utc)
    p = _lock_product(db, product_id)
    member = db.get(Member, member_id)
    if not member or member.local_id != p.local_id:
        raise ValueError("Soci inexistent o d'un altre local")
    if member.estat != "actiu":
        raise ValueError("El soci no està actiu")
    from . import ajustos, quotes  # import local: quotes depèn d'aquest mòdul
    if ajustos.get(db, p.local_id)["quota_obligatoria"] and not quotes.status(db, member_id, now.astimezone(TZ).date())["al_dia"]:
        raise ValueError("La quota del soci no està al dia: cal cobrar-la abans de dispensar")
    mg = grams_to_mg(grams)
    if stock_mg(db, p.id) < mg:
        raise ValueError("Estoc insuficient")
    local = db.get(Local, p.local_id)
    if pes_bascula_g is not None and local.tolerancia_bascula_mg is not None:
        if abs(grams_to_mg(pes_bascula_g) - mg) > local.tolerancia_bascula_mg:
            raise ValueError("El pes de la bàscula no coincideix amb la quantitat dispensada")
    for period, limit in (("dia", local.limit_diari_mg), ("mes", local.limit_mensual_mg)):
        if limit is not None and dispensed_mg(db, member_id, period, now) + mg > limit:
            raise ValueError(f"Supera el límit {'diari' if period == 'dia' else 'mensual'} del soci")
    from . import linies_preu, regles
    regles.check(db, member_id, p, mg, now)
    original = int((Decimal(mg) * linies_preu.price_for(db, member_id, p) / 1000).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    descompte, rebaixa = None, 0
    if discount_id is not None:
        from . import descomptes
        descompte, rebaixa = descomptes.apply(db, discount_id, p, original, mg, now.astimezone(TZ).date())
    m = StockMovement(
        ts=now, local_id=p.local_id, product_id=p.id, tipus="dispensacio", delta_mg=-mg, member_id=member_id,
        pes_bascula_mg=grams_to_mg(pes_bascula_g) if pes_bascula_g is not None else None,
        import_cent=original - rebaixa, user_id=actor.id)
    db.add(m)
    db.flush()
    if descompte is not None:
        from .models import MovementDiscount
        db.add(MovementDiscount(movement_id=m.id, discount_id=descompte.id, nom=descompte.nom, original_cent=original, descompte_cent=rebaixa))
    m.descompte_cent = rebaixa  # només per a la resposta (no és una columna)
    service.audit_append(db, {"accio": "dispensacio", "moviment": m.id, "soci": member_id, "producte": p.id,
                              "mg": mg, "import_cent": m.import_cent, "descompte": descompte.id if descompte else None, "per": actor.id})
    db.commit()
    return m


def correct(db: Session, actor: User, movement_id: int, nota: str) -> StockMovement:
    orig = db.get(StockMovement, movement_id)
    if not orig:
        raise ValueError("Moviment inexistent")
    if orig.tipus == "correccio":
        raise ValueError("Una correcció no es pot corregir")
    if db.scalar(select(StockMovement.id).where(StockMovement.corregeix_id == orig.id)):
        raise ValueError("Aquest moviment ja està corregit")
    pagat = db.scalar(select(CashEntry).where(CashEntry.movement_id == orig.id))
    if pagat and not db.scalar(select(CashEntry.id).where(CashEntry.corregeix_id == pagat.id)):
        raise ValueError("La dispensació està cobrada: corregeix primer el cobrament")
    _lock_product(db, orig.product_id)
    if stock_mg(db, orig.product_id) - orig.delta_mg < 0:
        raise ValueError("La correcció deixaria l'estoc negatiu")
    m = StockMovement(local_id=orig.local_id, product_id=orig.product_id, tipus="correccio",
                      delta_mg=-orig.delta_mg, member_id=orig.member_id, import_cent=-orig.import_cent if orig.import_cent else None,
                      corregeix_id=orig.id, user_id=actor.id, nota=nota)
    db.add(m)
    db.flush()
    service.audit_append(db, {"accio": "correccio", "moviment": m.id, "corregeix": orig.id, "per": actor.id})
    db.commit()
    return m


def shrink(db: Session, actor: User, product_id: int, grams: Decimal, nota: str) -> StockMovement:
    p = _lock_product(db, product_id)
    mg = grams_to_mg(grams)
    if stock_mg(db, p.id) < mg:
        raise ValueError("La merma supera l'estoc")
    m = StockMovement(local_id=p.local_id, product_id=p.id, tipus="merma", delta_mg=-mg, user_id=actor.id, nota=nota)
    db.add(m)
    db.flush()
    service.audit_append(db, {"accio": "merma", "moviment": m.id, "producte": p.id, "mg": mg, "per": actor.id})
    db.commit()
    return m


def adjust(db: Session, actor: User, product_id: int, grams_reals: Decimal, nota: str) -> StockMovement:
    """Ajust d'inventari: deixa l'estoc exactament en `grams_reals` (>= 0)."""
    p = _lock_product(db, product_id)
    real = int((Decimal(grams_reals) * 1000).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    if real < 0:
        raise ValueError("L'inventari real no pot ser negatiu")
    delta = real - stock_mg(db, p.id)
    if delta == 0:
        raise ValueError("L'estoc ja coincideix amb l'inventari")
    m = StockMovement(local_id=p.local_id, product_id=p.id, tipus="ajust", delta_mg=delta, user_id=actor.id, nota=nota)
    db.add(m)
    db.flush()
    service.audit_append(db, {"accio": "ajust_inventari", "moviment": m.id, "producte": p.id, "delta_mg": delta, "per": actor.id})
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

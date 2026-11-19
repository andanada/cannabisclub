"""Rutes: productes, estoc i moviments (extretes de main.py sense canviar-ne el comportament)."""
from decimal import Decimal

from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import idempotencia, linies_preu, stock
from ..models import Product, StockMovement, User
from .comu import CAN_CREATE_MEMBER, need_dispensari, need_permis, pot_dispensari


def register(app, db, current_user, check_local, need_manager, run, member_or_404, product_or_404):
    class ProductIn(BaseModel):
        local_id: int
        nom: str = Field(min_length=1, max_length=120)
        categoria: str = Field(default="", max_length=60)
        preu_cent_per_g: int = Field(ge=0, le=10_000_000)
        es_genetic: bool = False
        regalable: bool = False
        unitat: str = Field(default="g", max_length=1)
        granel: bool = True
        preu_entrada_cent: int | None = Field(default=None, ge=0, le=10_000_000)
        tara_g: Decimal | None = Field(default=None, ge=0, max_digits=9, decimal_places=3)
        sense_descomptes: bool = False
        estricte: bool = False  # el formulari nou el posa a true: aplica les regles del producte (no genètic = unitat, categories per tipus, granel)

    class EntradaIn(BaseModel):
        product_id: int
        grams: Decimal = Field(gt=0, max_digits=9, decimal_places=3)
        nota: str | None = Field(default=None, max_length=300)
        magatzem_id: int | None = None  # buit = magatzem principal

    class DispensacioIn(BaseModel):
        member_id: int
        product_id: int
        grams: Decimal = Field(gt=0, max_digits=9, decimal_places=3)
        pes_bascula_g: Decimal | None = Field(default=None, gt=0, max_digits=9, decimal_places=3)
        discount_id: int | None = None
        metode: str | None = Field(default=None, max_length=20)  # amb mètode es cobra en la mateixa transacció
        batch_id: int | None = None  # lot triat; buit = FIFO (lot més antic amb existències)
        regal: bool = False  # dispensat com a regal: import 0, producte regalable, sense cobrament
        client_ref: str | None = Field(default=None, pattern=idempotencia.REF_PATTERN)  # referència de l'operació: repetida, no es torna a fer

    class LiniaCarretIn(BaseModel):
        product_id: int
        grams: Decimal = Field(gt=0, max_digits=9, decimal_places=3)
        regal: bool = False

    class CarretIn(BaseModel):
        member_id: int
        linies: list[LiniaCarretIn] = Field(min_length=1, max_length=50)
        client_ref: str | None = Field(default=None, pattern=idempotencia.REF_PATTERN)

    class CorreccioIn(BaseModel):
        nota: str = Field(min_length=3, max_length=300)

    @app.post("/productes", status_code=201)
    def alta_producte(body: ProductIn, user: User = Depends(current_user), s: Session = Depends(db)):
        need_dispensari(user)
        check_local(s, user, body.local_id)
        # Amb `estricte` (el formulari nou) s'apliquen les regles del producte (no genètic = unitat, categories per tipus, tara…)
        p = run(stock.add_product, s, user, body.local_id, body.nom, body.categoria, body.preu_cent_per_g, body.es_genetic, body.regalable, body.unitat, body.granel,
                preu_entrada_cent=body.preu_entrada_cent, tara_g=body.tara_g, sense_descomptes=body.sense_descomptes, estricte=body.estricte)
        return {"id": p.id}

    class ProductUpdateIn(BaseModel):
        nom: str | None = Field(default=None, min_length=1, max_length=120)
        categoria: str | None = Field(default=None, max_length=60)
        preu_cent_per_g: int | None = Field(default=None, ge=0, le=10_000_000)
        actiu: bool | None = None
        es_genetic: bool | None = None
        regalable: bool | None = None
        unitat: str | None = Field(default=None, max_length=1)
        granel: bool | None = None
        preu_entrada_cent: int | None = Field(default=None, ge=0, le=10_000_000)
        tara_g: Decimal | None = Field(default=None, ge=0, max_digits=9, decimal_places=3)
        sense_descomptes: bool | None = None
        estricte: bool = False  # el formulari nou el posa a true: aplica les regles del producte (unitat, categories, granel)

    @app.patch("/productes/{product_id}")
    def edita_producte(product_id: int, body: ProductUpdateIn, user: User = Depends(current_user), s: Session = Depends(db)):
        need_dispensari(user)
        product_or_404(s, user, product_id)
        run(stock.update_product, s, user, product_id, body.nom, body.categoria, body.preu_cent_per_g, body.actiu, body.es_genetic, body.regalable, body.unitat, body.granel,
            preu_entrada_cent=body.preu_entrada_cent, tara_g=body.tara_g, sense_descomptes=body.sense_descomptes, estricte=body.estricte)
        return {"ok": True}

    @app.delete("/productes/{product_id}")
    def esborra_producte(product_id: int, user: User = Depends(current_user), s: Session = Depends(db)):
        """Només la gerència pot esborrar productes, i només si mai no han tingut moviments (si no, es desactiven)."""
        need_permis(user, 'esborrar_productes')  # els treballadors només activen o desactiven; esborrar és de la gerència o amb permís
        p = product_or_404(s, user, product_id)
        if s.scalar(select(StockMovement.id).where(StockMovement.product_id == p.id).limit(1)):
            raise HTTPException(422, "El producte ja té moviments d'estoc: no es pot esborrar, desactiva'l")
        from ..models import ProductImage
        from .. import service
        service.audit_append(s, {"accio": "esborra_producte", "producte": p.id, "nom": p.nom, "per": user.id})
        for img in s.scalars(select(ProductImage).where(ProductImage.product_id == p.id)):
            s.delete(img)
        from sqlalchemy.exc import IntegrityError
        s.delete(p)
        try:
            s.commit()
        except IntegrityError:
            s.rollback()
            raise HTTPException(422, "El producte té dades associades (lots, descomptes, regles…): desactiva'l en lloc d'esborrar-lo")
        return {"ok": True}

    class ImatgeIn(BaseModel):
        image_base64: str = Field(max_length=60_000)

    @app.put("/productes/{product_id}/imatge")
    def posa_imatge(product_id: int, body: ImatgeIn, user: User = Depends(current_user), s: Session = Depends(db)):
        need_manager(user)
        run(stock.set_image, s, user, product_or_404(s, user, product_id), body.image_base64)
        return {"ok": True}

    @app.delete("/productes/{product_id}/imatge")
    def treu_imatge(product_id: int, user: User = Depends(current_user), s: Session = Depends(db)):
        need_manager(user)
        run(stock.remove_image, s, user, product_or_404(s, user, product_id))
        return {"ok": True}

    @app.get("/locals/{local_id}/productes")
    def tots_els_productes(local_id: int, user: User = Depends(current_user), s: Session = Depends(db)):
        """Catàleg complet (també els inactius) per a la gestió; el dispensador només veu els actius a /estoc."""
        need_dispensari(user)
        check_local(s, user, local_id)
        prods = s.scalars(select(Product).where(Product.local_id == local_id).order_by(Product.actiu.desc(), Product.nom)).all()
        mg = stock.stock_by_product(s, [p.id for p in prods])
        total = stock.stock_by_product(s, [p.id for p in prods], total=True)
        imatges = stock.images_for(s, [p.id for p in prods])
        return [{"id": p.id, "nom": p.nom, "categoria": p.categoria, "preu_cent_per_g": p.preu_cent_per_g, "actiu": p.actiu, "es_genetic": p.es_genetic, "regalable": p.regalable, "unitat": p.unitat, "granel": p.granel,
                 "preu_entrada_cent": p.preu_entrada_cent, "tara_g": str(Decimal(p.tara_mg) / 1000), "sense_descomptes": p.sense_descomptes,
                 "estoc_g": str(Decimal(mg[p.id]) / 1000), "estoc_total_g": str(Decimal(total[p.id]) / 1000), "imatge": imatges.get(p.id)} for p in prods]

    @app.get("/locals/{local_id}/estoc")
    def veure_estoc(local_id: int, soci: int | None = None, user: User = Depends(current_user), s: Session = Depends(db)):
        check_local(s, user, local_id)
        prods = s.scalars(select(Product).where(Product.local_id == local_id, Product.actiu.is_(True)).order_by(Product.nom)).all()
        mg = stock.stock_by_product(s, [p.id for p in prods])
        imatges = stock.images_for(s, [p.id for p in prods])
        # Amb ?soci= els preus són els que paga aquest soci (la seva línia de preu, si en té)
        preus = linies_preu.effective_prices(s, member_or_404(s, user, soci).id, prods) if soci else {p.id: p.preu_cent_per_g for p in prods}
        return [{"id": p.id, "nom": p.nom, "categoria": p.categoria, "preu_cent_per_g": preus[p.id], "regalable": p.regalable, "unitat": p.unitat, "granel": p.granel,
                 "es_genetic": p.es_genetic, "sense_descomptes": p.sense_descomptes,
                 "estoc_g": str(Decimal(mg[p.id]) / 1000), "imatge": imatges.get(p.id)} for p in prods]

    @app.get("/locals/{local_id}/existencies")
    def existencies(local_id: int, user: User = Depends(current_user), s: Session = Depends(db)):
        need_dispensari(user)
        check_local(s, user, local_id)
        from .. import magatzems
        return magatzems.existencies(s, local_id)

    @app.get("/productes/{product_id}/moviments")
    def moviments_del_producte(product_id: int, user: User = Depends(current_user), s: Session = Depends(db)):
        need_dispensari(user)
        from .. import magatzems
        return magatzems.moviments_producte(s, product_or_404(s, user, product_id))

    @app.post("/moviments/entrada", status_code=201)
    def entrada(body: EntradaIn, user: User = Depends(current_user), s: Session = Depends(db)):
        need_dispensari(user)
        product_or_404(s, user, body.product_id)
        m = run(stock.receive, s, user, body.product_id, body.grams, body.nota, body.magatzem_id)
        return {"id": m.id}

    @app.post("/dispensacions", status_code=201)
    def dispensacio(body: DispensacioIn, user: User = Depends(current_user), s: Session = Depends(db)):
        need_dispensari(user)
        product_or_404(s, user, body.product_id)

        def fes():
            m = run(stock.dispense, s, user, body.member_id, body.product_id, body.grams, body.pes_bascula_g, None, body.discount_id, body.metode, body.batch_id, body.regal)
            return {"id": m.id, "import_cent": m.import_cent, "descompte_cent": getattr(m, "descompte_cent", 0), "cobrat": body.metode is not None, "regal": body.regal}
        return idempotencia.executa(s, user, "dispensacions", body.client_ref, body.model_dump(mode="json"), fes)

    @app.post("/dispensacions/carret", status_code=201)
    def dispensacio_carret(body: CarretIn, user: User = Depends(current_user), s: Session = Depends(db)):
        """Dispensa diversos productes d'una vegada i els paga del monedero del soci (tot o res)."""
        need_dispensari(user)
        for l in body.linies:
            product_or_404(s, user, l.product_id)

        def fes():
            return run(stock.dispense_cart, s, user, body.member_id, [l.model_dump() for l in body.linies])
        return idempotencia.executa(s, user, "carret", body.client_ref, body.model_dump(mode="json"), fes)

    @app.post("/moviments/{movement_id}/correccio", status_code=201)
    def correccio(movement_id: int, body: CorreccioIn, user: User = Depends(current_user), s: Session = Depends(db)):
        need_permis(user, 'corregir_estoc')
        orig = s.get(StockMovement, movement_id)
        if not orig:
            raise HTTPException(404, "Moviment inexistent")
        check_local(s, user, orig.local_id)
        m = run(stock.correct, s, user, movement_id, body.nota)
        return {"id": m.id}

    @app.post("/dispensacions/{movement_id}/devolucio", status_code=201)
    def devolucio(movement_id: int, body: CorreccioIn, user: User = Depends(current_user), s: Session = Depends(db)):
        if user.role not in CAN_CREATE_MEMBER and not user.pot_reemborsar:
            raise HTTPException(403, "No tens permís per fer devolucions")
        orig = s.get(StockMovement, movement_id)
        if not orig:
            raise HTTPException(404, "Moviment inexistent")
        check_local(s, user, orig.local_id)
        return run(stock.refund, s, user, movement_id, body.nota)

    class MermaIn(BaseModel):
        product_id: int
        grams: Decimal = Field(gt=0, max_digits=9, decimal_places=3)
        nota: str = Field(min_length=3, max_length=300)
        magatzem_id: int | None = None  # buit = dispensari (magatzem principal)

    class AjustIn(BaseModel):
        product_id: int
        grams_reals: Decimal = Field(ge=0, max_digits=9, decimal_places=3)
        nota: str = Field(min_length=3, max_length=300)

    @app.post("/moviments/merma", status_code=201)
    def merma(body: MermaIn, user: User = Depends(current_user), s: Session = Depends(db)):
        need_dispensari(user)
        product_or_404(s, user, body.product_id)
        return {"id": run(stock.shrink, s, user, body.product_id, body.grams, body.nota, body.magatzem_id).id}

    @app.post("/moviments/ajust", status_code=201)
    def ajust(body: AjustIn, user: User = Depends(current_user), s: Session = Depends(db)):
        need_manager(user)
        product_or_404(s, user, body.product_id)
        return {"id": run(stock.adjust, s, user, body.product_id, body.grams_reals, body.nota).id}

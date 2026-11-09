"""Rutes de controls de club, lots/traçabilitat i llibres signats."""
from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import ajustos, controls, llibres, lots, service, stock, unitats
from ..models import Batch, User, UserLocal
from .comu import check_local, member_or_404, need_admin, need_manager, product_or_404, rang, run


class ClubConfigIn(BaseModel):
    espera_dies: int | None = Field(default=None, ge=0, le=365)
    aval: str | None = Field(default=None, pattern="^(no|opcional|obligatori)$")
    alta_pendent: bool | None = None


class BaixaIn(BaseModel):
    motiu: str = Field(min_length=3, max_length=200)


class LimitIn(BaseModel):
    periode: str = Field(pattern="^(dia|mes)$")
    max_g: Decimal | None = Field(default=None, ge=0, le=Decimal("1000000"), max_digits=12, decimal_places=3)  # None = treure l'excepció
    motiu: str = Field(min_length=3, max_length=200)


class LotIn(BaseModel):
    codi: str = Field(max_length=40)
    origen: str | None = Field(default=None, max_length=120)
    proveidor: str | None = Field(default=None, max_length=120)
    collita: str | None = Field(default=None, max_length=40)
    data_entrada: date | None = None
    analisi: str | None = Field(default=None, max_length=300)


class EntradaLotIn(BaseModel):
    grams: Decimal = Field(gt=0, max_digits=9, decimal_places=3)
    nota: str | None = Field(default=None, max_length=300)
    magatzem_id: int | None = None


class DispensacioLotIn(BaseModel):
    member_id: int
    product_id: int
    grams: Decimal = Field(gt=0, max_digits=9, decimal_places=3)
    batch_id: int
    pes_bascula_g: Decimal | None = Field(default=None, gt=0, max_digits=9, decimal_places=3)
    discount_id: int | None = None
    metode: str | None = None


class VerificaIn(BaseModel):
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


def router(db, current_user) -> APIRouter:
    r = APIRouter()

    # ---------- controls del local ----------
    @r.get("/locals/{local_id}/club-config")
    def veure_config(local_id: int, user: User = Depends(current_user), s: Session = Depends(db)):
        need_manager(user)
        check_local(s, user, local_id)
        c = ajustos.get(s, local_id)
        return {k: c[k] for k in ("espera_dies", "aval", "alta_pendent")}

    @r.put("/locals/{local_id}/club-config")
    def canvia_config(local_id: int, body: ClubConfigIn, user: User = Depends(current_user), s: Session = Depends(db)):
        need_admin(user)
        check_local(s, user, local_id)
        c = run(ajustos.set_, s, user, local_id, body.model_dump())
        return {k: c[k] for k in ("espera_dies", "aval", "alta_pendent")}

    @r.post("/socis/{member_id}/aprovar")
    def aprova(member_id: int, user: User = Depends(current_user), s: Session = Depends(db)):
        need_manager(user)
        run(controls.approve, s, user, member_or_404(s, user, member_id))
        return {"ok": True}

    @r.post("/socis/{member_id}/baixa")
    def baixa_amb_motiu(member_id: int, body: BaixaIn, user: User = Depends(current_user), s: Session = Depends(db)):
        need_manager(user)
        run(service.set_member_status, s, user, member_or_404(s, user, member_id), "baixa", body.motiu)
        return {"ok": True}

    @r.get("/socis/{member_id}/limits")
    def veure_limits(member_id: int, user: User = Depends(current_user), s: Session = Depends(db)):
        need_manager(user)
        return controls.member_limits(s, member_or_404(s, user, member_id).id)

    @r.put("/socis/{member_id}/limits")
    def posa_limit(member_id: int, body: LimitIn, user: User = Depends(current_user), s: Session = Depends(db)):
        need_manager(user)
        m = member_or_404(s, user, member_id)
        mg = None if body.max_g is None else unitats.g_to_mg(body.max_g)
        run(controls.set_member_limit, s, user, m, body.periode, mg, body.motiu)
        return controls.member_limits(s, m.id)

    # ---------- lots ----------
    @r.post("/productes/{product_id}/lots", status_code=201)
    def alta_lot(product_id: int, body: LotIn, user: User = Depends(current_user), s: Session = Depends(db)):
        need_manager(user)
        p = product_or_404(s, user, product_id)
        b = run(lots.create, s, user, p, body.codi, body.origen, body.proveidor, body.collita, body.data_entrada, body.analisi)
        return {"id": b.id}

    @r.get("/productes/{product_id}/lots")
    def llista_lots(product_id: int, user: User = Depends(current_user), s: Session = Depends(db)):
        need_manager(user)
        product_or_404(s, user, product_id)
        return lots.list_batches(s, product_id)

    def _lot(s: Session, user: User, lot_id: int) -> Batch:
        b = s.get(Batch, lot_id)
        if not b:
            raise HTTPException(404, "Lot inexistent")
        check_local(s, user, b.local_id)
        return b

    @r.post("/lots/{lot_id}/tancar")
    def tanca_lot(lot_id: int, user: User = Depends(current_user), s: Session = Depends(db)):
        need_manager(user)
        b = _lot(s, user, lot_id)
        b.actiu = False
        service.audit_append(s, {"accio": "tanca_lot", "lot": b.id, "per": user.id})
        s.commit()
        return {"ok": True}

    @r.post("/lots/{lot_id}/entrada", status_code=201)
    def entrada_amb_lot(lot_id: int, body: EntradaLotIn, user: User = Depends(current_user), s: Session = Depends(db)):
        need_manager(user)
        b = _lot(s, user, lot_id)
        m = run(stock.receive, s, user, b.product_id, body.grams, body.nota, body.magatzem_id, b.id)
        return {"id": m.id}

    @r.post("/dispensacions/amb-lot", status_code=201)
    def dispensa_amb_lot(body: DispensacioLotIn, user: User = Depends(current_user), s: Session = Depends(db)):
        """Dispensació amb selecció manual de lot (la normal, /dispensacions, reparteix per FIFO)."""
        product_or_404(s, user, body.product_id)
        m = run(stock.dispense, s, user, body.member_id, body.product_id, body.grams, body.pes_bascula_g, None,
                body.discount_id, body.metode, body.batch_id)
        return {"id": m.id, "import_cent": m.import_cent}

    @r.get("/lots/{lot_id}/tracabilitat")
    def tracabilitat(lot_id: int, user: User = Depends(current_user), s: Session = Depends(db)):
        need_manager(user)
        t = lots.trace(s, _lot(s, user, lot_id))
        service.audit_append(s, {"accio": "consulta_tracabilitat", "lot": lot_id, "per": user.id})
        s.commit()
        return t

    @r.get("/lots/{lot_id}/tracabilitat.csv")
    def tracabilitat_csv(lot_id: int, user: User = Depends(current_user), s: Session = Depends(db)):
        need_manager(user)
        t = lots.trace(s, _lot(s, user, lot_id))
        csv = lots.trace_csv(t)
        service.audit_append(s, {"accio": "exporta_tracabilitat", "lot": lot_id, "per": user.id})
        s.commit()
        return Response(csv, media_type="text/csv")

    # ---------- llibres signats ----------
    def _llibre(nom: str, fn, local_id: int, des: date, fins: date, user: User, s: Session) -> Response:
        need_manager(user)
        check_local(s, user, local_id)
        rang(des, fins)
        csv = fn(s, local_id, des, fins)
        h = llibres.sign_and_log(s, user, nom, local_id, des, fins, csv)
        return Response(csv, media_type="text/csv", headers={"X-Content-SHA256": h, "Content-Disposition": f'attachment; filename="llibre-{nom}-{des}-{fins}.csv"'})

    @r.get("/locals/{local_id}/llibres/socis.csv")
    def llibre_socis(local_id: int, des: date, fins: date, user: User = Depends(current_user), s: Session = Depends(db)):
        return _llibre("socis", llibres.members_book, local_id, des, fins, user, s)

    @r.get("/locals/{local_id}/llibres/estoc.csv")
    def llibre_estoc(local_id: int, des: date, fins: date, user: User = Depends(current_user), s: Session = Depends(db)):
        return _llibre("estoc", llibres.stock_book, local_id, des, fins, user, s)

    @r.post("/llibres/verificar")
    def verifica_llibre(body: VerificaIn, user: User = Depends(current_user), s: Session = Depends(db)):
        need_manager(user)
        permesos = None if user.role == "admin" else set(s.scalars(select(UserLocal.local_id).where(UserLocal.user_id == user.id)))
        return {"coincidencies": llibres.verify(s, body.sha256, permesos)}

    return r

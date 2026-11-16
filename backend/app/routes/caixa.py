"""Rutes: caixa, cobraments i despeses (extretes de main.py sense canviar-ne el comportament)."""

from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .. import cash, idempotencia
from ..models import CashEntry, StockMovement, User
from .comu import CAN_CREATE_MEMBER


class CorreccioIn(BaseModel):
    nota: str = Field(min_length=3, max_length=300)


def register(app, db, current_user, check_local, need_manager, run):
    class ObrirIn(BaseModel):
        local_id: int
        opening_cent: int = Field(ge=0)

    class TancarIn(BaseModel):
        local_id: int
        counted_cent: int = Field(ge=0)

    class CobramentIn(BaseModel):
        movement_id: int
        metode: str

    class DespesaIn(BaseModel):
        local_id: int
        cent: int = Field(gt=0)
        metode: str
        categoria: str = Field(min_length=1, max_length=60)
        concepte: str = Field(min_length=3, max_length=300)
        client_ref: str | None = Field(default=None, pattern=idempotencia.REF_PATTERN)  # referència de l'operació: repetida, no es torna a fer

    @app.post("/caixa/obrir", status_code=201)
    def obrir_caixa(body: ObrirIn, user: User = Depends(current_user), s: Session = Depends(db)):
        need_manager(user)
        check_local(s, user, body.local_id)
        cs = run(cash.open_session, s, user, body.local_id, body.opening_cent)
        return {"sessio": cs.id}

    @app.post("/caixa/tancar")
    def tancar_caixa(body: TancarIn, user: User = Depends(current_user), s: Session = Depends(db)):
        need_manager(user)
        check_local(s, user, body.local_id)
        cs = run(cash.close_session, s, user, body.local_id, body.counted_cent)
        return {"sessio": cs.id, "esperat_cent": cs.expected_cent, "comptat_cent": cs.counted_cent, "diferencia_cent": cs.diff_cent,
                "sense_cobrar": cs.sense_cobrar, "sense_cobrar_cent": cs.sense_cobrar_cent}

    @app.post("/cobraments", status_code=201)
    def cobrament(body: CobramentIn, user: User = Depends(current_user), s: Session = Depends(db)):
        mv = s.get(StockMovement, body.movement_id)
        if not mv:
            raise HTTPException(404, "Moviment inexistent")
        check_local(s, user, mv.local_id)
        e = run(cash.charge, s, user, body.movement_id, body.metode)
        return {"apunt": e.id, "import_cent": e.import_cent}

    @app.post("/despeses", status_code=201)
    def despesa(body: DespesaIn, user: User = Depends(current_user), s: Session = Depends(db)):
        need_manager(user)
        check_local(s, user, body.local_id)

        def fes():
            e = run(cash.expense, s, user, body.local_id, body.cent, body.metode, body.categoria, body.concepte)
            return {"apunt": e.id}
        return idempotencia.executa(s, user, "despeses", body.client_ref, body.model_dump(mode="json"), fes)

    @app.post("/caixa/apunts/{entry_id}/correccio", status_code=201)
    def correccio_apunt(entry_id: int, body: CorreccioIn, user: User = Depends(current_user), s: Session = Depends(db)):
        need_manager(user)
        orig = s.get(CashEntry, entry_id)
        if not orig:
            raise HTTPException(404, "Apunt inexistent")
        check_local(s, user, orig.local_id)
        e = run(cash.correct_entry, s, user, entry_id, body.nota)
        return {"apunt": e.id}

    @app.get("/locals/{local_id}/caixa")
    def estat_caixa(local_id: int, user: User = Depends(current_user), s: Session = Depends(db)):
        check_local(s, user, local_id)
        cs = cash.current_session(s, local_id)
        if not cs:
            return {"oberta": False}
        out = {"oberta": True, "sessio": cs.id, "obertura_cent": cs.opening_cent}
        if user.role in CAN_CREATE_MEMBER:
            out["esperat_cent"] = cash.expected_cash(s, cs)
            pendents = cash.unpaid_dispensations(s, local_id, cs.opened_at)
            out["sense_cobrar"], out["sense_cobrar_cent"] = pendents, sum(p["import_cent"] for p in pendents)
        return out

"""Rutes: caixa, cobraments i despeses (extretes de main.py sense canviar-ne el comportament)."""

from datetime import date

from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .. import cash, gastos, idempotencia
from ..models import CashEntry, CashRegister, CashSession, StockMovement, User
from .comu import CAN_CREATE_MEMBER, need_permis, need_recepcio, pot_dispensari, pot_recepcio


class CorreccioIn(BaseModel):
    nota: str = Field(min_length=3, max_length=300)


def register(app, db, current_user, check_local, need_manager, run):
    class ObrirIn(BaseModel):
        local_id: int
        opening_cent: int = Field(ge=0, le=100_000_000)
        register_id: int | None = None  # caixa registradora (buit = la caixa del local, com abans)
        assigned_to: int | None = None  # empleat que hi treballa (buit = qui l'obre)

    class TancarIn(BaseModel):
        local_id: int
        counted_cent: int = Field(ge=0, le=100_000_000)
        session_id: int | None = None  # buit = la caixa de qui tanca
        fons_cent: int | None = Field(default=None, ge=0, le=100_000_000)  # fons de caixa que es deixa al calaix
        billets_cent: int | None = Field(default=None, ge=0, le=100_000_000)  # del que surt (comptat - fons): quant són billets
        monedes_cent: int | None = Field(default=None, ge=0, le=100_000_000)  # ... i quant són monedes

    class CobramentIn(BaseModel):
        movement_id: int
        metode: str

    class DespesaIn(BaseModel):
        local_id: int
        cent: int = Field(gt=0, le=100_000_000)
        metode: str
        categoria: str = Field(min_length=1, max_length=60)
        concepte: str = Field(min_length=3, max_length=300)
        client_ref: str | None = Field(default=None, pattern=idempotencia.REF_PATTERN)  # referència de l'operació: repetida, no es torna a fer

    @app.post("/caixa/obrir", status_code=201)
    def obrir_caixa(body: ObrirIn, user: User = Depends(current_user), s: Session = Depends(db)):
        need_recepcio(user)  # recepció (o gerència): el dispensari no toca la caixa
        check_local(s, user, body.local_id)
        cs = run(cash.open_session, s, user, body.local_id, body.opening_cent, body.register_id, body.assigned_to)
        return {"sessio": cs.id}

    @app.post("/caixa/tancar")
    def tancar_caixa(body: TancarIn, user: User = Depends(current_user), s: Session = Depends(db)):
        need_recepcio(user)  # recepció (o gerència): el dispensari no toca la caixa
        check_local(s, user, body.local_id)
        cs = run(cash.close_session, s, user, body.local_id, body.counted_cent, body.session_id, body.fons_cent, body.billets_cent, body.monedes_cent)
        return {"sessio": cs.id, "esperat_cent": cs.expected_cent, "comptat_cent": cs.counted_cent, "diferencia_cent": cs.diff_cent,
                "fons_deixat_cent": cs.fons_deixat_cent, "sortida_billets_cent": cs.sortida_billets_cent, "sortida_monedes_cent": cs.sortida_monedes_cent,
                "tpv": cash.tpv_totals(s, cs.id), "sense_cobrar": cs.sense_cobrar, "sense_cobrar_cent": cs.sense_cobrar_cent}

    @app.post("/cobraments", status_code=201)
    def cobrament(body: CobramentIn, user: User = Depends(current_user), s: Session = Depends(db)):
        if not (pot_recepcio(user) or pot_dispensari(user)):  # cal haver triat el rol del dia (recepció o dispensari)
            raise HTTPException(403, "Tria el teu rol del dia per cobrar")
        mv = s.get(StockMovement, body.movement_id)
        if not mv:
            raise HTTPException(404, "Moviment inexistent")
        check_local(s, user, mv.local_id)
        e = run(cash.charge, s, user, body.movement_id, body.metode)
        return {"apunt": e.id, "import_cent": e.import_cent}

    @app.post("/despeses", status_code=201)
    def despesa(body: DespesaIn, user: User = Depends(current_user), s: Session = Depends(db)):
        need_recepcio(user)  # recepció (o gerència): el dispensari no toca la caixa
        check_local(s, user, body.local_id)

        def fes():
            e, g = run(gastos.registra_de_caixa, s, user, body.local_id, body.cent, body.metode, body.categoria, body.concepte)  # apareix també a Gastos
            return {"apunt": e.id, "gasto": g.id}
        return idempotencia.executa(s, user, "despeses", body.client_ref, body.model_dump(mode="json"), fes)

    @app.post("/caixa/apunts/{entry_id}/correccio", status_code=201)
    def correccio_apunt(entry_id: int, body: CorreccioIn, user: User = Depends(current_user), s: Session = Depends(db)):
        need_permis(user, 'corregir_caixa')  # anul·lar un apunt de caixa: gerència o permís explícit (qui cobra no ho pot fer tot sol)
        orig = s.get(CashEntry, entry_id)
        if not orig:
            raise HTTPException(404, "Apunt inexistent")
        check_local(s, user, orig.local_id)
        e = run(cash.correct_entry, s, user, entry_id, body.nota)
        return {"apunt": e.id}

    @app.get("/locals/{local_id}/caixa")
    def estat_caixa(local_id: int, user: User = Depends(current_user), s: Session = Depends(db)):
        check_local(s, user, local_id)
        try:
            cs = cash.current_session(s, local_id, actor=user)
        except ValueError as e:   # diverses caixes obertes i cap assignada a l'usuari
            return {"oberta": False, "ambigua": True, "motiu": str(e)}
        gestor = pot_recepcio(user)
        # Deutes de sessions anteriors (o fets amb la caixa tancada): no han de quedar invisibles; es cobren amb la caixa oberta.
        anteriors = cash.unpaid_dispensations(s, local_id, None, cs.opened_at if cs else None) if gestor else None
        extra = {} if anteriors is None else {"sense_cobrar_anteriors": anteriors, "sense_cobrar_anteriors_cent": sum(p["import_cent"] for p in anteriors)}
        if not cs:
            return {"oberta": False, "fons_darrer_cent": cash.last_fons(s, local_id) if gestor else None, **extra}
        out = {"oberta": True, "sessio": cs.id, "obertura_cent": cs.opening_cent, "caixa_id": cs.register_id, **extra}
        if gestor:
            out["esperat_cent"] = cash.expected_cash(s, cs)
            out["fons_darrer_cent"] = cash.last_fons(s, local_id, cs.register_id)
            out["tpv"] = cash.tpv_totals(s, cs.id)
            pendents = cash.unpaid_dispensations(s, local_id, cs.opened_at)
            out["sense_cobrar"], out["sense_cobrar_cent"] = pendents, sum(p["import_cent"] for p in pendents)
        return out

    class CaixaRegIn(BaseModel):
        nom: str = Field(min_length=1, max_length=60)
        warehouse_id: int | None = None

    class CaixaRegUpdateIn(BaseModel):
        nom: str | None = Field(default=None, max_length=60)
        actiu: bool | None = None

    @app.get("/locals/{local_id}/caixes")
    def llista_caixes(local_id: int, user: User = Depends(current_user), s: Session = Depends(db)):
        need_manager(user)
        check_local(s, user, local_id)
        return cash.registers_list(s, local_id)

    @app.post("/locals/{local_id}/caixes", status_code=201)
    def alta_caixa(local_id: int, body: CaixaRegIn, user: User = Depends(current_user), s: Session = Depends(db)):
        need_manager(user)
        check_local(s, user, local_id)
        return {"id": run(cash.register_create, s, user, local_id, body.nom, body.warehouse_id).id}

    @app.put("/caixes/{register_id}")
    def edita_caixa(register_id: int, body: CaixaRegUpdateIn, user: User = Depends(current_user), s: Session = Depends(db)):
        need_manager(user)
        reg = s.get(CashRegister, register_id)
        if not reg:
            raise HTTPException(404, "Caixa inexistent")
        check_local(s, user, reg.local_id)
        run(cash.register_update, s, user, reg, body.nom, body.actiu)
        return {"ok": True}

    @app.get("/caixa/sessions/{session_id}/tpv")
    def full_tpv(session_id: int, user: User = Depends(current_user), s: Session = Depends(db)):
        """Fulla de totals del TPV (targeta i Bizum) d'un torn, per imprimir en acabar-lo."""
        need_recepcio(user)
        cs = s.get(CashSession, session_id)
        if not cs:
            raise HTTPException(404, "Sessió de caixa inexistent")
        check_local(s, user, cs.local_id)
        return {"sessio": cs.id, "obertura": cs.opened_at.isoformat(), "tancament": cs.closed_at.isoformat() if cs.closed_at else None,
                **cash.tpv_totals(s, cs.id)}

    @app.get("/locals/{local_id}/caixa/sessions")
    def resum_sessions(local_id: int, des: date, fins: date, user: User = Depends(current_user), s: Session = Depends(db)):
        need_recepcio(user)  # recepció (o gerència): el dispensari no toca la caixa
        check_local(s, user, local_id)
        if fins < des:
            raise HTTPException(422, "Rang de dates invàlid")
        return cash.sessions_summary(s, local_id, des, fins)

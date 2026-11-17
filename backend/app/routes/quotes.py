"""Rutes: quotes i ajustos del local (extretes de main.py sense canviar-ne el comportament)."""

from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .. import ajustos, idempotencia, moneder, quotes, service
from ..models import Local, User


def register(app, db, current_user, need_admin, run, member_or_404):
    class QuotaIn(BaseModel):
        import_cent: int = Field(gt=0, le=quotes.MAX_IMPORT_CENT)
        metode: str
        mesos: int = Field(default=1, ge=1, le=quotes.MAX_MESOS)
        nota: str | None = Field(default=None, max_length=200)
        client_ref: str | None = Field(default=None, pattern=idempotencia.REF_PATTERN)  # referència de l'operació: repetida, no es torna a fer

    @app.post("/socis/{member_id}/quotes", status_code=201)
    def cobrar_quota(member_id: int, body: QuotaIn, user: User = Depends(current_user), s: Session = Depends(db)):
        m = member_or_404(s, user, member_id)

        def fes():
            q = run(quotes.charge, s, user, m, body.import_cent, body.metode, body.mesos, None, body.nota)
            return {"id": q.id, "valid_des": q.valid_des.isoformat(), "valid_fins": q.valid_fins.isoformat(), "apunt": q.cash_entry_id}
        return idempotencia.executa(s, user, f"quotes/{member_id}", body.client_ref, body.model_dump(mode="json"), fes)

    @app.get("/socis/{member_id}/quotes")
    def historial_quotes(member_id: int, user: User = Depends(current_user), s: Session = Depends(db)):
        m = member_or_404(s, user, member_id)
        service.audit_append(s, {"accio": "consulta_quotes", "soci": m.id, "per": user.id})
        s.commit()
        return {"estat": quotes.status(s, m.id), "historial": quotes.history(s, m.id)}

    class RecarregaIn(BaseModel):
        import_cent: int = Field(gt=0, le=moneder.MAX_RECARREGA_CENT)
        metode: str
        client_ref: str | None = Field(default=None, pattern=idempotencia.REF_PATTERN)

    @app.post("/socis/{member_id}/moneder/recarrega", status_code=201)
    def recarregar_moneder(member_id: int, body: RecarregaIn, user: User = Depends(current_user), s: Session = Depends(db)):
        m = member_or_404(s, user, member_id)

        def fes():
            w = run(moneder.recharge, s, user, m, body.import_cent, body.metode)
            return {"id": w.id, "saldo_cent": moneder.saldo(s, m.id), "apunt": w.cash_entry_id}
        return idempotencia.executa(s, user, f"moneder/{member_id}", body.client_ref, body.model_dump(mode="json"), fes)

    @app.get("/socis/{member_id}/moneder")
    def veure_moneder(member_id: int, user: User = Depends(current_user), s: Session = Depends(db)):
        m = member_or_404(s, user, member_id)
        return {"actiu": moneder.actiu(s, m.local_id), "saldo_cent": moneder.saldo(s, m.id),
                "limit_negatiu_cent": moneder.limit_negatiu_cent(s, m.local_id), "historial": moneder.history(s, m.id)}

    class AjustosIn(BaseModel):
        edat_minima: int | None = Field(default=None, ge=18, le=99)
        inactivitat_dies: int | None = Field(default=None, ge=1, le=365)
        decimals_dispensacio: int | None = Field(default=None, ge=0, le=3)
        perdua_maxima_mg: int | None = Field(default=None, ge=0, le=10_000_000)
        moneder_actiu: bool | None = None
        moneder_limit_cent: int | None = Field(default=None, ge=0, le=1_000_000)
        quota_obligatoria: bool | None = None
        quota_cent: int | None = Field(default=None, ge=0, le=quotes.MAX_IMPORT_CENT)
        quota_mesos: int | None = Field(default=None, ge=1, le=quotes.MAX_MESOS)

    @app.put("/locals/{local_id}/config")
    def canvia_config(local_id: int, body: AjustosIn, user: User = Depends(current_user), s: Session = Depends(db)):
        need_admin(user)
        if not s.get(Local, local_id):
            raise HTTPException(404, "Local inexistent")
        return run(ajustos.set_, s, user, local_id, body.model_dump())

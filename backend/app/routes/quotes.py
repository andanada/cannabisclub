"""Rutes: quotes i ajustos del local (extretes de main.py sense canviar-ne el comportament)."""

from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .. import ajustos, quotes, service
from ..models import Local, User


def register(app, db, current_user, need_admin, run, member_or_404):
    class QuotaIn(BaseModel):
        import_cent: int = Field(gt=0, le=quotes.MAX_IMPORT_CENT)
        metode: str
        mesos: int = Field(default=1, ge=1, le=quotes.MAX_MESOS)
        nota: str | None = Field(default=None, max_length=200)

    @app.post("/socis/{member_id}/quotes", status_code=201)
    def cobrar_quota(member_id: int, body: QuotaIn, user: User = Depends(current_user), s: Session = Depends(db)):
        q = run(quotes.charge, s, user, member_or_404(s, user, member_id), body.import_cent, body.metode, body.mesos, None, body.nota)
        return {"id": q.id, "valid_des": q.valid_des.isoformat(), "valid_fins": q.valid_fins.isoformat(), "apunt": q.cash_entry_id}

    @app.get("/socis/{member_id}/quotes")
    def historial_quotes(member_id: int, user: User = Depends(current_user), s: Session = Depends(db)):
        m = member_or_404(s, user, member_id)
        service.audit_append(s, {"accio": "consulta_quotes", "soci": m.id, "per": user.id})
        s.commit()
        return {"estat": quotes.status(s, m.id), "historial": quotes.history(s, m.id)}

    class AjustosIn(BaseModel):
        quota_obligatoria: bool | None = None
        quota_cent: int | None = Field(default=None, ge=0, le=quotes.MAX_IMPORT_CENT)
        quota_mesos: int | None = Field(default=None, ge=1, le=quotes.MAX_MESOS)

    @app.put("/locals/{local_id}/config")
    def canvia_config(local_id: int, body: AjustosIn, user: User = Depends(current_user), s: Session = Depends(db)):
        need_admin(user)
        if not s.get(Local, local_id):
            raise HTTPException(404, "Local inexistent")
        return run(ajustos.set_, s, user, local_id, body.model_dump())

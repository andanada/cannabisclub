"""Rutes: regles (extretes de main.py sense canviar-ne el comportament)."""
from decimal import Decimal

from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .. import regles
from ..models import Regla, User


def register(app, db, current_user, check_local, need_manager, need_admin, run):
    class ReglaIn(BaseModel):
        nom: str = Field(max_length=60)
        ambit: str
        categoria: str | None = Field(default=None, max_length=60)
        product_id: int | None = None
        periode: str
        max_g: Decimal = Field(gt=0, le=1_000_000, max_digits=12, decimal_places=3)   # sense límit, «1e30» acabava en un 500

    class ReglaUpdateIn(BaseModel):
        nom: str | None = Field(default=None, max_length=60)
        max_g: Decimal | None = Field(default=None, gt=0, le=1_000_000, max_digits=12, decimal_places=3)
        actiu: bool | None = None

    @app.get("/locals/{local_id}/regles")
    def llista_regles(local_id: int, user: User = Depends(current_user), s: Session = Depends(db)):
        need_manager(user)
        check_local(s, user, local_id)
        return regles.list_rules(s, local_id)

    @app.post("/locals/{local_id}/regles", status_code=201)
    def alta_regla(local_id: int, body: ReglaIn, user: User = Depends(current_user), s: Session = Depends(db)):
        need_admin(user)
        check_local(s, user, local_id)
        r = run(regles.create, s, user, local_id, body.nom, body.ambit, body.categoria, body.product_id, body.periode, body.max_g)
        return {"id": r.id}

    @app.put("/regles/{regla_id}")
    def edita_regla(regla_id: int, body: ReglaUpdateIn, user: User = Depends(current_user), s: Session = Depends(db)):
        need_admin(user)
        r = s.get(Regla, regla_id)
        if not r:
            raise HTTPException(404, "Regla inexistent")
        check_local(s, user, r.local_id)
        run(regles.update, s, user, r, body.actiu, body.nom, body.max_g)
        return {"ok": True}

"""Rutes: descomptes (extretes de main.py sense canviar-ne el comportament)."""
from datetime import date

from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .. import descomptes, quotes
from ..models import Discount, User


def register(app, db, current_user, check_local, need_manager, run, product_or_404):
    class DescompteIn(BaseModel):
        nom: str = Field(max_length=60)
        tipus: str
        valor: int
        ambit: str
        categoria: str | None = Field(default=None, max_length=60)
        product_id: int | None = None
        inici: date | None = None
        fi: date | None = None

    class DescompteUpdateIn(BaseModel):
        nom: str | None = Field(default=None, max_length=60)
        valor: int | None = None
        actiu: bool | None = None
        inici: date | None = None
        fi: date | None = None

    @app.get("/locals/{local_id}/descomptes")
    def llista_descomptes(local_id: int, producte: int | None = None, tots: bool = False, user: User = Depends(current_user), s: Session = Depends(db)):
        check_local(s, user, local_id)
        if tots:
            need_manager(user)
        p = product_or_404(s, user, producte) if producte else None
        return descomptes.list_discounts(s, local_id, quotes.avui(), p, tots)

    @app.post("/locals/{local_id}/descomptes", status_code=201)
    def alta_descompte(local_id: int, body: DescompteIn, user: User = Depends(current_user), s: Session = Depends(db)):
        need_manager(user)
        check_local(s, user, local_id)
        d = run(descomptes.create, s, user, local_id, body.nom, body.tipus, body.valor, body.ambit, body.categoria, body.product_id, body.inici, body.fi)
        return {"id": d.id}

    @app.put("/descomptes/{discount_id}")
    def edita_descompte(discount_id: int, body: DescompteUpdateIn, user: User = Depends(current_user), s: Session = Depends(db)):
        need_manager(user)
        d = s.get(Discount, discount_id)
        if not d:
            raise HTTPException(404, "Descompte inexistent")
        check_local(s, user, d.local_id)
        run(descomptes.update, s, user, d, body.actiu, body.nom, body.valor, body.inici, body.fi, frozenset({"inici", "fi"} & body.model_fields_set))
        return {"ok": True}

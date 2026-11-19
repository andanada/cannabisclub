"""Rutes: magatzems (extretes de main.py sense canviar-ne el comportament)."""
from decimal import Decimal

from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .. import magatzems
from ..models import User, Warehouse


def register(app, db, current_user, check_local, need_manager, run, product_or_404):
    class MagatzemIn(BaseModel):
        nom: str = Field(max_length=60)

    class MagatzemUpdateIn(BaseModel):
        nom: str | None = Field(default=None, max_length=60)
        actiu: bool | None = None

    class TraspasIn(BaseModel):
        product_id: int
        de: int | None = None  # buit = magatzem principal
        a: int | None = None
        grams: Decimal = Field(gt=0, max_digits=9, decimal_places=3)

    @app.get("/locals/{local_id}/magatzems")
    def llista_magatzems(local_id: int, user: User = Depends(current_user), s: Session = Depends(db)):
        need_manager(user)
        check_local(s, user, local_id)
        return magatzems.llista(s, local_id)

    @app.post("/locals/{local_id}/magatzems", status_code=201)
    def alta_magatzem(local_id: int, body: MagatzemIn, user: User = Depends(current_user), s: Session = Depends(db)):
        need_manager(user)
        check_local(s, user, local_id)
        return {"id": run(magatzems.create, s, user, local_id, body.nom).id}

    @app.put("/magatzems/{magatzem_id}")
    def edita_magatzem(magatzem_id: int, body: MagatzemUpdateIn, user: User = Depends(current_user), s: Session = Depends(db)):
        need_manager(user)
        w = s.get(Warehouse, magatzem_id)
        if not w:
            raise HTTPException(404, "Magatzem inexistent")
        check_local(s, user, w.local_id)
        run(magatzems.update, s, user, w, body.nom, body.actiu)
        return {"ok": True}

    @app.get("/locals/{local_id}/magatzems/estoc")
    def estoc_per_magatzem(local_id: int, user: User = Depends(current_user), s: Session = Depends(db)):
        need_manager(user)
        check_local(s, user, local_id)
        return magatzems.estoc(s, local_id)

    @app.post("/moviments/traspas", status_code=201)
    def traspas_estoc(body: TraspasIn, user: User = Depends(current_user), s: Session = Depends(db)):
        from .comu import need_dispensari
        need_dispensari(user)
        p = product_or_404(s, user, body.product_id)
        run(magatzems.transfer, s, user, p, body.de, body.a, body.grams)
        return {"ok": True}

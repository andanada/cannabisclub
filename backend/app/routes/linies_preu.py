"""Rutes: linies_preu (extretes de main.py sense canviar-ne el comportament)."""

from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .. import linies_preu
from ..models import PriceLine, User


def register(app, db, current_user, check_local, need_manager, run, member_or_404):
    class LiniaPreuIn(BaseModel):
        nom: str = Field(max_length=60)

    class LiniaPreuUpdateIn(BaseModel):
        nom: str | None = Field(default=None, max_length=60)
        actiu: bool | None = None

    class PreuLiniaIn(BaseModel):
        preu_cent_per_g: int = Field(ge=0, le=linies_preu.MAX_PREU)

    class AssignaLiniaIn(BaseModel):
        price_line_id: int | None = None

    def linia_or_404(s: Session, user: User, linia_id: int) -> PriceLine:
        need_manager(user)
        l = s.get(PriceLine, linia_id)
        if not l:
            raise HTTPException(404, "Línia de preu inexistent")
        check_local(s, user, l.local_id)
        return l

    @app.get("/locals/{local_id}/linies-preu")
    def llista_linies_preu(local_id: int, user: User = Depends(current_user), s: Session = Depends(db)):
        need_manager(user)
        check_local(s, user, local_id)
        return linies_preu.llista(s, local_id)

    @app.post("/locals/{local_id}/linies-preu", status_code=201)
    def alta_linia_preu(local_id: int, body: LiniaPreuIn, user: User = Depends(current_user), s: Session = Depends(db)):
        need_manager(user)
        check_local(s, user, local_id)
        return {"id": run(linies_preu.create, s, user, local_id, body.nom).id}

    @app.get("/linies-preu/{linia_id}")
    def detall_linia_preu(linia_id: int, user: User = Depends(current_user), s: Session = Depends(db)):
        return linies_preu.detall(s, linia_or_404(s, user, linia_id))

    @app.put("/linies-preu/{linia_id}")
    def edita_linia_preu(linia_id: int, body: LiniaPreuUpdateIn, user: User = Depends(current_user), s: Session = Depends(db)):
        run(linies_preu.update, s, user, linia_or_404(s, user, linia_id), body.nom, body.actiu)
        return {"ok": True}

    @app.put("/linies-preu/{linia_id}/preus/{product_id}")
    def posa_preu_linia(linia_id: int, product_id: int, body: PreuLiniaIn, user: User = Depends(current_user), s: Session = Depends(db)):
        run(linies_preu.set_price, s, user, linia_or_404(s, user, linia_id), product_id, body.preu_cent_per_g)
        return {"ok": True}

    @app.delete("/linies-preu/{linia_id}/preus/{product_id}")
    def esborra_preu_linia(linia_id: int, product_id: int, user: User = Depends(current_user), s: Session = Depends(db)):
        if not linies_preu.remove_price(s, user, linia_or_404(s, user, linia_id), product_id):
            raise HTTPException(404, "Aquest producte no té preu a la línia")
        return {"ok": True}

    @app.get("/socis/{member_id}/linia-preu")
    def linia_preu_del_soci(member_id: int, user: User = Depends(current_user), s: Session = Depends(db)):
        return linies_preu.member_line(s, member_or_404(s, user, member_id).id)

    @app.put("/socis/{member_id}/linia-preu")
    def assigna_linia_preu(member_id: int, body: AssignaLiniaIn, user: User = Depends(current_user), s: Session = Depends(db)):
        need_manager(user)
        run(linies_preu.assign, s, user, member_or_404(s, user, member_id), body.price_line_id)
        return {"ok": True}

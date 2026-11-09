"""Rutes: contenidors (extretes de main.py sense canviar-ne el comportament)."""
from decimal import Decimal

from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .. import contenidors
from ..models import Container, ContainerType, User


def register(app, db, current_user, check_local, need_manager, run):
    class TipusContenidorIn(BaseModel):
        nom: str = Field(max_length=60)
        tara_g: Decimal = Field(ge=0, le=50_000, decimal_places=3)

    class TipusContenidorUpdateIn(BaseModel):
        nom: str | None = Field(default=None, max_length=60)
        tara_g: Decimal | None = Field(default=None, ge=0, le=50_000, decimal_places=3)
        actiu: bool | None = None

    class ContenidorIn(BaseModel):
        codi: str = Field(max_length=40)
        type_id: int
        product_id: int | None = None
        brut_g: Decimal | None = Field(default=None, ge=0, le=50_000, decimal_places=3)

    class ContenidorUpdateIn(BaseModel):
        codi: str | None = Field(default=None, max_length=40)
        type_id: int | None = None
        product_id: int | None = None
        brut_g: Decimal | None = Field(default=None, ge=0, le=50_000, decimal_places=3)
        actiu: bool | None = None

    @app.get("/locals/{local_id}/tipus-contenidor")
    def llista_tipus_contenidor(local_id: int, user: User = Depends(current_user), s: Session = Depends(db)):
        need_manager(user)
        check_local(s, user, local_id)
        return contenidors.llista_tipus(s, local_id)

    @app.post("/locals/{local_id}/tipus-contenidor", status_code=201)
    def alta_tipus_contenidor(local_id: int, body: TipusContenidorIn, user: User = Depends(current_user), s: Session = Depends(db)):
        need_manager(user)
        check_local(s, user, local_id)
        return {"id": run(contenidors.create_type, s, user, local_id, body.nom, body.tara_g).id}

    @app.put("/tipus-contenidor/{tipus_id}")
    def edita_tipus_contenidor(tipus_id: int, body: TipusContenidorUpdateIn, user: User = Depends(current_user), s: Session = Depends(db)):
        need_manager(user)
        t = s.get(ContainerType, tipus_id)
        if not t:
            raise HTTPException(404, "Tipus de contenidor inexistent")
        check_local(s, user, t.local_id)
        run(contenidors.update_type, s, user, t, body.nom, body.tara_g, body.actiu)
        return {"ok": True}

    @app.get("/locals/{local_id}/contenidors")
    def llista_contenidors(local_id: int, user: User = Depends(current_user), s: Session = Depends(db)):
        need_manager(user)
        check_local(s, user, local_id)
        return contenidors.llista(s, local_id)

    @app.post("/locals/{local_id}/contenidors", status_code=201)
    def alta_contenidor(local_id: int, body: ContenidorIn, user: User = Depends(current_user), s: Session = Depends(db)):
        need_manager(user)
        check_local(s, user, local_id)
        return {"id": run(contenidors.create, s, user, local_id, body.codi, body.type_id, body.product_id, body.brut_g).id}

    @app.put("/contenidors/{contenidor_id}")
    def edita_contenidor(contenidor_id: int, body: ContenidorUpdateIn, user: User = Depends(current_user), s: Session = Depends(db)):
        need_manager(user)
        c = s.get(Container, contenidor_id)
        if not c:
            raise HTTPException(404, "Contenidor inexistent")
        check_local(s, user, c.local_id)
        run(contenidors.update, s, user, c, {k: getattr(body, k) for k in body.model_fields_set})
        return {"ok": True}

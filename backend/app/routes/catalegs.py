"""Rutes: aspecte de les categories de producte i monedes (només responsables per escriure)."""
from fastapi import Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .. import catalegs
from ..models import User


def register(app, db, current_user, check_local, need_manager, run):
    class CategoriaIn(BaseModel):
        nom: str = Field(min_length=1, max_length=60)
        icona: str = Field(default="", max_length=8)
        color: str = Field(default="", max_length=10)

    @app.get("/locals/{local_id}/categories")
    def llista_categories(local_id: int, user: User = Depends(current_user), s: Session = Depends(db)):
        check_local(s, user, local_id)  # també el dispensador: l'aspecte es veu a la pantalla de dispensar
        return {"icones": catalegs.ICONES, "colors": catalegs.COLORS, "categories": catalegs.categories(s, local_id)}

    @app.put("/locals/{local_id}/categories")
    def desa_categoria(local_id: int, body: CategoriaIn, user: User = Depends(current_user), s: Session = Depends(db)):
        need_manager(user)
        check_local(s, user, local_id)
        run(catalegs.desa_categoria, s, user, local_id, body.nom, body.icona, body.color)
        return {"ok": True}

    class MonedaIn(BaseModel):
        nom: str = Field(min_length=1, max_length=60)
        codi: str = Field(min_length=1, max_length=8)

    @app.get("/locals/{local_id}/monedes")
    def llista_monedes(local_id: int, user: User = Depends(current_user), s: Session = Depends(db)):
        need_manager(user)
        check_local(s, user, local_id)
        return catalegs.monedes(s, local_id)

    @app.post("/locals/{local_id}/monedes", status_code=201)
    def alta_moneda(local_id: int, body: MonedaIn, user: User = Depends(current_user), s: Session = Depends(db)):
        need_manager(user)
        check_local(s, user, local_id)
        return {"id": run(catalegs.crea_moneda, s, user, local_id, body.nom, body.codi)}

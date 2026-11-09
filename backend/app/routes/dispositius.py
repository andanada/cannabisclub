"""Rutes: dispositius (extretes de main.py sense canviar-ne el comportament)."""

import json

from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from .. import dispositius
from ..models import DeviceProfile, Local, User


def register(app, db, current_user, check_local, need_admin, run):
    class DispositiuIn(BaseModel):
        kind: str
        nom: str = Field(max_length=60)
        config: dict = Field(default={}, max_length=40)
        per_defecte: bool = False

        @field_validator("config")
        @classmethod
        def _config_petita(cls, v):
            if len(json.dumps(v, default=str)) > 2000:
                raise ValueError("La configuració és massa gran")
            return v

    class DispositiuUpdateIn(BaseModel):
        nom: str | None = Field(default=None, max_length=60)
        config: dict | None = Field(default=None, max_length=40)
        per_defecte: bool | None = None

        @field_validator("config")
        @classmethod
        def _config_petita(cls, v):
            if v is not None and len(json.dumps(v, default=str)) > 2000:
                raise ValueError("La configuració és massa gran")
            return v

    def dispositiu_or_404(s: Session, did: int) -> DeviceProfile:
        d = s.get(DeviceProfile, did)
        if not d:
            raise HTTPException(404, "Dispositiu inexistent")
        return d

    @app.get("/locals/{local_id}/dispositius")
    def llista_dispositius(local_id: int, kind: str | None = None, user: User = Depends(current_user), s: Session = Depends(db)):
        check_local(s, user, local_id)  # qualsevol rol del local: la tauleta necessita el seu perfil per treballar
        return dispositius.list_profiles(s, local_id, kind)

    @app.post("/locals/{local_id}/dispositius", status_code=201)
    def alta_dispositiu(local_id: int, body: DispositiuIn, user: User = Depends(current_user), s: Session = Depends(db)):
        need_admin(user)
        if not s.get(Local, local_id):
            raise HTTPException(404, "Local inexistent")
        d = run(dispositius.create, s, user, local_id, body.kind, body.nom, body.config, body.per_defecte)
        return {"id": d.id}

    @app.put("/dispositius/{device_id}")
    def edita_dispositiu(device_id: int, body: DispositiuUpdateIn, user: User = Depends(current_user), s: Session = Depends(db)):
        need_admin(user)
        run(dispositius.update, s, user, dispositiu_or_404(s, device_id), body.nom, body.config, body.per_defecte)
        return {"ok": True}

    @app.delete("/dispositius/{device_id}")
    def esborra_dispositiu(device_id: int, user: User = Depends(current_user), s: Session = Depends(db)):
        need_admin(user)
        run(dispositius.delete, s, user, dispositiu_or_404(s, device_id))
        return {"ok": True}

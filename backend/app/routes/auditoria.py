"""Rutes: verificació i ancoratge de l'auditoria (extretes de main.py sense canviar-ne el comportament)."""

from fastapi import Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .. import service
from ..models import User


def register(app, db, current_user, need_admin):
    class AncoratgeIn(BaseModel):
        seq: int = Field(ge=1)
        hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    def _verifica(s: Session, user: User, ancora: dict | None):
        need_admin(user)
        d = service.audit_verify_detail(s, ancora)
        return {"integra": d["integra"], "primera_alterada": d["primera_alterada"], "ultim_seq": d["ultim_seq"],
                "ultim_hash": d["ultim_hash"], "entrades": d["entrades"], "avisos": d["avisos"]}

    @app.get("/auditoria/verificar")
    def verificar(user: User = Depends(current_user), s: Session = Depends(db)):
        return _verifica(s, user, None)

    @app.post("/auditoria/verificar")
    def verificar_amb_ancora(body: AncoratgeIn, user: User = Depends(current_user), s: Session = Depends(db)):
        """Verifica la cadena contra un ancoratge guardat fora de l'equip: detecta que s'hagi retallat el final."""
        return _verifica(s, user, body.model_dump())

    @app.get("/auditoria/ancoratge")
    def ancoratge(user: User = Depends(current_user), s: Session = Depends(db)):
        need_admin(user)
        return service.audit_anchor(s) or {"seq": 0, "hash": ""}

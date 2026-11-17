"""Rutes: locals, usuaris, límits i contrasenyes (extretes de main.py sense canviar-ne el comportament)."""
from decimal import ROUND_HALF_UP, Decimal

from fastapi import Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .. import carnet_login, service, usuaris
from ..models import Local, User


def register(app, db, current_user, need_admin, run, usuari_or_404):
    class LocalIn(BaseModel):
        nom: str = Field(min_length=2, max_length=120)

    class UsuariIn(BaseModel):
        username: str = Field(min_length=3, max_length=60)
        password: str = Field(max_length=200)
        role: str
        local_ids: list[int] = Field(default=[], max_length=50)

    MAX_LIMIT_DIARI_G = Decimal("100000")
    MAX_LIMIT_MENSUAL_G = Decimal("1000000")
    MAX_TOLERANCIA_G = Decimal("1000")

    def to_mg(g: Decimal | None) -> int | None:
        """Grams -> mil·ligrams arrodonint al més proper (0,0005 g = 1 mg); abans es truncava i 0,0019 g donava 1 mg."""
        return None if g is None else int((g * 1000).quantize(Decimal(1), rounding=ROUND_HALF_UP))

    class LimitsIn(BaseModel):
        limit_diari_g: Decimal | None = Field(default=None, ge=0, le=MAX_LIMIT_DIARI_G, allow_inf_nan=False)
        limit_mensual_g: Decimal | None = Field(default=None, ge=0, le=MAX_LIMIT_MENSUAL_G, allow_inf_nan=False)
        tolerancia_bascula_g: Decimal | None = Field(default=None, ge=0, le=MAX_TOLERANCIA_G, allow_inf_nan=False)

    @app.post("/locals", status_code=201)
    def alta_local(body: LocalIn, user: User = Depends(current_user), s: Session = Depends(db)):
        need_admin(user)
        return {"id": run(service.create_local, s, user, body.nom).id}

    @app.post("/usuaris", status_code=201)
    def alta_usuari(body: UsuariIn, user: User = Depends(current_user), s: Session = Depends(db)):
        need_admin(user)
        u, secret = run(service.create_user, s, user, body.username, body.password, body.role, body.local_ids)
        return {"id": u.id, "totp_secret": secret}

    @app.get("/usuaris")
    def llista_usuaris(user: User = Depends(current_user), s: Session = Depends(db)):
        need_admin(user)
        return usuaris.list_users(s)

    class CarnetUsuariIn(BaseModel):
        codi: str = Field(max_length=64)
        pin: str = Field(max_length=12)

    class CarnetUsuariGenerarIn(BaseModel):
        pin: str = Field(max_length=12)
        prefix: str = Field(default="STF", pattern=r"^[A-Z0-9]{2,6}$")

    @app.put("/usuaris/{user_id}/carnet")
    def posa_carnet_usuari(user_id: int, body: CarnetUsuariIn, user: User = Depends(current_user), s: Session = Depends(db)):
        need_admin(user)
        run(carnet_login.assign, s, user, usuari_or_404(s, user_id), body.codi, body.pin)
        return {"ok": True}

    @app.post("/usuaris/{user_id}/carnet/generar", status_code=201)
    def genera_carnet_usuari(user_id: int, body: CarnetUsuariGenerarIn, user: User = Depends(current_user), s: Session = Depends(db)):
        need_admin(user)
        return {"codi": run(carnet_login.generate, s, user, usuari_or_404(s, user_id), body.pin, body.prefix)}  # l'únic cop que es mostra

    @app.delete("/usuaris/{user_id}/carnet")
    def retira_carnet_usuari(user_id: int, user: User = Depends(current_user), s: Session = Depends(db)):
        need_admin(user)
        if not carnet_login.remove(s, user, usuari_or_404(s, user_id)):
            raise HTTPException(404, "Aquest usuari no té carnet")
        return {"ok": True}

    class UsuariUpdateIn(BaseModel):
        active: bool | None = None
        role: str | None = None
        local_ids: list[int] | None = None
        pot_reemborsar: bool | None = None
        pot_editar_descomptes: bool | None = None
        moneder_limit_cent: int | None = Field(default=None, ge=0, le=1_000_000)  # enviat com a null = el límit del local

    @app.patch("/usuaris/{user_id}")
    def edita_usuari(user_id: int, body: UsuariUpdateIn, user: User = Depends(current_user), s: Session = Depends(db)):
        need_admin(user)
        privilegis = {k: getattr(body, k) for k in ("pot_reemborsar", "pot_editar_descomptes", "moneder_limit_cent") if k in body.model_fields_set}
        run(usuaris.update_user, s, user, usuari_or_404(s, user_id), body.active, body.role, body.local_ids, privilegis)
        return {"ok": True}

    @app.post("/usuaris/{user_id}/totp")
    def reinicia_totp(user_id: int, user: User = Depends(current_user), s: Session = Depends(db)):
        need_admin(user)
        return {"totp_secret": usuaris.reset_totp(s, user, usuari_or_404(s, user_id))}

    class ContrasenyaIn(BaseModel):
        password: str = Field(max_length=200)

    @app.post("/usuaris/{user_id}/contrasenya")
    def posa_contrasenya(user_id: int, body: ContrasenyaIn, user: User = Depends(current_user), s: Session = Depends(db)):
        need_admin(user)
        run(usuaris.set_password, s, user, usuari_or_404(s, user_id), body.password)
        return {"ok": True}

    class CanviContrasenyaIn(BaseModel):
        actual: str = Field(max_length=200)
        nova: str = Field(max_length=200)

    @app.post("/auth/canvi-contrasenya")
    def canvi_contrasenya(body: CanviContrasenyaIn, authorization: str = Header(default=""), user: User = Depends(current_user), s: Session = Depends(db)):
        _, _, token = authorization.partition(" ")
        try:
            usuaris.change_own_password(s, user, body.actual, body.nova, token)
        except service.LoginLocked:
            raise HTTPException(429, "Massa intents fallits: queda bloquejat uns minuts.")
        except PermissionError as e:
            raise HTTPException(403, str(e))
        except ValueError as e:
            raise HTTPException(422, str(e))
        return {"ok": True}

    @app.put("/locals/{local_id}/limits")
    def limits(local_id: int, body: LimitsIn, user: User = Depends(current_user), s: Session = Depends(db)):
        need_admin(user)
        loc = s.get(Local, local_id)
        if not loc:
            raise HTTPException(404, "Local inexistent")
        diari, mensual, tol = (to_mg(g) for g in (body.limit_diari_g, body.limit_mensual_g, body.tolerancia_bascula_g))
        if diari is not None and mensual is not None and diari > mensual:
            raise HTTPException(422, "El límit diari no pot superar el mensual")
        abans = {"diari_mg": loc.limit_diari_mg, "mensual_mg": loc.limit_mensual_mg, "tolerancia_mg": loc.tolerancia_bascula_mg}
        loc.limit_diari_mg, loc.limit_mensual_mg, loc.tolerancia_bascula_mg = diari, mensual, tol
        despres = {"diari_mg": diari, "mensual_mg": mensual, "tolerancia_mg": tol}
        service.audit_append(s, {"accio": "canvi_limits", "local": local_id, "abans": abans, "despres": despres, "per": user.id})
        s.commit()
        return {"ok": True}

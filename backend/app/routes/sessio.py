"""Rutes: inici i tancament de sessió, canvi de PIN i perfil (extretes de main.py sense canviar-ne el comportament)."""
import hashlib
import logging

from fastapi import Depends, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from .. import ajustos, carnet_login, permisos, service, versio
from ..models import Local, User, UserCard, UserLocal

log = logging.getLogger("club")


def register(app, db, current_user, ip_limiter):
    class LoginIn(BaseModel):
        # Límits: aquests valors poden acabar a l'auditoria, que és només d'afegir i no es pot netejar.
        username: str = Field(max_length=60)
        password: str = Field(max_length=200)
        totp: str = Field(default="", max_length=10)

    @app.get("/auth/opcions")
    def opcions_login():
        """Públic: la pantalla d'entrada hi consulta si ha de demanar el codi de l'app d'autenticació."""
        return {"totp": service.totp_required(), "carnet": carnet_login.enabled()}

    @app.get("/salut")
    def salut(s: Session = Depends(db)):
        """Per a monitoratge (systemd, Tailscale, un curl des de cron): 200 si la base de dades respon, 503 si no."""
        try:
            s.execute(text("SELECT 1"))
        except Exception:
            log.exception("salut: la base de dades no respon")
            return JSONResponse({"ok": False}, status_code=503)
        return {"ok": True, "versio": versio.actual()}

    @app.post("/auth/login")
    def login(body: LoginIn, request: Request, s: Session = Depends(db)):
        ip = carnet_login.client_ip(request.client.host if request.client else None, request.headers.get("x-forwarded-for")) or "?"
        if not ip_limiter.allow("login:" + ip):
            raise HTTPException(429, "Massa peticions des d'aquesta adreça. Torna-ho a provar d'aquí a un minut.")
        try:
            token = service.login(s, body.username, body.password, body.totp)
        except service.LoginLocked:
            raise HTTPException(429, "Massa intents fallits: l'accés queda bloquejat uns minuts. Torna-ho a provar més tard.")
        if not token:
            raise HTTPException(401, "Credencials incorrectes")
        return {"token": token}

    class LoginCarnetIn(BaseModel):
        codi: str = Field(max_length=64)
        pin: str = Field(default="", max_length=12)

    @app.post("/auth/login-carnet")
    def login_carnet(body: LoginCarnetIn, request: Request, s: Session = Depends(db)):
        """Entrada ràpida d'un treballador: carnet RFID + PIN (no per a administradors)."""
        if not carnet_login.enabled():
            raise HTTPException(403, "L'entrada amb carnet està desactivada en aquest servidor")
        ip = carnet_login.client_ip(request.client.host if request.client else None, request.headers.get("x-forwarded-for"))
        if not carnet_login.network_allowed(ip):
            raise HTTPException(403, "L'entrada amb carnet només es pot fer des de la xarxa del club")
        try:
            if not ip_limiter.allow("carnet:" + (ip or "?")):
                raise HTTPException(429, "Massa peticions des d'aquesta adreça. Torna-ho a provar d'aquí a un minut.")
            token = carnet_login.login(s, body.codi, body.pin, ip)
        except service.LoginLocked:
            raise HTTPException(429, "Massa intents fallits amb carnet: queda bloquejat uns minuts. Entra amb usuari i contrasenya.")
        if not token:
            raise HTTPException(401, "Carnet o PIN incorrectes")
        return {"token": token, "canvi_pin": carnet_login.pin_antic(body.pin)}

    class PinCarnetIn(BaseModel):
        actual: str = Field(max_length=12)
        nova: str = Field(max_length=12)

    @app.post("/auth/carnet-pin")
    def canvia_pin_carnet(body: PinCarnetIn, authorization: str = Header(default=""), user: User = Depends(current_user), s: Session = Depends(db)):
        _, _, tok = authorization.partition(" ")
        try:
            carnet_login.change_pin(s, user, body.actual, body.nova, hashlib.sha256(tok.encode()).hexdigest())
        except service.LoginLocked:
            raise HTTPException(429, "Massa intents fallits: queda bloquejat uns minuts.")
        except ValueError as e:
            raise HTTPException(422, str(e))
        return {"ok": True}

    class RolDiaIn(BaseModel):
        rol: str = Field(max_length=12)

    @app.post("/auth/rol-dia")
    def rol_dia(body: RolDiaIn, user: User = Depends(current_user), authorization: str = Header(default=""), s: Session = Depends(db)):
        """El treballador tria el rol del dia (recepcio o dispensari). La gerència no n'ha de triar."""
        _, _, token = authorization.partition(" ")
        try:
            service.set_rol_dia(s, token, user, body.rol)
        except ValueError as e:
            raise HTTPException(422, str(e))
        return {"rol_dia": body.rol}

    @app.get("/me")
    def me(user: User = Depends(current_user), s: Session = Depends(db)):
        if user.role == "admin":
            locs = s.scalars(select(Local).order_by(Local.id)).all()
        else:
            ids = [r.local_id for r in s.scalars(select(UserLocal).where(UserLocal.user_id == user.id))]
            locs = [s.get(Local, i) for i in ids]
        return {"id": user.id, "username": user.username, "role": user.role, "rol_dia": getattr(user, "rol_dia", None), "permisos": permisos.efectius(user), "te_carnet": s.get(UserCard, user.id) is not None,
                "pot_reemborsar": user.role in ("admin", "encarregat") or user.pot_reemborsar,
                "pot_editar_descomptes": user.role in ("admin", "encarregat") or user.pot_editar_descomptes,
                "locals": [{"id": l.id, "nom": l.nom, "limit_diari_mg": l.limit_diari_mg,
                            "limit_mensual_mg": l.limit_mensual_mg,
                            "tolerancia_bascula_mg": l.tolerancia_bascula_mg, **ajustos.get(s, l.id)} for l in locs]}

    @app.post("/auth/logout")
    def logout(authorization: str = Header(default=""), s: Session = Depends(db)):
        import hashlib
        from ..models import SessionToken
        _, _, token = authorization.partition(" ")
        row = s.get(SessionToken, hashlib.sha256(token.encode()).hexdigest()) if token else None
        if row:
            s.delete(row)
            s.commit()
        return {"ok": True}

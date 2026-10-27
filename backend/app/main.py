from datetime import date
from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import service
from .db import make_engine, make_session_factory
from .models import Member, User, UserLocal

CAN_CREATE_MEMBER = {"admin", "encarregat"}


def get_db_factory():
    engine = make_engine()
    return make_session_factory(engine)


def create_app(session_factory=None) -> FastAPI:
    app = FastAPI(title="club-gestio")
    factory = session_factory or get_db_factory()

    def db():
        s = factory()
        try:
            yield s
        finally:
            s.close()

    def current_user(authorization: str = Header(default=""), s: Session = Depends(db)) -> User:
        scheme, _, token = authorization.partition(" ")
        user = service.user_from_token(s, token) if scheme.lower() == "bearer" and token else None
        if not user:
            raise HTTPException(401, "No autenticat")
        return user

    def check_local(s: Session, user: User, local_id: int) -> None:
        if user.role == "admin":
            return
        if not s.get(UserLocal, (user.id, local_id)):
            raise HTTPException(403, "Sense accés a aquest local")

    class LoginIn(BaseModel):
        username: str
        password: str
        totp: str

    class MemberIn(BaseModel):
        local_id: int
        nom: str = Field(min_length=2, max_length=120)
        document: str = Field(min_length=5, max_length=30)
        naixement: date
        telefon: str | None = None
        email: str | None = None

    @app.post("/auth/login")
    def login(body: LoginIn, s: Session = Depends(db)):
        token = service.login(s, body.username, body.password, body.totp)
        if not token:
            raise HTTPException(401, "Credencials incorrectes")
        return {"token": token}

    @app.post("/socis", status_code=201)
    def alta_soci(body: MemberIn, user: User = Depends(current_user), s: Session = Depends(db)):
        if user.role not in CAN_CREATE_MEMBER:
            raise HTTPException(403, "El teu rol no pot donar d'alta socis")
        check_local(s, user, body.local_id)
        try:
            m = service.create_member(s, user, body.local_id, body.nom, body.document,
                                      body.naixement, body.telefon, body.email)
        except ValueError as e:
            raise HTTPException(422, str(e))
        return {"id": m.id}

    @app.get("/socis/{member_id}")
    def veure_soci(member_id: int, user: User = Depends(current_user), s: Session = Depends(db)):
        m = s.get(Member, member_id)
        if not m:
            raise HTTPException(404, "No existeix")
        check_local(s, user, m.local_id)
        service.audit_append(s, {"accio": "consulta_soci", "soci": m.id, "per": user.id})
        s.commit()
        return service.member_view(m)

    @app.get("/auditoria/verificar")
    def verificar(user: User = Depends(current_user), s: Session = Depends(db)):
        if user.role != "admin":
            raise HTTPException(403, "Només administradors")
        ok, seq = service.audit_verify(s)
        return {"integra": ok, "primera_alterada": seq}

    return app

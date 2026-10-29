"""Entrada al programa amb carnet RFID per als treballadors (canvis de lloc de feina ràpids, sense escriure).

Seguretat: un carnet RFID només identifica; no és un segon factor. Per això els administradors queden exclosos (entren
sempre amb contrasenya), els intents fallits bloquegen l'entrada amb carnet uns minuts i tot queda a l'auditoria."""
import hashlib
import os
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from . import service, socis
from .models import LoginAttempt, MemberCard, SessionToken, User, UserCard

KEY_BLOQUEIG = "#carnet"  # clau dels intents fallits (no pot coincidir amb cap nom d'usuari)
MAX_INTENTS = 10


def enabled() -> bool:
    return os.environ.get("CLUB_LOGIN_CARNET", "1") != "0"


def assign(db: Session, actor: User, user: User, codi: str) -> None:
    if user.role == "admin":
        raise ValueError("Els administradors entren sempre amb contrasenya: no poden tenir carnet d'entrada")
    idx = socis.card_index(codi)  # valida el format (4 a 64 caràcters)
    altre = db.scalar(select(UserCard).where(UserCard.code_idx == idx, UserCard.user_id != user.id))
    if altre or db.scalar(select(MemberCard.id).where(MemberCard.code_idx == idx)):
        raise ValueError("Aquest carnet ja està assignat a un altre usuari o a un soci")
    fila = db.get(UserCard, user.id)
    if fila:
        fila.code_idx, fila.creat_per = idx, actor.id
    else:
        db.add(UserCard(user_id=user.id, code_idx=idx, creat_per=actor.id))
    service.audit_append(db, {"accio": "assigna_carnet_usuari", "usuari": user.id, "per": actor.id})
    db.commit()


def remove(db: Session, actor: User, user: User) -> bool:
    fila = db.get(UserCard, user.id)
    if not fila:
        return False
    db.delete(fila)
    service.audit_append(db, {"accio": "retira_carnet_usuari", "usuari": user.id, "per": actor.id})
    db.commit()
    return True


def login(db: Session, codi: str) -> str | None:
    """Torna un token de sessió o None. Llança LoginLocked si hi ha massa intents fallits recents."""
    ara = datetime.now(timezone.utc)
    desde = ara - timedelta(minutes=service.LOCKOUT_MINUTES)
    db.execute(delete(LoginAttempt).where(LoginAttempt.ts < desde))
    fallits = db.scalar(select(func.count()).select_from(LoginAttempt).where(LoginAttempt.username == KEY_BLOQUEIG, LoginAttempt.ts >= desde))
    if fallits >= MAX_INTENTS:
        db.commit()
        raise service.LoginLocked()
    user = None
    try:
        idx = socis.card_index(codi)
        fila = db.scalar(select(UserCard).where(UserCard.code_idx == idx))
        user = db.get(User, fila.user_id) if fila else None
    except ValueError:
        pass
    if not user or not user.active or user.role == "admin":
        db.add(LoginAttempt(username=KEY_BLOQUEIG))
        db.commit()
        return None
    token = secrets.token_urlsafe(32)
    db.add(SessionToken(token_hash=hashlib.sha256(token.encode()).hexdigest(), user_id=user.id,
                        expires_at=ara + timedelta(hours=service.SESSION_HOURS)))
    service.audit_append(db, {"accio": "login", "usuari": user.username, "metode": "carnet", "ok": True})
    db.commit()
    return token

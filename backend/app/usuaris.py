"""Administració d'usuaris: llistat, activar/desactivar, rol, locals, contrasenya i TOTP."""
import hashlib

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from . import crypto, security, service
from .models import Local, SessionToken, User, UserLocal


def _local_ids(db: Session, user_id: int) -> list[int]:
    return sorted(db.scalars(select(UserLocal.local_id).where(UserLocal.user_id == user_id)))


def list_users(db: Session) -> list[dict]:
    return [{"id": u.id, "username": u.username, "role": u.role, "active": u.active, "local_ids": _local_ids(db, u.id)}
            for u in db.scalars(select(User).order_by(User.username))]


def _close_sessions(db: Session, user_id: int, keep_hash: str | None = None) -> None:
    q = delete(SessionToken).where(SessionToken.user_id == user_id)
    if keep_hash:
        q = q.where(SessionToken.token_hash != keep_hash)
    db.execute(q)


def update_user(db: Session, actor: User, user: User, active: bool | None = None, role: str | None = None,
                local_ids: list[int] | None = None) -> None:
    if active is None and role is None and local_ids is None:
        raise ValueError("No hi ha cap canvi")
    if role is not None and role not in service.ROLS:
        raise ValueError("Rol no vàlid")
    if local_ids is not None:
        local_ids = sorted(set(local_ids))
        for lid in local_ids:
            if not db.get(Local, lid):
                raise ValueError(f"El local {lid} no existeix")
    perd_admin = user.role == "admin" and user.active and (active is False or (role is not None and role != "admin"))
    if user.id == actor.id and (active is False or (role is not None and role != user.role)):
        raise ValueError("No et pots desactivar ni canviar el rol a tu mateix")
    if perd_admin:
        altres = db.scalar(select(func.count()).select_from(User).where(User.role == "admin", User.active.is_(True), User.id != user.id))
        if altres == 0:
            raise ValueError("Ha de quedar almenys un administrador actiu")
    canvis = {}
    if active is not None and active != user.active:
        canvis["active"] = [user.active, active]
        user.active = active
    if role is not None and role != user.role:
        canvis["role"] = [user.role, role]
        user.role = role
    if local_ids is not None and local_ids != _local_ids(db, user.id):
        canvis["local_ids"] = [_local_ids(db, user.id), local_ids]
        db.execute(delete(UserLocal).where(UserLocal.user_id == user.id))
        for lid in local_ids:
            db.add(UserLocal(user_id=user.id, local_id=lid))
    if not canvis:
        raise ValueError("No hi ha cap canvi")
    if "active" in canvis or "role" in canvis or "local_ids" in canvis:
        _close_sessions(db, user.id)  # els permisos nous s'apliquen a la propera entrada
    service.audit_append(db, {"accio": "edita_usuari", "usuari": user.id, "canvis": canvis, "per": actor.id})
    db.commit()


def reset_totp(db: Session, actor: User, user: User) -> str:
    """Genera un secret TOTP nou (el vell deixa de servir) i tanca les sessions de l'usuari. Només es retorna ara."""
    secret = security.new_totp_secret()
    user.totp_secret_enc = crypto.encrypt(secret)
    _close_sessions(db, user.id)
    service.audit_append(db, {"accio": "reinicia_totp", "usuari": user.id, "per": actor.id})
    db.commit()
    return secret


def set_password(db: Session, actor: User, user: User, password: str) -> None:
    user.password_hash = security.hash_password(password)  # ValueError si és massa curta
    _close_sessions(db, user.id)
    service.audit_append(db, {"accio": "canvia_contrasenya_usuari", "usuari": user.id, "per": actor.id})
    db.commit()


def change_own_password(db: Session, user: User, current: str, new: str, token: str) -> None:
    service.assert_not_locked(db, user.username)  # amb un token robat no es poden provar contrasenyes sense límit
    if not security.verify_password(current, user.password_hash):
        service.register_failure(db, user.username)
        db.commit()
        raise PermissionError("La contrasenya actual no és correcta")
    service.clear_failures(db, user.username)
    if new == current:
        raise ValueError("La contrasenya nova ha de ser diferent de l'actual")
    user.password_hash = security.hash_password(new)
    _close_sessions(db, user.id, keep_hash=hashlib.sha256(token.encode()).hexdigest())  # tanca les altres sessions
    service.audit_append(db, {"accio": "canvia_contrasenya", "usuari": user.id, "per": user.id})
    db.commit()

"""Entrada al programa amb carnet RFID + PIN per als treballadors (canvis de lloc de feina ràpids, sense escriure usuari).

Seguretat en capes:
  1. El carnet és «alguna cosa que tens» i el PIN, «alguna cosa que saps»: un carnet perdut o copiat no obre cap sessió.
  2. Només s'admeten carnets generats pel programa (codi llarg i imprevisible amb dígit de control), mai l'UID del xip.
  3. El PIN es desa com Argon2 d'un HMAC (pebre = CLUB_INDEX_KEY): una còpia de la base de dades no permet provar PIN fora de línia.
  4. Bloqueig per usuari després de 5 PIN erronis en 15 minuts i límit global d'intents amb carnets desconeguts.
  5. Els administradors queden exclosos (entren sempre amb contrasenya) i tot queda a l'auditoria.
  6. Opcional: només des de les xarxes del club (CLUB_CARNET_XARXES, p. ex. 192.168.1.0/24)."""
import hashlib
import hmac
import ipaddress
import os
import re
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from . import security, service, socis
from .models import LoginAttempt, MemberCard, SessionToken, User, UserCard

KEY_DESCONEGUTS = "#carnet"          # intents amb carnets que no existeixen (no pot coincidir amb cap nom d'usuari)
MAX_DESCONEGUTS = 30
MAX_PIN_ERRONIS = 5
PIN_RE = re.compile(r"\d{4,8}")


def enabled() -> bool:
    return os.environ.get("CLUB_LOGIN_CARNET", "1") != "0"


# ---------- xarxa permesa ----------

def network_allowed(ip: str | None) -> bool:
    """Sense CLUB_CARNET_XARXES no hi ha restricció. Amb ella, només s'accepta una IP dins d'alguna de les xarxes (CIDR)."""
    xarxes = [x.strip() for x in os.environ.get("CLUB_CARNET_XARXES", "").split(",") if x.strip()]
    if not xarxes:
        return True
    try:
        adr = ipaddress.ip_address(ip or "")
    except ValueError:
        return False
    return any(adr in ipaddress.ip_network(x, strict=False) for x in xarxes)


def client_ip(client_host: str | None, forwarded_for: str | None) -> str | None:
    """IP del client. Només es fa cas de X-Forwarded-For amb CLUB_TRUST_PROXY=1 (darrere nginx), i només de l'última entrada,
    que és la que afegeix el nostre proxy; les anteriors les pot falsificar el client."""
    if os.environ.get("CLUB_TRUST_PROXY") == "1" and forwarded_for:
        return forwarded_for.split(",")[-1].strip()
    return client_host


# ---------- PIN ----------

def validate_pin(pin: str) -> None:
    if not isinstance(pin, str) or not PIN_RE.fullmatch(pin):
        raise ValueError("El PIN ha de tenir de 4 a 8 xifres")
    if len(set(pin)) == 1:
        raise ValueError("El PIN és massa fàcil (xifres repetides)")
    digits = [int(c) for c in pin]
    passos = {b - a for a, b in zip(digits, digits[1:])}
    if passos in ({1}, {-1}):
        raise ValueError("El PIN és massa fàcil (seqüència)")


def _pin_digest(user_id: int, pin: str) -> str:
    return hmac.new(service._index_key(), f"PIN|{user_id}|{pin}".encode(), hashlib.sha256).hexdigest()


def _hash_pin(user_id: int, pin: str) -> str:
    return security.hash_secret(_pin_digest(user_id, pin))


def _pin_ok(user_id: int, pin: str, pin_hash: str | None) -> bool:
    """Sempre fa la comprovació Argon2 (amb un hash de mentida si no n'hi ha) perquè el temps no delati res."""
    return security.verify_password(_pin_digest(user_id, pin or ""), pin_hash or security.dummy_hash()) and bool(pin_hash)


# ---------- gestió (administrador) ----------

def _usable(db: Session, user: User, idx: str) -> None:
    if user.role == "admin":
        raise ValueError("Els administradors entren sempre amb contrasenya: no poden tenir carnet d'entrada")
    altre = db.scalar(select(UserCard).where(UserCard.code_idx == idx, UserCard.user_id != user.id))
    if altre or db.scalar(select(MemberCard.id).where(MemberCard.code_idx == idx)):
        raise ValueError("Aquest carnet ja està assignat a un altre usuari o a un soci")


def assign(db: Session, actor: User, user: User, codi: str, pin: str) -> None:
    if not socis.card_code_valid(codi.strip().upper()):
        raise ValueError("Per seguretat només s'admeten carnets generats pel programa (codi llarg amb dígit de control): "
                         "genera'n un de nou en lloc de fer servir el codi d'un xip qualsevol")
    validate_pin(pin)
    idx = socis.card_index(codi)
    _usable(db, user, idx)
    pin_hash = _hash_pin(user.id, pin)
    fila = db.get(UserCard, user.id)
    if fila:
        fila.code_idx, fila.pin_hash, fila.creat_per = idx, pin_hash, actor.id
    else:
        db.add(UserCard(user_id=user.id, code_idx=idx, pin_hash=pin_hash, creat_per=actor.id))
    _reinicia_bloqueig(db, user.id)
    service.audit_append(db, {"accio": "assigna_carnet_usuari", "usuari": user.id, "per": actor.id})
    db.commit()


def generate(db: Session, actor: User, user: User, pin: str, prefix: str = "STF") -> str:
    """Genera un carnet nou (substitueix l'anterior) i el torna UNA sola vegada: a la base de dades només queda l'empremta."""
    for _ in range(5):
        codi = socis.generate_card_code(prefix)
        try:
            assign(db, actor, user, codi, pin)
            return codi
        except ValueError as e:
            db.rollback()
            if "PIN" in str(e) or "administradors" in str(e):
                raise
    raise ValueError("No s'ha pogut generar un carnet únic")


def remove(db: Session, actor: User, user: User) -> bool:
    fila = db.get(UserCard, user.id)
    if not fila:
        return False
    db.delete(fila)
    _reinicia_bloqueig(db, user.id)
    service.audit_append(db, {"accio": "retira_carnet_usuari", "usuari": user.id, "per": actor.id})
    db.commit()
    return True


def change_pin(db: Session, user: User, actual: str, nova: str) -> None:
    fila = db.get(UserCard, user.id)
    if not fila:
        raise ValueError("No tens cap carnet d'entrada")
    if not _pin_ok(user.id, actual, fila.pin_hash):
        raise ValueError("El PIN actual no és correcte")
    validate_pin(nova)
    fila.pin_hash = _hash_pin(user.id, nova)
    service.audit_append(db, {"accio": "canvia_pin_carnet", "usuari": user.id, "per": user.id})
    db.commit()


# ---------- entrada ----------

def _clau(user_id: int) -> str:
    return f"#carnet:{user_id}"


def _reinicia_bloqueig(db: Session, user_id: int) -> None:
    db.execute(delete(LoginAttempt).where(LoginAttempt.username == _clau(user_id)))


def _fallits(db: Session, clau: str, desde: datetime) -> int:
    return db.scalar(select(func.count()).select_from(LoginAttempt).where(LoginAttempt.username == clau, LoginAttempt.ts >= desde))


def login(db: Session, codi: str, pin: str) -> str | None:
    """Torna un token de sessió o None. Llança LoginLocked si hi ha massa intents fallits (de l'usuari o amb carnets desconeguts)."""
    ara = datetime.now(timezone.utc)
    desde = ara - timedelta(minutes=service.LOCKOUT_MINUTES)
    db.execute(delete(LoginAttempt).where(LoginAttempt.ts < desde))
    if _fallits(db, KEY_DESCONEGUTS, desde) >= MAX_DESCONEGUTS:
        db.commit()
        raise service.LoginLocked()
    fila = user = None
    try:
        fila = db.scalar(select(UserCard).where(UserCard.code_idx == socis.card_index(codi)))
        user = db.get(User, fila.user_id) if fila else None
    except ValueError:
        pass
    if not user:
        _pin_ok(0, pin or "", None)  # mateixa feina que amb un usuari real
        db.add(LoginAttempt(username=KEY_DESCONEGUTS))
        db.commit()
        return None
    clau = _clau(user.id)
    fallits = _fallits(db, clau, desde)
    if fallits >= MAX_PIN_ERRONIS:
        if fallits == MAX_PIN_ERRONIS:  # només s'audita el moment del bloqueig: un anònim no pot inflar l'auditoria
            service.audit_append(db, {"accio": "carnet_bloquejat", "usuari": user.username})
            db.add(LoginAttempt(username=clau))
        db.commit()
        raise service.LoginLocked()
    bo = _pin_ok(user.id, pin or "", fila.pin_hash) and user.active and user.role != "admin"
    if not bo:
        db.add(LoginAttempt(username=clau))
        db.commit()
        return None
    _reinicia_bloqueig(db, user.id)
    token = secrets.token_urlsafe(32)
    db.add(SessionToken(token_hash=hashlib.sha256(token.encode()).hexdigest(), user_id=user.id,
                        expires_at=ara + timedelta(hours=service.SESSION_HOURS)))
    service.audit_append(db, {"accio": "login", "usuari": user.username, "metode": "carnet+pin", "ok": True})
    db.commit()
    return token

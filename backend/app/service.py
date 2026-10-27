import hashlib
import hmac
import json
import os
import secrets
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import audit, crypto, security
from .models import AuditLog, Member, SessionToken, User

SESSION_HOURS = 8
MAJORIA_EDAT = 18


def _canon(payload: dict) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def audit_append(db: Session, payload: dict) -> AuditLog:
    last = db.scalar(select(AuditLog).order_by(AuditLog.seq.desc()).limit(1))
    prev = last.hash if last else audit.GENESIS
    h = audit._digest(prev, payload)
    row = AuditLog(payload=_canon(payload), prev_hash=prev, hash=h)
    db.add(row)
    db.flush()
    return row


def audit_verify(db: Session) -> tuple[bool, int | None]:
    chain = [
        audit.Entry(r.seq, json.loads(r.payload), r.prev_hash, r.hash)
        for r in db.scalars(select(AuditLog).order_by(AuditLog.seq))
    ]
    # seq pot tenir forats si s'han esborrat files: la cadena de hash ho detecta igualment
    prev = audit.GENESIS
    for e in chain:
        if e.prev_hash != prev or e.hash != audit._digest(prev, e.payload):
            return False, e.seq
        prev = e.hash
    return True, None


def _index_key() -> bytes:
    key = os.environ.get("CLUB_INDEX_KEY")
    if not key:
        raise RuntimeError("Falta CLUB_INDEX_KEY")
    return key.encode()


def document_index(document: str) -> str:
    norm = "".join(document.split()).upper()
    return hmac.new(_index_key(), norm.encode(), hashlib.sha256).hexdigest()


def login(db: Session, username: str, password: str, totp: str) -> str | None:
    user = db.scalar(select(User).where(User.username == username, User.active.is_(True)))
    ok = bool(user) and security.verify_password(password, user.password_hash)
    ok = ok and security.verify_totp(crypto.decrypt(user.totp_secret_enc), totp)
    audit_append(db, {"accio": "login", "usuari": username, "ok": ok})
    if not ok:
        db.commit()
        return None
    token = secrets.token_urlsafe(32)
    db.add(SessionToken(
        token_hash=hashlib.sha256(token.encode()).hexdigest(),
        user_id=user.id,
        expires_at=datetime.now(timezone.utc) + timedelta(hours=SESSION_HOURS),
    ))
    db.commit()
    return token


def user_from_token(db: Session, token: str) -> User | None:
    s = db.get(SessionToken, hashlib.sha256(token.encode()).hexdigest())
    if not s:
        return None
    exp = s.expires_at if s.expires_at.tzinfo else s.expires_at.replace(tzinfo=timezone.utc)
    if exp < datetime.now(timezone.utc):
        return None
    u = db.get(User, s.user_id)
    return u if u and u.active else None


def create_member(db: Session, actor: User, local_id: int, nom: str, document: str,
                  naixement: date, telefon: str | None, email: str | None) -> Member:
    avui = date.today()
    edat = avui.year - naixement.year - ((avui.month, avui.day) < (naixement.month, naixement.day))
    if edat < MAJORIA_EDAT:
        raise ValueError("El soci ha de ser major d'edat")
    idx = document_index(document)
    if db.scalar(select(Member).where(Member.local_id == local_id, Member.document_idx == idx)):
        raise ValueError("Ja existeix un soci amb aquest document en aquest local")
    m = Member(
        local_id=local_id, nom_enc=crypto.encrypt(nom), document_enc=crypto.encrypt(document),
        document_idx=idx, naixement_enc=crypto.encrypt(naixement.isoformat()),
        telefon_enc=crypto.encrypt(telefon), email_enc=crypto.encrypt(email), creat_per=actor.id,
    )
    db.add(m)
    db.flush()
    audit_append(db, {"accio": "alta_soci", "soci": m.id, "local": local_id, "per": actor.id})
    db.commit()
    return m


def member_view(m: Member) -> dict:
    return {
        "id": m.id, "local_id": m.local_id, "nom": crypto.decrypt(m.nom_enc),
        "document": crypto.decrypt(m.document_enc), "naixement": crypto.decrypt(m.naixement_enc),
        "telefon": crypto.decrypt(m.telefon_enc), "email": crypto.decrypt(m.email_enc), "estat": m.estat,
    }


ESTATS = {"actiu", "suspes", "baixa"}


def set_member_status(db: Session, actor: User, member: Member, estat: str) -> None:
    if estat not in ESTATS:
        raise ValueError("Estat no vàlid")
    if member.estat == estat:
        raise ValueError("El soci ja té aquest estat")
    if member.estat == "baixa" and actor.role != "admin":
        raise ValueError("Només un administrador pot reactivar un soci de baixa")
    anterior, member.estat = member.estat, estat
    audit_append(db, {"accio": "canvi_estat_soci", "soci": member.id, "de": anterior, "a": estat, "per": actor.id})
    db.commit()


def check_in(db: Session, actor: User, member: Member):
    from .models import CheckIn
    if member.estat != "actiu":
        raise ValueError("El soci no està actiu")
    c = CheckIn(local_id=member.local_id, member_id=member.id, user_id=actor.id)
    db.add(c)
    db.flush()
    audit_append(db, {"accio": "entrada_soci", "soci": member.id, "per": actor.id})
    db.commit()
    return c


def find_member_by_document(db: Session, local_id: int, document: str) -> Member | None:
    return db.scalar(select(Member).where(Member.local_id == local_id, Member.document_idx == document_index(document)))


def create_local(db: Session, actor: User, nom: str):
    from .models import Local
    if db.scalar(select(Local).where(Local.nom == nom)):
        raise ValueError("Ja existeix un local amb aquest nom")
    loc = Local(nom=nom)
    db.add(loc)
    db.flush()
    audit_append(db, {"accio": "alta_local", "local": loc.id, "per": actor.id})
    db.commit()
    return loc


ROLS = {"admin", "encarregat", "dispensador"}


def create_user(db: Session, actor: User | None, username: str, password: str, role: str, local_ids: list[int]):
    """Retorna (usuari, secret TOTP en clar). El secret només es mostra en crear-lo."""
    from .models import Local, UserLocal
    if role not in ROLS:
        raise ValueError("Rol no vàlid")
    if db.scalar(select(User).where(User.username == username)):
        raise ValueError("Aquest nom d'usuari ja existeix")
    for lid in local_ids:
        if not db.get(Local, lid):
            raise ValueError(f"El local {lid} no existeix")
    secret = security.new_totp_secret()
    u = User(username=username, password_hash=security.hash_password(password),
             totp_secret_enc=crypto.encrypt(secret), role=role)
    db.add(u)
    db.flush()
    for lid in local_ids:
        db.add(UserLocal(user_id=u.id, local_id=lid))
    audit_append(db, {"accio": "alta_usuari", "usuari": u.id, "rol": role, "per": actor.id if actor else None})
    db.commit()
    return u, secret

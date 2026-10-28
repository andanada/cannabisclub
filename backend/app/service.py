import hashlib
import hmac
import json
import os
import re
import secrets
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import delete, func, select, text
from sqlalchemy.orm import Session

from . import audit, crypto, security
from .models import AuditLog, Member, SessionToken, User

SESSION_HOURS = 8
MAJORIA_EDAT = 18


def _canon(payload: dict) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


AUDIT_LOCK_KEY = 7_203_411  # clau arbitrària de l'«advisory lock» que serialitza la cadena d'auditoria


def audit_append(db: Session, payload: dict) -> AuditLog:
    if db.get_bind().dialect.name == "postgresql":
        # Sense això, dues transaccions simultànies llegirien el mateix «últim hash» i la cadena es bifurcaria
        # (la verificació la donaria per alterada). El bloqueig dura fins al commit i només afecta a l'auditoria.
        db.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": AUDIT_LOCK_KEY})
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


MAX_FAILED_LOGINS = 5
LOCKOUT_MINUTES = 15


class LoginLocked(Exception):
    """Massa intents fallits: el nom d'usuari queda bloquejat uns minuts."""


def assert_not_locked(db: Session, key: str) -> None:
    """Llança LoginLocked si el nom ha acumulat massa intents fallits recents (sense auditar: no es pot inflar des de fora)."""
    from .models import LoginAttempt
    since = datetime.now(timezone.utc) - timedelta(minutes=LOCKOUT_MINUTES)
    fails = db.scalar(select(func.count()).select_from(LoginAttempt).where(LoginAttempt.username == key[:60], LoginAttempt.ts >= since))
    if fails >= MAX_FAILED_LOGINS:
        raise LoginLocked()


def register_failure(db: Session, key: str) -> None:
    from .models import LoginAttempt
    db.add(LoginAttempt(username=key[:60]))


def clear_failures(db: Session, key: str) -> int:
    from .models import LoginAttempt
    return db.execute(delete(LoginAttempt).where(LoginAttempt.username == key[:60])).rowcount or 0


def login(db: Session, username: str, password: str, totp: str) -> str | None:
    from .models import LoginAttempt
    key = username[:60]
    since = datetime.now(timezone.utc) - timedelta(minutes=LOCKOUT_MINUTES)
    db.execute(delete(LoginAttempt).where(LoginAttempt.ts < since))  # esborra els intents ja caducats
    fails = db.scalar(select(func.count()).select_from(LoginAttempt).where(LoginAttempt.username == key, LoginAttempt.ts >= since))
    if fails >= MAX_FAILED_LOGINS:
        # Es bloqueja abans de comprovar res i també per a noms inexistents: així no es revela si un usuari existeix.
        # Només s'audita el moment en què es bloqueja: si no, qualsevol anònim podria inflar l'auditoria (només d'afegir).
        if fails == MAX_FAILED_LOGINS:
            audit_append(db, {"accio": "login_bloquejat", "usuari": key})
            db.add(LoginAttempt(username=key))  # el següent intent ja no torna a auditar
            db.commit()
        raise LoginLocked()
    user = db.scalar(select(User).where(User.username == username, User.active.is_(True)))
    # Sempre es calcula un hash, existeixi o no l'usuari, perquè el temps de resposta no delati els noms d'usuari.
    ok = security.verify_password(password, user.password_hash if user else security.dummy_hash())
    ok = bool(user) and ok
    ok = ok and security.verify_totp(crypto.decrypt(user.totp_secret_enc), totp)
    audit_append(db, {"accio": "login", "usuari": key, "ok": ok})
    if not ok:
        db.add(LoginAttempt(username=key))
        db.commit()
        return None
    db.execute(delete(LoginAttempt).where(LoginAttempt.username == key))  # un accés correcte reinicia el compte
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


LLETRES_DNI = "TRWAGMYFPDXBNJZSQVHLCKE"


def validate_document(document: str) -> None:
    """DNI (8 xifres + lletra) i NIE (X/Y/Z + 7 xifres + lletra) es comproven amb la lletra de control;
    qualsevol altre document (passaport…) ha de tenir 5 a 20 lletres o xifres."""
    doc = "".join(document.split()).upper()
    if re.fullmatch(r"\d{8}[A-Z]", doc):
        numero = int(doc[:8])
    elif re.fullmatch(r"[XYZ]\d{7}[A-Z]", doc):
        numero = int(str("XYZ".index(doc[0])) + doc[1:8])
    elif re.fullmatch(r"[A-Z0-9]{5,20}", doc):
        return
    else:
        raise ValueError("El document no és vàlid (DNI, NIE o passaport: només lletres i xifres)")
    if LLETRES_DNI[numero % 23] != doc[8]:
        raise ValueError("La lletra de control del document no és correcta")


def create_member(db: Session, actor: User, local_id: int, nom: str, document: str,
                  naixement: date, telefon: str | None, email: str | None) -> Member:
    validate_document(document)
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


MAX_SIGNATURE_BYTES = 200_000
MIN_SIGNATURE_BYTES = 400  # un llenç buit queda per sota d'aquest mida
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def _signature_hash(png: bytes, member_id: int, ts_iso: str) -> str:
    return hashlib.sha256(png + f"|{member_id}|{ts_iso}".encode()).hexdigest()


def save_signature(db: Session, actor: User, member: Member, png_b64: str):
    import base64
    import binascii
    from .models import Signature, now as _now
    try:
        png = base64.b64decode(png_b64, validate=True)
    except (binascii.Error, ValueError):
        raise ValueError("La signatura no és vàlida")
    if not png.startswith(PNG_MAGIC):
        raise ValueError("La signatura ha de ser una imatge PNG")
    if len(png) > MAX_SIGNATURE_BYTES:
        raise ValueError("La signatura és massa gran")
    if len(png) < MIN_SIGNATURE_BYTES:
        raise ValueError("La signatura està buida")
    ts = _now()
    sig = Signature(member_id=member.id, user_id=actor.id, ts=ts, png_enc=crypto.encrypt(png_b64),
                    sha256=_signature_hash(png, member.id, ts.isoformat()))
    db.add(sig)
    db.flush()
    audit_append(db, {"accio": "signatura_alta", "soci": member.id, "signatura": sig.id, "sha256": sig.sha256, "per": actor.id})
    db.commit()
    return sig


def read_signature(db: Session, actor: User, member: Member) -> dict | None:
    from .models import Signature
    sig = db.scalar(select(Signature).where(Signature.member_id == member.id).order_by(Signature.id.desc()).limit(1))
    if not sig:
        return None
    png_b64 = crypto.decrypt(sig.png_enc)
    import base64
    from .models import Signature as _S  # noqa: F401
    ok = _signature_hash(base64.b64decode(png_b64), member.id, sig.ts.replace(tzinfo=sig.ts.tzinfo or timezone.utc).isoformat()) == sig.sha256
    audit_append(db, {"accio": "consulta_signatura", "soci": member.id, "per": actor.id})
    db.commit()
    return {"id": sig.id, "ts": sig.ts.isoformat(), "sha256": sig.sha256, "hash_valid": ok, "png_base64": png_b64}

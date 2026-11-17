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
from .models import AuditAnchor, AuditLog, Member, SessionToken, User

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
    signat = {**payload, audit.ALG_KEY: audit.ALG_HMAC}  # entrades noves: HMAC (vegeu el docstring d'audit.py)
    h = audit.digest_h1(prev, signat)
    row = AuditLog(payload=_canon(signat), prev_hash=prev, hash=h, alg=audit.ALG_HMAC)
    db.add(row)
    db.flush()
    return row


def audit_anchor(db: Session) -> dict | None:
    """Últim seq i hash de la cadena: cal guardar-los FORA d'aquest equip (paper, un altre servidor, correu). Després
    audit_verify(anchor=...) detecta que s'hagi retallat el final o refet la cadena. None si encara és buida."""
    last = db.scalar(select(AuditLog).order_by(AuditLog.seq.desc()).limit(1))
    return {"seq": last.seq, "hash": last.hash} if last else None


def _anchor_sig(seq: int, h: str, key: bytes | None = None) -> str:
    return hmac.new(key or audit.audit_key(), f"club-anchor|{seq}|{h}".encode(), hashlib.sha256).hexdigest()


def audit_anchor_save(db: Session, origen: str = "manual") -> AuditAnchor | None:
    """Desa l'ancoratge actual (últim seq + hash) a la taula audit_anchors (només d'afegir). audit_verify el comprova:
    retallar el final de la cadena o refer-la passa a ser detectable també sense ancoratge extern. No substitueix
    l'ancoratge FORA de l'equip (qui controla la BD podria refer cadena i taula d'ancoratges si és propietari)."""
    a = audit_anchor(db)
    if not a:
        return None
    row = AuditAnchor(seq=a["seq"], hash=a["hash"], origen=origen[:40], sig=_anchor_sig(a["seq"], a["hash"]))
    db.add(row)
    db.flush()
    return row


def _hmac_des_de() -> int | None:
    v = os.environ.get("CLUB_AUDIT_HMAC_DES_DE", "").strip()
    return int(v) if v.isdigit() else None


def audit_verify_detail(db: Session, anchor: dict | None = None, batch: int = 1000) -> dict:
    """Verifica la cadena per lots (paginació per seq: memòria constant). Retorna un diccionari amb `integra`,
    `primera_alterada`, `ultim_seq`, `ultim_hash`, `entrades` i `avisos` (p. ex. «sense_ancoratge»).
    L'ancoratge és {"seq": n, "hash": h}: l'entrada n ha d'existir amb aquest hash i la cadena no pot acabar abans."""
    key = audit.audit_key()
    tall = _hmac_des_de()
    prev, ultim_seq, n, vist_h1, ancora_vista, vist_alg = audit.GENESIS, 0, 0, False, False, False
    # ancoratges desats a la BD: només els signats amb HMAC de la clau d'auditoria (els altres es poden haver forjat; s'ignoren)
    interns = {q: h for q, h, sg in db.execute(select(AuditAnchor.seq, AuditAnchor.hash, AuditAnchor.sig)).all()
               if sg and hmac.compare_digest(sg, _anchor_sig(q, h, key))}
    avisos: list[str] = []

    def res(ok, seq):
        return {"integra": ok, "primera_alterada": seq, "ultim_seq": ultim_seq, "ultim_hash": prev, "entrades": n, "avisos": avisos}

    cursor = 0
    while True:
        files = db.execute(select(AuditLog.seq, AuditLog.payload, AuditLog.prev_hash, AuditLog.hash, AuditLog.alg)
                           .where(AuditLog.seq > cursor).order_by(AuditLog.seq).limit(batch)).all()
        if not files:
            break
        for seq, payload_txt, prev_hash, h, alg in files:
            payload = json.loads(payload_txt)
            h1 = audit.is_h1(payload)
            # seq pot tenir forats si s'han esborrat files: la cadena de hash ho detecta igualment
            degradada = (vist_h1 and not h1) or (tall is not None and seq >= tall and not h1)
            # columna alg: si hi és ha de coincidir amb el payload, i un cop vista no pot desaparèixer (entrades antigues: NULL)
            alg_dolent = (alg is not None and (alg == audit.ALG_HMAC) != h1) or (vist_alg and alg is None)
            if prev_hash != prev or degradada or alg_dolent or h != audit.expected_hash(prev, payload, key):
                return res(False, seq)
            if seq in interns and interns[seq] != h:
                return res(False, seq)
            vist_h1 = vist_h1 or h1
            vist_alg = vist_alg or alg is not None
            if anchor and seq == anchor["seq"]:
                if h != anchor["hash"]:
                    return res(False, seq)
                ancora_vista = True
            prev, ultim_seq, n, cursor = h, seq, n + 1, seq
    if interns and max(interns) > ultim_seq:  # la cadena acaba abans d'un ancoratge intern: retallada
        return res(False, ultim_seq + 1)
    if anchor:
        if not ancora_vista:  # la cadena acaba abans de l'ancoratge (retallada) o l'entrada ancorada ha desaparegut
            return res(False, ultim_seq + 1 if ultim_seq < anchor["seq"] else anchor["seq"])
    else:
        avisos.append("ancoratge_intern" if interns else "sense_ancoratge")
    if n and not vist_h1:
        avisos.append("sense_hmac")
    return res(True, None)


def audit_verify(db: Session, anchor: dict | None = None) -> tuple[bool, int | None]:
    d = audit_verify_detail(db, anchor)
    return d["integra"], d["primera_alterada"]


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


def register_attempt(db: Session, key: str, maxim: int = MAX_FAILED_LOGINS) -> int:
    """Registra l'intent i el confirma ABANS de verificar res; llança LoginLocked si ja n'hi ha més de `maxim` en la
    finestra. Així les peticions en paral·lel es veuen entre elles (el patró comprovar→verificar→registrar es podia saltar).
    Retorna el nombre d'intents comptant aquest. Cal fer clear_failures() quan la verificació surt bé."""
    from .models import LoginAttempt
    since = datetime.now(timezone.utc) - timedelta(minutes=LOCKOUT_MINUTES)
    db.add(LoginAttempt(username=key[:60]))
    db.commit()
    n = db.scalar(select(func.count()).select_from(LoginAttempt).where(LoginAttempt.username == key[:60], LoginAttempt.ts >= since))
    if n > maxim:
        raise LoginLocked()
    return n


def totp_required() -> bool:
    """El segon factor és obligatori. Només es pot desactivar amb CLUB_TOTP=0 (p. ex. en un servidor de proves)."""
    return os.environ.get("CLUB_TOTP", "1") != "0"


def login(db: Session, username: str, password: str, totp: str) -> str | None:
    """Entrada amb usuari, contrasenya i TOTP.

    L'intent es registra i es confirma (commit) ABANS de la verificació Argon2: així deu peticions en paral·lel veuen
    cadascuna els intents de les altres i només les primeres MAX_FAILED_LOGINS arriben a verificar-se. Un èxit esborra
    el compte. A l'auditoria mai va el text rebut: només l'id de l'usuari si existeix; per a un nom inexistent no s'hi
    deixa res (un anònim no pot escriure en un registre que només s'afegeix)."""
    from .models import LoginAttempt
    key = username[:60]
    ara = datetime.now(timezone.utc)
    since = ara - timedelta(minutes=LOCKOUT_MINUTES)
    db.execute(delete(LoginAttempt).where(LoginAttempt.ts < since))  # esborra els intents ja caducats
    db.execute(delete(SessionToken).where(SessionToken.expires_at < ara))  # i les sessions caducades
    db.add(LoginAttempt(username=key))
    db.commit()
    intents = db.scalar(select(func.count()).select_from(LoginAttempt).where(LoginAttempt.username == key, LoginAttempt.ts >= since))
    user = db.scalar(select(User).where(User.username == username, User.active.is_(True)))
    if intents > MAX_FAILED_LOGINS:
        # Bloquejat abans de comprovar res i també per a noms inexistents: no es revela si l'usuari existeix.
        if intents == MAX_FAILED_LOGINS + 1 and user:  # només el moment del bloqueig, i només per a usuaris reals
            audit_append(db, {"accio": "login_bloquejat", "usuari": user.id})
            db.commit()
        raise LoginLocked()
    # Sempre es calcula un hash, existeixi o no l'usuari, perquè el temps de resposta no delati els noms d'usuari.
    ok = security.verify_password(password, user.password_hash if user else security.dummy_hash())
    ok = bool(user) and ok
    if totp_required():
        pas = security.totp_step(crypto.decrypt(user.totp_secret_enc), totp) if ok else None
        # el codi només es «gasta» si la contrasenya també era bona; un codi ja usat no serveix una segona vegada
        ok = ok and pas is not None and security.totp_consume(db, user.id, pas)
    if user:
        audit_append(db, {"accio": "login", "usuari": user.id, "ok": ok})
    if not ok:
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


PERFIL_CAMPS = ("genere", "adreca", "ciutat", "codi_postal", "provincia", "pais")
GENERES = {"", "home", "dona", "altre"}


def normalitza_perfil(dades: dict | None) -> dict:
    """Dades de perfil (gènere i adreça) netes: només els camps coneguts, retallats, sense valors desmesurats."""
    out = {}
    for k in PERFIL_CAMPS:
        v = ((dades or {}).get(k) or "").strip()
        if len(v) > (12 if k == "codi_postal" else 120):
            raise ValueError(f"El camp «{k}» és massa llarg")
        if k == "genere" and v not in GENERES:
            raise ValueError("Gènere no vàlid")
        out[k] = v
    return out


def llegeix_perfil(m: Member) -> dict:
    import json
    brut = crypto.decrypt(m.perfil_enc) if m.perfil_enc else None
    return {**{k: "" for k in PERFIL_CAMPS}, **(json.loads(brut) if brut else {})}


def codi_soci(m: Member, nom: str) -> str:
    """Codi curt visible: inicials del nom i número de soci (p. ex. PP12)."""
    ini = "".join(p[0] for p in nom.split()[:2] if p[:1].isalnum()).upper() or "S"
    return f"{ini}{m.id}"


def create_member(db: Session, actor: User, local_id: int, nom: str, document: str,
                  naixement: date, telefon: str | None, email: str | None, *,
                  perfil: dict | None = None, tipus: str | None = None) -> Member:
    validate_document(document)
    perfil = normalitza_perfil(perfil)
    tipus = (tipus or "Ordinari").strip()[:40] or "Ordinari"
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
        perfil_enc=crypto.encrypt(json.dumps(perfil, ensure_ascii=False)) if any(perfil.values()) else None, tipus=tipus,
    )
    from . import ajustos
    if ajustos.get(db, local_id)["alta_pendent"]:
        m.estat = "pendent"  # un gestor l'ha d'aprovar (controls.approve)
    db.add(m)
    db.flush()
    audit_append(db, {"accio": "alta_soci", "soci": m.id, "local": local_id, "per": actor.id})
    db.commit()
    return m


def member_name(m: Member) -> str:
    return crypto.decrypt(m.nom_enc)


def member_view(m: Member) -> dict:
    return {
        "id": m.id, "local_id": m.local_id, "nom": crypto.decrypt(m.nom_enc),
        "document": crypto.decrypt(m.document_enc), "naixement": crypto.decrypt(m.naixement_enc),
        "telefon": crypto.decrypt(m.telefon_enc), "email": crypto.decrypt(m.email_enc), "estat": m.estat,
        "tipus": m.tipus, "descompte_pct": m.descompte_pct, "codi": codi_soci(m, crypto.decrypt(m.nom_enc)), **llegeix_perfil(m),
    }


ESTATS = {"pendent", "actiu", "suspes", "baixa"}


def set_member_status(db: Session, actor: User, member: Member, estat: str, motiu: str | None = None) -> None:
    if estat not in ESTATS:
        raise ValueError("Estat no vàlid")
    if member.estat == estat:
        raise ValueError("El soci ja té aquest estat")
    if "pendent" in (member.estat, estat):  # control de dues persones: només controls.approve treu un soci de pendent
        raise ValueError("L'estat «pendent» només canvia amb l'aprovació d'un altre gestor (aprovar)")
    if member.estat == "baixa" and actor.role != "admin":
        raise ValueError("Només un administrador pot reactivar un soci de baixa")
    if member.suprimit_en is not None:
        raise ValueError("El soci està suprimit (seudonimitzat): no es pot reactivar")
    anterior, member.estat = member.estat, estat
    member.baixa_en = datetime.now(timezone.utc) if estat == "baixa" else None
    audit_append(db, {"accio": "canvi_estat_soci", "soci": member.id, "de": anterior, "a": estat,
                              **({"motiu": motiu.strip()[:200]} if motiu and motiu.strip() else {}), "per": actor.id})
    db.commit()


def check_in(db: Session, actor: User, member: Member, via: str = "manual"):
    from .models import CheckIn
    if member.estat != "actiu":
        raise ValueError("El soci no està actiu")
    c = CheckIn(local_id=member.local_id, member_id=member.id, user_id=actor.id, tipus="entrada", via=via)
    db.add(c)
    db.flush()
    audit_append(db, {"accio": "entrada_soci", "soci": member.id, "via": via, "per": actor.id})
    db.commit()
    return c


DINS_MAX_HORES = 24  # una entrada sense sortida de fa més d'això ja no compta com «dins» (s'han oblidat de fitxar la sortida)


def _dins_ids(db: Session, local_id: int) -> dict[int, datetime]:
    """Socis que ara són dins: la seva darrera marca (entrada o sortida) és una entrada de fa menys de 24 h. {soci: hora d'entrada}"""
    from .models import CheckIn
    limit = datetime.now(timezone.utc) - timedelta(hours=DINS_MAX_HORES)
    darrera = {}
    for c in db.scalars(select(CheckIn).where(CheckIn.local_id == local_id, CheckIn.ts >= limit).order_by(CheckIn.id)):
        darrera[c.member_id] = c
    return {m: c.ts for m, c in darrera.items() if c.tipus == "entrada"}


def check_out(db: Session, actor: User, member: Member, via: str = "manual"):
    from .models import CheckIn
    if member.id not in _dins_ids(db, member.local_id):
        raise ValueError("El soci no té cap entrada oberta")
    c = CheckIn(local_id=member.local_id, member_id=member.id, user_id=actor.id, tipus="sortida", via=via)
    db.add(c)
    db.flush()
    audit_append(db, {"accio": "sortida_soci", "soci": member.id, "via": via, "per": actor.id})
    db.commit()
    return c


def check_out_all(db: Session, actor: User, local_id: int) -> int:
    """«Sacar tots»: tanca el dia amb una sortida per a cada soci que és dins. Torna quants n'ha sortit."""
    from .models import CheckIn
    dins = _dins_ids(db, local_id)
    for mid in dins:
        db.add(CheckIn(local_id=local_id, member_id=mid, user_id=actor.id, tipus="sortida", via="manual"))
    audit_append(db, {"accio": "sortida_tots", "local": local_id, "n": len(dins), "per": actor.id})
    db.commit()
    return len(dins)


def access_state(db: Session, actor: User, local_id: int) -> dict:
    """Pantalla d'accés manual: socis actius dins (amb hora d'entrada) i fora. Els noms es desxifren aquí (una consulta)."""
    dins = _dins_ids(db, local_id)
    out_dins, out_fora = [], []
    for m in db.scalars(select(Member).where(Member.local_id == local_id, Member.estat == "actiu")):
        nom = crypto.decrypt(m.nom_enc)
        if m.id in dins:
            out_dins.append({"id": m.id, "nom": nom, "entrada": dins[m.id].isoformat()})
        else:
            out_fora.append({"id": m.id, "nom": nom})
    out_dins.sort(key=lambda x: x["entrada"])
    out_fora.sort(key=lambda x: x["nom"].casefold())
    audit_append(db, {"accio": "consulta_acces", "local": local_id, "per": actor.id})
    db.commit()
    return {"dins": out_dins, "fora": out_fora}


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


def save_signature(db: Session, actor: User, member: Member, png_b64: str, text_sha256: str | None = None):
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
                    sha256=_signature_hash(png, member.id, ts.isoformat()), text_sha256=text_sha256)
    db.add(sig)
    db.flush()
    audit_append(db, {"accio": "signatura_alta", "soci": member.id, "signatura": sig.id, "sha256": sig.sha256, **({"text": text_sha256} if text_sha256 else {}), "per": actor.id})
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

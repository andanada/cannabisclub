"""Gestió de socis més enllà de l'alta: edició de dades, llistat, foto i carnet (RFID)."""
import base64
import binascii
import hashlib
import hmac
import json
import re
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import crypto, quotes, service
from .models import Member, MemberCard, MemberPhoto, User

CAMPS = {"nom", "document", "naixement", "telefon", "email", "tipus", "descompte_pct", *service.PERFIL_CAMPS}


def _majoria(naixement: date, minima: int = service.MAJORIA_EDAT) -> None:
    avui = date.today()
    edat = avui.year - naixement.year - ((avui.month, avui.day) < (naixement.month, naixement.day))
    if edat < minima:
        raise ValueError("El soci ha de ser major d'edat" if minima <= service.MAJORIA_EDAT else f"El soci ha de tenir almenys {minima} anys")


def update_member(db: Session, actor: User, member: Member, canvis: dict) -> Member:
    """Aplica els camps indicats (nom, document, naixement, telefon, email). Telèfon i correu es poden buidar.
    L'auditoria només guarda QUINS camps han canviat, mai els valors (són dades personals)."""
    if not set(canvis) <= CAMPS:
        raise ValueError("Camp no editable")
    actuals = {"nom": crypto.decrypt(member.nom_enc), "document": crypto.decrypt(member.document_enc),
               "naixement": crypto.decrypt(member.naixement_enc), "telefon": crypto.decrypt(member.telefon_enc),
               "email": crypto.decrypt(member.email_enc)}
    fets = []
    if "nom" in canvis:
        nom = (canvis["nom"] or "").strip()
        if len(nom) < 2:
            raise ValueError("El nom ha de tenir almenys 2 caràcters")
        if nom != actuals["nom"]:
            member.nom_enc = crypto.encrypt(nom)
            fets.append("nom")
    if "document" in canvis:
        doc = (canvis["document"] or "").strip()
        if len(doc) < 5:
            raise ValueError("El document ha de tenir almenys 5 caràcters")
        if doc != actuals["document"]:
            service.validate_document(doc)
            idx = service.document_index(doc)
            if idx != member.document_idx and db.scalar(select(Member.id).where(
                    Member.local_id == member.local_id, Member.document_idx == idx, Member.id != member.id)):
                raise ValueError("Ja existeix un soci amb aquest document en aquest local")
            member.document_enc, member.document_idx = crypto.encrypt(doc), idx
            fets.append("document")
    if "naixement" in canvis:
        if canvis["naixement"] is None:
            raise ValueError("La data de naixement no pot estar buida")
        from . import ajustos
        _majoria(canvis["naixement"], ajustos.get(db, member.local_id)["edat_minima"])
        if canvis["naixement"].isoformat() != actuals["naixement"]:
            member.naixement_enc = crypto.encrypt(canvis["naixement"].isoformat())
            fets.append("naixement")
    for camp in ("telefon", "email"):
        if camp in canvis:
            nou = (canvis[camp] or "").strip() or None
            if nou != actuals[camp]:
                setattr(member, camp + "_enc", crypto.encrypt(nou))
                fets.append(camp)
    if "tipus" in canvis:
        tipus = (canvis["tipus"] or "").strip()[:40]
        if not tipus:
            raise ValueError("El tipus de membre no pot estar buit")
        if tipus != member.tipus:
            member.tipus = tipus
            fets.append("tipus")
    if "descompte_pct" in canvis:
        pct = canvis["descompte_pct"]
        if not isinstance(pct, int) or isinstance(pct, bool) or not 0 <= pct <= 100:
            raise ValueError("El descompte del soci ha d'estar entre 0 i 100 %")
        if pct != member.descompte_pct:
            member.descompte_pct = pct
            fets.append("descompte_pct")
    if set(canvis) & set(service.PERFIL_CAMPS):
        actual = service.llegeix_perfil(member)
        nou = service.normalitza_perfil({**actual, **{k: canvis[k] for k in canvis if k in service.PERFIL_CAMPS}})
        if nou != actual:
            member.perfil_enc = crypto.encrypt(json.dumps(nou, ensure_ascii=False)) if any(nou.values()) else None
            fets += sorted(k for k in service.PERFIL_CAMPS if nou[k] != actual[k])
    if not fets:
        raise ValueError("No hi ha cap canvi")
    service.audit_append(db, {"accio": "edita_soci", "soci": member.id, "camps": sorted(fets), "per": actor.id})
    db.commit()
    return member


def list_members(db: Session, actor: User, local_id: int, q: str | None, estat: str | None) -> list[dict]:
    if estat is not None and estat not in service.ESTATS:
        raise ValueError("Estat no vàlid")
    query = select(Member).where(Member.local_id == local_id)
    if estat:
        query = query.where(Member.estat == estat)
    avui = quotes.avui()
    fins_per_soci = quotes.ultimes_quotes(db, local_id)
    filtre = (q or "").strip().casefold()
    out = []
    for m in db.scalars(query):
        nom = crypto.decrypt(m.nom_enc)
        if filtre and filtre not in nom.casefold():
            continue
        fins = fins_per_soci.get(m.id)
        out.append({"id": m.id, "nom": nom, "estat": m.estat, "tipus": m.tipus, "codi": service.codi_soci(m, nom),
                    "quota": {"al_dia": bool(fins and fins >= avui), "valid_fins": fins.isoformat() if fins else None}})
    out.sort(key=lambda x: x["nom"].casefold())
    service.audit_append(db, {"accio": "llista_socis", "local": local_id, "filtrat": bool(filtre or estat), "n": len(out), "per": actor.id})
    db.commit()
    return out


# ---------- foto ----------

MAX_PHOTO_BYTES = 250_000
MIN_PHOTO_BYTES = 200
JPEG_MAGIC = b"\xff\xd8\xff"
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


MAX_PHOTOS_PER_MEMBER = 20  # les fotos no s'esborren (taula només d'afegir): el límit evita que s'acumulin sense fi


def save_photo(db: Session, actor: User, member: Member, image_b64: str) -> MemberPhoto:
    from sqlalchemy import func
    from . import consentiments
    if not consentiments.allowed(db, member.id, "foto"):
        raise ValueError("El soci no ha donat (o ha retirat) el consentiment per a la fotografia")
    if db.scalar(select(func.count()).select_from(MemberPhoto).where(MemberPhoto.member_id == member.id)) >= MAX_PHOTOS_PER_MEMBER:
        raise ValueError(f"S'ha arribat al límit de {MAX_PHOTOS_PER_MEMBER} fotos per soci")
    try:
        img = base64.b64decode(image_b64, validate=True)
    except (binascii.Error, ValueError):
        raise ValueError("La foto no és vàlida")
    if img.startswith(JPEG_MAGIC):
        mime = "image/jpeg"
    elif img.startswith(PNG_MAGIC):
        mime = "image/png"
    else:
        raise ValueError("La foto ha de ser una imatge JPEG o PNG")
    if len(img) > MAX_PHOTO_BYTES:
        raise ValueError("La foto és massa gran (màxim 250 KB)")
    if len(img) < MIN_PHOTO_BYTES:
        raise ValueError("La foto està buida")
    foto = MemberPhoto(member_id=member.id, user_id=actor.id, mime=mime, img_enc=crypto.encrypt(image_b64),
                       sha256=hashlib.sha256(img).hexdigest())
    db.add(foto)
    db.flush()
    service.audit_append(db, {"accio": "foto_soci", "soci": member.id, "foto": foto.id, "sha256": foto.sha256, "per": actor.id})
    db.commit()
    return foto


def has_photo(db: Session, member_id: int) -> bool:
    return db.scalar(select(MemberPhoto.id).where(MemberPhoto.member_id == member_id).limit(1)) is not None


def read_photo(db: Session, actor: User, member: Member) -> dict | None:
    f = db.scalar(select(MemberPhoto).where(MemberPhoto.member_id == member.id).order_by(MemberPhoto.id.desc()).limit(1))
    if not f:
        return None
    service.audit_append(db, {"accio": "consulta_foto", "soci": member.id, "per": actor.id})
    db.commit()
    return {"id": f.id, "ts": f.ts.isoformat(), "mime": f.mime, "sha256": f.sha256, "image_base64": crypto.decrypt(f.img_enc)}


# ---------- carnet ----------

CODI_RE = re.compile(r"[A-Za-z0-9:_./-]{4,64}")


def _norm(codi: str) -> str:
    codi = (codi or "").strip()
    if not CODI_RE.fullmatch(codi):
        raise ValueError("Codi de carnet no vàlid (4 a 64 caràcters: lletres, xifres i : _ . / -)")
    return codi.upper()


def card_index(codi: str) -> str:
    # Prefix «CARD|» perquè l'empremta d'un carnet mai coincideixi amb la d'un document.
    return hmac.new(service._index_key(), ("CARD|" + _norm(codi)).encode(), hashlib.sha256).hexdigest()


def assign_card(db: Session, actor: User, member: Member, codi: str) -> MemberCard:
    idx = card_index(codi)
    existent = db.scalar(select(MemberCard).where(MemberCard.local_id == member.local_id, MemberCard.code_idx == idx))
    if existent and existent.active:
        raise ValueError("El soci ja té aquest carnet" if existent.member_id == member.id else "Aquest carnet ja està assignat a un altre soci")
    for vell in db.scalars(select(MemberCard).where(MemberCard.member_id == member.id, MemberCard.active.is_(True))):
        vell.active = False  # un carnet nou substitueix l'anterior
    if existent:
        existent.member_id, existent.active, existent.creat_per = member.id, True, actor.id
        card = existent
    else:
        card = MemberCard(local_id=member.local_id, member_id=member.id, code_idx=idx, creat_per=actor.id)
        db.add(card)
    db.flush()
    service.audit_append(db, {"accio": "assigna_carnet", "soci": member.id, "carnet": card.id, "per": actor.id})
    db.commit()
    return card


def revoke_card(db: Session, actor: User, member: Member) -> None:
    actius = db.scalars(select(MemberCard).where(MemberCard.member_id == member.id, MemberCard.active.is_(True))).all()
    if not actius:
        raise ValueError("El soci no té cap carnet assignat")
    for c in actius:
        c.active = False
    service.audit_append(db, {"accio": "retira_carnet", "soci": member.id, "per": actor.id})
    db.commit()


def has_card(db: Session, member_id: int) -> bool:
    return db.scalar(select(MemberCard.id).where(MemberCard.member_id == member_id, MemberCard.active.is_(True)).limit(1)) is not None


def find_by_card(db: Session, local_id: int, codi: str) -> Member | None:
    try:
        idx = card_index(codi)
    except ValueError:
        return None
    c = db.scalar(select(MemberCard).where(MemberCard.local_id == local_id, MemberCard.code_idx == idx, MemberCard.active.is_(True)))
    return db.get(Member, c.member_id) if c else None


# ---------- generador de carnets ----------

import secrets

ALFABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"  # sense I, L, O, U: no es confonen en llegir ni en teclejar
_PREFIX_RE = re.compile(r"[A-Z0-9]{2,6}")


def _control(cos: str) -> str:
    return ALFABET[sum((i + 1) * ALFABET.index(c) for i, c in enumerate(cos)) % 31]


def generate_card_code(prefix: str = "CLB") -> str:
    """Codi imprevisible: prefix-9 caràcters aleatoris + 1 de control (detecta errors de lectura o de teclat)."""
    if not _PREFIX_RE.fullmatch(prefix):
        raise ValueError("El prefix ha de tenir 2 a 6 lletres majúscules o xifres")
    cos = "".join(secrets.choice(ALFABET) for _ in range(9))
    return f"{prefix}-{cos}{_control(cos)}"


def card_code_valid(codi: str) -> bool:
    try:
        _, resta = codi.rsplit("-", 1)
    except ValueError:
        return False
    return len(resta) == 10 and all(c in ALFABET for c in resta) and _control(resta[:9]) == resta[9]


def generate_and_assign_card(db: Session, actor: User, member: Member, prefix: str = "CLB") -> str:
    """Genera un carnet nou, l'assigna (substituint l'anterior) i retorna el codi. Només es desa l'empremta: el codi es
    mostra aquesta única vegada, així que s'ha d'imprimir o gravar a l'acte."""
    for _ in range(5):
        codi = generate_card_code(prefix)
        try:
            assign_card(db, actor, member, codi)
            return codi
        except ValueError:
            db.rollback()  # col·lisió pràcticament impossible; es torna a provar
    raise ValueError("No s'ha pogut generar un carnet únic")

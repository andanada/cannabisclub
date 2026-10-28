"""Gestió de socis més enllà de l'alta: edició de dades, llistat, foto i carnet (RFID)."""
import base64
import binascii
import hashlib
import hmac
import re
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import crypto, quotes, service
from .models import Member, MemberCard, MemberPhoto, User

CAMPS = {"nom", "document", "naixement", "telefon", "email"}


def _majoria(naixement: date) -> None:
    avui = date.today()
    edat = avui.year - naixement.year - ((avui.month, avui.day) < (naixement.month, naixement.day))
    if edat < service.MAJORIA_EDAT:
        raise ValueError("El soci ha de ser major d'edat")


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
        _majoria(canvis["naixement"])
        if canvis["naixement"].isoformat() != actuals["naixement"]:
            member.naixement_enc = crypto.encrypt(canvis["naixement"].isoformat())
            fets.append("naixement")
    for camp in ("telefon", "email"):
        if camp in canvis:
            nou = (canvis[camp] or "").strip() or None
            if nou != actuals[camp]:
                setattr(member, camp + "_enc", crypto.encrypt(nou))
                fets.append(camp)
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
        out.append({"id": m.id, "nom": nom, "estat": m.estat,
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

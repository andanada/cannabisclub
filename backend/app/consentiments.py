"""Consentiments per finalitat (RGPD art. 6-7). Taula només d'afegir: la retirada és un registre nou, així queda
l'historial complet. Cada registre desa la versió del text informatiu i el SHA-256 del text acceptat."""
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import service, textos
from .models import Consent, Member, User

CANALS = {"presencial", "web", "paper"}


def grant(db: Session, actor: User, member: Member, finalitats: list[str], versio: str, text_sha256: str,
          canal: str = "presencial", signature_id: int | None = None, commit: bool = True) -> list[Consent]:
    """Registra el consentiment (atorgat) de cada finalitat. Cal que el hash sigui el d'algun idioma d'aquella versió:
    no es pot «acceptar» un text que el servidor no coneix. `basic` és obligatori en un alta."""
    if canal not in CANALS:
        raise ValueError("Canal no vàlid")
    if not finalitats or not set(finalitats) <= set(textos.FINALITATS):
        raise ValueError("Finalitat no vàlida (basic, consum, foto, contacte)")
    if versio not in textos.versions() or textos.idioma_del_hash(versio, text_sha256) is None:
        raise ValueError("El text informatiu acceptat no coincideix amb cap versió publicada")
    out = []
    for f in dict.fromkeys(finalitats):
        if vigent(db, member.id, f):
            continue  # ja consta; no s'omple l'historial amb duplicats
        c = Consent(member_id=member.id, user_id=actor.id, finalitat=f, accio="atorgat", versio=versio,
                    text_sha256=text_sha256, canal=canal, signature_id=signature_id)
        db.add(c)
        db.flush()
        service.audit_append(db, {"accio": "consentiment", "soci": member.id, "finalitat": f, "versio": versio,
                                  "text": text_sha256, "per": actor.id})
        out.append(c)
    if commit:
        db.commit()
    return out


def withdraw(db: Session, actor: User, member: Member, finalitat: str, canal: str = "presencial") -> Consent:
    if finalitat == "basic":
        raise ValueError("El tractament bàsic no es retira: cal donar de baixa el soci")
    if finalitat not in textos.FINALITATS:
        raise ValueError("Finalitat no vàlida")
    ultim = last(db, member.id, finalitat)
    if not ultim or ultim.accio != "atorgat":
        raise ValueError("No hi ha cap consentiment vigent per a aquesta finalitat")
    c = Consent(member_id=member.id, user_id=actor.id, finalitat=finalitat, accio="retirat", versio=ultim.versio,
                text_sha256=ultim.text_sha256, canal=canal)
    db.add(c)
    db.flush()
    service.audit_append(db, {"accio": "retira_consentiment", "soci": member.id, "finalitat": finalitat, "per": actor.id})
    db.commit()
    return c


def last(db: Session, member_id: int, finalitat: str) -> Consent | None:
    return db.scalar(select(Consent).where(Consent.member_id == member_id, Consent.finalitat == finalitat)
                     .order_by(Consent.id.desc()).limit(1))


def vigent(db: Session, member_id: int, finalitat: str) -> bool:
    c = last(db, member_id, finalitat)
    return bool(c and c.accio == "atorgat")


def has_any(db: Session, member_id: int) -> bool:
    return db.scalar(select(Consent.id).where(Consent.member_id == member_id).limit(1)) is not None


def allowed(db: Session, member_id: int, finalitat: str) -> bool:
    """Un soci anterior al registre de consentiments (sense cap fila) manté el comportament antic; un soci amb
    registre només pot usar foto/contacte si el consentiment és vigent."""
    return vigent(db, member_id, finalitat) or not has_any(db, member_id)


def history(db: Session, member_id: int) -> list[dict]:
    return [{"id": c.id, "ts": c.ts.isoformat(), "finalitat": c.finalitat, "accio": c.accio, "versio": c.versio,
             "text_sha256": c.text_sha256, "canal": c.canal, "signature_id": c.signature_id}
            for c in db.scalars(select(Consent).where(Consent.member_id == member_id).order_by(Consent.id))]


def status(db: Session, member_id: int) -> dict:
    return {f: vigent(db, member_id, f) for f in textos.FINALITATS}

"""Supressió per seudonimització (RGPD art. 17).

Disseny
-------
* Es conserva la fila de `members` (i el seu id) perquè els llibres d'estoc, caixa, quotes i entrades —només d'afegir i
  amb obligacions de conservació— continuïn quadrant; però tots els camps personals queden anul·lats: nom, document,
  naixement, telèfon, correu, empremtes HMAC (document i carnets), aval, fotos i signatures.
* Les fotos i signatures viuen en taules només d'afegir. Mecanisme escollit: funció PostgreSQL `club_buida_binaris`
  (SECURITY DEFINER, propietat del propietari de la BD) + un trigger que només accepta l'UPDATE que ve d'aquesta funció
  i que només buida la imatge i el seu hash. El rol de l'aplicació (club_app) no té UPDATE a aquestes taules: només pot
  *cridar la funció*, que exigeix que el soci estigui de baixa. S'ha descartat el crypto-shredding per soci perquè
  obligaria a re-xifrar tot el que ja existeix amb una clau per soci i a custodiar-ne una taula de claus; i un rol
  propietari a l'aplicació trencaria el model de privilegis mínims.
* La retenció mínima (CLUB_RETENCIO_MIN_DIES, per defecte 365 dies des de la baixa) bloqueja la supressió.
* No es toca el text lliure de nota/concepte dels moviments (pot contenir dades personals si algú les hi escriu): és
  un risc residual documentat a docs/RGPD.md.
"""
import hashlib
import hmac
import os
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select, text, update
from sqlalchemy.orm import Session

from . import crypto, service
from .models import AuditLog, Member, MemberCard, MemberIncident, MemberPhoto, Signature

MIN_DIES_DEFECTE = 365
TOKEN_NOM = "Soci suprimit"


def retencio_min_dies() -> int:
    v = os.environ.get("CLUB_RETENCIO_MIN_DIES", "").strip()
    return int(v) if v.isdigit() else MIN_DIES_DEFECTE


def _aware(d: datetime) -> datetime:
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def baixa_date(db: Session, member: Member) -> datetime | None:
    """Data de la baixa: la columna baixa_en o, en socis anteriors a la columna, l'última entrada d'auditoria."""
    if member.baixa_en:
        return _aware(member.baixa_en)
    mid = int(member.id)
    q = (select(AuditLog.ts).where(AuditLog.payload.like('%"accio":"canvi_estat_soci"%'), AuditLog.payload.like('%"a":"baixa"%'),
                                   AuditLog.payload.like(f'%"soci":{mid},%') | AuditLog.payload.like(f'%"soci":{mid}}}%'))
         .order_by(AuditLog.seq.desc()).limit(1))
    ts = db.scalar(q)
    return _aware(ts) if ts else None


def bloqueig(db: Session, member: Member, ara: datetime | None = None) -> str | None:
    """Motiu pel qual NO es pot suprimir ara, o None si es pot."""
    ara = ara or datetime.now(timezone.utc)
    if member.suprimit_en is not None:
        return "ja_suprimit"
    if member.estat != "baixa":
        return "no_es_de_baixa"
    dies = retencio_min_dies()
    baixa = baixa_date(db, member)
    if dies > 0 and (baixa is None or ara - baixa < timedelta(days=dies)):
        return "retencio"
    return None


def pseudo_index(member_id: int) -> str:
    return hmac.new(service._index_key(), f"SUPR|{member_id}".encode(), hashlib.sha256).hexdigest()


def buida_binaris(db: Session, member_id: int, mode: str = "tot", cutoff: datetime | None = None) -> int:
    """Buida imatges de fotos i signatures. PostgreSQL: funció SECURITY DEFINER; SQLite (proves): UPDATE directe."""
    cutoff = cutoff or datetime.now(timezone.utc)
    if db.get_bind().dialect.name == "postgresql":
        # el tall i la retenció els calcula la funció (configuració de la BD que l'aplicació no pot escriure); `cutoff` només val a SQLite
        return int(db.execute(text("SELECT club_buida_binaris(:m, :mode)"), {"m": member_id, "mode": mode}).scalar() or 0)
    n = 0
    if mode == "tot":
        for t, col in ((MemberPhoto, "img_enc"), (Signature, "png_enc")):
            n += db.execute(update(t.__table__).where(t.member_id == member_id, getattr(t, col) != "")
                            .values({col: "", "sha256": "0" * 64})).rowcount
    else:
        ultimes = {m: i for m, i in db.execute(select(MemberPhoto.member_id, MemberPhoto.id).order_by(MemberPhoto.id))}
        for fid, mid, ts in db.execute(select(MemberPhoto.id, MemberPhoto.member_id, MemberPhoto.ts).where(MemberPhoto.img_enc != "")).all():
            if (not member_id or mid == member_id) and _aware(ts) < cutoff and ultimes[mid] > fid:
                n += db.execute(update(MemberPhoto.__table__).where(MemberPhoto.id == fid).values(img_enc="", sha256="0" * 64)).rowcount
    return n


def pseudonymize(db: Session, actor_id: int | None, member: Member, motiu: str = "") -> dict:
    """Seudonimitza un soci de baixa un cop vençuda la retenció. Torna un resum (sense dades personals)."""
    b = bloqueig(db, member)
    if b == "ja_suprimit":
        raise ValueError("El soci ja està suprimit")
    if b == "no_es_de_baixa":
        raise ValueError("Només es pot suprimir un soci de baixa")
    if b == "retencio":
        raise ValueError(f"Bloquejat per la política de conservació: calen {retencio_min_dies()} dies des de la baixa")
    if member.baixa_en is None:
        # Soci de baixa d'abans de la columna `baixa_en`: la data era a l'auditoria. La funció SQL que buida les imatges exigeix
        # baixa_en (no es refia de l'aplicació), així que s'omple abans: si no, la purga petaria sempre amb aquest soci.
        antiga = baixa_date(db, member)
        if antiga is not None:
            member.baixa_en = antiga
            db.flush()
    binaris = buida_binaris(db, member.id, "tot")
    targetes = db.execute(delete(MemberCard).where(MemberCard.member_id == member.id)).rowcount
    member.nom_enc = crypto.encrypt(f"{TOKEN_NOM} #{member.id}")
    member.document_enc = crypto.encrypt("SUPRIMIT")
    member.document_idx = pseudo_index(member.id)
    member.naixement_enc = crypto.encrypt("1900-01-01")
    member.telefon_enc = None
    member.perfil_enc = None
    for inc in db.scalars(select(MemberIncident).where(MemberIncident.member_id == member.id)):
        inc.descripcio_enc = crypto.encrypt("[suprimit]")  # text lliure: pot contenir dades personals
    member.email_enc = None
    member.avalador_id = None
    member.suprimit_en = datetime.now(timezone.utc)
    service.audit_append(db, {"accio": "supressio_soci", "soci": member.id, "binaris": binaris, "carnets": targetes,
                              "motiu": (motiu or "")[:100], "per": actor_id})
    db.commit()
    return {"soci": member.id, "binaris_buidats": binaris, "carnets_esborrats": targetes}

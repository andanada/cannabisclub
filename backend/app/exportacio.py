"""Dret d'accés i portabilitat (RGPD art. 15 i 20): exportació de totes les dades d'un soci en JSON i CSV de consum.
La foto i la signatura NO s'hi incrusten (pesen): s'hi posa l'enllaç i el hash. Cada exportació queda a l'auditoria."""
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import consentiments, informes_socis, moneder, quotes, service, socis
from .auditoria_consulta import entrades_del_soci
from .csvutil import to_csv
from .models import CheckIn, Member, MemberCard, MemberPhoto, Signature, User


def _ts(d) -> str:
    return d.isoformat()


def export_member(db: Session, actor: User, member: Member) -> dict:
    fitxa = service.member_view(member)
    dades = {
        "format": "club-gestio/export-soci/v1",
        "fitxa": {**fitxa, "creat": _ts(member.creat), "doc_verificat": member.doc_verificat, "avalador_id": member.avalador_id,
                  "baixa_en": _ts(member.baixa_en) if member.baixa_en else None},
        "consentiments": consentiments.history(db, member.id),
        "consentiments_vigents": consentiments.status(db, member.id),
        "quotes": quotes.history(db, member.id),
        "monedero": {"saldo_cent": moneder.saldo(db, member.id), "moviments": moneder.history(db, member.id, limit=100000)},
        "entrades": [{"id": c.id, "ts": _ts(c.ts)} for c in db.scalars(select(CheckIn).where(CheckIn.member_id == member.id).order_by(CheckIn.id))],
        "dispensacions": informes_socis.consumption(db, member, date(1970, 1, 1), date(2999, 12, 31)),
        "carnets": [{"id": c.id, "actiu": c.active, "creat": _ts(c.creat)} for c in db.scalars(select(MemberCard).where(MemberCard.member_id == member.id))],
        "fotos": [{"id": f.id, "ts": _ts(f.ts), "mime": f.mime, "sha256": f.sha256, "buidada": f.img_enc == "",
                   "enllac": f"/socis/{member.id}/foto"} for f in db.scalars(select(MemberPhoto).where(MemberPhoto.member_id == member.id).order_by(MemberPhoto.id))],
        "signatures": [{"id": g.id, "ts": _ts(g.ts), "sha256": g.sha256, "text_sha256": g.text_sha256, "buidada": g.png_enc == "",
                        "enllac": f"/socis/{member.id}/signatura"} for g in db.scalars(select(Signature).where(Signature.member_id == member.id).order_by(Signature.id))],
        "auditoria": entrades_del_soci(db, member.id),
    }
    service.audit_append(db, {"accio": "exporta_soci", "soci": member.id, "per": actor.id})
    db.commit()
    return dades


def consumption_csv(db: Session, actor: User, member: Member) -> str:
    r = informes_socis.consumption(db, member, date(1970, 1, 1), date(2999, 12, 31))
    service.audit_append(db, {"accio": "exporta_consum_soci", "soci": member.id, "per": actor.id})
    db.commit()
    return to_csv(["id", "data", "producte", "grams", "import_cent", "corregida"],
                  [[d["id"], d["ts"], d["producte"], d["grams"], d["import_cent"], d["corregida"]] for d in r["dispensacions"]])

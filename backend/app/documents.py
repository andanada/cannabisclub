"""Documents del soci (foto del document d'identitat davant i darrere, contracte signat, altres) i contracte descarregable.

Els fitxers es desen xifrats (Fernet) amb el seu SHA-256; cada pujada, lectura i esborrat queda a l'auditoria. Es poden
esborrar (a diferència de fotos i signatures, que només s'afegeixen): la supressió RGPD d'un soci els elimina."""
import base64
import binascii
import hashlib
import html
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import consentiments, crypto, service, textos
from .models import Local, Member, MemberDocument, User

TIPUS = {"nif_davant": "Document d'identitat (davant)", "nif_darrera": "Document d'identitat (darrere)",
         "contracte": "Contracte signat", "altre": "Altre document"}
MAX_BYTES = 400_000
MAX_PER_SOCI = 20
MIMES = {b"\xff\xd8\xff": "image/jpeg", b"\x89PNG\r\n\x1a\n": "image/png", b"%PDF-": "application/pdf"}


def _mime(contingut: bytes) -> str:
    for magic, mime in MIMES.items():
        if contingut.startswith(magic):
            return mime
    raise ValueError("El fitxer ha de ser una imatge JPEG, PNG o un PDF")


def pujar(db: Session, actor: User, member: Member, tipus: str, nom: str, data_b64: str) -> MemberDocument:
    if tipus not in TIPUS:
        raise ValueError("Tipus de document no vàlid")
    try:
        contingut = base64.b64decode(data_b64, validate=True)
    except (binascii.Error, ValueError):
        raise ValueError("El fitxer no és vàlid")
    if len(contingut) < 100:
        raise ValueError("El fitxer està buit")
    if len(contingut) > MAX_BYTES:
        raise ValueError("El fitxer és massa gran (màxim 400 KB)")
    mime = _mime(contingut)
    if db.scalar(select(func.count()).select_from(MemberDocument).where(MemberDocument.member_id == member.id)) >= MAX_PER_SOCI:
        raise ValueError(f"S'ha arribat al límit de {MAX_PER_SOCI} documents per soci")
    nom = (nom or TIPUS[tipus]).strip()[:120] or TIPUS[tipus]
    d = MemberDocument(local_id=member.local_id, member_id=member.id, tipus=tipus, nom=nom, mime=mime,
                       data_enc=crypto.encrypt(data_b64), sha256=hashlib.sha256(contingut).hexdigest(), user_id=actor.id)
    db.add(d)
    db.flush()
    service.audit_append(db, {"accio": "document_soci", "soci": member.id, "document": d.id, "tipus": tipus, "sha256": d.sha256, "per": actor.id})
    db.commit()
    return d


def llista(db: Session, actor: User, member: Member) -> list[dict]:
    noms = {i: n for i, n in db.execute(select(User.id, User.username))}
    return [{"id": d.id, "tipus": d.tipus, "nom": d.nom, "mime": d.mime, "sha256": d.sha256, "ts": d.ts.isoformat(), "per": noms.get(d.user_id)}
            for d in db.scalars(select(MemberDocument).where(MemberDocument.member_id == member.id).order_by(MemberDocument.id.desc()))]


def llegir(db: Session, actor: User, d: MemberDocument) -> dict:
    service.audit_append(db, {"accio": "consulta_document", "soci": d.member_id, "document": d.id, "per": actor.id})
    db.commit()
    return {"id": d.id, "nom": d.nom, "mime": d.mime, "data_base64": crypto.decrypt(d.data_enc), "sha256": d.sha256}


def esborrar(db: Session, actor: User, d: MemberDocument) -> None:
    service.audit_append(db, {"accio": "esborra_document", "soci": d.member_id, "document": d.id, "sha256": d.sha256, "per": actor.id})
    db.delete(d)
    db.commit()


def _text_signat(sig_hash: str | None, idioma: str) -> tuple[str, str]:
    """El text informatiu que el soci va signar (per hash), o el vigent en l'idioma demanat si no es pot identificar."""
    if sig_hash:
        for v in textos.versions():
            for i in textos.IDIOMES:
                if textos.sha256(v, i) == sig_hash:
                    return v, textos.text(v, i)
    idioma = idioma if idioma in textos.IDIOMES else "ca"
    return textos.VERSIO_ACTUAL, textos.text(textos.VERSIO_ACTUAL, idioma)


def contracte_html(db: Session, actor: User, member: Member, idioma: str = "ca") -> str:
    """Contracte/justificant d'alta imprimible (HTML autònom): dades del soci, text informatiu signat, consentiments i signatura.
    Tot el text s'escapa. La descàrrega queda a l'auditoria."""
    from .models import Signature
    local = db.get(Local, member.local_id)
    sig = db.scalar(select(Signature).where(Signature.member_id == member.id).order_by(Signature.id.desc()).limit(1))
    versio, text = _text_signat(sig.text_sha256 if sig else None, idioma)
    perfil = service.llegeix_perfil(member)
    estat = consentiments.status(db, member.id)
    esc = html.escape
    png = crypto.decrypt(sig.png_enc) if sig and sig.png_enc else None
    dades = [("Nom", crypto.decrypt(member.nom_enc)), ("Document", crypto.decrypt(member.document_enc)),
             ("Data de naixement", crypto.decrypt(member.naixement_enc)), ("Adreça", ", ".join(x for x in (perfil["adreca"], perfil["codi_postal"], perfil["ciutat"], perfil["provincia"], perfil["pais"]) if x)),
             ("Número de soci", str(member.id))]
    files = "".join(f"<tr><th>{esc(k)}</th><td>{esc(v)}</td></tr>" for k, v in dades if v)
    cons = ", ".join(f for f, ok in estat.items() if ok) or "—"
    service.audit_append(db, {"accio": "descarrega_contracte", "soci": member.id, "per": actor.id})
    db.commit()
    return ("<!doctype html><html lang=\"ca\"><head><meta charset=\"utf-8\"><title>Contracte de soci</title>"
            "<style>body{font:14px/1.5 system-ui,sans-serif;max-width:760px;margin:24px auto;padding:0 16px;color:#111}"
            "table{border-collapse:collapse;width:100%}th,td{text-align:left;padding:4px 8px;border-bottom:1px solid #ddd}"
            "pre{white-space:pre-wrap;font:inherit}img{max-width:320px;border:1px solid #ccc}</style></head><body>"
            f"<h1>{esc(local.nom if local else 'Club')}</h1><h2>Contracte d'alta de soci</h2><table>{files}</table>"
            f"<h3>Informació sobre el tractament de dades (versió {esc(versio)})</h3><pre>{esc(text)}</pre>"
            f"<p><strong>Consentiments vigents:</strong> {esc(cons)}</p>"
            f"<h3>Signatura</h3>{('<img alt=\"Signatura\" src=\"data:image/png;base64,' + esc(png) + '\">') if png else '<p>Sense signatura.</p>'}"
            f"<p>Generat el {esc(datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC'))}.</p></body></html>")

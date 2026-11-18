"""Incidències i avalats d'un soci. Les incidències són text lliure xifrat; cada alta, tancament i consulta queda a l'auditoria."""
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import crypto, service
from .models import Member, MemberIncident, User

MAX_DESCRIPCIO = 1000
TIPUS = {"nota": "Observació", "comportament": "Mal comportament", "objecte": "Objecte oblidat al club", "avis": "Avís"}


def crea(db: Session, actor: User, member: Member, descripcio: str, tipus: str = "nota", alerta: bool = False) -> MemberIncident:
    if tipus not in TIPUS:
        raise ValueError("Tipus d'observació no vàlid")
    text = (descripcio or "").strip()
    if len(text) < 3:
        raise ValueError("Escriu la descripció de la incidència")
    if len(text) > MAX_DESCRIPCIO:
        raise ValueError("La descripció és massa llarga")
    i = MemberIncident(local_id=member.local_id, member_id=member.id, descripcio_enc=crypto.encrypt(text), creat_per=actor.id, tipus=tipus, alerta=bool(alerta))
    db.add(i)
    db.flush()
    service.audit_append(db, {"accio": "incidencia_soci", "soci": member.id, "incidencia": i.id, "tipus": tipus, "alerta": bool(alerta), "per": actor.id})
    db.commit()
    return i


def tanca(db: Session, actor: User, incident: MemberIncident) -> None:
    if incident.estat == "tancada":
        raise ValueError("La incidència ja està tancada")
    incident.estat = "tancada"
    incident.tancada_en = datetime.now(timezone.utc)
    incident.tancada_per = actor.id
    service.audit_append(db, {"accio": "tanca_incidencia", "soci": incident.member_id, "incidencia": incident.id, "per": actor.id})
    db.commit()


def llista(db: Session, actor: User, member: Member) -> list[dict]:
    noms = {i: n for i, n in db.execute(select(User.id, User.username))}
    service.audit_append(db, {"accio": "consulta_incidencies", "soci": member.id, "per": actor.id})
    db.commit()
    return [{"id": i.id, "descripcio": crypto.decrypt(i.descripcio_enc), "estat": i.estat, "creat": i.creat.isoformat(),
             "creat_per": noms.get(i.creat_per), "tipus": i.tipus, "alerta": i.alerta, "tancada_en": i.tancada_en.isoformat() if i.tancada_en else None}
            for i in db.scalars(select(MemberIncident).where(MemberIncident.member_id == member.id).order_by(MemberIncident.id.desc()))]


def alertes(db: Session, member_id: int) -> list[dict]:
    """Observacions obertes marcades amb alerta: s'ensenyen al personal quan el soci fa l'entrada o es dispensa. No s'audita cada
    lectura (passa a cada entrada); sí l'alta i el tancament."""
    return [{"id": i.id, "tipus": i.tipus, "descripcio": crypto.decrypt(i.descripcio_enc), "creat": i.creat.isoformat()}
            for i in db.scalars(select(MemberIncident).where(MemberIncident.member_id == member_id, MemberIncident.estat == "oberta",
                                                             MemberIncident.alerta.is_(True)).order_by(MemberIncident.id))]


def avalats(db: Session, actor: User, member: Member) -> list[dict]:
    """Socis que ha avalat aquest soci."""
    service.audit_append(db, {"accio": "consulta_avalats", "soci": member.id, "per": actor.id})
    db.commit()
    return [{"id": m.id, "nom": crypto.decrypt(m.nom_enc), "estat": m.estat, "creat": m.creat.isoformat(), "tipus": m.tipus}
            for m in db.scalars(select(Member).where(Member.avalador_id == member.id).order_by(Member.id))]

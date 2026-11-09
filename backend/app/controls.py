"""Controls de club configurables per local (valors per defecte = comportament anterior):

* `espera_dies` (0): dies mínims des de l'alta abans de poder dispensar.
* `aval` («no»): avalador de l'alta («no», «opcional», «obligatori»).
* `alta_pendent` (fals): els socis nous entren en estat «pendent» i un gestor els ha d'aprovar (admin, o un gestor
  diferent del que ha fet l'alta: control de dues persones).
* Excepcions de límit per soci (diari/mensual) amb motiu i auditoria, que substitueixen el límit del local.

Hook: `stock.dispense` crida `controls.check_dispense(...)` (una línia) i fa servir `controls.limit_for(...)` per als límits.
També es registra que s'ha exhibit el document en l'alta (`members.doc_verificat`)."""
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import ajustos, service
from .models import Member, MemberLimit, User

PERIODES = {"dia", "mes"}
MAX_LIMIT_MG = 1_000_000_000


def _aware(d: datetime) -> datetime:
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def check_dispense(db: Session, member: Member, product, now: datetime) -> None:
    """Llança ValueError si els controls del local impedeixen dispensar a aquest soci."""
    if member.estat == "pendent":
        raise ValueError("El soci està pendent d'aprovació per un gestor")
    cfg = ajustos.get(db, member.local_id)
    if cfg["espera_dies"] > 0 and (now - _aware(member.creat)).days < cfg["espera_dies"]:
        raise ValueError(f"El soci encara està en el període d'espera ({cfg['espera_dies']} dies des de l'alta)")
    if cfg["aval"] == "obligatori" and member.avalador_id is None:
        raise ValueError("El soci no té avalador registrat (obligatori en aquest local)")


def limit_for(db: Session, member_id: int, periode: str, limit_local: int | None) -> int | None:
    """Límit efectiu: l'excepció del soci si n'hi ha, i si no el del local."""
    ex = db.get(MemberLimit, (member_id, periode))
    return ex.max_mg if ex else limit_local


# ---------- alta ----------

def complete_alta(db: Session, actor: User, member: Member, doc_verificat: bool, avalador_id: int | None) -> None:
    cfg = ajustos.get(db, member.local_id)
    if avalador_id is not None:
        if cfg["aval"] == "no":
            raise ValueError("Aquest local no fa servir avalador")
        av = db.get(Member, avalador_id)
        if not av or av.local_id != member.local_id or av.id == member.id:
            raise ValueError("L'avalador ha de ser un altre soci d'aquest local")
        if av.estat != "actiu":
            raise ValueError("L'avalador ha de ser un soci actiu")
    elif cfg["aval"] == "obligatori":
        raise ValueError("Cal indicar l'avalador")
    member.doc_verificat = bool(doc_verificat)
    member.avalador_id = avalador_id
    service.audit_append(db, {"accio": "alta_controls", "soci": member.id, "doc_verificat": bool(doc_verificat),
                              "avalador": avalador_id, "per": actor.id})


def approve(db: Session, actor: User, member: Member) -> None:
    if member.estat != "pendent":
        raise ValueError("El soci no està pendent d'aprovació")
    if actor.role != "admin" and actor.id == member.creat_per:
        raise ValueError("L'alta l'ha d'aprovar un altre gestor (o un administrador)")
    member.estat = "actiu"
    service.audit_append(db, {"accio": "aprova_soci", "soci": member.id, "per": actor.id})
    db.commit()


# ---------- excepcions de límit per soci ----------

def set_member_limit(db: Session, actor: User, member: Member, periode: str, max_mg: int | None, motiu: str) -> None:
    """Posa (o treu, amb max_mg=None) l'excepció de límit d'un soci. El motiu és obligatori."""
    if periode not in PERIODES:
        raise ValueError("Període no vàlid (dia o mes)")
    motiu = (motiu or "").strip()
    if len(motiu) < 3:
        raise ValueError("Cal indicar el motiu de l'excepció")
    fila = db.get(MemberLimit, (member.id, periode))
    abans = fila.max_mg if fila else None
    if max_mg is None:
        if not fila:
            raise ValueError("El soci no té aquesta excepció")
        db.delete(fila)
    else:
        if not 0 <= max_mg <= MAX_LIMIT_MG:
            raise ValueError("Límit fora de rang")
        if fila:
            fila.max_mg, fila.motiu, fila.user_id, fila.ts = max_mg, motiu[:200], actor.id, datetime.now(timezone.utc)
        else:
            db.add(MemberLimit(member_id=member.id, periode=periode, max_mg=max_mg, motiu=motiu[:200], user_id=actor.id))
    service.audit_append(db, {"accio": "excepcio_limit", "soci": member.id, "periode": periode, "abans": abans,
                              "despres": max_mg, "motiu": motiu[:200], "per": actor.id})
    db.commit()


def member_limits(db: Session, member_id: int) -> list[dict]:
    return [{"periode": f.periode, "max_mg": f.max_mg, "motiu": f.motiu, "usuari_id": f.user_id, "ts": f.ts.isoformat()}
            for f in db.scalars(select(MemberLimit).where(MemberLimit.member_id == member_id).order_by(MemberLimit.periode))]

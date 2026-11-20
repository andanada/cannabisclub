"""Horaris: sol·licituds dels treballadors (canvi de torn, diferència d'horari) amb aprovació de l'encarregada, i avançaments de sou."""
from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import cash, gastos, service
from .horaris import _registre, _usuari_local
from .horaris_models import Advance, ShiftRequest, ShiftSlot
from .models import User

CATEGORIA_AVANCOS = "Sous/avançaments"
TIPUS_AVANCOS = "Avançament de sou"


def _slot_propi(db, local_id, user_id, data, torn) -> ShiftSlot:
    s = db.scalar(select(ShiftSlot).where(ShiftSlot.local_id == local_id, ShiftSlot.data == data, ShiftSlot.torn == torn, ShiftSlot.user_id == user_id))
    if not s:
        raise ValueError("No tens cap lloc assignat en aquest torn d'aquest dia")
    return s


def crea_sollicitud(db: Session, user: User, local_id: int, tipus: str, data: date, torn: str, minuts: int = 0,
                    substitut_id: int | None = None, comentari: str | None = None) -> ShiftRequest:
    if tipus not in ("canvi", "diferencia"):
        raise ValueError("Tipus de sol·licitud no vàlid")
    slot = _slot_propi(db, local_id, user.id, data, torn)
    if tipus == "diferencia":
        if minuts == 0 or abs(minuts) > 720:
            raise ValueError("La diferència ha de ser de 1 minut a 12 hores (negativa si surts abans)")
        substitut_id = None
    else:
        minuts = 0
        if substitut_id is not None:
            if substitut_id == user.id:
                raise ValueError("El substitut ha de ser un altre treballador")
            _usuari_local(db, local_id, substitut_id)
    r = ShiftRequest(local_id=local_id, user_id=user.id, tipus=tipus, data=data, torn=torn, lloc=slot.lloc, substitut_id=substitut_id,
                     minuts=minuts, comentari=(comentari or "").strip() or None)
    db.add(r)
    db.flush()
    service.audit_append(db, {"accio": "horaris_sollicitud", "id": r.id, "tipus": tipus, "per": user.id})
    db.commit()
    return r


def _pendent(db, rid: int) -> ShiftRequest:
    r = db.scalar(select(ShiftRequest).where(ShiftRequest.id == rid).with_for_update().execution_options(populate_existing=True))
    if not r:
        raise ValueError("Sol·licitud inexistent")
    if r.estat != "pendent":
        raise ValueError("Aquesta sol·licitud ja està resolta")
    return r


def aprova(db: Session, actor: User, rid: int, nota: str | None = None) -> ShiftRequest:
    r = _pendent(db, rid)
    slot = _slot_propi(db, r.local_id, r.user_id, r.data, r.torn)
    if r.tipus == "canvi":
        abans = str(slot.user_id)
        if r.substitut_id is None:
            db.delete(slot)
            despres = None
        else:
            altre = db.scalar(select(ShiftSlot).where(ShiftSlot.local_id == r.local_id, ShiftSlot.data == r.data, ShiftSlot.torn == r.torn,
                                                      ShiftSlot.user_id == r.substitut_id))
            if altre:
                raise ValueError("El substitut ja treballa en aquest torn")
            slot.user_id, slot.inici, slot.fi = r.substitut_id, None, None
            despres = str(r.substitut_id)
        _registre(db, actor, r.local_id, "canvi", r.data, r.torn, r.lloc, r.user_id, abans, despres, r.id)
    else:
        _registre(db, actor, r.local_id, "diferencia", r.data, r.torn, r.lloc, r.user_id, None, f"{r.minuts:+d} min", r.id)
    r.estat, r.resolt_per, r.resolt_ts, r.nota = "aprovada", actor.id, datetime.now(timezone.utc), (nota or "").strip() or None
    service.audit_append(db, {"accio": "horaris_aprova", "id": r.id, "per": actor.id})
    db.commit()
    return r


def rebutja(db: Session, actor: User, rid: int, nota: str | None = None) -> ShiftRequest:
    r = _pendent(db, rid)
    r.estat, r.resolt_per, r.resolt_ts, r.nota = "rebutjada", actor.id, datetime.now(timezone.utc), (nota or "").strip() or None
    service.audit_append(db, {"accio": "horaris_rebutja", "id": r.id, "per": actor.id})
    db.commit()
    return r


def cancela(db: Session, user: User, rid: int) -> ShiftRequest:
    r = _pendent(db, rid)
    if r.user_id != user.id:
        raise ValueError("Només pots cancel·lar les teves sol·licituds")
    r.estat, r.resolt_per, r.resolt_ts = "cancel·lada", user.id, datetime.now(timezone.utc)
    service.audit_append(db, {"accio": "horaris_cancela", "id": r.id, "per": user.id})
    db.commit()
    return r


def llista_sollicituds(db: Session, local_id: int, user: User | None, estat: str | None = None, limit: int = 200) -> list[dict]:
    """`user` None: totes (gerència); altrament només les d'aquest treballador."""
    noms = {i: n for i, n in db.execute(select(User.id, User.username))}
    q = select(ShiftRequest).where(ShiftRequest.local_id == local_id)
    if user is not None:
        q = q.where(ShiftRequest.user_id == user.id)
    if estat:
        q = q.where(ShiftRequest.estat == estat)
    return [{"id": r.id, "ts": r.ts.isoformat(), "usuari": noms.get(r.user_id), "user_id": r.user_id, "tipus": r.tipus, "data": r.data.isoformat(),
             "torn": r.torn, "lloc": r.lloc, "substitut": noms.get(r.substitut_id), "substitut_id": r.substitut_id, "minuts": r.minuts,
             "comentari": r.comentari or "", "estat": r.estat, "resolt_per": noms.get(r.resolt_per), "nota": r.nota or ""}
            for r in db.scalars(q.order_by(ShiftRequest.id.desc()).limit(limit))]


# ---------- avançaments ----------

def _catalog_id(db, actor, local_id, quin, nom) -> int:
    M = gastos.CATALEGS[quin]
    fila = db.scalar(select(M).where(M.local_id == local_id, M.nom == nom))
    if fila is None:
        return gastos.crea_catalog(db, actor, local_id, quin, nom, "Creat pels avançaments de sou", commit=False)
    if not fila.actiu:
        gastos.edita_catalog(db, actor, quin, fila.id, None, None, True, commit=False)
    return fila.id


def registra_avanc(db: Session, actor: User, local_id: int, data: date, user_id: int, cent: int, comentari: str | None,
                   de_caixa: bool, metode: str = "efectiu") -> Advance:
    """Apunta l'avançament i la despesa corresponent. Si surt de caixa, la despesa porta l'apunt de caixa (en efectiu per defecte)."""
    if cent <= 0:
        raise ValueError("L'import ha de ser positiu")
    _usuari_local(db, local_id, user_id)
    if de_caixa and metode not in cash.METODES:
        raise ValueError("Mètode de pagament no vàlid")
    if de_caixa:
        cash.comprova_metode_sortida(db, local_id, metode)
    nom = db.scalar(select(User.username).where(User.id == user_id))
    cat = _catalog_id(db, actor, local_id, "categories", CATEGORIA_AVANCOS)
    tip = _catalog_id(db, actor, local_id, "tipus", TIPUS_AVANCOS)
    text = f"Avançament a {nom}" + (f": {comentari.strip()}" if comentari and comentari.strip() else "")
    e = gastos.registra(db, actor, local_id, data, tip, cat, None, cent, metode if de_caixa else None, text[:300], commit=False)
    a = Advance(local_id=local_id, data=data, user_id=user_id, actor_id=actor.id, import_cent=cent,
                comentari=(comentari or "").strip() or None, de_caixa=de_caixa, expense_id=e.id)
    db.add(a)
    db.flush()
    service.audit_append(db, {"accio": "avanc", "id": a.id, "usuari": user_id, "cent": cent, "caixa": de_caixa, "per": actor.id})
    db.commit()
    return a


def anula_avanc(db: Session, actor: User, aid: int, nota: str) -> Advance:
    orig = db.get(Advance, aid)
    if not orig or orig.corregeix_id is not None:
        raise ValueError("Avançament inexistent")
    if db.scalar(select(Advance.id).where(Advance.corregeix_id == orig.id)):
        raise ValueError("Aquest avançament ja està anul·lat")
    gastos.anula(db, actor, orig.expense_id, nota, commit=False)  # també corregeix l'apunt de caixa, si en tenia
    a = Advance(local_id=orig.local_id, data=orig.data, user_id=orig.user_id, actor_id=actor.id, import_cent=orig.import_cent,
                comentari=nota, de_caixa=orig.de_caixa, corregeix_id=orig.id)
    db.add(a)
    db.flush()
    service.audit_append(db, {"accio": "anulacio_avanc", "id": a.id, "anula": orig.id, "per": actor.id})
    db.commit()
    return a


def llista_avancos(db: Session, local_id: int, des: date, fins: date) -> dict:
    noms = {i: n for i, n in db.execute(select(User.id, User.username))}
    anulats = set(db.scalars(select(Advance.corregeix_id).where(Advance.local_id == local_id, Advance.corregeix_id.is_not(None))))
    q = select(Advance).where(Advance.local_id == local_id, Advance.data >= des, Advance.data <= fins).order_by(Advance.data.desc(), Advance.id.desc())
    files, per_user = [], {}
    for a in db.scalars(q):
        anul = a.corregeix_id is not None
        files.append({"id": a.id, "data": a.data.isoformat(), "usuari": noms.get(a.user_id), "user_id": a.user_id, "import_cent": a.import_cent,
                      "comentari": a.comentari or "", "de_caixa": a.de_caixa, "anulacio": anul, "anulat": a.id in anulats, "per": noms.get(a.actor_id)})
        if not anul and a.id not in anulats:
            per_user[a.user_id] = per_user.get(a.user_id, 0) + a.import_cent
    return {"avancos": files, "totals": [{"user_id": k, "usuari": noms.get(k), "import_cent": v} for k, v in sorted(per_user.items())]}

"""Ajudes comunes de les rutes (permisos, 404 i traducció d'errors de negoci a HTTP)."""
from datetime import date

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import quotes, service, socis
from ..models import Member, Product, User, UserLocal

CAN_CREATE_MEMBER = {"admin", "encarregat"}


def acces_complet(user: User) -> bool:
    """Gerència (admin i encarregat): accés a tot, sense triar rol del dia."""
    return user.role in CAN_CREATE_MEMBER


def pot_recepcio(user: User) -> bool:
    """Caixa i donacions. Un treballador que ha triat «dispensari» no hi accedeix (per no descuadrar la caixa de recepció).
    Sense rol triat no té accés ni a recepció ni al dispensari: cal triar-lo en iniciar sessió."""
    return acces_complet(user) or getattr(user, "rol_dia", None) == "recepcio"


def pot_dispensari(user: User) -> bool:
    """Productes, estoc, inventaris i dispensar: dispensari o gerència."""
    return acces_complet(user) or getattr(user, "rol_dia", None) == "dispensari"


def need_recepcio(user: User) -> None:
    if not pot_recepcio(user):
        raise HTTPException(403, "Aquesta acció és de recepció: tria el rol «Recepció» o demana-ho a recepció")


def need_dispensari(user: User) -> None:
    if not pot_dispensari(user):
        raise HTTPException(403, "Aquesta acció és del dispensari: tria el rol «Dispensari» o demana-ho al dispensari")


def check_local(s: Session, user: User, local_id: int) -> None:
    if user.role == "admin":
        return
    if not s.get(UserLocal, (user.id, local_id)):
        raise HTTPException(403, "Sense accés a aquest local")


def member_payload(s: Session, m: Member, user: User) -> dict:
    """Fitxa del soci. Els gestors (admin, encarregat) la veuen sencera; el dispensador només el que necessita al
    taulell: nom, estat, quota, foto i carnet. Document, naixement, telèfon i correu no li arriben mai."""
    from .. import incidencies
    base = {"quota": quotes.status(s, m.id), "te_foto": socis.has_photo(s, m.id), "te_carnet": socis.has_card(s, m.id),
            "alertes": incidencies.alertes(s, m.id)}
    # Tot el personal (recepció i dispensari) pot consultar les dades dels socis; editar-les és de la gerència.
    return {**service.member_view(m), **base}


def product_or_404(s: Session, user: User, product_id: int) -> Product:
    p = s.get(Product, product_id)
    if not p:
        raise HTTPException(404, "Producte inexistent")
    check_local(s, user, p.local_id)
    return p


def run(fn, *a, **kw):
    try:
        return fn(*a, **kw)
    except ValueError as e:
        raise HTTPException(422, str(e))


def need_manager(user: User):
    if user.role not in CAN_CREATE_MEMBER:
        raise HTTPException(403, "El teu rol no pot fer aquesta operació")


def personal_del_local(s: Session, local_id: int) -> list[User]:
    ids = set(s.scalars(select(UserLocal.user_id).where(UserLocal.local_id == local_id)))
    return [u for u in s.scalars(select(User).where(User.active.is_(True)).order_by(User.username)) if u.role == "admin" or u.id in ids]


def empleat_valid(s: Session, local_id: int, usuari: int | None) -> None:
    """El filtre per empleat només admet gent que treballa en aquest local (o administradors)."""
    if usuari is not None and usuari not in {u.id for u in personal_del_local(s, local_id)}:
        raise HTTPException(422, "Aquest empleat no treballa en aquest local")


def rang(des: date, fins: date) -> None:
    if fins < des:
        raise HTTPException(422, "Rang de dates invàlid")


def need_admin(user: User):
    if user.role != "admin":
        raise HTTPException(403, "Només administradors")


def member_or_404(s: Session, user: User, member_id: int) -> Member:
    m = s.get(Member, member_id)
    if not m:
        raise HTTPException(404, "No existeix")
    check_local(s, user, m.local_id)
    return m


def usuari_or_404(s: Session, user_id: int) -> User:
    u = s.get(User, user_id)
    if not u:
        raise HTTPException(404, "Usuari inexistent")
    return u

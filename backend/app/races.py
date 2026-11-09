"""Carreres: una restricció d'unicitat de la base de dades es converteix en error de negocio net (ValueError)."""
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session


def flush_or_error(db: Session, missatge: str) -> None:
    """flush() que, si dues peticions simultànies xoquen amb un índex únic, desfà i llança ValueError(missatge)."""
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise ValueError(missatge)

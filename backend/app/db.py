import os
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker


class Base(DeclarativeBase):
    pass


def make_engine(url: str | None = None):
    url = url or os.environ.get("CLUB_DATABASE_URL") or os.environ.get("CLUB_APP_DATABASE_URL")
    if not url:
        raise RuntimeError("Falta CLUB_DATABASE_URL o CLUB_APP_DATABASE_URL")
    if url.startswith("sqlite"):
        kwargs = {"connect_args": {"check_same_thread": False}}
    else:
        # pre_ping: una connexió tallada (reinici de PostgreSQL, xarxa) es refà sola en lloc de donar un error a l'usuari.
        kwargs = {"pool_pre_ping": True, "pool_size": 10, "max_overflow": 10, "pool_recycle": 1800}
    return create_engine(url, **kwargs)


def make_session_factory(engine):
    return sessionmaker(engine, expire_on_commit=False)

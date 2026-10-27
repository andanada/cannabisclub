import os
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker


class Base(DeclarativeBase):
    pass


def make_engine(url: str | None = None):
    url = url or os.environ.get("CLUB_DATABASE_URL")
    if not url:
        raise RuntimeError("Falta CLUB_DATABASE_URL")
    kwargs = {"connect_args": {"check_same_thread": False}} if url.startswith("sqlite") else {}
    return create_engine(url, **kwargs)


def make_session_factory(engine):
    return sessionmaker(engine, expire_on_commit=False)

"""Creació de l'esquema. A PostgreSQL afegeix triggers que fan les taules d'apunts només d'afegir,
de manera que ni SQL directe pot modificar-los o esborrar-los (a més del bloqueig de l'aplicació)."""
from sqlalchemy import text

from .db import Base
from . import models  # noqa: F401  (registra les taules)

APPEND_ONLY = ["stock_movements", "cash_entries", "time_events", "checkins", "audit_log", "signatures", "quotes", "member_photos", "movement_discounts", "movement_warehouses"]

FUNCTION = """
CREATE OR REPLACE FUNCTION club_forbid_change() RETURNS trigger AS $$
BEGIN
  RAISE EXCEPTION 'La taula % és només d''afegir: operació % no permesa', TG_TABLE_NAME, TG_OP
    USING ERRCODE = '42501';
END;
$$ LANGUAGE plpgsql
"""


def missing_indexes(engine) -> list[str]:
    """Índexs del model que falten en taules que ja existien (create_all no els crea en taules existents)."""
    from sqlalchemy import inspect
    insp = inspect(engine)
    existents = {i["name"] for t in insp.get_table_names() for i in insp.get_indexes(t)}
    return sorted(i.name for t in Base.metadata.sorted_tables for i in t.indexes if i.name not in existents)


# Columnes afegides després de crear la taula. create_all no les afegeix a taules que ja existeixen, així que
# s'afegeixen amb ALTER TABLE (sempre amb valor per defecte: les files existents continuen valent).
COLUMNES_NOVES = {"products": [("es_genetic", {"postgresql": "BOOLEAN NOT NULL DEFAULT FALSE", "default": "BOOLEAN NOT NULL DEFAULT 0"})],
                  "user_cards": [("pin_hash", {"default": "TEXT"})]}


def missing_columns(engine) -> list[str]:
    from sqlalchemy import inspect
    insp = inspect(engine)
    out = []
    for taula, cols in COLUMNES_NOVES.items():
        if taula in insp.get_table_names():
            existents = {c["name"] for c in insp.get_columns(taula)}
            out += [f"{taula}.{c}" for c, _ in cols if c not in existents]
    return out


def add_missing_columns(engine) -> list[str]:
    afegides = missing_columns(engine)
    with engine.begin() as c:
        for tc in afegides:
            taula, col = tc.split(".")
            ddl = dict(COLUMNES_NOVES[taula])[col]
            c.execute(text(f"ALTER TABLE {taula} ADD COLUMN {col} {ddl[engine.dialect.name] if engine.dialect.name in ddl else ddl['default']}"))
    return afegides


def install(engine) -> None:
    Base.metadata.create_all(engine)
    add_missing_columns(engine)
    for t in Base.metadata.sorted_tables:
        for ix in t.indexes:
            ix.create(engine, checkfirst=True)
    if engine.dialect.name != "postgresql":
        return
    with engine.begin() as c:
        c.execute(text(FUNCTION))
        for t in APPEND_ONLY:
            c.execute(text(f"DROP TRIGGER IF EXISTS {t}_no_change ON {t}"))
            c.execute(text(f"CREATE TRIGGER {t}_no_change BEFORE UPDATE OR DELETE ON {t} "
                           f"FOR EACH ROW EXECUTE FUNCTION club_forbid_change()"))
            c.execute(text(f"DROP TRIGGER IF EXISTS {t}_no_truncate ON {t}"))
            c.execute(text(f"CREATE TRIGGER {t}_no_truncate BEFORE TRUNCATE ON {t} "
                           f"FOR EACH STATEMENT EXECUTE FUNCTION club_forbid_change()"))


def missing_tables(engine) -> list[str]:
    """Taules del model que encara no existeixen a la base de dades (p. ex. després d'actualitzar el programa)."""
    from sqlalchemy import inspect
    existents = set(inspect(engine).get_table_names())
    return sorted(t.name for t in Base.metadata.sorted_tables if t.name not in existents)


def _q(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def create_app_role(engine, role: str, password: str) -> None:
    """Crea (o actualitza la contrasenya de) el rol de l'aplicació: sense superusuari ni propietat de res."""
    from psycopg import sql
    with engine.begin() as c:
        raw = c.connection.driver_connection
        exists = c.execute(text("SELECT 1 FROM pg_roles WHERE rolname = :r"), {"r": role}).scalar()
        verb = "ALTER" if exists else "CREATE"
        stmt = sql.SQL(verb + " ROLE {} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT PASSWORD {}").format(
            sql.Identifier(role), sql.Literal(password))
        raw.execute(stmt)


def grant_app_role(engine, role: str) -> None:
    """Permisos mínims. Les taules d'apunts només admeten SELECT i INSERT; la resta, DML normal."""
    with engine.begin() as c:
        schema = c.execute(text("SELECT current_schema()")).scalar()
        s, r = _q(schema), _q(role)
        c.execute(text(f"GRANT USAGE ON SCHEMA {s} TO {r}"))
        for t in Base.metadata.sorted_tables:
            if t.name in APPEND_ONLY:
                c.execute(text(f"REVOKE ALL ON {s}.{_q(t.name)} FROM {r}"))
                c.execute(text(f"GRANT SELECT, INSERT ON {s}.{_q(t.name)} TO {r}"))
            else:
                c.execute(text(f"REVOKE ALL ON {s}.{_q(t.name)} FROM {r}"))
                c.execute(text(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {s}.{_q(t.name)} TO {r}"))
        c.execute(text(f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA {s} TO {r}"))

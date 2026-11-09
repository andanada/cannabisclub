"""Creació de l'esquema. A PostgreSQL afegeix triggers que fan les taules d'apunts només d'afegir,
de manera que ni SQL directe pot modificar-los o esborrar-los (a més del bloqueig de l'aplicació)."""
from sqlalchemy import text

from .db import Base
from . import models  # noqa: F401  (registra les taules)

APPEND_ONLY = ["stock_movements", "cash_entries", "time_events", "checkins", "audit_log", "signatures", "quotes", "member_photos", "movement_discounts", "movement_warehouses", "consents", "audit_anchors", "movement_batches"]

FUNCTION = """
CREATE OR REPLACE FUNCTION club_forbid_change() RETURNS trigger AS $$
BEGIN
  RAISE EXCEPTION 'La taula % és només d''afegir: operació % no permesa', TG_TABLE_NAME, TG_OP
    USING ERRCODE = '42501';
END;
$$ LANGUAGE plpgsql
"""


SESSION_FUNCTION = """
CREATE OR REPLACE FUNCTION club_cash_session_guard() RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'Les sessions de caixa no es poden esborrar' USING ERRCODE = '42501';
  END IF;
  IF OLD.closed_at IS NOT NULL THEN
    RAISE EXCEPTION 'Una sessió de caixa tancada no es pot modificar' USING ERRCODE = '42501';
  END IF;
  IF NEW.id <> OLD.id OR NEW.local_id <> OLD.local_id OR NEW.opened_at <> OLD.opened_at
     OR NEW.opened_by <> OLD.opened_by OR NEW.opening_cent <> OLD.opening_cent THEN
    RAISE EXCEPTION 'Les dades d''obertura de la caixa no es poden canviar' USING ERRCODE = '42501';
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql
"""


# Taules d'apunts amb dades personals xifrades que la supressió RGPD ha de poder buidar (fotos i signatures). El trigger
# només deixa passar un UPDATE que vingui de la funció club_buida_binaris (SECURITY DEFINER, propietat de l'usuari
# propietari de la BD) i que només toqui la imatge i el seu hash: el rol de l'aplicació NO pot fer cap UPDATE directe
# (ni té el privilegi ni passaria el trigger, perquè current_user seria ell).
BUIDABLES = {"member_photos": "img_enc", "signatures": "png_enc"}

SUPR_TRIGGER_FUNCTION = """
CREATE OR REPLACE FUNCTION club_forbid_change_buidable() RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'UPDATE'
     AND current_setting('club.supr_ok', true) = '1'
     AND current_user = (SELECT pg_get_userbyid(relowner) FROM pg_class WHERE oid = TG_RELID)
     AND NEW.id = OLD.id AND NEW.member_id = OLD.member_id AND NEW.ts = OLD.ts AND NEW.user_id = OLD.user_id THEN
    RETURN NEW;
  END IF;
  RAISE EXCEPTION 'La taula % és només d''afegir: operació % no permesa', TG_TABLE_NAME, TG_OP
    USING ERRCODE = '42501';
END;
$$ LANGUAGE plpgsql
"""

BUIDA_FUNCTION = """
CREATE OR REPLACE FUNCTION club_buida_binaris(p_member integer, p_mode text, p_cutoff timestamptz) RETURNS integer
LANGUAGE plpgsql SECURITY DEFINER SET search_path FROM CURRENT AS $$
DECLARE n integer := 0; k integer;
BEGIN
  IF p_mode = 'tot' THEN
    IF NOT EXISTS (SELECT 1 FROM members WHERE id = p_member AND estat = 'baixa') THEN
      RAISE EXCEPTION 'Només es poden buidar les dades d''un soci de baixa' USING ERRCODE = '42501';
    END IF;
    PERFORM set_config('club.supr_ok', '1', true);
    UPDATE member_photos SET img_enc = '', sha256 = repeat('0', 64) WHERE member_id = p_member AND img_enc <> '';
    GET DIAGNOSTICS k = ROW_COUNT; n := n + k;
    UPDATE signatures SET png_enc = '', sha256 = repeat('0', 64) WHERE member_id = p_member AND png_enc <> '';
    GET DIAGNOSTICS k = ROW_COUNT; n := n + k;
  ELSIF p_mode = 'fotos_velles' THEN
    PERFORM set_config('club.supr_ok', '1', true);
    UPDATE member_photos f SET img_enc = '', sha256 = repeat('0', 64)
      WHERE f.img_enc <> '' AND f.ts < p_cutoff
        AND EXISTS (SELECT 1 FROM member_photos g WHERE g.member_id = f.member_id AND g.id > f.id);
    GET DIAGNOSTICS k = ROW_COUNT; n := n + k;
  ELSE
    RAISE EXCEPTION 'Mode no vàlid' USING ERRCODE = '22023';
  END IF;
  PERFORM set_config('club.supr_ok', '', true);
  RETURN n;
END;
$$
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
                  "inventory_counts": [("expected_mg", {"default": "INTEGER"})],
                  "user_cards": [("pin_hash", {"default": "TEXT"})],
                  "users": [("last_totp_step", {"default": "BIGINT"})],
                  "members": [("baixa_en", {"postgresql": "TIMESTAMPTZ", "default": "TIMESTAMP"}),
                              ("suprimit_en", {"postgresql": "TIMESTAMPTZ", "default": "TIMESTAMP"}),
                              ("doc_verificat", {"postgresql": "BOOLEAN NOT NULL DEFAULT FALSE", "default": "BOOLEAN NOT NULL DEFAULT 0"}),
                              ("avalador_id", {"default": "INTEGER REFERENCES members(id)"})],
                  "audit_log": [("alg", {"default": "VARCHAR(8)"})],
                  "signatures": [("text_sha256", {"default": "VARCHAR(64)"})]}


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
        c.execute(text(SUPR_TRIGGER_FUNCTION))
        for t in APPEND_ONLY:
            c.execute(text(f"DROP TRIGGER IF EXISTS {t}_no_change ON {t}"))
            c.execute(text(f"CREATE TRIGGER {t}_no_change BEFORE UPDATE OR DELETE ON {t} "
                           f"FOR EACH ROW EXECUTE FUNCTION {'club_forbid_change_buidable' if t in BUIDABLES else 'club_forbid_change'}()"))
            c.execute(text(f"DROP TRIGGER IF EXISTS {t}_no_truncate ON {t}"))
            c.execute(text(f"CREATE TRIGGER {t}_no_truncate BEFORE TRUNCATE ON {t} "
                           f"FOR EACH STATEMENT EXECUTE FUNCTION club_forbid_change()"))
        c.execute(text(BUIDA_FUNCTION))
        c.execute(text("REVOKE ALL ON FUNCTION club_buida_binaris(integer, text, timestamptz) FROM PUBLIC"))
        # sessions de caixa: només passen d'oberta a tancada una vegada, i no s'esborren
        c.execute(text(SESSION_FUNCTION))
        c.execute(text("DROP TRIGGER IF EXISTS cash_sessions_guard ON cash_sessions"))
        c.execute(text("CREATE TRIGGER cash_sessions_guard BEFORE UPDATE OR DELETE ON cash_sessions "
                       "FOR EACH ROW EXECUTE FUNCTION club_cash_session_guard()"))
        # bases de dades antigues: movement_id era únic; ara es pot tornar a cobrar si es corregeix el cobrament
        c.execute(text("ALTER TABLE cash_entries DROP CONSTRAINT IF EXISTS cash_entries_movement_id_key"))


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
        c.execute(text(f"GRANT EXECUTE ON FUNCTION {s}.club_buida_binaris(integer, text, timestamptz) TO {r}"))
        c.execute(text(f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA {s} TO {r}"))

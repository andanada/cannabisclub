"""Creació de l'esquema. A PostgreSQL afegeix triggers que fan les taules d'apunts només d'afegir,
de manera que ni SQL directe pot modificar-los o esborrar-los (a més del bloqueig de l'aplicació)."""
from sqlalchemy import text

from .db import Base
from . import models  # noqa: F401  (registra les taules)

APPEND_ONLY = ["stock_movements", "cash_entries", "time_events", "checkins", "audit_log", "signatures", "quotes", "member_photos", "movement_discounts", "movement_warehouses", "consents", "audit_anchors", "movement_batches", "config_canari"]

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

# Totes les funcions SECURITY DEFINER fixen el search_path amb pg_catalog primer i pg_temp AL FINAL, i qualifiquen les
# taules amb l'esquema: així el rol de l'aplicació no pot fer ombra a taules/operadors amb objectes temporals
# (CVE-2007-2138 / CVE-2018-1058). A més es revoca TEMPORARY a PUBLIC (_restrict_temp).
SUPR_TRIGGER_FUNCTION = """
CREATE OR REPLACE FUNCTION club_forbid_change_buidable() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog, pg_temp AS $$
BEGIN
  IF TG_OP = 'UPDATE'
     AND pg_catalog.current_setting('club.supr_ok', true) = '1'
     AND current_user = (SELECT pg_catalog.pg_get_userbyid(relowner) FROM pg_catalog.pg_class WHERE oid = TG_RELID)
     AND NEW.id = OLD.id AND NEW.member_id = OLD.member_id AND NEW.ts = OLD.ts AND NEW.user_id = OLD.user_id THEN
    RETURN NEW;
  END IF;
  RAISE EXCEPTION 'La taula % és només d''afegir: operació % no permesa', TG_TABLE_NAME, TG_OP
    USING ERRCODE = '42501';
END;
$$
"""

# Configuració de retenció llegida per la funció de buidatge. L'escriu només el propietari (install / set_retention);
# el rol de l'aplicació no hi té cap privilegi. Rastre propi de cada buidatge: taula només d'afegir, sense privilegis per a l'app.
RETENCIO_DDL = (
    "CREATE TABLE IF NOT EXISTS {s}.club_retencio_cfg (clau text PRIMARY KEY, valor integer NOT NULL CHECK (valor >= 0))",
    "CREATE TABLE IF NOT EXISTS {s}.club_buida_log (id bigserial PRIMARY KEY, ts timestamptz NOT NULL DEFAULT now(), "
    "member_id integer NOT NULL, mode text NOT NULL, n integer NOT NULL, tall timestamptz, per text NOT NULL DEFAULT session_user)",
)
RETENCIO_PRIVADES = ("club_retencio_cfg", "club_buida_log")

BUIDA_FUNCTION = """
CREATE OR REPLACE FUNCTION {s}.club_buida_binaris(p_member integer, p_mode text) RETURNS integer
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, {s}, pg_temp AS $$
DECLARE n integer := 0; k integer; v_dies integer; v_tall timestamptz;
BEGIN
  IF p_mode = 'tot' THEN
    SELECT valor INTO v_dies FROM {s}.club_retencio_cfg WHERE clau = 'min_dies_baixa';
    v_dies := COALESCE(v_dies, 365);
    IF NOT EXISTS (SELECT 1 FROM {s}.members WHERE id = p_member AND estat = 'baixa'
                   AND (v_dies = 0 OR (baixa_en IS NOT NULL AND baixa_en <= now() - make_interval(days => v_dies)))) THEN
      RAISE EXCEPTION 'Només es poden buidar les dades d''un soci de baixa un cop vençuda la retenció' USING ERRCODE = '42501';
    END IF;
    PERFORM set_config('club.supr_ok', '1', true);
    UPDATE {s}.member_photos SET img_enc = '', sha256 = repeat('0', 64) WHERE member_id = p_member AND img_enc <> '';
    GET DIAGNOSTICS k = ROW_COUNT; n := n + k;
    UPDATE {s}.signatures SET png_enc = '', sha256 = repeat('0', 64) WHERE member_id = p_member AND png_enc <> '';
    GET DIAGNOSTICS k = ROW_COUNT; n := n + k;
  ELSIF p_mode = 'fotos_velles' THEN
    SELECT valor INTO v_dies FROM {s}.club_retencio_cfg WHERE clau = 'fotos_velles_dies';
    v_tall := now() - make_interval(days => COALESCE(v_dies, 365));
    PERFORM set_config('club.supr_ok', '1', true);
    UPDATE {s}.member_photos f SET img_enc = '', sha256 = repeat('0', 64)
      WHERE f.img_enc <> '' AND f.ts < v_tall
        AND (p_member = 0 OR f.member_id = p_member)  -- 0 = totes; un id = només les fotos d'aquest soci
        AND EXISTS (SELECT 1 FROM {s}.member_photos g WHERE g.member_id = f.member_id AND g.id > f.id);
    GET DIAGNOSTICS k = ROW_COUNT; n := n + k;
  ELSE
    RAISE EXCEPTION 'Mode no vàlid' USING ERRCODE = '22023';
  END IF;
  PERFORM set_config('club.supr_ok', '', true);
  INSERT INTO {s}.club_buida_log (member_id, mode, n, tall) VALUES (p_member, p_mode, n, v_tall);
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
                              ("avalador_id", {"default": "INTEGER REFERENCES members(id)"}),
                              ("perfil_enc", {"default": "TEXT"}),
                              ("tipus", {"default": "VARCHAR(40) NOT NULL DEFAULT 'Ordinari'"})],
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
        sch = _q(c.execute(text("SELECT current_schema()")).scalar())
        for ddl in RETENCIO_DDL:
            c.execute(text(ddl.format(s=sch)))
        c.execute(text("DROP TRIGGER IF EXISTS club_buida_log_no_change ON club_buida_log"))
        c.execute(text("CREATE TRIGGER club_buida_log_no_change BEFORE UPDATE OR DELETE ON club_buida_log "
                       "FOR EACH ROW EXECUTE FUNCTION club_forbid_change()"))
        # la signatura antiga (amb tall arbitrari) i la seva versió vulnerable desapareixen
        c.execute(text(f"DROP FUNCTION IF EXISTS {sch}.club_buida_binaris(integer, text, timestamptz)"))
        c.execute(text(BUIDA_FUNCTION.format(s=sch)))
        c.execute(text(f"REVOKE ALL ON FUNCTION {sch}.club_buida_binaris(integer, text) FROM PUBLIC"))
        _sync_retention(c, sch)
        _restrict_temp(c)
        # sessions de caixa: només passen d'oberta a tancada una vegada, i no s'esborren
        c.execute(text(SESSION_FUNCTION))
        c.execute(text("DROP TRIGGER IF EXISTS cash_sessions_guard ON cash_sessions"))
        c.execute(text("CREATE TRIGGER cash_sessions_guard BEFORE UPDATE OR DELETE ON cash_sessions "
                       "FOR EACH ROW EXECUTE FUNCTION club_cash_session_guard()"))
        # bases de dades antigues: movement_id era únic; ara es pot tornar a cobrar si es corregeix el cobrament
        c.execute(text("ALTER TABLE cash_entries DROP CONSTRAINT IF EXISTS cash_entries_movement_id_key"))


def _sync_retention(c, sch: str, min_dies: int | None = None, fotos_dies: int | None = None) -> None:
    import os

    def env(nom, defecte):
        v = os.environ.get(nom, "").strip()
        return int(v) if v.isdigit() else defecte
    valors = {"min_dies_baixa": env("CLUB_RETENCIO_MIN_DIES", 365) if min_dies is None else min_dies,
              "fotos_velles_dies": env("CLUB_RETENCIO_FOTOS_DIES", 365) if fotos_dies is None else fotos_dies}
    for k, v in valors.items():
        c.execute(text(f"INSERT INTO {sch}.club_retencio_cfg (clau, valor) VALUES (:k, :v) "
                       f"ON CONFLICT (clau) DO UPDATE SET valor = EXCLUDED.valor"), {"k": k, "v": int(v)})


def set_retention(engine, min_dies: int | None = None, fotos_dies: int | None = None) -> None:
    """Fixa (com a PROPIETARI) la retenció que aplica la funció de buidatge. Sense arguments, torna a llegir l'entorn
    (CLUB_RETENCIO_MIN_DIES / CLUB_RETENCIO_FOTOS_DIES); `actualitzar-bd` ho fa a cada execució."""
    with engine.begin() as c:
        _sync_retention(c, _q(c.execute(text("SELECT current_schema()")).scalar()), min_dies, fotos_dies)


def _restrict_temp(c) -> None:
    """Ningú (PUBLIC) pot crear objectes temporals: sense pg_temp, el rol de l'aplicació no pot fer ombra a res."""
    db = _q(c.execute(text("SELECT current_database()")).scalar())
    c.execute(text(f"REVOKE TEMPORARY ON DATABASE {db} FROM PUBLIC"))
    c.execute(text(f"GRANT TEMPORARY ON DATABASE {db} TO CURRENT_USER"))


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
        for t in RETENCIO_PRIVADES:  # configuració i rastre del buidatge: l'aplicació no hi toca mai
            c.execute(text(f"REVOKE ALL ON {s}.{t} FROM {r}"))
        c.execute(text(f"GRANT EXECUTE ON FUNCTION {s}.club_buida_binaris(integer, text) TO {r}"))
        _restrict_temp(c)
        c.execute(text(f"REVOKE TEMPORARY ON DATABASE {_q(c.execute(text('SELECT current_database()')).scalar())} FROM {r}"))
        c.execute(text(f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA {s} TO {r}"))

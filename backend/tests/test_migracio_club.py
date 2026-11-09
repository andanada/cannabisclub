"""Migració idempotent de les columnes i taules RGPD/club sobre una base de dades de la versió anterior."""
import os
import uuid

import pytest
from sqlalchemy import create_engine, inspect, text

from app import schema

pg_only = pytest.mark.skipif(not os.environ.get("CLUB_TEST_PG_URL"), reason="Cal PostgreSQL (CLUB_TEST_PG_URL)")

# Les taules tal com eren abans d'aquestes columnes (DDL mínim, compatible amb SQLite i PostgreSQL)
ANTIC = [
    "CREATE TABLE locals (id INTEGER PRIMARY KEY, nom VARCHAR(120) UNIQUE NOT NULL, limit_diari_mg INTEGER, limit_mensual_mg INTEGER, tolerancia_bascula_mg INTEGER)",
    "CREATE TABLE users (id INTEGER PRIMARY KEY, username VARCHAR(60) UNIQUE NOT NULL, password_hash VARCHAR(255) NOT NULL, totp_secret_enc TEXT NOT NULL, role VARCHAR(20) NOT NULL, active BOOLEAN)",
    "CREATE TABLE members (id INTEGER PRIMARY KEY, local_id INTEGER NOT NULL, nom_enc TEXT NOT NULL, document_enc TEXT NOT NULL, document_idx VARCHAR(64) NOT NULL, naixement_enc TEXT NOT NULL, telefon_enc TEXT, email_enc TEXT, estat VARCHAR(20), creat TIMESTAMP, creat_per INTEGER NOT NULL)",
    "CREATE TABLE audit_log (seq INTEGER PRIMARY KEY, ts TIMESTAMP, payload TEXT NOT NULL, prev_hash VARCHAR(64) NOT NULL, hash VARCHAR(64) NOT NULL)",
    "CREATE TABLE signatures (id INTEGER PRIMARY KEY, ts TIMESTAMP, member_id INTEGER NOT NULL, user_id INTEGER NOT NULL, kind VARCHAR(20), png_enc TEXT NOT NULL, sha256 VARCHAR(64) NOT NULL)",
]
NOVES = {"users.last_totp_step", "members.baixa_en", "members.suprimit_en", "members.doc_verificat", "members.avalador_id",
         "audit_log.alg", "signatures.text_sha256"}
TAULES = {"consents", "audit_anchors", "member_limits", "batches", "movement_batches"}


def _migra(engine):
    with engine.begin() as c:
        for ddl in ANTIC:
            c.execute(text(ddl))
        c.execute(text("INSERT INTO locals (id, nom) VALUES (1, 'L')"))
        c.execute(text("INSERT INTO users (id, username, password_hash, totp_secret_enc, role, active) VALUES (1, 'u', 'h', 't', 'admin', true)"))
        c.execute(text("INSERT INTO members (id, local_id, nom_enc, document_enc, document_idx, naixement_enc, estat, creat_per) VALUES (1, 1, 'n', 'd', 'x', 'b', 'actiu', 1)"))
        c.execute(text("INSERT INTO audit_log (seq, payload, prev_hash, hash) VALUES (1, '{}', 'a', 'b')"))
    assert NOVES <= set(schema.missing_columns(engine))
    schema.install(engine)
    assert schema.missing_columns(engine) == []
    assert TAULES <= set(inspect(engine).get_table_names())
    schema.install(engine)  # idempotent
    with engine.connect() as c:
        assert c.execute(text("SELECT doc_verificat FROM members WHERE id = 1")).scalar() in (False, 0)
        assert c.execute(text("SELECT alg FROM audit_log WHERE seq = 1")).scalar() is None
        assert c.execute(text("SELECT last_totp_step FROM users")).scalar() is None


def test_migracio_de_columnes_sqlite(tmp_path):
    _migra(create_engine(f"sqlite:///{tmp_path / 'a.db'}"))


@pg_only
def test_migracio_de_columnes_postgres():
    pg = os.environ["CLUB_TEST_PG_URL"]
    nom = "t_" + uuid.uuid4().hex[:12]
    admin = create_engine(pg)
    with admin.begin() as c:
        c.execute(text(f"CREATE SCHEMA {nom}"))
    engine = create_engine(pg, connect_args={"options": f"-csearch_path={nom}"})
    try:
        _migra(engine)
    finally:
        engine.dispose()
        with admin.begin() as c:
            c.execute(text(f"DROP SCHEMA {nom} CASCADE"))
        admin.dispose()

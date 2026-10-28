"""Actualització d'una base de dades existent: les taules noves s'han de poder crear sense tocar les dades."""
import pytest
from sqlalchemy import create_engine, inspect, text

from app import cli, crypto, schema
from app.db import Base
from app.main import get_db_factory

TAULES_NOVES = {"quotes", "member_photos", "member_cards", "local_settings", "login_attempts", "device_profiles", "product_images", "discounts", "movement_discounts", "dispensing_rules", "inventory_sessions", "inventory_counts", "price_lines", "product_prices", "member_price_lines", "container_types", "containers"}


def bd_antiga(url):
    """Una base de dades tal com la deixava la versió anterior: sense les taules noves."""
    engine = create_engine(url)
    antigues = [t for t in Base.metadata.sorted_tables if t.name not in TAULES_NOVES]
    Base.metadata.create_all(engine, tables=antigues)
    return engine


@pytest.fixture
def entorn(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'club.db'}"
    monkeypatch.setenv("CLUB_DATABASE_URL", url)
    monkeypatch.setenv("CLUB_FIELD_KEY", crypto.generate_key())
    monkeypatch.setenv("CLUB_INDEX_KEY", "clau-index-de-prova")
    monkeypatch.delenv("CLUB_APP_DATABASE_URL", raising=False)
    return url


def test_missing_tables_detecta_les_taules_noves(entorn):
    engine = bd_antiga(entorn)
    assert set(schema.missing_tables(engine)) == TAULES_NOVES
    schema.install(engine)
    assert schema.missing_tables(engine) == []


def test_lapp_no_arrenca_amb_un_missatge_clar_si_falten_taules(entorn):
    bd_antiga(entorn)
    with pytest.raises(RuntimeError) as e:
        get_db_factory()
    assert "actualitzar-bd" in str(e.value) and "quotes" in str(e.value)


def test_ordre_actualitzar_bd_crea_les_taules_i_respecta_les_dades(entorn):
    engine = bd_antiga(entorn)
    with engine.begin() as c:
        c.execute(text("INSERT INTO locals (id, nom) VALUES (1, 'Local existent')"))
    assert cli.main(["actualitzar-bd"]) == 0
    assert TAULES_NOVES <= set(inspect(engine).get_table_names())
    with engine.connect() as c:
        assert c.execute(text("SELECT nom FROM locals")).scalar() == "Local existent"
    assert cli.main(["actualitzar-bd"]) == 0  # es pot repetir sense problemes
    get_db_factory()  # ara sí arrenca


def test_ordre_actualitzar_bd_no_accepta_arguments_de_mes(entorn):
    assert cli.main(["actualitzar-bd", "extra"]) == 2


# ---------- sobre PostgreSQL real ----------
import os
import secrets
import uuid

pg_only = pytest.mark.skipif(not os.environ.get("CLUB_TEST_PG_URL"), reason="Cal PostgreSQL (CLUB_TEST_PG_URL)")


@pg_only
def test_actualitzar_bd_a_postgres_crea_taules_triggers_i_permisos(monkeypatch):
    base = os.environ["CLUB_TEST_PG_URL"]
    nom = "mig_" + uuid.uuid4().hex[:10]
    rol = "club_app_" + uuid.uuid4().hex[:8]
    admin = create_engine(base)
    with admin.begin() as c:
        c.execute(text(f"CREATE SCHEMA {nom}"))
    url = base + ("&" if "?" in base else "?") + f"options=-csearch_path%3D{nom}"
    monkeypatch.setenv("CLUB_DATABASE_URL", url)
    monkeypatch.setenv("CLUB_APP_ROLE", rol)
    monkeypatch.setenv("CLUB_FIELD_KEY", crypto.generate_key())
    monkeypatch.setenv("CLUB_INDEX_KEY", "clau-index-de-prova")
    try:
        engine = create_engine(url)
        antigues = [t for t in Base.metadata.sorted_tables if t.name not in TAULES_NOVES]
        Base.metadata.create_all(engine, tables=antigues)
        schema.create_app_role(engine, rol, secrets.token_urlsafe(16))  # el rol ja existia abans d'actualitzar
        assert set(schema.missing_tables(engine)) == TAULES_NOVES
        assert cli.main(["actualitzar-bd"]) == 0
        assert schema.missing_tables(engine) == []
        with engine.connect() as c:
            priv = lambda taula, op: c.execute(text("SELECT has_table_privilege(:r, :t, :o)"), {"r": rol, "t": f"{nom}.{taula}", "o": op}).scalar()
            assert priv("quotes", "INSERT") and priv("quotes", "SELECT") and not priv("quotes", "UPDATE") and not priv("quotes", "DELETE")
            assert priv("member_photos", "INSERT") and not priv("member_photos", "DELETE")
            assert priv("member_cards", "UPDATE") and priv("local_settings", "DELETE") and priv("login_attempts", "DELETE")
            triggers = set(c.execute(text("SELECT event_object_table FROM information_schema.triggers WHERE trigger_schema = :s"), {"s": nom}).scalars())
            assert {"quotes", "member_photos"} <= triggers
        engine.dispose()
    finally:
        with admin.begin() as c:
            c.execute(text(f"DROP SCHEMA {nom} CASCADE"))
            c.execute(text(f"DROP ROLE IF EXISTS {rol}"))
        admin.dispose()

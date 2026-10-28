"""Actualització d'una base de dades existent: les taules noves s'han de poder crear sense tocar les dades."""
import pytest
from sqlalchemy import create_engine, inspect, text

from app import cli, crypto, schema
from app.db import Base
from app.main import get_db_factory

TAULES_NOVES = {"quotes", "member_photos", "member_cards", "local_settings", "login_attempts"}


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

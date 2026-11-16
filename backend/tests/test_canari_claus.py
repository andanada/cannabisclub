"""Canari de claus: la BD recorda amb quines claus va néixer; arrencar amb unes altres és un error, no un 500 a mig servei."""
import pytest
from cryptography.fernet import Fernet
from sqlalchemy import select

from app import canari, crypto
from app.models import ConfigCanari, ImmutableError
from tests.test_api import ctx, env, token  # noqa: F401


def claus(factory):
    with factory() as s:
        return {c.clau: c.valor for c in s.scalars(select(ConfigCanari))}


def test_la_primera_vegada_es_crea_i_la_segona_es_comprova(ctx):
    _, factory, _ = ctx
    assert claus(factory) == {}
    assert canari.comprova(factory) == "creat"
    c = claus(factory)
    assert set(c) == {"field", "index", "audit"}
    assert "club-canari" not in "".join(c.values())                      # el text pla del canari no es desa enlloc
    assert crypto.decrypt(c["field"]) == canari.TEXT
    assert canari.comprova(factory) == "ok"
    assert claus(factory) == c                                           # i no es reescriu


def test_clau_de_camp_equivocada_atura_l_arrencada_amb_un_missatge_clar(ctx, monkeypatch):
    _, factory, _ = ctx
    canari.comprova(factory)
    monkeypatch.setenv("CLUB_FIELD_KEY", Fernet.generate_key().decode())
    with pytest.raises(RuntimeError) as e:
        canari.comprova(factory)
    assert "CLUB_FIELD_KEY" in str(e.value) and "NO són les" in str(e.value)


def test_clau_d_index_o_d_auditoria_equivocada_tambe_atura(ctx, monkeypatch):
    _, factory, _ = ctx
    canari.comprova(factory)
    monkeypatch.setenv("CLUB_INDEX_KEY", "una-clau-diferent-de-la-de-la-base-de-dades")
    with pytest.raises(RuntimeError) as e:
        canari.comprova(factory)
    assert "CLUB_INDEX_KEY" in str(e.value) or "CLUB_AUDIT_KEY" in str(e.value)


def test_sense_clau_de_camp_diu_que_falta_en_lloc_d_un_error_critic(ctx, monkeypatch):
    _, factory, _ = ctx
    canari.comprova(factory)
    monkeypatch.delenv("CLUB_FIELD_KEY")
    with pytest.raises(RuntimeError) as e:
        canari.comprova(factory)
    assert "CLUB_FIELD_KEY" in str(e.value)


def test_el_canari_no_es_pot_modificar_ni_esborrar(ctx):
    _, factory, _ = ctx
    canari.comprova(factory)
    with factory() as s:
        c = s.scalar(select(ConfigCanari))
        c.valor = "x"
        with pytest.raises(ImmutableError):
            s.commit()
        s.rollback()
        with pytest.raises(ImmutableError):
            s.delete(s.scalar(select(ConfigCanari)))
            s.commit()


def test_get_db_factory_comprova_el_canari(env, monkeypatch, tmp_path):
    """L'arrencada real (no la de les proves, que passa la seva pròpia factoria) comprova les claus."""
    from app import main, schema
    from app.db import make_engine
    url = f"sqlite:///{tmp_path / 'c.db'}"
    monkeypatch.setenv("CLUB_DATABASE_URL", url)
    monkeypatch.delenv("CLUB_APP_DATABASE_URL", raising=False)
    schema.install(make_engine())
    main.get_db_factory()                                                # crea el canari
    monkeypatch.setenv("CLUB_FIELD_KEY", Fernet.generate_key().decode())
    with pytest.raises(RuntimeError):
        main.get_db_factory()

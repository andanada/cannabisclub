"""Estabilitat i rendiment per a producció: salut, errors controlats, índexs, consultes, sessions."""
from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine, event, func, inspect, select, text

from app import cli, crypto, schema, service
from app.db import Base
from app.models import SessionToken
from tests.test_api import PASS, ctx, env, token  # noqa: F401
from tests.test_stock import setup_data


def test_salut_respon_sense_autenticacio_i_comprova_la_bd(ctx):
    client, factory, sec = ctx
    r = client.get("/salut")
    assert r.status_code == 200 and r.json() == {"ok": True}
    assert "no-store" in r.headers["cache-control"]


def test_salut_dona_503_si_la_bd_falla(ctx, monkeypatch):
    client, factory, sec = ctx
    from sqlalchemy.orm import Session
    real = Session.execute
    monkeypatch.setattr(Session, "execute", lambda self, stmt, *a, **k: (_ for _ in ()).throw(RuntimeError("bd caiguda")) if "SELECT 1" in str(stmt) else real(self, stmt, *a, **k))
    r = client.get("/salut")
    assert r.status_code == 503 and r.json() == {"ok": False}


def test_un_error_inesperat_no_filtra_detalls_i_porta_un_identificador(ctx, monkeypatch):
    client, factory, sec = ctx
    enc = token(client, sec, "enc")
    monkeypatch.setattr("app.stock.stock_by_product", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("secret intern: password=XYZ")))
    from fastapi.testclient import TestClient
    quiet = TestClient(client.app, raise_server_exceptions=False)
    r = quiet.get("/locals/1/estoc", headers=enc)
    assert r.status_code == 500
    cos = r.json()
    assert "XYZ" not in r.text and "secret" not in r.text and "Traceback" not in r.text
    assert cos["detail"] and len(cos["id"]) >= 8


def test_estoc_no_fa_una_consulta_per_producte(ctx):
    client, factory, sec = ctx
    enc = token(client, sec, "enc")
    for i in range(12):
        client.post("/productes", json={"local_id": 1, "nom": f"P{i}", "preu_cent_per_g": 100}, headers=enc)
    comptador = {"n": 0}
    engine = factory().get_bind()

    @event.listens_for(engine, "before_cursor_execute")
    def _conta(*a):
        comptador["n"] += 1
    assert len(client.get("/locals/1/estoc", headers=enc).json()) == 12
    assert len(client.get("/locals/1/productes", headers=enc).json()) == 12
    event.remove(engine, "before_cursor_execute", _conta)
    assert comptador["n"] <= 14, comptador["n"]  # abans: >24 (una per producte i endpoint)


def test_estoc_agrupat_dona_els_mateixos_valors(ctx):
    client, factory, sec = ctx
    enc = token(client, sec, "enc")
    mid, pid = setup_data(client, enc, factory)
    client.post("/dispensacions", json={"member_id": mid, "product_id": pid, "grams": "2.5"}, headers=enc)
    assert client.get("/locals/1/estoc", headers=enc).json()[0]["estoc_g"] == "7.5"
    assert client.get("/locals/1/informe/estoc", headers=enc).json()["productes"][0]["estoc_g"] == "7.5"


# ---------- índexs ----------

def bd_sense_index(url):
    engine = create_engine(url)
    Base.metadata.create_all(engine)
    with engine.begin() as c:
        for ix in [i["name"] for t in inspect(engine).get_table_names() for i in inspect(engine).get_indexes(t) if i["name"].startswith("ix_")]:
            c.execute(text(f'DROP INDEX "{ix}"'))
    return engine


def test_els_index_que_falten_es_detecten_i_actualitzar_bd_els_crea(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'club.db'}"
    monkeypatch.setenv("CLUB_DATABASE_URL", url)
    monkeypatch.setenv("CLUB_FIELD_KEY", crypto.generate_key())
    monkeypatch.setenv("CLUB_INDEX_KEY", "x")
    engine = bd_sense_index(url)
    falten = schema.missing_indexes(engine)
    assert "ix_stock_mov_product" in falten and "ix_cash_entries_local_ts" in falten
    assert cli.main(["actualitzar-bd"]) == 0
    assert schema.missing_indexes(engine) == []
    assert cli.main(["actualitzar-bd"]) == 0  # idempotent


# ---------- sessions i capçaleres ----------

def test_el_login_purga_les_sessions_caducades(ctx):
    client, factory, sec = ctx
    token(client, sec, "enc")
    s = factory()
    s.add(SessionToken(token_hash="x" * 64, user_id=1, expires_at=datetime.now(timezone.utc) - timedelta(days=1)))
    s.commit()
    s.close()
    token(client, sec, "disp")
    s = factory()
    assert s.get(SessionToken, "x" * 64) is None
    s.close()


def test_hsts_nomes_si_es_demana(ctx, monkeypatch):
    client, factory, sec = ctx
    assert "strict-transport-security" not in client.get("/salut").headers
    monkeypatch.setenv("CLUB_HSTS", "1")
    assert "max-age" in client.get("/salut").headers["strict-transport-security"]

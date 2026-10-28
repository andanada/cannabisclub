import os
import secrets

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError

from app import schema
from app.db import make_session_factory
from app.main import create_app
from fastapi.testclient import TestClient
from tests.test_api import ctx, env, token  # noqa: F401
from tests.test_stock import setup_data

pg_only = pytest.mark.skipif(not os.environ.get("CLUB_TEST_PG_URL"), reason="Cal PostgreSQL (CLUB_TEST_PG_URL)")
ROLE = "club_app_test"


@pytest.fixture
def app_engine(ctx):
    client, owner_factory, sec = ctx
    with owner_factory() as s:
        owner_engine = s.get_bind()
        schema_name = s.execute(text("SELECT current_schema()")).scalar()
    pw = secrets.token_urlsafe(16)
    schema.create_app_role(owner_engine, ROLE, pw)
    schema.grant_app_role(owner_engine, ROLE)
    eng = create_engine(owner_engine.url.set(username=ROLE, password=pw),
                        connect_args={"options": f"-csearch_path={schema_name}"})
    yield eng, client, sec, owner_factory
    eng.dispose()


@pg_only
def test_l_aplicacio_funciona_amb_el_rol_sense_privilegis(app_engine):
    eng, owner_client, sec, owner_factory = app_engine
    client = TestClient(create_app(make_session_factory(eng)))
    enc = token(client, sec, "enc")
    mid, pid = setup_data(client, enc, owner_factory)
    assert client.post("/caixa/obrir", json={"local_id": 1, "opening_cent": 1000}, headers=enc).status_code == 201
    d = client.post("/dispensacions", json={"member_id": mid, "product_id": pid, "grams": "2"}, headers=enc)
    assert d.status_code == 201
    assert client.post("/cobraments", json={"movement_id": d.json()["id"], "metode": "efectiu"}, headers=enc).status_code == 201
    assert client.post(f"/socis/{mid}/estat", json={"estat": "suspes"}, headers=enc).status_code == 200
    assert client.post(f"/moviments/{d.json()['id']}/correccio", json={"nota": "x"}, headers=enc).status_code == 422  # cobrada
    assert client.get("/auditoria/verificar", headers=token(client, sec, "admin")).json()["integra"] is True
    assert client.post("/fitxatge", json={"local_id": 1, "tipus": "entrada"}, headers=enc).status_code == 201


@pg_only
def test_el_rol_de_l_aplicacio_fa_servir_les_funcions_noves(app_engine):
    """Quotes, foto, carnet, ajustos, productes, usuaris i bloqueig de login amb el rol sense privilegis."""
    import base64
    import pyotp
    eng, owner_client, sec, owner_factory = app_engine
    client = TestClient(create_app(make_session_factory(eng)))
    enc, admin = token(client, sec, "enc"), token(client, sec, "admin")
    mid, pid = setup_data(client, enc, owner_factory)
    assert client.post("/caixa/obrir", json={"local_id": 1, "opening_cent": 0}, headers=enc).status_code == 201
    assert client.post(f"/socis/{mid}/quotes", json={"import_cent": 2500, "metode": "efectiu", "mesos": 3}, headers=enc).status_code == 201
    assert client.get(f"/socis/{mid}", headers=enc).json()["quota"]["al_dia"] is True
    jpeg = base64.b64encode(b"\xff\xd8\xff\xe0" + bytes(range(256)) * 2).decode()
    assert client.post(f"/socis/{mid}/foto", json={"image_base64": jpeg}, headers=enc).status_code == 201
    assert client.post(f"/socis/{mid}/carnet", json={"codi": "CARNET-1"}, headers=enc).status_code == 201
    assert client.post(f"/socis/{mid}/carnet", json={"codi": "CARNET-2"}, headers=enc).status_code == 201  # actualitza i desactiva
    assert client.get("/locals/1/socis/carnet?codi=CARNET-2", headers=enc).json()["id"] == mid
    assert client.patch(f"/socis/{mid}", json={"nom": "Anna Garcia"}, headers=enc).status_code == 200
    assert client.patch(f"/productes/{pid}", json={"preu_cent_per_g": 900}, headers=enc).status_code == 200
    assert client.put("/locals/1/config", json={"quota_obligatoria": True, "quota_cent": 2500}, headers=admin).status_code == 200
    assert client.put("/locals/1/config", json={"quota_cent": 0}, headers=admin).status_code == 200  # esborra una fila d'ajustos
    assert client.get("/locals/1/informe/vendes", params={"des": "2020-01-01", "fins": "2099-01-01"}, headers=enc).status_code == 200
    d = [u for u in client.get("/usuaris", headers=admin).json() if u["username"] == "disp"][0]
    assert client.patch(f"/usuaris/{d['id']}", json={"role": "encarregat", "local_ids": [1, 2]}, headers=admin).status_code == 200
    # bloqueig: 5 fallades i, esborrar intents vells i reiniciar al login correcte, també amb el rol restringit
    for _ in range(5):
        client.post("/auth/login", json={"username": "disp", "password": "contrasenya-equivocada", "totp": "000000"})
    assert client.post("/auth/login", json={"username": "disp", "password": "x", "totp": "1"}).status_code == 429
    assert client.get("/auditoria/verificar", headers=admin).json()["integra"] is True


@pg_only
@pytest.mark.parametrize("sql,fragment", [
    ("UPDATE quotes SET mesos = 1", "permission denied"),
    ("DELETE FROM member_photos", "permission denied"),
    ("UPDATE stock_movements SET delta_mg = 1", "permission denied"),
    ("DELETE FROM audit_log", "permission denied"),
    ("TRUNCATE audit_log CASCADE", "permission denied"),
    ("ALTER TABLE audit_log DISABLE TRIGGER USER", "must be owner"),
    ("DROP TRIGGER audit_log_no_change ON audit_log", "must be owner"),
    ("DROP TABLE members", "must be owner"),
    ("CREATE TABLE intrus (x int)", "permission denied"),
    ("ALTER TABLE cash_entries DISABLE TRIGGER ALL", "must be owner"),
])
def test_el_rol_de_l_aplicacio_no_pot_saltar_les_proteccions(app_engine, sql, fragment):
    eng, *_ = app_engine
    with eng.connect() as c:
        with pytest.raises(DBAPIError) as e:
            c.execute(text(sql))
            c.commit()
        assert fragment in str(e.value)


@pg_only
def test_el_rol_no_es_superusuari_ni_propietari(app_engine):
    eng, *_ = app_engine
    with eng.connect() as c:
        r = c.execute(text("SELECT rolsuper, rolcreaterole, rolcreatedb FROM pg_roles WHERE rolname = current_user")).one()
        assert r == (False, False, False)
        owner = c.execute(text("SELECT tableowner FROM pg_tables WHERE tablename = 'audit_log' AND schemaname = current_schema()")).scalar()
        assert owner != ROLE

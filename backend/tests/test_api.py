import pyotp
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.pool import StaticPool

from app import crypto, security
from app.db import Base, make_session_factory
from app.main import create_app
from app.models import AuditLog, Local, Member, User, UserLocal

PASS = "contrasenya-molt-llarga"


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv("CLUB_FIELD_KEY", crypto.generate_key())
    monkeypatch.setenv("CLUB_INDEX_KEY", "clau-d-index-per-a-proves")


@pytest.fixture
def ctx(env):
    import os
    import uuid
    from sqlalchemy import create_engine, text
    from app import schema
    pg = os.environ.get("CLUB_TEST_PG_URL")
    schema_name = None
    if pg:
        schema_name = "t_" + uuid.uuid4().hex[:12]
        admin = create_engine(pg)
        with admin.begin() as c:
            c.execute(text(f"CREATE SCHEMA {schema_name}"))
        engine = create_engine(pg, connect_args={"options": f"-csearch_path={schema_name}"})
    else:
        engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    schema.install(engine)
    factory = make_session_factory(engine)
    s = factory()
    s.add_all([Local(id=1, nom="Local A"), Local(id=2, nom="Local B")])
    secrets_ = {}
    for name, role, locals_ in [("admin", "admin", []), ("enc", "encarregat", [1]), ("disp", "dispensador", [1])]:
        sec = security.new_totp_secret()
        secrets_[name] = sec
        u = User(username=name, password_hash=security.hash_password(PASS),
                 totp_secret_enc=crypto.encrypt(sec), role=role)
        s.add(u)
        s.flush()
        for lid in locals_:
            s.add(UserLocal(user_id=u.id, local_id=lid))
    s.commit()
    if pg:  # hem inserit locals amb id explícit: avança la seqüència
        s.execute(text("SELECT setval(pg_get_serial_sequence('locals', 'id'), 2)"))
        s.commit()
    s.close()
    yield TestClient(create_app(factory)), factory, secrets_
    if pg:
        engine.dispose()
        with admin.begin() as c:
            c.execute(text(f"DROP SCHEMA {schema_name} CASCADE"))
        admin.dispose()


def token(client, secrets_, name):
    r = client.post("/auth/login", json={"username": name, "password": PASS, "totp": pyotp.TOTP(secrets_[name]).now()})
    assert r.status_code == 200
    return {"Authorization": f"Bearer {r.json()['token']}"}


SOCI = {"local_id": 1, "nom": "Anna Prova", "document": "12345678Z", "naixement": "1990-05-20",
        "telefon": "600111222", "email": "anna@example.com"}


def test_login_incorrecte(ctx):
    client, _, sec = ctx
    r = client.post("/auth/login", json={"username": "enc", "password": "mala-contrasenya", "totp": "123456"})
    assert r.status_code == 401
    r = client.post("/auth/login", json={"username": "enc", "password": PASS, "totp": "000000" if pyotp.TOTP(sec["enc"]).now() != "000000" else "111111"})
    assert r.status_code == 401


def test_sense_token_no_hi_ha_acces(ctx):
    client, _, _ = ctx
    assert client.post("/socis", json=SOCI).status_code == 401
    assert client.get("/socis/1").status_code == 401


def test_alta_i_consulta_amb_dades_xifrades_a_la_bd(ctx):
    client, factory, sec = ctx
    h = token(client, sec, "enc")
    r = client.post("/socis", json=SOCI, headers=h)
    assert r.status_code == 201
    mid = r.json()["id"]
    v = client.get(f"/socis/{mid}", headers=h).json()
    assert v["nom"] == "Anna Prova" and v["document"] == "12345678Z"
    s = factory()
    raw = s.execute(text("select nom_enc, document_enc, telefon_enc, email_enc from members")).one()
    assert all("Anna" not in x and "12345678" not in x and "600111" not in x and "anna@" not in x for x in raw)
    s.close()


def test_menor_dedat_duplicat_i_rols(ctx):
    client, _, sec = ctx
    enc, disp = token(client, sec, "enc"), token(client, sec, "disp")
    assert client.post("/socis", json={**SOCI, "naixement": "2015-01-01"}, headers=enc).status_code == 422
    assert client.post("/socis", json=SOCI, headers=enc).status_code == 201
    assert client.post("/socis", json={**SOCI, "document": " 12345678 z "}, headers=enc).status_code == 422
    assert client.post("/socis", json={**SOCI, "document": "99999999R"}, headers=disp).status_code == 403


def test_aillament_entre_locals(ctx):
    client, _, sec = ctx
    enc = token(client, sec, "enc")
    assert client.post("/socis", json={**SOCI, "local_id": 2}, headers=enc).status_code == 403
    admin = token(client, sec, "admin")
    r = client.post("/socis", json={**SOCI, "local_id": 2}, headers=admin)
    assert r.status_code == 201
    assert client.get(f"/socis/{r.json()['id']}", headers=enc).status_code == 403


def test_auditoria_registra_i_detecta_manipulacio(ctx):
    client, factory, sec = ctx
    enc, admin = token(client, sec, "enc"), token(client, sec, "admin")
    mid = client.post("/socis", json=SOCI, headers=enc).json()["id"]
    client.get(f"/socis/{mid}", headers=enc)
    assert client.get("/auditoria/verificar", headers=admin).json() == {"integra": True, "primera_alterada": None}
    s = factory()
    if s.bind.dialect.name == "postgresql":  # simula un atacant amb permisos de propietari
        s.execute(text("ALTER TABLE audit_log DISABLE TRIGGER USER"))
    row = s.scalars(select(AuditLog).where(AuditLog.payload.like("%alta_soci%"))).one()
    row.payload = row.payload.replace('"per":2', '"per":1')
    s.commit()
    s.close()
    res = client.get("/auditoria/verificar", headers=admin).json()
    assert res["integra"] is False and res["primera_alterada"] is not None
    assert client.get("/auditoria/verificar", headers=enc).status_code == 403


def test_segon_factor_es_pot_desactivar_nomes_amb_la_variable(ctx, monkeypatch):
    client, _factory, _sec = ctx
    assert client.get("/auth/opcions").json() == {"totp": True}
    sense_codi = {"username": "enc", "password": PASS}
    assert client.post("/auth/login", json=sense_codi).status_code == 401  # per defecte el codi és obligatori
    monkeypatch.setenv("CLUB_TOTP", "0")
    assert client.get("/auth/opcions").json() == {"totp": False}
    assert client.post("/auth/login", json={**sense_codi, "password": "mala-contrasenya"}).status_code == 401  # la contrasenya segueix sent obligatòria
    assert client.post("/auth/login", json=sense_codi).status_code == 200

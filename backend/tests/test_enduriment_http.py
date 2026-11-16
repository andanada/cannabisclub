"""Enduriment de la capa HTTP: documentació oberta, fitxers de prova, mida del cos, límits dels camps."""
import json

from app.db import make_engine
from tests.test_api import PASS, SOCI, ctx, env, token  # noqa: F401


def test_no_s_exposen_docs_ni_esquema_openapi(ctx):
    client, _, _ = ctx
    app = client.app
    assert app.docs_url is None and app.redoc_url is None and app.openapi_url is None
    for p in ("/docs", "/redoc", "/openapi.json"):
        assert client.get(p).status_code == 404


def test_no_es_serveix_la_carpeta_de_proves_del_frontend(ctx):
    client, _, _ = ctx
    assert client.get("/test/carnets.test.js").status_code == 404
    assert client.get("/test/").status_code == 404
    assert client.get("/app.js").status_code == 200  # la resta segueix servint-se


def test_l_arrel_serveix_index_i_els_ocults_segueixen_bloquejats(ctx):
    client, _, _ = ctx
    r = client.get("/")   # Starlette demana el camí «.» per a l'arrel: no s'ha de confondre amb un fitxer ocult
    assert r.status_code == 200 and "<html" in r.text.lower()
    for p in ("/.env", "/.git/config", "/a/../.env"):
        assert client.get(p).status_code == 404


def test_el_motor_amaga_els_parametres_sql(monkeypatch, tmp_path):
    e = make_engine(f"sqlite:///{tmp_path / 'x.db'}")
    assert e.hide_parameters is True


def test_cos_massa_gran_es_rebutja_amb_413(ctx):
    client, _, _ = ctx
    gran = json.dumps({"username": "a", "password": "x" * 2_000_000, "totp": ""})
    r = client.post("/auth/login", content=gran, headers={"Content-Type": "application/json"})
    assert r.status_code == 413


def test_cos_massa_gran_sense_content_length_tambe_es_rebutja(ctx):
    client, _, _ = ctx
    def tros():
        yield b'{"username":"a","password":"'
        for _ in range(40):
            yield b"x" * 50_000
        yield b'","totp":""}'
    r = client.post("/auth/login", content=tros(), headers={"Content-Type": "application/json"})
    assert r.status_code == 413


def test_contrasenya_i_config_i_limits_tenen_cotes(ctx):
    client, _, sec = ctx
    admin = token(client, sec, "admin")
    r = client.post("/usuaris", json={"username": "nou1", "password": "x" * 300, "role": "dispensador"}, headers=admin)
    assert r.status_code == 422
    r = client.post("/locals/1/dispositius", json={"kind": "bascula", "nom": "b", "config": {"k": "x" * 5000}}, headers=admin)
    assert r.status_code == 422
    for body in ({"limit_diari_g": "1e30"}, {"limit_mensual_g": "99999999999"}, {"tolerancia_bascula_g": "5000"}):
        assert client.put("/locals/1/limits", json=body, headers=admin).status_code == 422, body


def test_limits_arrodoneixen_half_up_validen_coherencia_i_auditen_abans_i_despres(ctx):
    from sqlalchemy import select
    from app.models import AuditLog, Local
    client, factory, sec = ctx
    admin = token(client, sec, "admin")
    r = client.put("/locals/1/limits", json={"limit_diari_g": "1.0005", "limit_mensual_g": "10", "tolerancia_bascula_g": "0.0019"}, headers=admin)
    assert r.status_code == 200
    s = factory()
    loc = s.get(Local, 1)
    assert (loc.limit_diari_mg, loc.limit_mensual_mg, loc.tolerancia_bascula_mg) == (1001, 10000, 2)
    s.close()
    # el diari no pot superar el mensual
    assert client.put("/locals/1/limits", json={"limit_diari_g": "20", "limit_mensual_g": "10"}, headers=admin).status_code == 422
    assert client.put("/locals/1/limits", json={"limit_diari_g": "-1"}, headers=admin).status_code == 422
    assert client.put("/locals/1/limits", json={"limit_diari_g": "NaN"}, headers=admin).status_code == 422
    client.put("/locals/1/limits", json={"limit_diari_g": "5", "limit_mensual_g": "50"}, headers=admin)
    s = factory()
    ult = [json.loads(a.payload) for a in s.scalars(select(AuditLog).order_by(AuditLog.seq)) if '"canvi_limits"' in a.payload][-1]
    s.close()
    assert ult["abans"] == {"diari_mg": 1001, "mensual_mg": 10000, "tolerancia_mg": 2}
    assert ult["despres"] == {"diari_mg": 5000, "mensual_mg": 50000, "tolerancia_mg": None}

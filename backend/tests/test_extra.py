from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pyotp
from sqlalchemy import select

from app import personal
from app.models import Local, User
from tests.test_api import PASS, SOCI, ctx, env, token  # noqa: F401
from tests.test_stock import estoc, setup_data


def test_merma_i_ajust(ctx):
    client, factory, sec = ctx
    enc, disp = token(client, sec, "enc"), token(client, sec, "disp")
    mid, pid = setup_data(client, enc, factory)  # 10 g
    assert client.post("/moviments/merma", json={"product_id": pid, "grams": "0.5", "nota": "humitat"}, headers=enc).status_code == 201
    assert Decimal(estoc(client, enc)) == Decimal("9.5")
    assert client.post("/moviments/merma", json={"product_id": pid, "grams": "50", "nota": "massa"}, headers=enc).status_code == 422
    assert client.post("/moviments/merma", json={"product_id": pid, "grams": "1", "nota": "no puc"}, headers=disp).status_code == 403
    assert client.post("/moviments/ajust", json={"product_id": pid, "grams_reals": "9.5", "nota": "recompte"}, headers=enc).status_code == 422
    assert client.post("/moviments/ajust", json={"product_id": pid, "grams_reals": "8", "nota": "recompte"}, headers=enc).status_code == 201
    assert Decimal(estoc(client, enc)) == 8


def test_tolerancia_de_bascula(ctx):
    client, factory, sec = ctx
    enc, admin = token(client, sec, "enc"), token(client, sec, "admin")
    mid, pid = setup_data(client, enc, factory)
    assert client.put("/locals/1/limits", json={"tolerancia_bascula_g": "0.1"}, headers=enc).status_code == 403
    assert client.put("/locals/1/limits", json={"tolerancia_bascula_g": "0.1"}, headers=admin).status_code == 200
    bad = client.post("/dispensacions", json={"member_id": mid, "product_id": pid, "grams": "2", "pes_bascula_g": "2.5"}, headers=enc)
    assert bad.status_code == 422 and "bàscula" in bad.json()["detail"]
    ok = client.post("/dispensacions", json={"member_id": mid, "product_id": pid, "grams": "2", "pes_bascula_g": "2.05"}, headers=enc)
    assert ok.status_code == 201


def test_estat_soci_checkin_i_cerca(ctx):
    client, factory, sec = ctx
    enc, disp, admin = token(client, sec, "enc"), token(client, sec, "disp"), token(client, sec, "admin")
    mid = client.post("/socis", json=SOCI, headers=enc).json()["id"]
    assert client.post(f"/socis/{mid}/entrada", headers=disp).status_code == 201
    assert client.post(f"/socis/{mid}/estat", json={"estat": "suspes"}, headers=disp).status_code == 403
    assert client.post(f"/socis/{mid}/estat", json={"estat": "suspes"}, headers=enc).status_code == 200
    assert client.post(f"/socis/{mid}/entrada", headers=disp).status_code == 422       # suspès no entra
    assert client.post(f"/socis/{mid}/estat", json={"estat": "baixa"}, headers=enc).status_code == 200
    assert client.post(f"/socis/{mid}/estat", json={"estat": "actiu"}, headers=enc).status_code == 422  # reactivar: només admin
    assert client.post(f"/socis/{mid}/estat", json={"estat": "actiu"}, headers=admin).status_code == 200
    r = client.get("/locals/1/socis/cerca", params={"document": " 12345678z "}, headers=disp)
    assert r.status_code == 200 and r.json()["id"] == mid
    assert client.get("/locals/1/socis/cerca", params={"document": "00000000T"}, headers=disp).status_code == 404
    assert client.get("/locals/2/socis/cerca", params={"document": "12345678Z"}, headers=enc).status_code == 403


def test_fitxatge_maquina_d_estats(ctx):
    client, factory, sec = ctx
    h = token(client, sec, "disp")
    f = lambda t: client.post("/fitxatge", json={"local_id": 1, "tipus": t}, headers=h).status_code
    assert f("sortida") == 422 and f("pausa_inici") == 422
    assert f("entrada") == 201 and f("entrada") == 422
    assert f("pausa_inici") == 201 and f("sortida") == 422 and f("pausa_fi") == 201
    assert f("sortida") == 201 and f("sortida") == 422
    assert client.post("/fitxatge", json={"local_id": 2, "tipus": "entrada"}, headers=h).status_code == 403


def test_hores_treballades_amb_pauses(ctx):
    client, factory, sec = ctx
    s = factory()
    u = s.scalars(select(User).where(User.username == "disp")).one()
    base = datetime.now(timezone.utc).replace(hour=8, minute=0, second=0, microsecond=0)
    for dt, t in [(0, "entrada"), (4 * 3600, "pausa_inici"), (4 * 3600 + 1800, "pausa_fi"), (9 * 3600, "sortida"), (24 * 3600 - 3600, "entrada")]:
        personal.clock(s, u, 1, t, now=base + timedelta(seconds=dt))
    s.close()
    enc = token(client, sec, "enc")
    des = (base - timedelta(days=1)).date().isoformat()
    fins = (base + timedelta(days=2)).date().isoformat()
    r = client.get("/locals/1/hores", params={"des": des, "fins": fins}, headers=enc).json()
    uid = str(u.id)
    assert r[uid]["segons_treballats"] == 9 * 3600 - 1800 and r[uid]["torns"] == 1
    assert r[uid]["torn_obert"] is True   # l'última entrada no té sortida
    assert client.get("/locals/1/hores", params={"des": des, "fins": fins}, headers=token(client, sec, "disp")).status_code == 403


def test_admin_crea_locals_usuaris_i_el_nou_usuari_pot_entrar(ctx):
    client, factory, sec = ctx
    admin, enc = token(client, sec, "admin"), token(client, sec, "enc")
    assert client.post("/locals", json={"nom": "Local C"}, headers=enc).status_code == 403
    lid = client.post("/locals", json={"nom": "Local C"}, headers=admin).json()["id"]
    assert client.post("/locals", json={"nom": "Local C"}, headers=admin).status_code == 422
    r = client.post("/usuaris", json={"username": "nou", "password": PASS, "role": "dispensador", "local_ids": [lid]}, headers=admin)
    assert r.status_code == 201
    secret = r.json()["totp_secret"]
    login = client.post("/auth/login", json={"username": "nou", "password": PASS, "totp": pyotp.TOTP(secret).now()})
    assert login.status_code == 200
    assert client.post("/usuaris", json={"username": "x1", "password": "curta", "role": "dispensador"}, headers=admin).status_code == 422
    assert client.post("/usuaris", json={"username": "x2", "password": PASS, "role": "superusuari"}, headers=admin).status_code == 422
    assert client.post("/usuaris", json={"username": "x3", "password": PASS, "role": "admin", "local_ids": [999]}, headers=admin).status_code == 422

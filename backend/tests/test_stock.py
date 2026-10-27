from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import select

from app import stock
from app.models import ImmutableError, Local, Member, StockMovement, User
from tests.test_api import SOCI, ctx, env, token  # noqa: F401  (fixtures)


def setup_data(client, h, factory, gprod="10"):
    mid = client.post("/socis", json=SOCI, headers=h).json()["id"]
    pid = client.post("/productes", json={"local_id": 1, "nom": "Producte A", "preu_cent_per_g": 800}, headers=h).json()["id"]
    assert client.post("/moviments/entrada", json={"product_id": pid, "grams": gprod}, headers=h).status_code == 201
    return mid, pid


def estoc(client, h):
    return {p["nom"]: p["estoc_g"] for p in client.get("/locals/1/estoc", headers=h).json()}["Producte A"]


def test_entrada_dispensacio_i_import(ctx):
    client, factory, sec = ctx
    enc, disp = token(client, sec, "enc"), token(client, sec, "disp")
    mid, pid = setup_data(client, enc, factory)
    assert estoc(client, enc) == "10"
    r = client.post("/dispensacions", json={"member_id": mid, "product_id": pid, "grams": "2.5", "pes_bascula_g": "2.5"}, headers=disp)
    assert r.status_code == 201 and r.json()["import_cent"] == 2000
    assert Decimal(estoc(client, enc)) == Decimal("7.5")


def test_estoc_mai_negatiu(ctx):
    client, factory, sec = ctx
    enc = token(client, sec, "enc")
    mid, pid = setup_data(client, enc, factory, gprod="1")
    r = client.post("/dispensacions", json={"member_id": mid, "product_id": pid, "grams": "1.001"}, headers=enc)
    assert r.status_code == 422 and "insuficient" in r.json()["detail"]
    assert Decimal(estoc(client, enc)) == 1


def test_quantitats_no_valides(ctx):
    client, factory, sec = ctx
    enc = token(client, sec, "enc")
    mid, pid = setup_data(client, enc, factory)
    for g in ("0", "-1", "abc"):
        assert client.post("/dispensacions", json={"member_id": mid, "product_id": pid, "grams": g}, headers=enc).status_code == 422


def test_limit_diari_i_correccio_allibera_cupo(ctx):
    client, factory, sec = ctx
    enc = token(client, sec, "enc")
    s = factory(); s.get(Local, 1).limit_diari_mg = 5000; s.commit(); s.close()
    mid, pid = setup_data(client, enc, factory)
    a = client.post("/dispensacions", json={"member_id": mid, "product_id": pid, "grams": "4"}, headers=enc)
    assert a.status_code == 201
    over = client.post("/dispensacions", json={"member_id": mid, "product_id": pid, "grams": "2"}, headers=enc)
    assert over.status_code == 422 and "límit diari" in over.json()["detail"]
    fix = client.post(f"/moviments/{a.json()['id']}/correccio", json={"nota": "error de pes"}, headers=enc)
    assert fix.status_code == 201
    assert Decimal(estoc(client, enc)) == 10
    assert client.post("/dispensacions", json={"member_id": mid, "product_id": pid, "grams": "2"}, headers=enc).status_code == 201


def test_correccio_nomes_una_vegada_i_no_sobre_correccio(ctx):
    client, factory, sec = ctx
    enc = token(client, sec, "enc")
    mid, pid = setup_data(client, enc, factory)
    d = client.post("/dispensacions", json={"member_id": mid, "product_id": pid, "grams": "1"}, headers=enc).json()["id"]
    c = client.post(f"/moviments/{d}/correccio", json={"nota": "motiu"}, headers=enc)
    assert c.status_code == 201
    assert client.post(f"/moviments/{d}/correccio", json={"nota": "motiu"}, headers=enc).status_code == 422
    assert client.post(f"/moviments/{c.json()['id']}/correccio", json={"nota": "motiu"}, headers=enc).status_code == 422


def test_correccio_d_entrada_no_pot_deixar_estoc_negatiu(ctx):
    client, factory, sec = ctx
    enc = token(client, sec, "enc")
    mid, pid = setup_data(client, enc, factory, gprod="5")
    client.post("/dispensacions", json={"member_id": mid, "product_id": pid, "grams": "4"}, headers=enc)
    entrada_id = 1
    r = client.post(f"/moviments/{entrada_id}/correccio", json={"nota": "entrada duplicada"}, headers=enc)
    assert r.status_code == 422 and "negatiu" in r.json()["detail"]


def test_moviments_immutables(ctx):
    client, factory, sec = ctx
    enc = token(client, sec, "enc")
    setup_data(client, enc, factory)
    s = factory()
    m = s.scalars(select(StockMovement)).first()
    m.delta_mg = 999999
    with pytest.raises(ImmutableError):
        s.commit()
    s.rollback()
    with pytest.raises(ImmutableError):
        s.delete(s.scalars(select(StockMovement)).first())
        s.commit()
    s.close()


def test_soci_baixa_i_altre_local(ctx):
    client, factory, sec = ctx
    enc = token(client, sec, "enc")
    mid, pid = setup_data(client, enc, factory)
    s = factory(); s.get(Member, mid).estat = "baixa"; s.commit(); s.close()
    assert client.post("/dispensacions", json={"member_id": mid, "product_id": pid, "grams": "1"}, headers=enc).status_code == 422
    admin = token(client, sec, "admin")
    p2 = client.post("/productes", json={"local_id": 2, "nom": "B", "preu_cent_per_g": 1}, headers=admin).json()["id"]
    assert client.post("/dispensacions", json={"member_id": mid, "product_id": p2, "grams": "1"}, headers=enc).status_code == 403

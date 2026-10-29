import json

import pytest
from sqlalchemy import select

from app.models import AuditLog, ImmutableError, MovementWarehouse
from tests.test_api import ctx, env, token  # noqa: F401
from tests.test_stock import setup_data


def magatzem(client, h, nom="Safata"):
    return client.post("/locals/1/magatzems", json={"nom": nom}, headers=h)


def traspas(client, h, pid, de, a, g):
    return client.post("/moviments/traspas", json={"product_id": pid, "de": de, "a": a, "grams": g}, headers=h)


def estoc(client, h, pid):
    """{magatzem_id|None: grams} d'un producte, segons la vista per magatzems."""
    fila = next(f for f in client.get("/locals/1/magatzems/estoc", headers=h).json() if f["product_id"] == pid)
    return {e["magatzem_id"]: e["g"] for e in fila["estocs"]}


def disponible(client, h, pid):
    return next(p for p in client.get("/locals/1/estoc", headers=h).json() if p["id"] == pid)["estoc_g"]


def test_la_llista_comença_amb_el_principal_i_afegeix_magatzems(ctx):
    client, factory, sec = ctx
    enc = token(client, sec, "enc")
    assert client.get("/locals/1/magatzems", headers=enc).json() == [{"id": None, "nom": "Principal", "principal": True, "actiu": True}]
    mid = magatzem(client, enc).json()["id"]
    llista = client.get("/locals/1/magatzems", headers=enc).json()
    assert [m["nom"] for m in llista] == ["Principal", "Safata"] and llista[1]["id"] == mid and llista[1]["principal"] is False


def test_traspas_mou_estoc_i_nomes_el_principal_es_pot_dispensar(ctx):
    client, factory, sec = ctx
    enc = token(client, sec, "enc")
    mid, pid = setup_data(client, enc, factory)        # 10 g al principal
    saf = magatzem(client, enc).json()["id"]
    assert traspas(client, enc, pid, None, saf, "4").status_code == 201
    assert estoc(client, enc, pid) == {None: "6", saf: "4"}
    assert disponible(client, enc, pid) == "6"          # el de la safata no es pot dispensar
    assert client.post("/dispensacions", json={"member_id": mid, "product_id": pid, "grams": "7"}, headers=enc).status_code == 422
    assert client.post("/dispensacions", json={"member_id": mid, "product_id": pid, "grams": "6"}, headers=enc).status_code == 201
    assert traspas(client, enc, pid, saf, None, "1").status_code == 201                    # tornar-ne al principal
    assert estoc(client, enc, pid) == {None: "1", saf: "3"}


def test_traspas_no_pot_deixar_negatiu_ni_ser_absurd(ctx):
    client, factory, sec = ctx
    enc = token(client, sec, "enc")
    _, pid = setup_data(client, enc, factory)
    saf = magatzem(client, enc).json()["id"]
    assert traspas(client, enc, pid, None, saf, "11").status_code == 422          # més del que hi ha
    assert traspas(client, enc, pid, saf, None, "1").status_code == 422            # el magatzem és buit
    assert traspas(client, enc, pid, None, None, "1").status_code == 422           # mateix origen i destí
    assert traspas(client, enc, pid, saf, saf, "1").status_code == 422
    assert traspas(client, enc, pid, None, 9999, "1").status_code == 422
    assert traspas(client, enc, pid, None, saf, "0").status_code == 422
    assert traspas(client, enc, 9999, None, saf, "1").status_code == 404


def test_entrada_directa_a_un_magatzem(ctx):
    client, factory, sec = ctx
    enc = token(client, sec, "enc")
    _, pid = setup_data(client, enc, factory)
    saf = magatzem(client, enc).json()["id"]
    r = client.post("/moviments/entrada", json={"product_id": pid, "grams": "5", "magatzem_id": saf}, headers=enc)
    assert r.status_code == 201
    assert estoc(client, enc, pid) == {None: "10", saf: "5"}
    assert disponible(client, enc, pid) == "10"
    assert client.post("/moviments/entrada", json={"product_id": pid, "grams": "5", "magatzem_id": 9999}, headers=enc).status_code == 422


def test_desactivar_magatzem_nomes_si_esta_buit_i_no_admet_entrades(ctx):
    client, factory, sec = ctx
    enc = token(client, sec, "enc")
    _, pid = setup_data(client, enc, factory)
    saf = magatzem(client, enc).json()["id"]
    traspas(client, enc, pid, None, saf, "2")
    assert client.put(f"/magatzems/{saf}", json={"actiu": False}, headers=enc).status_code == 422   # encara té estoc
    traspas(client, enc, pid, saf, None, "2")
    assert client.put(f"/magatzems/{saf}", json={"actiu": False}, headers=enc).status_code == 200
    assert traspas(client, enc, pid, None, saf, "1").status_code == 422                              # desactivat
    assert client.put(f"/magatzems/{saf}", json={"nom": "Armari"}, headers=enc).status_code == 200


def test_el_producte_no_es_pot_desactivar_si_te_estoc_en_un_magatzem(ctx):
    client, factory, sec = ctx
    enc = token(client, sec, "enc")
    _, pid = setup_data(client, enc, factory)
    saf = magatzem(client, enc).json()["id"]
    traspas(client, enc, pid, None, saf, "10")                                    # el principal queda a 0
    assert client.patch(f"/productes/{pid}", json={"actiu": False}, headers=enc).status_code == 422


def test_validacio_permisos_i_auditoria(ctx):
    client, factory, sec = ctx
    enc, disp = token(client, sec, "enc"), token(client, sec, "disp")
    _, pid = setup_data(client, enc, factory)
    assert magatzem(client, disp).status_code == 403
    assert client.get("/locals/1/magatzems", headers=disp).status_code == 403
    assert client.post("/locals/2/magatzems", json={"nom": "X"}, headers=enc).status_code == 403
    assert magatzem(client, enc, nom=" ").status_code == 422
    assert magatzem(client, enc, nom="Principal").status_code == 422             # reservat
    saf = magatzem(client, enc).json()["id"]
    assert magatzem(client, enc).status_code == 422                               # repetit
    assert traspas(client, disp, pid, None, saf, "1").status_code == 403
    assert client.put("/magatzems/9999", json={"actiu": False}, headers=enc).status_code == 404
    assert client.put(f"/magatzems/{saf}", json={}, headers=enc).status_code == 422
    traspas(client, enc, pid, None, saf, "1")
    s = factory()
    accions = {json.loads(a.payload)["accio"] for a in s.scalars(select(AuditLog))}
    s.close()
    assert {"alta_magatzem", "traspas_estoc"} <= accions


def test_lassignacio_de_magatzem_d_un_moviment_es_immutable(ctx):
    client, factory, sec = ctx
    enc = token(client, sec, "enc")
    _, pid = setup_data(client, enc, factory)
    saf = magatzem(client, enc).json()["id"]
    traspas(client, enc, pid, None, saf, "1")
    s = factory()
    mw = s.scalar(select(MovementWarehouse))
    mw.warehouse_id = mw.warehouse_id + 1
    with pytest.raises(ImmutableError):
        s.commit()
    s.rollback()
    s.close()

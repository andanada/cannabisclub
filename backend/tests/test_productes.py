import json
from decimal import Decimal

from sqlalchemy import select

from app.models import AuditLog
from tests.test_api import SOCI, ctx, env, token  # noqa: F401
from tests.test_stock import estoc, setup_data


def nou(client, h, nom, preu=500, local=1):
    r = client.post("/productes", json={"local_id": local, "nom": nom, "categoria": "flor", "preu_cent_per_g": preu}, headers=h)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def test_canvi_de_preu_nomes_afecta_les_dispensacions_noves(ctx):
    client, factory, sec = ctx
    enc = token(client, sec, "enc")
    mid, pid = setup_data(client, enc, factory)  # 10 g a 800 cèntims/g
    antiga = client.post("/dispensacions", json={"member_id": mid, "product_id": pid, "grams": "1"}, headers=enc).json()
    assert antiga["import_cent"] == 800
    assert client.patch(f"/productes/{pid}", json={"preu_cent_per_g": 1000}, headers=enc).status_code == 200
    nova = client.post("/dispensacions", json={"member_id": mid, "product_id": pid, "grams": "1"}, headers=enc).json()
    assert nova["import_cent"] == 1000
    # la dispensació antiga conserva el seu import: el registre és immutable
    s = factory()
    from app.models import StockMovement
    assert s.get(StockMovement, antiga["id"]).import_cent == 800
    s.close()


def test_editar_nom_categoria_i_preu_queda_a_lauditoria(ctx):
    client, factory, sec = ctx
    enc = token(client, sec, "enc")
    pid = nou(client, enc, "Vell", preu=500)
    r = client.patch(f"/productes/{pid}", json={"nom": "Nou nom", "categoria": "resina", "preu_cent_per_g": 650}, headers=enc)
    assert r.status_code == 200
    p = [x for x in client.get("/locals/1/estoc", headers=enc).json() if x["id"] == pid][0]
    assert (p["nom"], p["categoria"], p["preu_cent_per_g"]) == ("Nou nom", "resina", 650)
    s = factory()
    last = [json.loads(a.payload) for a in s.scalars(select(AuditLog).order_by(AuditLog.seq))][-1]
    s.close()
    assert last["accio"] == "edita_producte" and last["producte"] == pid
    assert last["canvis"]["preu_cent_per_g"] == [500, 650] and last["canvis"]["nom"] == ["Vell", "Nou nom"]
    assert client.get("/auditoria/verificar", headers=token(client, sec, "admin")).json()["integra"] is True


def test_nom_duplicat_es_rebutja_en_crear_i_en_editar(ctx):
    client, factory, sec = ctx
    enc = token(client, sec, "enc")
    nou(client, enc, "Amnesia")
    pid2 = nou(client, enc, "Critical")
    r = client.post("/productes", json={"local_id": 1, "nom": "Amnesia", "preu_cent_per_g": 100}, headers=enc)
    assert r.status_code == 422 and "Ja existeix" in r.json()["detail"]
    r = client.patch(f"/productes/{pid2}", json={"nom": "Amnesia"}, headers=enc)
    assert r.status_code == 422 and "Ja existeix" in r.json()["detail"]
    # el mateix nom en un altre local sí que es pot
    nou(client, token(client, sec, "admin"), "Amnesia", local=2)


def test_sense_canvis_o_valors_invalids(ctx):
    client, factory, sec = ctx
    enc = token(client, sec, "enc")
    pid = nou(client, enc, "Producte", preu=500)
    assert client.patch(f"/productes/{pid}", json={}, headers=enc).status_code == 422
    assert client.patch(f"/productes/{pid}", json={"preu_cent_per_g": 500, "nom": "Producte"}, headers=enc).status_code == 422
    assert client.patch(f"/productes/{pid}", json={"preu_cent_per_g": -1}, headers=enc).status_code == 422
    assert client.patch(f"/productes/{pid}", json={"nom": "  "}, headers=enc).status_code == 422
    assert client.patch("/productes/9999", json={"preu_cent_per_g": 1}, headers=enc).status_code == 404


def test_desactivar_exigeix_estoc_zero_i_es_pot_reactivar(ctx):
    client, factory, sec = ctx
    enc = token(client, sec, "enc")
    mid, pid = setup_data(client, enc, factory)  # 10 g
    r = client.patch(f"/productes/{pid}", json={"actiu": False}, headers=enc)
    assert r.status_code == 422 and "estoc" in r.json()["detail"].lower()
    assert client.post("/moviments/merma", json={"product_id": pid, "grams": "10", "nota": "retirat"}, headers=enc).status_code == 201
    assert client.patch(f"/productes/{pid}", json={"actiu": False}, headers=enc).status_code == 200
    assert all(p["id"] != pid for p in client.get("/locals/1/estoc", headers=enc).json())
    assert client.post("/moviments/entrada", json={"product_id": pid, "grams": "1"}, headers=enc).status_code == 422
    llista = client.get("/locals/1/productes", headers=enc).json()
    assert [p for p in llista if p["id"] == pid][0]["actiu"] is False
    assert client.patch(f"/productes/{pid}", json={"actiu": True}, headers=enc).status_code == 200
    assert client.post("/moviments/entrada", json={"product_id": pid, "grams": "1"}, headers=enc).status_code == 201


def test_llista_completa_nomes_per_a_responsables_i_del_seu_local(ctx):
    client, factory, sec = ctx
    enc, disp, admin = token(client, sec, "enc"), token(client, sec, "disp"), token(client, sec, "admin")
    pid = nou(client, enc, "Producte")
    assert client.get("/locals/1/productes", headers=enc).status_code == 200
    assert client.get("/locals/1/productes", headers=disp).status_code == 403
    assert client.get("/locals/2/productes", headers=enc).status_code == 403
    assert client.patch(f"/productes/{pid}", json={"preu_cent_per_g": 1}, headers=disp).status_code == 403
    pid2 = nou(client, admin, "Altre local", local=2)
    assert client.patch(f"/productes/{pid2}", json={"preu_cent_per_g": 1}, headers=enc).status_code == 403

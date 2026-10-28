import json

from sqlalchemy import select

from app.models import AuditLog
from tests.test_api import ctx, env, token  # noqa: F401
from tests.test_stock import setup_data


def tipus(client, h, nom="Pot 10 g", tara_g="12.5", **extra):
    return client.post("/locals/1/tipus-contenidor", json={"nom": nom, "tara_g": tara_g, **extra}, headers=h)


def cont(client, h, tid, codi="C-001", **extra):
    return client.post("/locals/1/contenidors", json={"codi": codi, "type_id": tid, **extra}, headers=h)


def test_tipus_i_contenidor_amb_pes_net(ctx):
    client, factory, sec = ctx
    enc = token(client, sec, "enc")
    _, pid = setup_data(client, enc, factory)
    tid = tipus(client, enc).json()["id"]
    cid = cont(client, enc, tid, product_id=pid).json()["id"]
    c = client.get("/locals/1/contenidors", headers=enc).json()[0]
    assert c["codi"] == "C-001" and c["tipus"] == "Pot 10 g" and c["tara_g"] == "12.5" and c["producte"] == "Producte A"
    assert c["brut_g"] is None and c["net_g"] is None
    assert client.put(f"/contenidors/{cid}", json={"brut_g": "22.5"}, headers=enc).status_code == 200
    c = client.get("/locals/1/contenidors", headers=enc).json()[0]
    assert c["brut_g"] == "22.5" and c["net_g"] == "10"
    assert client.put(f"/contenidors/{cid}", json={"brut_g": "5"}, headers=enc).status_code == 422  # menys que la tara
    assert client.put(f"/contenidors/{cid}", json={"brut_g": None, "product_id": None}, headers=enc).status_code == 200  # buidar
    c = client.get("/locals/1/contenidors", headers=enc).json()[0]
    assert c["brut_g"] is None and c["producte"] is None


def test_validacio_unicitat_i_permisos(ctx):
    client, factory, sec = ctx
    enc, disp = token(client, sec, "enc"), token(client, sec, "disp")
    _, pid = setup_data(client, enc, factory)
    assert tipus(client, disp).status_code == 403
    assert client.get("/locals/1/contenidors", headers=disp).status_code == 403
    assert client.post("/locals/2/tipus-contenidor", json={"nom": "X", "tara_g": "1"}, headers=enc).status_code == 403
    for mal in [{"nom": " "}, {"tara_g": "-1"}, {"tara_g": "abc"}, {"tara_g": "100000"}]:
        assert tipus(client, enc, **mal).status_code == 422, mal
    tid = tipus(client, enc).json()["id"]
    assert tipus(client, enc).status_code == 422                                    # nom repetit
    assert cont(client, enc, 9999).status_code == 422                               # tipus inexistent
    assert cont(client, enc, tid, codi=" ").status_code == 422
    assert cont(client, enc, tid, product_id=9999).status_code == 422
    assert cont(client, enc, tid, brut_g="1").status_code == 422                    # brut per sota de la tara
    assert cont(client, enc, tid).status_code == 201
    assert cont(client, enc, tid).status_code == 422                                # codi repetit
    assert client.put("/contenidors/9999", json={"actiu": False}, headers=enc).status_code == 404
    assert client.put("/contenidors/1", json={}, headers=enc).status_code == 422
    assert client.put(f"/tipus-contenidor/{tid}", json={"actiu": False}, headers=enc).status_code == 200
    assert cont(client, enc, tid, codi="C-002").status_code == 422                  # tipus desactivat


def test_auditoria(ctx):
    client, factory, sec = ctx
    enc = token(client, sec, "enc")
    tid = tipus(client, enc).json()["id"]
    cid = cont(client, enc, tid).json()["id"]
    client.put(f"/contenidors/{cid}", json={"brut_g": "20"}, headers=enc)
    s = factory()
    accions = {json.loads(a.payload)["accio"] for a in s.scalars(select(AuditLog))}
    s.close()
    assert {"alta_tipus_contenidor", "alta_contenidor", "edita_contenidor"} <= accions

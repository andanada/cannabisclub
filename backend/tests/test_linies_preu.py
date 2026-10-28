import json

from sqlalchemy import select

from app.models import AuditLog
from tests.test_api import SOCI, ctx, env, token  # noqa: F401
from tests.test_stock import setup_data


def linia(client, h, nom="VIP", **extra):
    return client.post("/locals/1/linies-preu", json={"nom": nom, **extra}, headers=h)


def preu(client, h, lid, pid, cent):
    return client.put(f"/linies-preu/{lid}/preus/{pid}", json={"preu_cent_per_g": cent}, headers=h)


def assigna(client, h, mid, lid):
    return client.put(f"/socis/{mid}/linia-preu", json={"price_line_id": lid}, headers=h)


def dispensa(client, h, mid, pid, g="2", **extra):
    return client.post("/dispensacions", json={"member_id": mid, "product_id": pid, "grams": g, **extra}, headers=h)


def test_el_soci_amb_linia_paga_el_preu_de_la_linia_i_la_resta_el_base(ctx):
    client, factory, sec = ctx
    enc = token(client, sec, "enc")
    mid, pid = setup_data(client, enc, factory)  # 10 g a 800 cèntims/g
    lid = linia(client, enc).json()["id"]
    assert preu(client, enc, lid, pid, 600).status_code == 200
    assert dispensa(client, enc, mid, pid).json()["import_cent"] == 1600           # encara sense línia: preu base
    assert assigna(client, enc, mid, lid).status_code == 200
    assert dispensa(client, enc, mid, pid).json()["import_cent"] == 1200           # 2 g a 6 €/g
    altre = client.post("/productes", json={"local_id": 1, "nom": "B", "categoria": "flor", "preu_cent_per_g": 500}, headers=enc).json()["id"]
    client.post("/moviments/entrada", json={"product_id": altre, "grams": "10"}, headers=enc)
    assert dispensa(client, enc, mid, altre).json()["import_cent"] == 1000         # producte sense preu a la línia: preu base
    assert assigna(client, enc, mid, None).status_code == 200
    assert dispensa(client, enc, mid, pid).json()["import_cent"] == 1600           # sense línia un altre cop


def test_el_descompte_s_aplica_sobre_el_preu_de_la_linia(ctx):
    client, factory, sec = ctx
    enc = token(client, sec, "enc")
    mid, pid = setup_data(client, enc, factory)
    lid = linia(client, enc).json()["id"]
    preu(client, enc, lid, pid, 600)
    assigna(client, enc, mid, lid)
    did = client.post("/locals/1/descomptes", json={"nom": "Mig", "tipus": "percent", "valor": 50, "ambit": "tot"}, headers=enc).json()["id"]
    r = dispensa(client, enc, mid, pid, discount_id=did).json()
    assert r["import_cent"] == 600 and r["descompte_cent"] == 600                  # 2 g × 6 € = 12 € → -50 %


def test_linia_desactivada_no_s_aplica_i_el_detall_mostra_tots_els_productes(ctx):
    client, factory, sec = ctx
    enc = token(client, sec, "enc")
    mid, pid = setup_data(client, enc, factory)
    lid = linia(client, enc).json()["id"]
    preu(client, enc, lid, pid, 600)
    assigna(client, enc, mid, lid)
    assert client.put(f"/linies-preu/{lid}", json={"actiu": False}, headers=enc).status_code == 200
    assert dispensa(client, enc, mid, pid).json()["import_cent"] == 1600
    d = client.get(f"/linies-preu/{lid}", headers=enc).json()
    assert d["actiu"] is False and d["preus"] == [{"product_id": pid, "nom": "Producte A", "base_cent": 800, "preu_cent": 600}]
    assert client.delete(f"/linies-preu/{lid}/preus/{pid}", headers=enc).status_code == 200
    assert client.get(f"/linies-preu/{lid}", headers=enc).json()["preus"][0]["preu_cent"] is None
    assert client.delete(f"/linies-preu/{lid}/preus/{pid}", headers=enc).status_code == 404  # ja no hi és


def test_estoc_amb_soci_mostra_els_preus_efectius(ctx):
    client, factory, sec = ctx
    enc, disp = token(client, sec, "enc"), token(client, sec, "disp")
    mid, pid = setup_data(client, enc, factory)
    lid = linia(client, enc).json()["id"]
    preu(client, enc, lid, pid, 600)
    assigna(client, enc, mid, lid)
    assert client.get("/locals/1/estoc", headers=disp).json()[0]["preu_cent_per_g"] == 800
    assert client.get(f"/locals/1/estoc?soci={mid}", headers=disp).json()[0]["preu_cent_per_g"] == 600
    assert client.get("/locals/1/estoc?soci=9999", headers=disp).status_code == 404
    assert client.get(f"/socis/{mid}/linia-preu", headers=disp).json() == {"price_line_id": lid, "nom": "VIP"}


def test_validacio_permisos_i_aillament(ctx):
    client, factory, sec = ctx
    enc, disp = token(client, sec, "enc"), token(client, sec, "disp")
    mid, pid = setup_data(client, enc, factory)
    assert linia(client, disp).status_code == 403
    assert client.get("/locals/1/linies-preu", headers=disp).status_code == 403
    assert client.post("/locals/2/linies-preu", json={"nom": "X"}, headers=enc).status_code == 403
    assert linia(client, enc, nom=" ").status_code == 422
    lid = linia(client, enc).json()["id"]
    assert linia(client, enc).status_code == 422                                     # nom repetit
    for cent in (-1, 10_000_001):
        assert preu(client, enc, lid, pid, cent).status_code == 422
    assert preu(client, enc, lid, 9999, 100).status_code == 422                      # producte inexistent
    assert preu(client, enc, 9999, pid, 100).status_code == 404
    assert assigna(client, enc, mid, 9999).status_code == 422
    assert assigna(client, disp, mid, lid).status_code == 403
    assert client.put(f"/linies-preu/{lid}", json={}, headers=enc).status_code == 422
    llista = client.get("/locals/1/linies-preu", headers=enc).json()
    assert llista == [{"id": lid, "nom": "VIP", "actiu": True, "socis": 0, "productes": 0}]
    assigna(client, enc, mid, lid)
    preu(client, enc, lid, pid, 700)
    assert client.get("/locals/1/linies-preu", headers=enc).json()[0]["socis"] == 1
    assert client.get("/locals/1/linies-preu", headers=enc).json()[0]["productes"] == 1


def test_auditoria(ctx):
    client, factory, sec = ctx
    enc = token(client, sec, "enc")
    mid, pid = setup_data(client, enc, factory)
    lid = linia(client, enc).json()["id"]
    preu(client, enc, lid, pid, 600)
    assigna(client, enc, mid, lid)
    s = factory()
    accions = {json.loads(a.payload)["accio"] for a in s.scalars(select(AuditLog))}
    s.close()
    assert {"alta_linia_preu", "preu_linia", "assigna_linia_preu"} <= accions

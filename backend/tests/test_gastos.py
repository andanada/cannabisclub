"""Despeses i comptabilitat: catàlegs, comptes amb suma/resta, despesa de caixa atòmica i anul·lació."""
from datetime import date

from tests.test_api import ctx, env, token  # noqa: F401

AVUI = date.today().isoformat()


def _cataleg(client, h):
    cat = client.post("/locals/1/gastos/categories", json={"nom": "Subministraments"}, headers=h).json()["id"]
    tip = client.post("/locals/1/gastos/tipus", json={"nom": "Llum"}, headers=h).json()["id"]
    tc = client.post("/locals/1/gastos/tipus-compte", json={"nom": "Despeses", "operacio": "resta", "es_despesa": True}, headers=h).json()["id"]
    cm = client.post("/locals/1/gastos/comptes", json={"numero": "600", "tipus_id": tc}, headers=h).json()["id"]
    return cat, tip, cm


def _gasto(client, h, cat, tip, cm, cent=2500, metode=None, **extra):
    return client.post("/gastos", json={"local_id": 1, "data": AVUI, "type_id": tip, "category_id": cat, "account_id": cm,
                                         "import_cent": cent, "metode": metode, **extra}, headers=h)


def test_cataleg_unic_i_nomes_responsables(ctx):
    client, _, sec = ctx
    enc, disp = token(client, sec, "enc"), token(client, sec, "disp")
    assert client.post("/locals/1/gastos/categories", json={"nom": "Lloguer"}, headers=enc).status_code == 201
    assert client.post("/locals/1/gastos/categories", json={"nom": "Lloguer"}, headers=enc).status_code == 422
    assert client.post("/locals/1/gastos/categories", json={"nom": "X"}, headers=disp).status_code == 403
    assert client.get("/locals/1/gastos/categories", headers=disp).status_code == 403
    assert client.post("/locals/1/gastos/tipus-compte", json={"nom": "T", "operacio": "multiplica"}, headers=enc).status_code == 422


def test_despesa_sense_caixa_no_toca_la_caixa_i_mou_el_compte(ctx):
    client, _, sec = ctx
    enc = token(client, sec, "enc")
    cat, tip, cm = _cataleg(client, enc)
    r = _gasto(client, enc, cat, tip, cm)
    assert r.status_code == 201 and r.json()["caixa"] is False
    comptes = client.get("/locals/1/gastos/comptes", headers=enc).json()
    assert comptes[0]["numero"] == "600" and comptes[0]["import_cent"] == -2500  # tipus «resta»
    l = client.get("/locals/1/gastos", params={"des": AVUI, "fins": AVUI}, headers=enc).json()
    assert len(l) == 1 and l[0]["categoria"] == "Subministraments" and l[0]["compte"] == "600"


def test_despesa_de_caixa_i_anulacio_atomiques(ctx):
    client, _, sec = ctx
    enc = token(client, sec, "enc")
    cat, tip, cm = _cataleg(client, enc)
    assert _gasto(client, enc, cat, tip, cm, metode="efectiu").status_code == 422  # sense caixa oberta: res a mitges
    assert client.get("/locals/1/gastos", params={"des": AVUI, "fins": AVUI}, headers=enc).json() == []
    client.post("/caixa/obrir", json={"local_id": 1, "opening_cent": 10000}, headers=enc)
    r = _gasto(client, enc, cat, tip, cm, cent=3000, metode="efectiu").json()
    assert r["caixa"] is True
    assert client.post(f"/gastos/{r['id']}/anulacio", json={"nota": "duplicada"}, headers=enc).status_code == 201
    assert client.post(f"/gastos/{r['id']}/anulacio", json={"nota": "altra vegada"}, headers=enc).status_code == 422
    t = client.post("/caixa/tancar", json={"local_id": 1, "counted_cent": 10000}, headers=enc).json()
    assert t["esperat_cent"] == 10000  # la despesa i la seva anul·lació es compensen
    assert client.get("/locals/1/gastos/comptes", headers=enc).json()[0]["import_cent"] == 0


def test_validacions_de_la_despesa(ctx):
    client, _, sec = ctx
    enc = token(client, sec, "enc")
    cat, tip, cm = _cataleg(client, enc)
    assert _gasto(client, enc, cat, tip, cm, cent=0).status_code == 422
    assert _gasto(client, enc, cat, 9999, cm).status_code == 422
    assert client.post("/gastos", json={"local_id": 1, "data": "2999-01-01", "type_id": tip, "category_id": cat, "import_cent": 100}, headers=enc).status_code == 422
    client.put(f"/gastos/categories/{cat}", json={"actiu": False}, headers=enc)
    assert _gasto(client, enc, cat, tip, cm).status_code == 422  # categoria inactiva


def test_despesa_repetida_amb_la_mateixa_referencia_no_es_duplica(ctx):
    client, _, sec = ctx
    enc = token(client, sec, "enc")
    cat, tip, cm = _cataleg(client, enc)
    a = _gasto(client, enc, cat, tip, cm, client_ref="ref-gasto-000000001")
    b = _gasto(client, enc, cat, tip, cm, client_ref="ref-gasto-000000001")
    assert a.status_code == 201 and b.status_code in (200, 201)
    assert len(client.get("/locals/1/gastos", params={"des": AVUI, "fins": AVUI}, headers=enc).json()) == 1

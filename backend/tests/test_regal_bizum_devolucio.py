"""Bizum, regal i devolució atòmica d'una dispensació."""
from tests.ajuda_caixa import activa_targeta
from tests.test_api import ctx, env, token  # noqa: F401
from tests.test_stock import setup_data


def _prepara(client, enc):
    client.post("/caixa/obrir", json={"local_id": 1, "opening_cent": 1000}, headers=enc)
    pid = client.post("/productes", json={"local_id": 1, "nom": "Flor", "preu_cent_per_g": 1000, "es_genetic": True, "regalable": True}, headers=enc).json()["id"]
    client.post("/moviments/entrada", json={"product_id": pid, "grams": "20"}, headers=enc)
    from tests.test_api import SOCI
    mid = client.post("/socis", json=SOCI, headers=enc).json()["id"]
    return pid, mid


def _estoc(client, enc, pid):
    return next(p for p in client.get("/locals/1/productes", headers=enc).json() if p["id"] == pid)["estoc_g"]


def test_cobrament_per_bizum_no_entra_a_l_efectiu(ctx):
    client, _, sec = ctx
    enc = token(client, sec, "enc")
    activa_targeta(client, sec)
    pid, mid = _prepara(client, enc)
    r = client.post("/dispensacions", json={"member_id": mid, "product_id": pid, "grams": "2", "metode": "bizum"}, headers=enc)
    assert r.status_code == 201 and r.json()["import_cent"] == 2000
    assert client.post("/dispensacions", json={"member_id": mid, "product_id": pid, "grams": "1", "metode": "cripto"}, headers=enc).status_code == 422
    t = client.post("/caixa/tancar", json={"local_id": 1, "counted_cent": 1000}, headers=enc).json()
    assert t["esperat_cent"] == 1000 and t["diferencia_cent"] == 0  # el Bizum no és efectiu del calaix


def test_regal_import_zero_sense_cobrament_i_nomes_si_es_regalable(ctx):
    client, _, sec = ctx
    enc = token(client, sec, "enc")
    pid, mid = _prepara(client, enc)
    r = client.post("/dispensacions", json={"member_id": mid, "product_id": pid, "grams": "1", "regal": True}, headers=enc)
    assert r.status_code == 201 and r.json()["import_cent"] == 0 and r.json()["regal"] is True
    assert _estoc(client, enc, pid) == "19"
    assert client.post("/dispensacions", json={"member_id": mid, "product_id": pid, "grams": "1", "regal": True, "metode": "efectiu"}, headers=enc).status_code == 422
    client.patch(f"/productes/{pid}", json={"regalable": False}, headers=enc)
    assert client.post("/dispensacions", json={"member_id": mid, "product_id": pid, "grams": "1", "regal": True}, headers=enc).status_code == 422


def test_devolucio_cobrada_reposa_estoc_i_treu_de_caixa(ctx):
    client, _, sec = ctx
    enc, disp = token(client, sec, "enc"), token(client, sec, "disp")
    pid, mid = _prepara(client, enc)
    d = client.post("/dispensacions", json={"member_id": mid, "product_id": pid, "grams": "3", "metode": "efectiu"}, headers=enc).json()
    assert _estoc(client, enc, pid) == "17"
    assert client.post(f"/dispensacions/{d['id']}/devolucio", json={"nota": "error de producte"}, headers=disp).status_code == 403
    r = client.post(f"/dispensacions/{d['id']}/devolucio", json={"nota": "error de producte"}, headers=enc)
    assert r.status_code == 201 and r.json()["retornat_cent"] == 3000
    assert _estoc(client, enc, pid) == "20"
    assert client.post(f"/dispensacions/{d['id']}/devolucio", json={"nota": "altra vegada"}, headers=enc).status_code == 422


def test_devolucio_sense_caixa_oberta_no_fa_res_a_mitges(ctx):
    client, _, sec = ctx
    enc = token(client, sec, "enc")
    pid, mid = _prepara(client, enc)
    d = client.post("/dispensacions", json={"member_id": mid, "product_id": pid, "grams": "3", "metode": "efectiu"}, headers=enc).json()
    client.post("/caixa/tancar", json={"local_id": 1, "counted_cent": 4000}, headers=enc)
    r = client.post(f"/dispensacions/{d['id']}/devolucio", json={"nota": "tard"}, headers=enc)
    assert r.status_code == 422
    assert _estoc(client, enc, pid) == "17"  # ni estoc ni caixa tocats


def test_devolucio_de_dispensacio_no_cobrada_nomes_repon_estoc(ctx):
    client, _, sec = ctx
    enc = token(client, sec, "enc")
    pid, mid = _prepara(client, enc)
    d = client.post("/dispensacions", json={"member_id": mid, "product_id": pid, "grams": "2"}, headers=enc).json()
    r = client.post(f"/dispensacions/{d['id']}/devolucio", json={"nota": "no el vol"}, headers=enc)
    assert r.status_code == 201 and r.json()["retornat_cent"] == 0 and _estoc(client, enc, pid) == "20"

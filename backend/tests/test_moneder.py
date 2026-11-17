"""Monedero del soci: recàrrega a la caixa, pagament, devolució, límit negatiu i que no dupliqui ingressos."""
from tests.test_api import SOCI, ctx, env, token  # noqa: F401


def _prepara(client, enc, activa=True, limit=0):
    admin = None
    client.post("/caixa/obrir", json={"local_id": 1, "opening_cent": 1000}, headers=enc)
    pid = client.post("/productes", json={"local_id": 1, "nom": "Flor", "preu_cent_per_g": 1000, "es_genetic": True}, headers=enc).json()["id"]
    client.post("/moviments/entrada", json={"product_id": pid, "grams": "20"}, headers=enc)
    mid = client.post("/socis", json=SOCI, headers=enc).json()["id"]
    return pid, mid


def _activa(client, sec, limit=0):
    adm = token(client, sec, "admin")
    assert client.put("/locals/1/config", json={"moneder_actiu": True, "moneder_limit_cent": limit}, headers=adm).status_code == 200


def _saldo(client, enc, mid):
    return client.get(f"/socis/{mid}/moneder", headers=enc).json()["saldo_cent"]


def test_moneder_desactivat_per_defecte(ctx):
    client, _, sec = ctx
    enc = token(client, sec, "enc")
    pid, mid = _prepara(client, enc)
    r = client.post(f"/socis/{mid}/moneder/recarrega", json={"import_cent": 1000, "metode": "efectiu"}, headers=enc)
    assert r.status_code == 422
    assert client.post("/dispensacions", json={"member_id": mid, "product_id": pid, "grams": "1", "metode": "monedero"}, headers=enc).status_code == 422


def test_recarrega_paga_i_no_duplica_ingressos(ctx):
    client, _, sec = ctx
    enc = token(client, sec, "enc")
    _activa(client, sec)
    pid, mid = _prepara(client, enc)
    r = client.post(f"/socis/{mid}/moneder/recarrega", json={"import_cent": 5000, "metode": "efectiu"}, headers=enc)
    assert r.status_code == 201 and r.json()["saldo_cent"] == 5000
    d = client.post("/dispensacions", json={"member_id": mid, "product_id": pid, "grams": "3", "metode": "monedero"}, headers=enc)
    assert d.status_code == 201 and d.json()["cobrat"] is True
    assert _saldo(client, enc, mid) == 2000
    # sense saldo suficient no es pot pagar i no es dispensa res
    assert client.post("/dispensacions", json={"member_id": mid, "product_id": pid, "grams": "5", "metode": "monedero"}, headers=enc).status_code == 422
    est = next(p for p in client.get("/locals/1/productes", headers=enc).json() if p["id"] == pid)["estoc_g"]
    assert est == "17"
    # l'efectiu esperat: obertura + recàrrega en efectiu (gastar saldo no mou el calaix)
    t = client.post("/caixa/tancar", json={"local_id": 1, "counted_cent": 6000}, headers=enc).json()
    assert t["esperat_cent"] == 6000


def test_devolucio_d_un_pagament_torna_el_saldo(ctx):
    client, _, sec = ctx
    enc = token(client, sec, "enc")
    _activa(client, sec)
    pid, mid = _prepara(client, enc)
    client.post(f"/socis/{mid}/moneder/recarrega", json={"import_cent": 5000, "metode": "targeta"}, headers=enc)
    d = client.post("/dispensacions", json={"member_id": mid, "product_id": pid, "grams": "3", "metode": "monedero"}, headers=enc).json()
    assert _saldo(client, enc, mid) == 2000
    assert client.post(f"/dispensacions/{d['id']}/devolucio", json={"nota": "error"}, headers=enc).status_code == 201
    assert _saldo(client, enc, mid) == 5000


def test_limit_negatiu(ctx):
    client, _, sec = ctx
    enc = token(client, sec, "enc")
    _activa(client, sec, limit=1500)
    pid, mid = _prepara(client, enc)
    client.post(f"/socis/{mid}/moneder/recarrega", json={"import_cent": 1000, "metode": "efectiu"}, headers=enc)
    assert client.post("/dispensacions", json={"member_id": mid, "product_id": pid, "grams": "2", "metode": "monedero"}, headers=enc).status_code == 201  # 2000 > 1000, queda en -1000
    assert _saldo(client, enc, mid) == -1000
    assert client.post("/dispensacions", json={"member_id": mid, "product_id": pid, "grams": "1", "metode": "monedero"}, headers=enc).status_code == 422  # -2000 < -1500


def test_anular_recarrega_nomes_si_el_saldo_ho_permet(ctx):
    client, _, sec = ctx
    enc = token(client, sec, "enc")
    _activa(client, sec)
    pid, mid = _prepara(client, enc)
    r = client.post(f"/socis/{mid}/moneder/recarrega", json={"import_cent": 3000, "metode": "efectiu"}, headers=enc).json()
    client.post("/dispensacions", json={"member_id": mid, "product_id": pid, "grams": "2", "metode": "monedero"}, headers=enc)
    assert client.post(f"/caixa/apunts/{r['apunt']}/correccio", json={"nota": "recàrrega errònia"}, headers=enc).status_code == 422  # ja gastat
    r2 = client.post(f"/socis/{mid}/moneder/recarrega", json={"import_cent": 500, "metode": "efectiu"}, headers=enc).json()
    assert client.post(f"/caixa/apunts/{r2['apunt']}/correccio", json={"nota": "recàrrega errònia"}, headers=enc).status_code == 201
    assert _saldo(client, enc, mid) == 1000


def test_recarrega_repetida_amb_la_mateixa_referencia_no_es_duplica(ctx):
    client, _, sec = ctx
    enc = token(client, sec, "enc")
    _activa(client, sec)
    pid, mid = _prepara(client, enc)
    body = {"import_cent": 1000, "metode": "efectiu", "client_ref": "ref-recarrega-0001"}
    a = client.post(f"/socis/{mid}/moneder/recarrega", json=body, headers=enc)
    b = client.post(f"/socis/{mid}/moneder/recarrega", json=body, headers=enc)
    assert a.status_code == 201 and b.status_code in (200, 201) and _saldo(client, enc, mid) == 1000

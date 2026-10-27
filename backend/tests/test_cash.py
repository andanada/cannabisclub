from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.models import CashEntry, ImmutableError
from tests.test_api import SOCI, ctx, env, token  # noqa: F401
from tests.test_stock import setup_data


def disp(client, h, mid, pid, g="2"):
    r = client.post("/dispensacions", json={"member_id": mid, "product_id": pid, "grams": g}, headers=h)
    assert r.status_code == 201
    return r.json()["id"], r.json()["import_cent"]


def test_sense_caixa_oberta_no_es_pot_cobrar_ni_gastar(ctx):
    client, factory, sec = ctx
    enc = token(client, sec, "enc")
    mid, pid = setup_data(client, enc, factory)
    d, _ = disp(client, enc, mid, pid)
    assert client.post("/cobraments", json={"movement_id": d, "metode": "efectiu"}, headers=enc).status_code == 422
    assert client.post("/despeses", json={"local_id": 1, "cent": 500, "metode": "efectiu", "categoria": "x", "concepte": "compra"}, headers=enc).status_code == 422


def test_cicle_complet_quadrament_i_diferencia(ctx):
    client, factory, sec = ctx
    enc, disp_h = token(client, sec, "enc"), token(client, sec, "disp")
    mid, pid = setup_data(client, enc, factory)
    assert client.post("/caixa/obrir", json={"local_id": 1, "opening_cent": 10000}, headers=enc).status_code == 201
    assert client.post("/caixa/obrir", json={"local_id": 1, "opening_cent": 1}, headers=enc).status_code == 422
    d, imp = disp(client, disp_h, mid, pid, "2")           # 2 g * 800 = 1600
    assert imp == 1600
    assert client.post("/cobraments", json={"movement_id": d, "metode": "efectiu"}, headers=disp_h).status_code == 201
    assert client.post("/cobraments", json={"movement_id": d, "metode": "efectiu"}, headers=disp_h).status_code == 422  # doble cobrament
    d2, imp2 = disp(client, disp_h, mid, pid, "1")         # 800 amb targeta: no entra al calaix
    assert client.post("/cobraments", json={"movement_id": d2, "metode": "targeta"}, headers=disp_h).status_code == 201
    assert client.post("/despeses", json={"local_id": 1, "cent": 300, "metode": "efectiu", "categoria": "neteja", "concepte": "lleixiu"}, headers=enc).status_code == 201
    # esperat en efectiu: 10000 + 1600 - 300 = 11300
    r = client.post("/caixa/tancar", json={"local_id": 1, "counted_cent": 11250}, headers=enc).json()
    assert r["esperat_cent"] == 11300 and r["diferencia_cent"] == -50
    assert client.post("/cobraments", json={"movement_id": d, "metode": "efectiu"}, headers=disp_h).status_code == 422  # caixa tancada


def test_dispensador_no_pot_obrir_ni_gastar_ni_veure_informes(ctx):
    client, factory, sec = ctx
    h = token(client, sec, "disp")
    assert client.post("/caixa/obrir", json={"local_id": 1, "opening_cent": 0}, headers=h).status_code == 403
    assert client.post("/despeses", json={"local_id": 1, "cent": 1, "metode": "efectiu", "categoria": "x", "concepte": "abc"}, headers=h).status_code == 403
    assert client.get("/locals/1/informe", params={"des": "2020-01-01", "fins": "2099-01-01"}, headers=h).status_code == 403


def test_no_es_pot_corregir_dispensacio_cobrada_sense_corregir_cobrament(ctx):
    client, factory, sec = ctx
    enc = token(client, sec, "enc")
    mid, pid = setup_data(client, enc, factory)
    client.post("/caixa/obrir", json={"local_id": 1, "opening_cent": 0}, headers=enc)
    d, _ = disp(client, enc, mid, pid)
    ap = client.post("/cobraments", json={"movement_id": d, "metode": "efectiu"}, headers=enc).json()["apunt"]
    r = client.post(f"/moviments/{d}/correccio", json={"nota": "error"}, headers=enc)
    assert r.status_code == 422 and "cobrament" in r.json()["detail"]
    assert client.post(f"/caixa/apunts/{ap}/correccio", json={"nota": "anul·lat"}, headers=enc).status_code == 201
    assert client.post(f"/moviments/{d}/correccio", json={"nota": "error"}, headers=enc).status_code == 201
    # ja corregida: no es pot tornar a cobrar
    assert client.post("/cobraments", json={"movement_id": d, "metode": "efectiu"}, headers=enc).status_code == 422


def test_informe_resta_correccions_i_agrupa_despeses(ctx):
    client, factory, sec = ctx
    enc = token(client, sec, "enc")
    mid, pid = setup_data(client, enc, factory)
    client.post("/caixa/obrir", json={"local_id": 1, "opening_cent": 0}, headers=enc)
    d1, _ = disp(client, enc, mid, pid, "2")   # 1600
    d2, _ = disp(client, enc, mid, pid, "1")   # 800
    a1 = client.post("/cobraments", json={"movement_id": d1, "metode": "efectiu"}, headers=enc).json()["apunt"]
    client.post("/cobraments", json={"movement_id": d2, "metode": "targeta"}, headers=enc)
    client.post(f"/caixa/apunts/{a1}/correccio", json={"nota": "anul·lat"}, headers=enc)   # -1600
    g = client.post("/despeses", json={"local_id": 1, "cent": 1000, "metode": "efectiu", "categoria": "compres", "concepte": "estoc"}, headers=enc).json()["apunt"]
    client.post("/despeses", json={"local_id": 1, "cent": 200, "metode": "efectiu", "categoria": "neteja", "concepte": "lleixiu"}, headers=enc)
    client.post(f"/caixa/apunts/{g}/correccio", json={"nota": "devolució"}, headers=enc)   # +1000 sobre la despesa
    today = date.today().isoformat()
    r = client.get("/locals/1/informe", params={"des": today, "fins": today}, headers=enc).json()
    assert r["ingressos_cent"] == 800                      # 1600 + 800 - 1600
    assert r["despeses_cent"] == 200                       # 1000 + 200 - 1000
    assert r["despeses_per_categoria"] == {"compres": 0, "neteja": 200}
    assert r["resultat_cent"] == 600
    assert r["dispensat_mg"] == 3000
    csv_ = client.get("/locals/1/apunts.csv", params={"des": today, "fins": today}, headers=enc)
    assert csv_.status_code == 200 and csv_.text.splitlines()[0].startswith("id,data_hora_utc")
    assert len(csv_.text.splitlines()) == 1 + 6


def test_apunts_immutables(ctx):
    client, factory, sec = ctx
    enc = token(client, sec, "enc")
    client.post("/caixa/obrir", json={"local_id": 1, "opening_cent": 0}, headers=enc)
    client.post("/despeses", json={"local_id": 1, "cent": 100, "metode": "efectiu", "categoria": "x", "concepte": "abc"}, headers=enc)
    s = factory()
    e = s.scalars(select(CashEntry)).first()
    e.import_cent = -1
    with pytest.raises(ImmutableError):
        s.commit()
    s.rollback(); s.close()

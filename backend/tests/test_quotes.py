from datetime import date, timedelta

from sqlalchemy import select

from app import quotes
from app.models import CashEntry, ImmutableError, Quota
from tests.test_api import SOCI, ctx, env, token  # noqa: F401
from tests.test_stock import setup_data

import pytest


def obrir(client, h, cent=0):
    assert client.post("/caixa/obrir", json={"local_id": 1, "opening_cent": cent}, headers=h).status_code == 201


def quota(client, h, mid, cent=2000, metode="efectiu", mesos=1):
    return client.post(f"/socis/{mid}/quotes", json={"import_cent": cent, "metode": metode, "mesos": mesos}, headers=h)


def test_add_months_respecta_final_de_mes():
    assert quotes.add_months(date(2026, 1, 31), 1) == date(2026, 2, 28)
    assert quotes.add_months(date(2024, 1, 31), 1) == date(2024, 2, 29)
    assert quotes.add_months(date(2026, 11, 15), 3) == date(2027, 2, 15)
    assert quotes.add_months(date(2026, 12, 31), 12) == date(2027, 12, 31)


def test_cobrar_quota_entra_a_caixa_i_deixa_al_dia(ctx):
    client, factory, sec = ctx
    enc = token(client, sec, "enc")
    mid = client.post("/socis", json=SOCI, headers=enc).json()["id"]
    assert client.get(f"/socis/{mid}", headers=enc).json()["quota"] == {"al_dia": False, "valid_fins": None}
    obrir(client, enc, 10000)
    r = quota(client, enc, mid, 2500, "efectiu", 3)
    assert r.status_code == 201
    v = client.get(f"/socis/{mid}", headers=enc).json()["quota"]
    assert v["al_dia"] is True
    assert date.fromisoformat(v["valid_fins"]) > date.today()
    # la quota és un ingrés de caixa en efectiu: 10000 + 2500
    assert client.get("/locals/1/caixa", headers=enc).json()["esperat_cent"] == 12500
    informe = client.get(f"/locals/1/informe?des={date.today()}&fins={date.today()}", headers=enc).json()
    assert informe["ingressos_cent"] == 2500


def test_renovar_abans_de_caducar_allarga_des_del_final(ctx):
    client, factory, sec = ctx
    enc = token(client, sec, "enc")
    mid = client.post("/socis", json=SOCI, headers=enc).json()["id"]
    obrir(client, enc)
    primera = quota(client, enc, mid, mesos=1).json()
    segona = quota(client, enc, mid, mesos=1).json()
    h = client.get(f"/socis/{mid}/quotes", headers=enc).json()
    a, b = sorted(h["historial"], key=lambda x: x["id"])
    assert date.fromisoformat(b["valid_des"]) == date.fromisoformat(a["valid_fins"]) + timedelta(days=1)
    assert primera["valid_fins"] == a["valid_fins"] and segona["valid_fins"] == b["valid_fins"]


def test_sense_caixa_oberta_o_dades_invalides(ctx):
    client, factory, sec = ctx
    enc = token(client, sec, "enc")
    mid = client.post("/socis", json=SOCI, headers=enc).json()["id"]
    assert quota(client, enc, mid).status_code == 422  # caixa tancada
    obrir(client, enc)
    assert quota(client, enc, mid, cent=0).status_code == 422
    assert quota(client, enc, mid, mesos=0).status_code == 422
    assert quota(client, enc, mid, mesos=25).status_code == 422
    assert quota(client, enc, mid, metode="bizum").status_code == 422
    assert client.post("/socis/9999/quotes", json={"import_cent": 1, "metode": "efectiu", "mesos": 1}, headers=enc).status_code == 404


def test_soci_de_baixa_no_pot_pagar_quota(ctx):
    client, factory, sec = ctx
    enc = token(client, sec, "enc")
    mid = client.post("/socis", json=SOCI, headers=enc).json()["id"]
    obrir(client, enc)
    client.post(f"/socis/{mid}/estat", json={"estat": "baixa"}, headers=enc)
    assert quota(client, enc, mid).status_code == 422


def test_corregir_el_cobrament_anulla_la_quota(ctx):
    client, factory, sec = ctx
    enc = token(client, sec, "enc")
    mid = client.post("/socis", json=SOCI, headers=enc).json()["id"]
    obrir(client, enc, 0)
    q = quota(client, enc, mid, 2000).json()
    s = factory()
    entry = s.scalar(select(CashEntry).where(CashEntry.tipus == "quota"))
    s.close()
    assert client.post(f"/caixa/apunts/{entry.id}/correccio", json={"nota": "error de cobrament"}, headers=enc).status_code == 201
    assert client.get(f"/socis/{mid}", headers=enc).json()["quota"]["al_dia"] is False
    h = client.get(f"/socis/{mid}/quotes", headers=enc).json()
    assert h["historial"][0]["anulada"] is True
    assert client.get("/locals/1/caixa", headers=enc).json()["esperat_cent"] == 0
    assert q["id"] == h["historial"][0]["id"]


def test_les_quotes_no_es_poden_editar_ni_esborrar(ctx):
    client, factory, sec = ctx
    enc = token(client, sec, "enc")
    mid = client.post("/socis", json=SOCI, headers=enc).json()["id"]
    obrir(client, enc)
    quota(client, enc, mid)
    s = factory()
    qq = s.scalar(select(Quota))
    qq.mesos = 99
    with pytest.raises(ImmutableError):
        s.commit()
    s.rollback()
    s.delete(s.scalar(select(Quota)))
    with pytest.raises(ImmutableError):
        s.commit()
    s.close()


def test_aillament_per_local_i_rols(ctx):
    client, factory, sec = ctx
    enc, disp, admin = token(client, sec, "enc"), token(client, sec, "disp"), token(client, sec, "admin")
    mid = client.post("/socis", json=SOCI, headers=enc).json()["id"]
    altre = client.post("/socis", json={**SOCI, "local_id": 2, "document": "99999999R"}, headers=admin).json()["id"]
    obrir(client, enc)
    assert quota(client, enc, altre).status_code == 403
    assert client.get(f"/socis/{altre}/quotes", headers=enc).status_code == 403
    assert quota(client, disp, mid).status_code == 201  # recepció: qualsevol rol del local pot cobrar la quota


def test_quota_obligatoria_bloqueja_la_dispensacio(ctx):
    client, factory, sec = ctx
    enc, admin = token(client, sec, "enc"), token(client, sec, "admin")
    mid, pid = setup_data(client, enc, factory)
    obrir(client, enc)
    d = {"member_id": mid, "product_id": pid, "grams": "1"}
    assert client.post("/dispensacions", json=d, headers=enc).status_code == 201  # per defecte no s'exigeix
    assert client.put("/locals/1/config", json={"quota_obligatoria": True}, headers=enc).status_code == 403  # només admin
    assert client.put("/locals/1/config", json={"quota_obligatoria": True}, headers=admin).status_code == 200
    r = client.post("/dispensacions", json=d, headers=enc)
    assert r.status_code == 422 and "quota" in r.json()["detail"].lower()
    assert quota(client, enc, mid).status_code == 201
    assert client.post("/dispensacions", json=d, headers=enc).status_code == 201
    assert client.get("/me", headers=enc).json()["locals"][0]["quota_obligatoria"] is True


def test_config_de_quota_per_defecte(ctx):
    client, factory, sec = ctx
    admin = token(client, sec, "admin")
    r = client.put("/locals/1/config", json={"quota_cent": 2500, "quota_mesos": 6}, headers=admin)
    assert r.status_code == 200
    loc = [l for l in client.get("/me", headers=admin).json()["locals"] if l["id"] == 1][0]
    assert loc["quota_cent"] == 2500 and loc["quota_mesos"] == 6 and loc["quota_obligatoria"] is False
    assert client.put("/locals/1/config", json={"quota_mesos": 99}, headers=admin).status_code == 422
    assert client.put("/locals/9/config", json={"quota_cent": 1}, headers=admin).status_code == 404

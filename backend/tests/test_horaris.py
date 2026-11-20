"""Horaris: configuració, calendari, permisos, aprovació de canvis, càlculs i avançaments (que compten com a despesa)."""
from datetime import date

from tests.test_api import ctx, env, token  # noqa: F401

AVUI = date.today().isoformat()
DILLUNS = "2031-03-03"   # dilluns: dos torns
DIUMENGE = "2031-03-09"  # diumenge: un sol torn


def _uid(client, h, nom):
    return next(u["id"] for u in client.get("/locals/1/horaris/mes", params={"any": 2031, "mes": 3}, headers=h).json()["treballadors"] if u["username"] == nom)


def _slot(client, h, d, torn, lloc, uid, **extra):
    return client.put("/locals/1/horaris/slot", json={"data": d, "torn": torn, "lloc": lloc, "user_id": uid, **extra}, headers=h)


def _mes(client, h):
    return client.get("/locals/1/horaris/mes", params={"any": 2031, "mes": 3}, headers=h).json()


def test_config_per_defecte_i_festius_especials(ctx):
    client, _, sec = ctx
    enc = token(client, sec, "enc")
    cfg = client.get("/locals/1/horaris/config", headers=enc).json()
    assert cfg["torns"]["mati"] == ["10:00", "16:30"] and cfg["dies_unics"] == [6]
    dies = {d["data"]: d for d in client.get("/locals/1/horaris/mes", params={"any": 2031, "mes": 12}, headers=enc).json()["dies"]}
    assert [t["torn"] for t in dies["2031-12-02"]["torns"]] == ["mati", "tarda"]
    assert [t["torn"] for t in dies["2031-12-07"]["torns"]] == ["unic"]       # diumenge
    assert dies["2031-12-24"]["torns"][1]["fi"] == "20:00"
    assert dies["2031-12-25"]["torns"][0]["torn"] == "unic" and dies["2031-12-25"]["torns"][0]["fi"] == "21:00"
    d1 = client.get("/locals/1/horaris/mes", params={"any": 2032, "mes": 1}, headers=enc).json()["dies"][0]
    assert d1["torns"][0]["inici"] == "15:00" and d1["torns"][0]["fi"] == "21:00"


def test_config_editable_nomes_per_gerencia(ctx):
    client, _, sec = ctx
    enc, disp = token(client, sec, "enc"), token(client, sec, "disp")
    cfg = client.get("/locals/1/horaris/config", headers=enc).json()
    cfg["torns"]["mati"] = ["09:00", "16:00"]
    assert client.put("/locals/1/horaris/config", json=cfg, headers=disp).status_code == 403
    assert client.put("/locals/1/horaris/config", json=cfg, headers=enc).status_code == 200
    assert client.get("/locals/1/horaris/config", headers=disp).json()["torns"]["mati"] == ["09:00", "16:00"]
    cfg["torns"]["mati"] = ["25:00", "16:00"]
    assert client.put("/locals/1/horaris/config", json=cfg, headers=enc).status_code == 422


def test_assignar_calcular_i_treure(ctx):
    client, _, sec = ctx
    enc = token(client, sec, "enc")
    disp_id = _uid(client, enc, "disp")
    enc_id = _uid(client, enc, "enc")
    assert _slot(client, enc, DILLUNS, "mati", "dispensari", disp_id).status_code == 200
    assert _slot(client, enc, DILLUNS, "mati", "recepcio", disp_id).status_code == 422  # ja és a l'altre lloc del torn
    assert _slot(client, enc, DILLUNS, "tarda", "recepcio", disp_id, inici="17:30", fi="23:00").status_code == 200
    assert _slot(client, enc, DIUMENGE, "mati", "recepcio", enc_id).status_code == 422   # el diumenge només hi ha torn únic
    assert _slot(client, enc, DIUMENGE, "unic", "dispensari", enc_id).status_code == 200
    t = {x["usuari"]: x for x in _mes(client, enc)["totals"]}
    assert t["disp"]["torns"] == 2 and t["disp"]["minuts"] == 390 + 330   # 10:00-16:30 + 17:30-23:00
    assert t["enc"]["torns"] == 1 and t["enc"]["hores"] == 8.0
    assert _slot(client, enc, DILLUNS, "tarda", "recepcio", None).status_code == 200  # tocar-ho un altre cop el lleva
    assert {x["usuari"]: x for x in _mes(client, enc)["totals"]}["disp"]["torns"] == 1
    assert client.put("/locals/1/horaris/torn", json={"data": DILLUNS, "torn": "mati", "inici": "11:00", "fi": "16:30"}, headers=enc).status_code == 200
    assert {x["usuari"]: x for x in _mes(client, enc)["totals"]}["disp"]["minuts"] == 330
    assert client.put("/locals/1/horaris/torn", json={"data": DILLUNS, "torn": "mati", "inici": None, "fi": None}, headers=enc).status_code == 200
    assert {x["usuari"]: x for x in _mes(client, enc)["totals"]}["disp"]["minuts"] == 390


def test_treballador_no_modifica_el_calendari(ctx):
    client, _, sec = ctx
    enc, disp = token(client, sec, "enc"), token(client, sec, "disp")
    uid = _uid(client, enc, "disp")
    assert _slot(client, disp, DILLUNS, "mati", "dispensari", uid).status_code == 403
    assert client.put("/locals/1/horaris/torn", json={"data": DILLUNS, "torn": "mati", "inici": "11:00", "fi": "12:00"}, headers=disp).status_code == 403
    assert client.get("/locals/1/horaris/mes", params={"any": 2031, "mes": 3}, headers=disp).status_code == 200
    assert client.get("/locals/1/horaris/registre", params={"des": AVUI, "fins": AVUI}, headers=disp).status_code == 403
    assert client.get("/locals/1/horaris/mes", params={"any": 2031, "mes": 3}).status_code == 401


def test_diferencia_no_compta_fins_aprovar(ctx):
    client, _, sec = ctx
    enc, disp = token(client, sec, "enc"), token(client, sec, "disp")
    uid = _uid(client, enc, "disp")
    _slot(client, enc, DILLUNS, "mati", "dispensari", uid)
    sol = {"tipus": "diferencia", "data": DILLUNS, "torn": "mati", "minuts": -60, "comentari": "surto abans"}
    assert client.post("/locals/1/horaris/sollicituds", json={**sol, "torn": "tarda"}, headers=disp).status_code == 422  # no hi treballa
    assert client.post("/locals/1/horaris/sollicituds", json={**sol, "minuts": 0}, headers=disp).status_code == 422
    rid = client.post("/locals/1/horaris/sollicituds", json=sol, headers=disp).json()["id"]
    assert {x["usuari"]: x for x in _mes(client, enc)["totals"]}["disp"]["minuts"] == 390   # encara no compta
    assert _mes(client, enc)["pendents"] == 1
    assert client.post(f"/horaris/sollicituds/{rid}/aprova", json={}, headers=disp).status_code == 403   # el treballador no s'ho aprova
    assert client.post(f"/horaris/sollicituds/{rid}/aprova", json={}, headers=enc).status_code == 200
    assert client.post(f"/horaris/sollicituds/{rid}/aprova", json={}, headers=enc).status_code == 422     # ja resolta
    t = {x["usuari"]: x for x in _mes(client, enc)["totals"]}["disp"]
    assert t["minuts"] == 330 and t["torns"] == 1 and t["minuts_diferencies"] == -60
    reg = client.get("/locals/1/horaris/registre", params={"des": AVUI, "fins": AVUI}, headers=enc).json()
    assert [r["accio"] for r in reg][:2] == ["diferencia", "assigna"] and reg[0]["request_id"] == rid


def test_canvi_de_torn_s_aplica_en_aprovar_i_rebutjar_no_el_toca(ctx):
    client, _, sec = ctx
    enc, disp = token(client, sec, "enc"), token(client, sec, "disp")
    uid, eid = _uid(client, enc, "disp"), _uid(client, enc, "enc")
    _slot(client, enc, DILLUNS, "mati", "recepcio", uid)
    sol = {"tipus": "canvi", "data": DILLUNS, "torn": "mati", "substitut_id": eid}
    r1 = client.post("/locals/1/horaris/sollicituds", json=sol, headers=disp).json()["id"]
    assert client.post(f"/horaris/sollicituds/{r1}/rebutja", json={"nota": "no"}, headers=enc).status_code == 200
    assert _mes(client, enc)["dies"][2]["torns"][0]["llocs"]["recepcio"]["user_id"] == uid
    r2 = client.post("/locals/1/horaris/sollicituds", json=sol, headers=disp).json()["id"]
    r3 = client.post("/locals/1/horaris/sollicituds", json=sol, headers=disp).json()["id"]
    assert client.post(f"/horaris/sollicituds/{r2}/cancela", headers=enc).status_code == 422
    assert client.post(f"/horaris/sollicituds/{r3}/cancela", headers=disp).status_code == 200
    assert client.post(f"/horaris/sollicituds/{r2}/aprova", json={}, headers=enc).status_code == 200
    assert _mes(client, enc)["dies"][2]["torns"][0]["llocs"]["recepcio"]["user_id"] == eid
    totals = {x["usuari"]: x for x in _mes(client, enc)["totals"]}
    assert "disp" not in totals and totals["enc"]["torns"] == 1
    # el treballador només veu les seves sol·licituds; la gerència, totes
    assert len(client.get("/locals/1/horaris/sollicituds", headers=disp).json()) == 3
    assert len(client.get("/locals/1/horaris/sollicituds", params={"estat": "aprovada"}, headers=enc).json()) == 1


def test_avancos_nomes_gerencia_i_compten_com_a_despesa(ctx):
    client, _, sec = ctx
    enc, disp = token(client, sec, "enc"), token(client, sec, "disp")
    uid = _uid(client, enc, "disp")
    cos = {"data": AVUI, "user_id": uid, "import_cent": 5000, "comentari": "per al lloguer"}
    assert client.post("/locals/1/horaris/avancos", json=cos, headers=disp).status_code == 403
    assert client.get("/locals/1/horaris/avancos", params={"des": AVUI, "fins": AVUI}, headers=disp).status_code == 403
    r = client.post("/locals/1/horaris/avancos", json=cos, headers=enc)
    assert r.status_code == 201
    gastos = client.get("/locals/1/gastos", params={"des": AVUI, "fins": AVUI}, headers=enc).json()
    assert len(gastos) == 1 and gastos[0]["categoria"] == "Sous/avançaments" and gastos[0]["import_cent"] == 5000 and gastos[0]["caixa"] is False
    # de caixa: cal caixa oberta; res a mitges si falla
    assert client.post("/locals/1/horaris/avancos", json={**cos, "de_caixa": True}, headers=enc).status_code == 422
    assert len(client.get("/locals/1/horaris/avancos", params={"des": AVUI, "fins": AVUI}, headers=enc).json()["avancos"]) == 1
    client.post("/caixa/obrir", json={"local_id": 1, "opening_cent": 10000}, headers=enc)
    c = client.post("/locals/1/horaris/avancos", json={**cos, "import_cent": 3000, "de_caixa": True}, headers=enc)
    assert c.status_code == 201
    gastos = client.get("/locals/1/gastos", params={"des": AVUI, "fins": AVUI}, headers=enc).json()
    assert len(gastos) == 2 and sum(g["caixa"] for g in gastos) == 1
    llista = client.get("/locals/1/horaris/avancos", params={"des": AVUI, "fins": AVUI}, headers=enc).json()
    assert llista["totals"] == [{"user_id": uid, "usuari": "disp", "import_cent": 8000}]
    # anul·lació: es compensa la caixa i el total
    assert client.post(f"/horaris/avancos/{c.json()['id']}/anulacio", json={"nota": "error"}, headers=enc).status_code == 201
    assert client.post(f"/horaris/avancos/{c.json()['id']}/anulacio", json={"nota": "error"}, headers=enc).status_code == 422
    llista = client.get("/locals/1/horaris/avancos", params={"des": AVUI, "fins": AVUI}, headers=enc).json()
    assert llista["totals"][0]["import_cent"] == 5000
    t = client.post("/caixa/tancar", json={"local_id": 1, "counted_cent": 10000}, headers=enc).json()
    assert t["esperat_cent"] == 10000
    # validacions
    assert client.post("/locals/1/horaris/avancos", json={**cos, "import_cent": 0}, headers=enc).status_code == 422
    assert client.post("/locals/1/horaris/avancos", json={**cos, "user_id": 9999}, headers=enc).status_code == 422


def test_registre_de_canvis_es_append_only(ctx):
    import pytest
    from app.horaris_models import ShiftChange
    from app.models import ImmutableError
    client, factory, sec = ctx
    enc = token(client, sec, "enc")
    _slot(client, enc, DILLUNS, "mati", "dispensari", _uid(client, enc, "disp"))
    s = factory()
    c = s.query(ShiftChange).first()
    c.abans = "x"
    with pytest.raises(ImmutableError):
        s.flush()

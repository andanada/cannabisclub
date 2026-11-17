"""Diverses caixes registradores: una sessió oberta per caixa, caixa de cada empleat, magatzem propi i resum de sessions."""
from datetime import date

from tests.test_api import SOCI, ctx, env, token  # noqa: F401

AVUI = date.today().isoformat()


def _uid(client, adm, nom):
    return next(u["id"] for u in client.get("/usuaris", headers=adm).json() if u["username"] == nom)


def _escena(client, enc):
    mag = client.post("/locals/1/magatzems", json={"nom": "Dispensari"}, headers=enc).json()["id"]
    c1 = client.post("/locals/1/caixes", json={"nom": "Dispensari", "warehouse_id": mag}, headers=enc).json()["id"]
    c2 = client.post("/locals/1/caixes", json={"nom": "Entrada"}, headers=enc).json()["id"]
    return mag, c1, c2


def test_una_sessio_per_caixa_i_una_per_empleat(ctx):
    client, _, sec = ctx
    adm, enc = token(client, sec, "admin"), token(client, sec, "enc")
    mag, c1, c2 = _escena(client, enc)
    assert client.post("/locals/1/caixes", json={"nom": "Entrada"}, headers=enc).status_code == 422  # nom repetit
    disp_id = _uid(client, adm, "disp")
    ob = lambda **k: client.post("/caixa/obrir", json={"local_id": 1, "opening_cent": 1000, **k}, headers=enc)  # noqa: E731
    assert ob(register_id=c1, assigned_to=disp_id).status_code == 201
    assert ob(register_id=c1).status_code == 422                        # aquesta caixa ja és oberta
    assert ob(register_id=c2, assigned_to=disp_id).status_code == 422   # l'empleat ja en té una
    assert ob(register_id=c2).status_code == 201                        # una altra caixa, per al responsable
    assert ob().status_code == 201                                      # i la caixa implícita encara es pot obrir una vegada
    assert ob().status_code == 422
    est = client.get("/locals/1/caixes", headers=enc).json()
    assert {c["nom"]: c["oberta"] for c in est["caixes"]} == {"Dispensari": True, "Entrada": True}
    assert client.put(f"/caixes/{c1}", json={"actiu": False}, headers=enc).status_code == 422  # oberta: no es pot desactivar


def test_cada_empleat_cobra_a_la_seva_caixa_i_descompta_del_magatzem_de_la_caixa(ctx):
    client, _, sec = ctx
    adm, enc, disp = token(client, sec, "admin"), token(client, sec, "enc"), token(client, sec, "disp")
    mag, c1, c2 = _escena(client, enc)
    pid = client.post("/productes", json={"local_id": 1, "nom": "Flor", "preu_cent_per_g": 1000, "es_genetic": True}, headers=enc).json()["id"]
    client.post("/moviments/entrada", json={"product_id": pid, "grams": "10"}, headers=enc)                        # magatzem principal
    client.post("/moviments/traspas", json={"product_id": pid, "de": None, "a": mag, "grams": "4"}, headers=enc)   # 4 g al del Dispensari
    mid = client.post("/socis", json=SOCI, headers=enc).json()["id"]
    s1 = client.post("/caixa/obrir", json={"local_id": 1, "opening_cent": 0, "register_id": c1, "assigned_to": _uid(client, adm, "disp")}, headers=enc).json()["sessio"]
    s2 = client.post("/caixa/obrir", json={"local_id": 1, "opening_cent": 500, "register_id": c2}, headers=enc).json()["sessio"]
    # el dispensador (caixa Dispensari, magatzem propi): només hi ha 4 g
    assert client.post("/dispensacions", json={"member_id": mid, "product_id": pid, "grams": "5", "metode": "efectiu"}, headers=disp).status_code == 422
    assert client.post("/dispensacions", json={"member_id": mid, "product_id": pid, "grams": "3", "metode": "efectiu"}, headers=disp).status_code == 201
    assert client.get("/locals/1/caixa", headers=disp).json()["sessio"] == s1
    # l'encarregat (Entrada, sense magatzem): treballa a la seva i descompta del principal (6 g)
    assert client.get("/locals/1/caixa", headers=enc).json()["sessio"] == s2
    assert client.post("/dispensacions", json={"member_id": mid, "product_id": pid, "grams": "2", "metode": "targeta"}, headers=enc).status_code == 201
    # tancament per sessió, cada una amb el seu efectiu
    t1 = client.post("/caixa/tancar", json={"local_id": 1, "counted_cent": 3000, "session_id": s1}, headers=enc).json()
    assert t1["esperat_cent"] == 3000 and t1["diferencia_cent"] == 0
    t2 = client.post("/caixa/tancar", json={"local_id": 1, "counted_cent": 500}, headers=enc).json()
    assert t2["esperat_cent"] == 500  # la targeta no entra al calaix
    resum = client.get("/locals/1/caixa/sessions", params={"des": AVUI, "fins": AVUI}, headers=enc).json()
    per = {r["id"]: r for r in resum}
    assert per[s1]["empleat"] == "disp" and per[s1]["caixa"] == "Dispensari" and per[s1]["efectiu_cent"] == 3000
    assert per[s2]["targeta_cent"] == 2000 and per[s2]["total_cent"] == 2000 and per[s2]["diferencia_cent"] == 0


def test_ambigu_si_hi_ha_diverses_caixes_i_cap_es_teva(ctx):
    client, _, sec = ctx
    enc, disp = token(client, sec, "enc"), token(client, sec, "disp")
    mag, c1, c2 = _escena(client, enc)
    client.post("/caixa/obrir", json={"local_id": 1, "opening_cent": 0, "register_id": c1}, headers=enc)
    client.post("/caixa/obrir", json={"local_id": 1, "opening_cent": 0, "register_id": c2, "assigned_to": None}, headers=enc)
    est = client.get("/locals/1/caixa", headers=disp).json()
    assert est["oberta"] is False and est["ambigua"] is True
    pid = client.post("/productes", json={"local_id": 1, "nom": "Flor", "preu_cent_per_g": 1000, "es_genetic": True}, headers=enc).json()["id"]
    client.post("/moviments/entrada", json={"product_id": pid, "grams": "10"}, headers=enc)
    mid = client.post("/socis", json=SOCI, headers=enc).json()["id"]
    r = client.post("/dispensacions", json={"member_id": mid, "product_id": pid, "grams": "1", "metode": "efectiu"}, headers=disp)
    assert r.status_code == 422 and "cap és teva" in r.text

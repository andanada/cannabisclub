"""Privilegis d'un dispensador: devolucions, editar descomptes i límit negatiu propi del monedero."""
from tests.test_api import SOCI, ctx, env, token  # noqa: F401


def _uid(client, adm, nom):
    return next(u["id"] for u in client.get("/usuaris", headers=adm).json() if u["username"] == nom)


def test_devolucio_i_descomptes_nomes_amb_privilegi(ctx):
    client, _, sec = ctx
    adm, enc = token(client, sec, "admin"), token(client, sec, "enc")
    disp = token(client, sec, "disp")
    client.post("/caixa/obrir", json={"local_id": 1, "opening_cent": 0}, headers=enc)
    pid = client.post("/productes", json={"local_id": 1, "nom": "Flor", "preu_cent_per_g": 1000, "es_genetic": True}, headers=enc).json()["id"]
    client.post("/moviments/entrada", json={"product_id": pid, "grams": "10"}, headers=enc)
    mid = client.post("/socis", json=SOCI, headers=enc).json()["id"]
    d = client.post("/dispensacions", json={"member_id": mid, "product_id": pid, "grams": "1", "metode": "efectiu"}, headers=disp).json()
    cos = {"tipus": "percent", "nom": "D", "valor": 10, "ambit": "tot"}
    assert client.post(f"/dispensacions/{d['id']}/devolucio", json={"nota": "motiu"}, headers=disp).status_code == 403
    assert client.post("/locals/1/descomptes", json=cos, headers=disp).status_code == 403
    assert client.get(f"/socis/{mid}/consum", params={"des": "2020-01-01", "fins": "2999-01-01"}, headers=disp).status_code == 403
    r = client.patch(f"/usuaris/{_uid(client, adm, 'disp')}", json={"pot_reemborsar": True, "pot_editar_descomptes": True}, headers=adm)
    assert r.status_code == 200
    disp = token(client, sec, "disp")  # els permisos nous s'apliquen en tornar a entrar
    assert client.get("/me", headers=disp).json()["pot_reemborsar"] is True
    assert client.get(f"/socis/{mid}/consum", params={"des": "2020-01-01", "fins": "2999-01-01"}, headers=disp).status_code == 200
    assert client.post(f"/dispensacions/{d['id']}/devolucio", json={"nota": "motiu"}, headers=disp).status_code == 201
    assert client.post("/locals/1/descomptes", json=cos, headers=disp).status_code in (200, 201)


def test_limit_negatiu_propi_de_l_empleat(ctx):
    client, _, sec = ctx
    adm, enc = token(client, sec, "admin"), token(client, sec, "enc")
    client.put("/locals/1/config", json={"moneder_actiu": True, "moneder_limit_cent": 0}, headers=adm)
    client.post("/caixa/obrir", json={"local_id": 1, "opening_cent": 0}, headers=enc)
    pid = client.post("/productes", json={"local_id": 1, "nom": "Flor", "preu_cent_per_g": 1000, "es_genetic": True}, headers=enc).json()["id"]
    client.post("/moviments/entrada", json={"product_id": pid, "grams": "10"}, headers=enc)
    mid = client.post("/socis", json=SOCI, headers=enc).json()["id"]
    def paga(): return client.post("/dispensacions", json={"member_id": mid, "product_id": pid, "grams": "1", "metode": "monedero"}, headers=enc).status_code
    assert paga() == 422  # límit del local: 0
    client.patch(f"/usuaris/{_uid(client, adm, 'enc')}", json={"moneder_limit_cent": 1500}, headers=adm)
    assert paga() == 201  # l'empleat pot deixar fins a -15 €
    assert client.get(f"/socis/{mid}/moneder", headers=enc).json()["saldo_cent"] == -1000
    assert paga() == 422  # -20 € passaria del seu límit
    assert client.patch(f"/usuaris/{_uid(client, adm, 'enc')}", json={"moneder_limit_cent": 2_000_000}, headers=adm).status_code == 422

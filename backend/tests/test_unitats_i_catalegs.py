"""Productes en unitats i a granel, aspecte de categories i monedes."""
from tests.test_api import SOCI, ctx, env, token  # noqa: F401


def _prod(client, enc, **k):
    return client.post("/productes", json={"local_id": 1, "nom": "P", "preu_cent_per_g": 300, "es_genetic": False, **k}, headers=enc)


def _escena(client, enc, **k):
    client.post("/caixa/obrir", json={"local_id": 1, "opening_cent": 0}, headers=enc)
    pid = _prod(client, enc, **k).json()["id"]
    client.post("/moviments/entrada", json={"product_id": pid, "grams": "10"}, headers=enc)
    return pid, client.post("/socis", json=SOCI, headers=enc).json()["id"]


def test_producte_en_unitats_nomes_enters_i_no_genetic(ctx):
    client, _, sec = ctx
    enc = token(client, sec, "enc")
    assert _prod(client, enc, nom="Clon", unitat="u", es_genetic=True).status_code == 422
    assert _prod(client, enc, nom="X", unitat="kg").status_code == 422
    pid, mid = _escena(client, enc, nom="Aigua", unitat="u")
    disp = lambda q: client.post("/dispensacions", json={"member_id": mid, "product_id": pid, "grams": q, "metode": "efectiu"}, headers=enc)  # noqa: E731
    assert disp("1.5").status_code == 422
    r = disp("2")
    assert r.status_code == 201 and r.json()["import_cent"] == 600  # 2 unitats × 3,00 €
    p = next(x for x in client.get("/locals/1/productes", headers=enc).json() if x["id"] == pid)
    assert p["unitat"] == "u" and p["estoc_g"] == "8"
    # la unitat no es pot canviar un cop hi ha moviments
    assert client.patch(f"/productes/{pid}", json={"unitat": "g"}, headers=enc).status_code == 422
    assert client.patch(f"/productes/{pid}", json={"es_genetic": True}, headers=enc).status_code == 422


def test_no_granel_nomes_quantitats_senceres(ctx):
    client, _, sec = ctx
    enc = token(client, sec, "enc")
    pid, mid = _escena(client, enc, nom="Preroll", granel=False)
    disp = lambda q: client.post("/dispensacions", json={"member_id": mid, "product_id": pid, "grams": q, "metode": "efectiu"}, headers=enc)  # noqa: E731
    assert disp("1.5").status_code == 422 and disp("2").status_code == 201
    assert client.patch(f"/productes/{pid}", json={"granel": True}, headers=enc).status_code == 200
    assert disp("1.5").status_code == 201


def test_aspecte_de_categories(ctx):
    client, _, sec = ctx
    enc, disp = token(client, sec, "enc"), token(client, sec, "disp")
    _prod(client, enc, nom="Aigua", categoria="Begudes")
    _prod(client, enc, nom="Cafè", categoria="Begudes")
    r = client.get("/locals/1/categories", headers=disp).json()
    assert r["categories"] == [{"nom": "Begudes", "icona": "", "color": "", "productes": 2}]
    assert client.put("/locals/1/categories", json={"nom": "Begudes", "icona": "🥤", "color": "blau"}, headers=disp).status_code == 403
    assert client.put("/locals/1/categories", json={"nom": "Begudes", "icona": "💩", "color": "blau"}, headers=enc).status_code == 422
    assert client.put("/locals/1/categories", json={"nom": "Begudes", "icona": "🥤", "color": "fosc"}, headers=enc).status_code == 422
    assert client.put("/locals/1/categories", json={"nom": "Begudes", "icona": "🥤", "color": "blau"}, headers=enc).status_code == 200
    assert client.get("/locals/1/categories", headers=disp).json()["categories"][0]["color"] == "blau"


def test_monedes(ctx):
    client, _, sec = ctx
    enc = token(client, sec, "enc")
    assert client.post("/locals/1/monedes", json={"nom": "Euro", "codi": "eur"}, headers=enc).status_code == 201
    assert client.post("/locals/1/monedes", json={"nom": "Euro 2", "codi": "EUR"}, headers=enc).status_code == 422
    assert client.post("/locals/1/monedes", json={"nom": "Crèdits", "codi": "C R!"}, headers=enc).status_code == 422
    assert [m["codi"] for m in client.get("/locals/1/monedes", headers=enc).json()] == ["EUR"]

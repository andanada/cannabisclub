from datetime import date, timedelta

from sqlalchemy import text

from tests.test_api import ctx, env, token  # noqa: F401
from tests.test_stock import setup_data


def test_dispensacio_amb_metode_cobra_atomicament(ctx):
    client, factory, sec = ctx
    enc = token(client, sec, "enc")
    mid, pid = setup_data(client, enc, factory)
    assert client.post("/caixa/obrir", json={"local_id": 1, "opening_cent": 0}, headers=enc).status_code == 201
    r = client.post("/dispensacions", json={"member_id": mid, "product_id": pid, "grams": "1", "metode": "efectiu"}, headers=enc)
    assert r.status_code == 201 and r.json()["cobrat"] is True
    caixa = client.get("/locals/1/caixa", headers=enc).json()
    assert caixa["esperat_cent"] == 800 and caixa["sense_cobrar"] == []


def test_dispensacio_amb_metode_sense_caixa_no_dispensa(ctx):
    client, factory, sec = ctx
    enc = token(client, sec, "enc")
    mid, pid = setup_data(client, enc, factory)
    r = client.post("/dispensacions", json={"member_id": mid, "product_id": pid, "grams": "1", "metode": "efectiu"}, headers=enc)
    assert r.status_code == 422
    est = {p["nom"]: p["estoc_g"] for p in client.get("/locals/1/estoc", headers=enc).json()}
    assert est["Producte A"] == "10"  # res a mitges


def test_tancar_caixa_informa_de_sense_cobrar(ctx):
    client, factory, sec = ctx
    enc = token(client, sec, "enc")
    mid, pid = setup_data(client, enc, factory)
    client.post("/caixa/obrir", json={"local_id": 1, "opening_cent": 0}, headers=enc)
    client.post("/dispensacions", json={"member_id": mid, "product_id": pid, "grams": "2"}, headers=enc)
    abans = client.get("/locals/1/caixa", headers=enc).json()
    assert abans["sense_cobrar_cent"] == 1600 and len(abans["sense_cobrar"]) == 1
    r = client.post("/caixa/tancar", json={"local_id": 1, "counted_cent": 0}, headers=enc).json()
    assert r["sense_cobrar_cent"] == 1600 and r["sense_cobrar"][0]["import_cent"] == 1600


def test_descompte_editar_nomes_fi_no_esborra_inici(ctx):
    client, factory, sec = ctx
    enc = token(client, sec, "enc")
    ini, fi = date.today() - timedelta(days=1), date.today() + timedelta(days=10)
    did = client.post("/locals/1/descomptes", json={"nom": "D", "tipus": "percent", "valor": 10, "ambit": "tot",
                                                    "inici": ini.isoformat(), "fi": fi.isoformat()}, headers=enc).json()["id"]
    nou = fi + timedelta(days=5)
    assert client.put(f"/descomptes/{did}", json={"fi": nou.isoformat()}, headers=enc).status_code == 200
    d = next(x for x in client.get("/locals/1/descomptes?tots=true", headers=enc).json() if x["id"] == did)
    assert d["inici"] == ini.isoformat() and d["fi"] == nou.isoformat()


def test_immutable_i_integritat_donen_409(ctx):
    from sqlalchemy.exc import IntegrityError
    from app.models import ImmutableError
    client, factory, sec = ctx
    app = client.app

    def a():
        raise ImmutableError("Els moviments d'estoc no es poden modificar: crea una correcció")

    def b():
        raise IntegrityError("INSERT secret", {}, Exception("detall intern"))
    for path, fn in (("/_prova_immutable", a), ("/_prova_integritat", b)):
        app.add_api_route(path, fn)
        app.router.routes.insert(0, app.router.routes.pop())  # abans del mount del frontend
    c = type(client)(app, raise_server_exceptions=False)
    r = c.get("/_prova_immutable")
    assert r.status_code == 409 and "correcció" in r.json()["detail"]
    r = c.get("/_prova_integritat")
    assert r.status_code == 409 and "secret" not in r.text and "intern" not in r.text

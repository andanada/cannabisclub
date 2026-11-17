"""Estadístiques: socis (gènere i edat amb llindar d'anonimat), dispensari i bar, finances."""
from datetime import date

from tests.test_api import SOCI, ctx, env, token  # noqa: F401


def _escena(client, enc):
    client.post("/caixa/obrir", json={"local_id": 1, "opening_cent": 0}, headers=enc)
    flor = client.post("/productes", json={"local_id": 1, "nom": "Flor", "preu_cent_per_g": 1000, "es_genetic": True}, headers=enc).json()["id"]
    beguda = client.post("/productes", json={"local_id": 1, "nom": "Aigua", "preu_cent_per_g": 200, "es_genetic": False}, headers=enc).json()["id"]
    for p in (flor, beguda):
        client.post("/moviments/entrada", json={"product_id": p, "grams": "50"}, headers=enc)
    mid = client.post("/socis", json={**SOCI, "genere": "dona"}, headers=enc).json()["id"]
    client.post("/dispensacions", json={"member_id": mid, "product_id": flor, "grams": "3", "metode": "efectiu"}, headers=enc)
    client.post("/dispensacions", json={"member_id": mid, "product_id": beguda, "grams": "2", "metode": "efectiu"}, headers=enc)
    return mid


def test_nomes_responsables(ctx):
    client, _, sec = ctx
    disp = token(client, sec, "disp")
    for t in ("membres", "dispensari", "finances"):
        assert client.get(f"/locals/1/estadistiques/{t}", headers=disp).status_code == 403


def test_membres_top_i_comptadors_i_genere_amagat_per_k(ctx):
    client, _, sec = ctx
    enc = token(client, sec, "enc")
    _escena(client, enc)
    r = client.get("/locals/1/estadistiques/membres", headers=enc).json()
    assert r["top_grams"][0]["soci"] == "Anna Prova" and r["top_grams"][0]["import_cent"] == 3400
    assert r["comptadors"]["nous_30d"] == 1 and r["comptadors"]["sense_visites_30d"] == 1
    assert len(r["nous_per_mes"]) == 12 and r["nous_per_mes"][-1]["socis"] == 1
    # un sol soci (< k): el gènere no es publica, ni el total
    assert r["genere"]["total"] is None and all(f["socis"] is None for f in r["genere"]["franges"] if f["franja"] == "Dona")


def test_dispensari_i_bar(ctx):
    client, _, sec = ctx
    enc = token(client, sec, "enc")
    _escena(client, enc)
    r = client.get("/locals/1/estadistiques/dispensari", headers=enc).json()
    assert r["dispensari"]["avui"] == 3000 and r["bar"]["avui"] == 400
    assert r["percentatge_genetics"] == round(3000 * 100 / 3400, 1)
    assert r["preu_mitja_genetics_cent_per_g"] == 1000
    assert r["top_genetics_grams"][0]["producte"] == "Flor" and r["top_no_genetics_import"][0]["producte"] == "Aigua"
    assert len(r["dispensari"]["mesos"]) == 6


def test_finances_vendes_despeses_i_benefici(ctx):
    client, _, sec = ctx
    enc = token(client, sec, "enc")
    _escena(client, enc)
    cat = client.post("/locals/1/gastos/categories", json={"nom": "C"}, headers=enc).json()["id"]
    tip = client.post("/locals/1/gastos/tipus", json={"nom": "T"}, headers=enc).json()["id"]
    client.post("/gastos", json={"local_id": 1, "data": date.today().isoformat(), "type_id": tip, "category_id": cat, "import_cent": 1000}, headers=enc)
    r = client.get("/locals/1/estadistiques/finances", headers=enc).json()
    mes = r["mesos"][date.today().month - 1]
    assert mes["vendes_cent"] == 3400 and mes["despeses_cent"] == 1000 and mes["benefici_cent"] == 2400
    assert r["ingressos"]["avui"] == 3400 and r["grams_any"] == "3" and r["mitjana_diaria_g"] == "3"
    assert client.get("/locals/1/estadistiques/finances", params={"any": 1999}, headers=enc).status_code == 422

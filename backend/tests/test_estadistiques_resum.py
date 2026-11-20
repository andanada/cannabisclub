"""Mòdul 8: rendibilitat per producte, resum mensual, finances dia a dia, categories del dispensari i top de visites."""
from datetime import date

from tests.ajuda_caixa import activa_targeta
from tests.test_api import SOCI, ctx, env, token  # noqa: F401

AVUI = date.today()
MES = AVUI.strftime("%Y-%m")
RANG = {"des": AVUI.replace(day=1).isoformat(), "fins": AVUI.isoformat()}


def _escena(client, enc, sec):
    activa_targeta(client, sec)
    client.post("/caixa/obrir", json={"local_id": 1, "opening_cent": 0}, headers=enc)
    p = lambda **k: client.post("/productes", json={"local_id": 1, **k}, headers=enc).json()["id"]  # noqa: E731
    weed = p(nom="Weed1", categoria="Weed", preu_cent_per_g=1000, es_genetic=True, regalable=True, preu_entrada_cent=300)
    hash_ = p(nom="Hash1", categoria="Hash", preu_cent_per_g=2000, es_genetic=True)
    aigua = p(nom="Aigua", categoria="Begudes", preu_cent_per_g=200, unitat="u", es_genetic=False)
    ent = lambda pid, g, cost=None: client.post("/moviments/entrada", json={"product_id": pid, "grams": g, **({"cost_cent": cost} if cost else {})}, headers=enc)  # noqa: E731
    ent(weed, "10", 3500)
    ent(weed, "5")            # sense cost: s'estima 5 g x 300 = 1500
    ent(hash_, "4", 6000)
    ent(aigua, "10", 1000)
    mid = client.post("/socis", json=SOCI, headers=enc).json()["id"]
    assert client.post(f"/socis/{mid}/quotes", json={"import_cent": 1000, "metode": "efectiu", "mesos": 1}, headers=enc).status_code == 201
    for cent, metode in ((20000, "efectiu"), (1000, "targeta"), (500, "bizum")):
        assert client.post(f"/socis/{mid}/moneder/recarrega", json={"import_cent": cent, "metode": metode}, headers=enc).status_code == 201
    client.patch(f"/socis/{mid}", json={"descompte_pct": 10}, headers=enc)
    imp = {}
    for nom, pid, g, extra in (("w", weed, "3", {}), ("h", hash_, "1", {}), ("a", aigua, "2", {}), ("r", weed, "1", {"regal": True})):
        r = client.post("/dispensacions", json={"member_id": mid, "product_id": pid, "grams": g, "metode": "monedero", **extra} if not extra else
                        {"member_id": mid, "product_id": pid, "grams": g, **extra}, headers=enc)
        assert r.status_code == 201, r.text
        imp[nom] = r.json()["import_cent"]
    assert imp["r"] == 0 and imp["w"] == 2700 and imp["h"] == 1800
    cat = client.post("/locals/1/gastos/categories", json={"nom": "Lloguer"}, headers=enc).json()["id"]
    tip = client.post("/locals/1/gastos/tipus", json={"nom": "T"}, headers=enc).json()["id"]
    base = {"local_id": 1, "data": AVUI.isoformat(), "type_id": tip, "category_id": cat}
    client.post("/gastos", json={**base, "import_cent": 7000}, headers=enc)                       # final de mes
    client.post("/gastos", json={**base, "import_cent": 800, "metode": "efectiu"}, headers=enc)   # de caixa
    return mid, imp


def test_rendibilitat_per_producte_i_totals(ctx):
    client, _, sec = ctx
    enc = token(client, sec, "enc")
    _, imp = _escena(client, enc, sec)
    r = client.get("/locals/1/estadistiques/rendibilitat", params=RANG, headers=enc).json()
    w = next(x for x in r["productes"] if x["nom"] == "Weed1")
    assert w["entrat"]["g"] == "15" and w["pagat_cent"] == 5000 and w["pagat_estimat"] is True
    assert w["dispensat"]["g"] == "3" and w["ingressat_cent"] == 2700 and w["regal"]["g"] == "1"
    assert w["regal_cost_cent"] == round(1000 * 5000 / 15000) and w["estoc"]["g"] == "11" and w["valor_potencial_cent"] == 11000
    assert w["benefici_cent"] == 2700 - 5000 and w["benefici_potencial_cent"] == 2700 - 5000 + 11000
    h = next(x for x in r["productes"] if x["nom"] == "Hash1")
    assert h["pagat_estimat"] is False and h["pagat_cent"] == 6000 and h["ingressat_cent"] == 1800
    a = next(x for x in r["productes"] if x["nom"] == "Aigua")
    assert a["entrat"]["ud"] == "10" and a["dispensat"]["ud"] == "2" and a["dispensat"]["g"] == "0"
    t = r["total"]
    assert t["pagat_cent"] == 5000 + 6000 + 1000 and t["ingressat_cent"] == imp["w"] + imp["h"] + imp["a"]
    assert t["benefici_cent"] == t["ingressat_cent"] - t["pagat_cent"]
    assert {c["categoria"] for c in r["per_categoria"]} == {"Weed", "Hash", "Begudes"}
    assert r["genetics"]["pagat_cent"] == 11000 and r["no_genetics"]["pagat_cent"] == 1000
    assert client.get("/locals/1/estadistiques/rendibilitat.csv", params=RANG, headers=enc).text.startswith("producte,")
    # fora del rang només queda l'estoc
    buit = client.get("/locals/1/estadistiques/rendibilitat", params={"des": "2000-01-01", "fins": "2000-01-31"}, headers=enc).json()
    assert buit["total"]["pagat_cent"] == 0 and buit["total"]["ingressat_cent"] == 0 and buit["total"]["valor_potencial_cent"] > 0


def test_resum_mensual(ctx):
    client, _, sec = ctx
    enc = token(client, sec, "enc")
    _, imp = _escena(client, enc, sec)
    r = client.get("/locals/1/estadistiques/resum-mensual", params={"mes": MES}, headers=enc).json()
    assert r["entrades"]["genetics"]["cent"] == 11000 and r["entrades"]["no_genetics"]["cent"] == 1000
    assert r["entrades"]["genetics"]["mg"]["g"] == "19" and r["entrades"]["no_genetics"]["mg"]["ud"] == "10" and r["entrades"]["estimat"] is True
    d = r["dispensat"]
    assert d["genetics"]["cent"] == imp["w"] + imp["h"] and d["genetics"]["mg"]["g"] == "4" and d["no_genetics"]["mg"]["ud"] == "2"
    assert r["regals"]["total"]["mg"]["g"] == "1"
    i = r["ingressos"]
    assert i["donacions"]["efectiu_cent"] == 20000 and i["donacions"]["targeta_cent"] == 1000 and i["donacions"]["bizum_cent"] == 500
    assert i["quotes"]["efectiu_cent"] == 1000 and i["total_cent"] == 22500
    desp = r["despeses"]
    assert desp["caixa_cent"] == 800
    assert any(x["categoria"] == "Lloguer" and x["import_cent"] == 800 for x in desp["caixa"])
    # compres d'estoc automàtiques (3500 + 6000 + 1000) pendents de revisió; la de 5 g no té cost, no genera despesa
    assert desp["pendent_cent"] == 3500 + 6000 + 1000
    assert desp["final_mes_cent"] == 7000 + 10500 and desp["total_cent"] == desp["caixa_cent"] + desp["final_mes_cent"]
    consumit = imp["w"] + imp["h"] + imp["a"]
    assert r["credit"]["final_cent"] == 21500 - consumit and r["credit"]["inici_cent"] == 0 and r["credit"]["diferencia_cent"] == 21500 - consumit
    assert r["total_net_cent"] == 22500 - desp["total_cent"]
    csv = client.get("/locals/1/estadistiques/resum-mensual.csv", params={"mes": MES}, headers=enc)
    assert csv.status_code == 200 and "Total net" in csv.text
    assert client.get("/locals/1/estadistiques/resum-mensual", params={"mes": "2026-13"}, headers=enc).status_code == 422


def test_finances_dia_a_dia(ctx):
    client, _, sec = ctx
    enc = token(client, sec, "enc")
    _escena(client, enc, sec)
    r = client.get("/locals/1/estadistiques/finances-dies", params=RANG, headers=enc).json()
    assert len(r["dies"]) == AVUI.day
    avui = next(x for x in r["dies"] if x["dia"] == AVUI.isoformat())
    assert avui["efectiu_cent"] == 21000 and avui["targeta_cent"] == 1000 and avui["bizum_cent"] == 500 and avui["total_cent"] == 22500
    assert avui["mati_cent"] + avui["tarda_cent"] == 22500 and avui["despeses_caixa_cent"] == 800
    assert r["totals"]["total_cent"] == 22500 and r["totals"]["despeses_caixa_cent"] == 800
    assert client.get("/locals/1/estadistiques/finances-dies", params={"des": "2020-01-01", "fins": "2022-01-01"}, headers=enc).status_code == 422


def test_dispensari_categories_i_top_visites(ctx):
    client, _, sec = ctx
    enc = token(client, sec, "enc")
    mid, _ = _escena(client, enc, sec)
    for _ in range(2):
        client.post(f"/socis/{mid}/entrada", headers=enc)
    r = client.get("/locals/1/estadistiques/dispensari", headers=enc).json()["categories"]
    assert r["categoria_top"] == "Weed"
    weed = next(c for c in r["categories"] if c["categoria"] == "Weed")
    assert weed["top"][0]["producte"] == "Weed1" and weed["top"][0]["quantitat"] == "3"
    m = client.get("/locals/1/estadistiques/membres", headers=enc).json()
    assert m["top_visites"] and m["top_visites"][0]["soci"] == "Anna Prova" and set(m["top_visites"][0]) == {"soci", "visites"}


def test_nomes_amb_permis_informes(ctx):
    client, _, sec = ctx
    disp = token(client, sec, "disp")
    for t in ("rendibilitat", "resum-mensual", "finances-dies"):
        assert client.get(f"/locals/1/estadistiques/{t}", params={**RANG, "mes": MES}, headers=disp).status_code == 403

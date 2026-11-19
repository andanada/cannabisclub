"""Normes del club configurables: edat mínima, decimals de la dispensació, alerta d'inactivitat i pèrdua màxima d'inventari."""
from tests.test_api import SOCI, ctx, env, token  # noqa: F401


def _cfg(client, sec, **k):
    return client.put("/locals/1/config", json=k, headers=token(client, sec, "admin"))


def test_edat_minima_configurable(ctx):
    client, _, sec = ctx
    enc = token(client, sec, "enc")
    assert _cfg(client, sec, edat_minima=17).status_code == 422
    assert _cfg(client, sec, edat_minima=40).status_code == 200
    r = client.post("/socis", json=SOCI, headers=enc)  # neix el 1990: té 36 anys, per sota de 40
    assert r.status_code == 422 and "40 anys" in r.text
    assert client.post("/socis", json={**SOCI, "document": "87654321X", "naixement": "1980-01-01"}, headers=enc).status_code == 201


def test_decimals_de_la_dispensacio(ctx):
    client, _, sec = ctx
    enc = token(client, sec, "enc")
    client.post("/caixa/obrir", json={"local_id": 1, "opening_cent": 0}, headers=enc)
    pid = client.post("/productes", json={"local_id": 1, "nom": "Flor", "preu_cent_per_g": 1000, "es_genetic": True}, headers=enc).json()["id"]
    client.post("/moviments/entrada", json={"product_id": pid, "grams": "20"}, headers=enc)
    mid = client.post("/socis", json=SOCI, headers=enc).json()["id"]
    def disp(g): return client.post("/dispensacions", json={"member_id": mid, "product_id": pid, "grams": g}, headers=enc).status_code
    assert disp("1.234") == 201
    assert _cfg(client, sec, decimals_dispensacio=1).status_code == 200
    assert disp("1.25") == 422 and disp("1.2") == 201 and disp("2") == 201
    assert _cfg(client, sec, decimals_dispensacio=0).status_code == 200
    assert disp("1.5") == 422 and disp("1") == 201


def test_perdua_maxima_a_l_inventari(ctx):
    client, _, sec = ctx
    enc = token(client, sec, "enc")
    pid = client.post("/productes", json={"local_id": 1, "nom": "Flor", "preu_cent_per_g": 1000, "es_genetic": True}, headers=enc).json()["id"]
    client.post("/moviments/entrada", json={"product_id": pid, "grams": "20"}, headers=enc)
    assert _cfg(client, sec, perdua_maxima_mg=500).status_code == 200

    def inventari(g):
        sid = client.post("/locals/1/inventaris", json={}, headers=enc).json()["id"]
        client.put(f"/inventaris/{sid}/linies/{pid}", json={"grams": g}, headers=enc)
        return client.post(f"/inventaris/{sid}/guardar", headers=enc).json()
    petita = inventari("19.8")   # falten 0,2 g: dins del que es tolera
    assert petita["alertes"] == []
    gran = inventari("18.8")     # falta 1 g: per sobre dels 0,5 g
    assert gran["alertes"] == [{"producte": "Flor", "diferencia_mg": -1200}]

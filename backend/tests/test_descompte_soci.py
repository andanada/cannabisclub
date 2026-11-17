"""Descompte permanent per soci (%)."""
from tests.test_api import SOCI, ctx, env, token  # noqa: F401


def test_descompte_del_soci_s_aplica_a_la_dispensacio(ctx):
    client, _, sec = ctx
    enc = token(client, sec, "enc")
    client.post("/caixa/obrir", json={"local_id": 1, "opening_cent": 0}, headers=enc)
    pid = client.post("/productes", json={"local_id": 1, "nom": "Flor", "preu_cent_per_g": 1000, "es_genetic": True}, headers=enc).json()["id"]
    client.post("/moviments/entrada", json={"product_id": pid, "grams": "20"}, headers=enc)
    mid = client.post("/socis", json=SOCI, headers=enc).json()["id"]
    assert client.get(f"/socis/{mid}", headers=enc).json()["descompte_pct"] == 0
    assert client.patch(f"/socis/{mid}", json={"descompte_pct": 150}, headers=enc).status_code == 422
    assert client.patch(f"/socis/{mid}", json={"descompte_pct": 10}, headers=enc).status_code == 200
    d = client.post("/dispensacions", json={"member_id": mid, "product_id": pid, "grams": "2"}, headers=enc).json()
    assert d["import_cent"] == 1800 and d["descompte_cent"] == 200
    assert client.patch(f"/socis/{mid}", json={"descompte_pct": 10}, headers=enc).status_code == 422  # sense canvis

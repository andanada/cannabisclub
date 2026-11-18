"""Consentiment explícit del registre de consum (art. 9.2.a RGPD): finalitat pròpia i, si el club ho exigeix, condició per dispensar."""
from app import textos
from tests.test_api import SOCI, ctx, env, token  # noqa: F401


def _preparat(client, sec):
    enc = token(client, sec, "enc")
    client.post("/caixa/obrir", json={"local_id": 1, "opening_cent": 0}, headers=enc)
    pid = client.post("/productes", json={"local_id": 1, "nom": "Flor", "preu_cent_per_g": 1000, "es_genetic": True}, headers=enc).json()["id"]
    client.post("/moviments/entrada", json={"product_id": pid, "grams": "20"}, headers=enc)
    mid = client.post("/socis", json=SOCI, headers=enc).json()["id"]
    return enc, pid, mid


def test_el_text_actual_es_v2_i_inclou_el_consum():
    assert textos.VERSIO_ACTUAL == "v2" and "v1" in textos.versions() and "consum" in textos.FINALITATS
    for idioma in textos.IDIOMES:
        assert "art. 9.2.a" in textos.text("v2", idioma) or "Art. 9(2)(a)" in textos.text("v2", idioma)


def test_per_defecte_no_s_exigeix_el_consentiment_de_consum(ctx):
    client, _, sec = ctx
    enc, pid, mid = _preparat(client, sec)
    assert client.post("/dispensacions", json={"member_id": mid, "product_id": pid, "grams": "1"}, headers=enc).status_code == 201


def test_si_el_club_l_exigeix_cal_el_consentiment_i_la_retirada_bloqueja(ctx):
    client, _, sec = ctx
    enc, pid, mid = _preparat(client, sec)
    assert client.put("/locals/1/config", json={"consum_exigit": True}, headers=token(client, sec, "admin")).status_code == 200
    disp = lambda: client.post("/dispensacions", json={"member_id": mid, "product_id": pid, "grams": "1"}, headers=enc)  # noqa: E731
    r = disp()
    assert r.status_code == 422 and "consum" in r.text
    h = textos.sha256("v2", "ca")
    assert client.post(f"/socis/{mid}/consentiments", json={"versio": "v2", "text_sha256": h, "finalitats": ["consum"]}, headers=enc).status_code == 201
    assert disp().status_code == 201
    assert client.post(f"/socis/{mid}/consentiments/retirada", json={"finalitat": "consum"}, headers=enc).status_code in (200, 201)
    assert disp().status_code == 422

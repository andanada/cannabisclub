"""Perfil ampliat del soci: gènere, adreça i tipus de membre (xifrats, editables, exportables i suprimibles)."""
from app import crypto
from app.models import Member
from tests.test_api import SOCI, ctx, env, token  # noqa: F401

PERFIL = {"genere": "dona", "adreca": "Carrer Major 1", "ciutat": "Girona", "codi_postal": "17001", "provincia": "Girona", "pais": "Espanya"}


def test_alta_amb_perfil_i_codi(ctx):
    client, factory, sec = ctx
    enc = token(client, sec, "enc")
    mid = client.post("/socis", json={**SOCI, **PERFIL, "tipus": "Terapèutic"}, headers=enc).json()["id"]
    f = client.get(f"/socis/{mid}", headers=enc).json()
    assert {k: f[k] for k in PERFIL} == PERFIL
    assert f["tipus"] == "Terapèutic" and f["codi"].endswith(str(mid))
    with factory() as s:  # a la base de dades no hi ha res en clar
        brut = s.get(Member, mid).perfil_enc
        assert "Carrer Major" not in brut and "Girona" not in brut
        assert "Girona" in crypto.decrypt(brut)


def test_alta_sense_perfil_dona_buits_i_tipus_per_defecte(ctx):
    client, _, sec = ctx
    enc = token(client, sec, "enc")
    mid = client.post("/socis", json=SOCI, headers=enc).json()["id"]
    f = client.get(f"/socis/{mid}", headers=enc).json()
    assert f["tipus"] == "Ordinari" and all(f[k] == "" for k in PERFIL)


def test_edicio_parcial_i_validacions(ctx):
    client, _, sec = ctx
    enc = token(client, sec, "enc")
    mid = client.post("/socis", json={**SOCI, **PERFIL}, headers=enc).json()["id"]
    assert client.patch(f"/socis/{mid}", json={"ciutat": "Barcelona"}, headers=enc).status_code == 200
    f = client.get(f"/socis/{mid}", headers=enc).json()
    assert f["ciutat"] == "Barcelona" and f["adreca"] == "Carrer Major 1"
    assert client.patch(f"/socis/{mid}", json={"ciutat": "Barcelona"}, headers=enc).status_code == 422  # sense canvis
    assert client.patch(f"/socis/{mid}", json={"genere": "x"}, headers=enc).status_code == 422
    assert client.post("/socis", json={**SOCI, "document": "87654321X", "genere": "x"}, headers=enc).status_code == 422
    assert client.patch(f"/socis/{mid}", json={"tipus": ""}, headers=enc).status_code == 422
    assert client.patch(f"/socis/{mid}", json={"tipus": "Convidat"}, headers=enc).status_code == 200


def test_el_dispensador_no_veu_el_perfil(ctx):
    client, _, sec = ctx
    enc = token(client, sec, "enc")
    mid = client.post("/socis", json={**SOCI, **PERFIL}, headers=enc).json()["id"]
    d = token(client, sec, "disp")
    f = client.get(f"/socis/{mid}", headers=d).json()
    assert "adreca" not in f and "ciutat" not in f


def test_exportacio_inclou_el_perfil(ctx):
    client, _, sec = ctx
    enc = token(client, sec, "enc")
    mid = client.post("/socis", json={**SOCI, **PERFIL}, headers=enc).json()["id"]
    ex = client.get(f"/socis/{mid}/exportacio", headers=enc).json()
    assert ex["fitxa"]["adreca"] == "Carrer Major 1"

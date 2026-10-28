from datetime import date, timedelta

import pytest

from app import service
from tests.test_api import SOCI, ctx, env, token  # noqa: F401
from tests.test_stock import setup_data


# ---------- format del document ----------

@pytest.mark.parametrize("doc", ["12345678Z", " 12345678 z ", "X1234567L", "y-1234567-x".replace("-", ""), "Z0000001Y", "AB123456", "P1234567"])
def test_documents_valids(doc):
    service.validate_document(doc)


@pytest.mark.parametrize("doc,motiu", [
    ("12345678A", "lletra"),    # lletra de DNI incorrecta
    ("X1234567A", "lletra"),    # lletra de NIE incorrecta
    ("1234", "no és vàlid"),       # massa curt
    ("AB 12", "no és vàlid"),
    ("amb-guió-i-ñ", "no és vàlid"),
    ("<script>alert(1)</script>", "no és vàlid"),
    ("A" * 25, "no és vàlid"),     # massa llarg per ser passaport
])
def test_documents_invalids(doc, motiu):
    with pytest.raises(ValueError) as e:
        service.validate_document(doc)
    assert motiu in str(e.value).lower()


def test_lalta_i_lediccio_rebutgen_un_dni_amb_la_lletra_equivocada(ctx):
    client, factory, sec = ctx
    enc = token(client, sec, "enc")
    r = client.post("/socis", json={**SOCI, "document": "12345678A"}, headers=enc)
    assert r.status_code == 422 and "lletra" in r.json()["detail"].lower()
    mid = client.post("/socis", json=SOCI, headers=enc).json()["id"]
    assert client.patch(f"/socis/{mid}", json={"document": "87654321A"}, headers=enc).status_code == 422
    assert client.patch(f"/socis/{mid}", json={"document": "87654321X"}, headers=enc).status_code == 200


# ---------- historial d'apunts de caixa ----------

def obrir(client, h):
    assert client.post("/caixa/obrir", json={"local_id": 1, "opening_cent": 0}, headers=h).status_code == 201


def rang():
    avui = date.today()
    return {"des": (avui - timedelta(days=1)).isoformat(), "fins": (avui + timedelta(days=1)).isoformat()}


def test_llista_dapunts_amb_estat_de_correccio(ctx):
    client, factory, sec = ctx
    enc, disp = token(client, sec, "enc"), token(client, sec, "disp")
    obrir(client, enc)
    a = client.post("/despeses", json={"local_id": 1, "cent": 500, "metode": "efectiu", "categoria": "neteja", "concepte": "lleixiu"}, headers=enc).json()["apunt"]
    client.post("/despeses", json={"local_id": 1, "cent": 300, "metode": "targeta", "categoria": "oficina", "concepte": "paper"}, headers=enc)
    client.post(f"/caixa/apunts/{a}/correccio", json={"nota": "import equivocat"}, headers=enc)
    r = client.get("/locals/1/apunts", params=rang(), headers=enc).json()
    assert [x["tipus"] for x in r] == ["correccio", "despesa", "despesa"]  # del més recent al més antic
    per = {x["id"]: x for x in r}
    assert per[a]["corregit"] is True and per[a]["import_cent"] == -500 and per[a]["usuari"] == "enc"
    assert [x for x in r if x["tipus"] == "correccio"][0]["corregeix_id"] == a
    assert sum(1 for x in r if x["corregit"]) == 1
    assert client.get("/locals/1/apunts", params=rang(), headers=disp).status_code == 403
    assert client.get("/locals/2/apunts", params=rang(), headers=enc).status_code == 403
    assert client.get("/locals/1/apunts", params={"des": "2026-02-01", "fins": "2026-01-01"}, headers=enc).status_code == 422


# ---------- historial de moviments d'estoc ----------

def test_llista_de_moviments_i_correccio(ctx):
    client, factory, sec = ctx
    enc, disp = token(client, sec, "enc"), token(client, sec, "disp")
    mid, pid = setup_data(client, enc, factory)  # entrada de 10 g
    d = client.post("/dispensacions", json={"member_id": mid, "product_id": pid, "grams": "2"}, headers=enc).json()["id"]
    client.post("/moviments/merma", json={"product_id": pid, "grams": "1", "nota": "humitat"}, headers=enc)
    client.post(f"/moviments/{d}/correccio", json={"nota": "error de pes"}, headers=enc)
    r = client.get("/locals/1/moviments", params=rang(), headers=enc).json()
    assert [x["tipus"] for x in r] == ["correccio", "merma", "dispensacio", "entrada"]
    per = {x["id"]: x for x in r}
    assert per[d]["corregit"] is True and per[d]["grams"] == "-2" and per[d]["producte"] == "Producte A" and per[d]["import_cent"] == 1600
    assert per[d]["soci_id"] == mid and "nom" not in per[d]  # només l'identificador: cap dada personal
    assert r[0]["corregeix_id"] == d and r[1]["nota"] == "humitat"
    assert client.get("/locals/1/moviments", params=rang(), headers=disp).status_code == 403
    assert client.get("/locals/2/moviments", params=rang(), headers=enc).status_code == 403


def test_els_historials_limiten_les_files(ctx):
    client, factory, sec = ctx
    enc = token(client, sec, "enc")
    obrir(client, enc)
    for i in range(4):
        client.post("/despeses", json={"local_id": 1, "cent": 100 + i, "metode": "efectiu", "categoria": "x", "concepte": f"despesa {i}"}, headers=enc)
    assert len(client.get("/locals/1/apunts", params={**rang(), "limit": 2}, headers=enc).json()) == 2
    assert client.get("/locals/1/apunts", params={**rang(), "limit": 0}, headers=enc).status_code == 422
    assert client.get("/locals/1/apunts", params={**rang(), "limit": 5000}, headers=enc).status_code == 422

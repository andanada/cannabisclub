"""Documents del soci (xifrats i esborrables) i contracte descarregable."""
import base64

from app import crypto
from app.models import MemberDocument
from sqlalchemy import select

from tests.test_api import SOCI, ctx, env, token  # noqa: F401

PNG = base64.b64encode(b"\x89PNG\r\n\x1a\n" + bytes(range(256)) * 2).decode()
PDF = base64.b64encode(b"%PDF-1.4\n" + b"x" * 300).decode()


def test_pujar_llistar_llegir_i_esborrar(ctx):
    client, factory, sec = ctx
    enc, disp = token(client, sec, "enc"), token(client, sec, "disp")
    mid = client.post("/socis", json=SOCI, headers=enc).json()["id"]
    assert client.post(f"/socis/{mid}/documents", json={"tipus": "nif_davant", "data_base64": PNG}, headers=disp).status_code == 403
    r = client.post(f"/socis/{mid}/documents", json={"tipus": "nif_davant", "data_base64": PNG}, headers=enc)
    assert r.status_code == 201
    did = r.json()["id"]
    assert client.post(f"/socis/{mid}/documents", json={"tipus": "contracte", "nom": "Contracte.pdf", "data_base64": PDF}, headers=enc).status_code == 201
    l = client.get(f"/socis/{mid}/documents", headers=enc).json()["documents"]
    assert {d["tipus"] for d in l} == {"nif_davant", "contracte"}
    with factory() as s:  # res en clar a la base de dades
        brut = s.scalar(select(MemberDocument.data_enc).where(MemberDocument.id == did))
        assert PNG[:40] not in brut and crypto.decrypt(brut) == PNG
    assert client.get(f"/documents/{did}", headers=enc).json()["data_base64"] == PNG
    assert client.get(f"/documents/{did}", headers=disp).status_code == 403
    assert client.delete(f"/documents/{did}", headers=enc).status_code == 200
    assert client.get(f"/documents/{did}", headers=enc).status_code == 404


def test_validacions_del_document(ctx):
    client, _, sec = ctx
    enc = token(client, sec, "enc")
    mid = client.post("/socis", json=SOCI, headers=enc).json()["id"]
    def put(**k): return client.post(f"/socis/{mid}/documents", json={"tipus": "altre", "data_base64": PNG, **k}, headers=enc).status_code
    assert put(tipus="foo") == 422
    assert put(data_base64="no-es-base64!!") == 422
    assert put(data_base64=base64.b64encode(b"MZ" + b"x" * 500).decode()) == 422  # ni imatge ni PDF
    assert put(data_base64=base64.b64encode(b"%PDF-" + b"x" * 500_000).decode()) == 422  # massa gran


def test_contracte_html_amb_dades_escapades_i_auditoria(ctx):
    client, _, sec = ctx
    enc = token(client, sec, "enc")
    mid = client.post("/socis", json={**SOCI, "nom": "Anna <b>Prova</b>", "adreca": "Carrer Major 1", "ciutat": "Girona"}, headers=enc).json()["id"]
    r = client.get(f"/socis/{mid}/contracte", headers=enc)
    assert r.status_code == 200 and "attachment" in r.headers["content-disposition"]
    assert "Anna &lt;b&gt;Prova&lt;/b&gt;" in r.text and "<b>Prova</b>" not in r.text
    assert "Carrer Major 1" in r.text and "Girona" in r.text and "Sense signatura" in r.text
    assert client.get(f"/socis/{mid}/contracte", params={"idioma": "es"}, headers=enc).status_code == 200


def test_l_extensio_la_dicta_el_contingut_no_el_nom(ctx):
    client, _, sec = ctx
    enc = token(client, sec, "enc")
    mid = client.post("/socis", json=SOCI, headers=enc).json()["id"]
    did = client.post(f"/socis/{mid}/documents", json={"tipus": "altre", "nom": "../x.html", "data_base64": PNG}, headers=enc).json()["id"]
    assert client.get(f"/documents/{did}", headers=enc).json()["nom"] == "x.png"

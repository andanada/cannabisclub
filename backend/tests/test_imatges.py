import base64

import pytest

from tests.test_api import ctx, env, token  # noqa: F401

JPEG = b"\xff\xd8\xff\xe0" + b"\x00\x10JFIF" + bytes(range(256)) * 2 + b"\xff\xd9"
PNG = b"\x89PNG\r\n\x1a\n" + bytes(range(256)) * 2
b64 = lambda b: base64.b64encode(b).decode()


def producte(client, h, nom="Amnesia", local=1):
    return client.post("/productes", json={"local_id": local, "nom": nom, "preu_cent_per_g": 800}, headers=h).json()["id"]


def test_pujar_llistar_canviar_i_treure_la_imatge(ctx):
    client, factory, sec = ctx
    enc, disp = token(client, sec, "enc"), token(client, sec, "disp")
    pid = producte(client, enc)
    assert client.get("/locals/1/estoc", headers=disp).json()[0]["imatge"] is None
    assert client.put(f"/productes/{pid}/imatge", json={"image_base64": b64(JPEG)}, headers=enc).status_code == 200
    img = client.get("/locals/1/estoc", headers=disp).json()[0]["imatge"]  # el dispensador la veu al triar el producte
    assert img["mime"] == "image/jpeg" and base64.b64decode(img["image_base64"]) == JPEG
    assert client.get("/locals/1/productes", headers=enc).json()[0]["imatge"]["mime"] == "image/jpeg"
    assert client.put(f"/productes/{pid}/imatge", json={"image_base64": b64(PNG)}, headers=enc).status_code == 200
    assert client.get("/locals/1/estoc", headers=disp).json()[0]["imatge"]["mime"] == "image/png"  # substitueix
    assert client.delete(f"/productes/{pid}/imatge", headers=enc).status_code == 200
    assert client.get("/locals/1/estoc", headers=disp).json()[0]["imatge"] is None
    assert client.delete(f"/productes/{pid}/imatge", headers=enc).status_code == 422  # ja no en té


def test_imatge_invalida_massa_gran_o_sense_permis(ctx):
    client, factory, sec = ctx
    enc, disp, admin = token(client, sec, "enc"), token(client, sec, "disp"), token(client, sec, "admin")
    pid = producte(client, enc)
    put = lambda b, h=enc, p=pid: client.put(f"/productes/{p}/imatge", json={"image_base64": b}, headers=h).status_code
    assert put("això no és base64!!") == 422
    assert put(b64(b"GIF89a" + bytes(500))) == 422
    assert put(b64(b"\xff\xd8\xff" + b"x")) == 422
    assert put(b64(b"\xff\xd8\xff" + bytes(40_000))) == 422  # és una miniatura: màxim 30 KB
    assert put(b64(JPEG), disp) == 403
    assert put(b64(JPEG), enc, 9999) == 404
    altre = producte(client, admin, "Altre local", local=2)
    assert put(b64(JPEG), enc, altre) == 403  # d'un altre local


def test_la_imatge_queda_a_lauditoria_i_surt_amb_el_producte_inactiu(ctx):
    import json
    from sqlalchemy import select
    from app.models import AuditLog
    client, factory, sec = ctx
    enc = token(client, sec, "enc")
    pid = producte(client, enc)
    client.put(f"/productes/{pid}/imatge", json={"image_base64": b64(JPEG)}, headers=enc)
    s = factory()
    a = json.loads(s.scalars(select(AuditLog).order_by(AuditLog.seq.desc())).first().payload)
    s.close()
    assert a["accio"] == "imatge_producte" and a["producte"] == pid
    client.patch(f"/productes/{pid}", json={"actiu": False}, headers=enc)
    assert client.get("/locals/1/productes", headers=enc).json()[0]["imatge"]["mime"] == "image/jpeg"

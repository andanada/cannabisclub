import base64
import struct
import zlib

import pytest
from sqlalchemy import select, text

from app.models import ImmutableError, Signature
from tests.test_api import SOCI, ctx, env, token  # noqa: F401


def png_bytes(w=300, h=120, noise=True):
    """PNG vàlid i prou gran: el soroll evita que es comprimeixi a quasi res, com una signatura real."""
    import os
    raw = b"".join(b"\x00" + (os.urandom(w * 3) if noise else b"\xff" * (w * 3)) for _ in range(h))
    def chunk(t, d):
        c = struct.pack(">I", len(d)) + t + d
        return c + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")


def b64(b):
    return base64.b64encode(b).decode()


def test_signar_llegir_i_xifrat_en_repos(ctx):
    client, factory, sec = ctx
    enc = token(client, sec, "enc")
    mid = client.post("/socis", json=SOCI, headers=enc).json()["id"]
    png = png_bytes()
    r = client.post(f"/socis/{mid}/signatura", json={"png_base64": b64(png)}, headers=enc)
    assert r.status_code == 201
    got = client.get(f"/socis/{mid}/signatura", headers=enc).json()
    assert base64.b64decode(got["png_base64"]) == png and got["hash_valid"] is True and got["sha256"] == r.json()["sha256"]
    s = factory()
    raw = s.execute(text("select png_enc from signatures")).scalar()
    assert b64(png)[:60] not in raw  # a la BD no hi és la imatge en clar
    s.close()


def test_signatura_rebutja_no_png_buida_massa_gran_i_base64_dolent(ctx):
    client, factory, sec = ctx
    enc = token(client, sec, "enc")
    mid = client.post("/socis", json=SOCI, headers=enc).json()["id"]
    post = lambda p: client.post(f"/socis/{mid}/signatura", json={"png_base64": p}, headers=enc)
    assert post("no-es-base64!!").status_code == 422
    assert post(b64(b"GIF89a" + b"x" * 1000)).status_code == 422
    assert post(b64(b"\x89PNG\r\n\x1a\n" + b"x" * 10)).status_code == 422                 # buida
    assert post(b64(b"\x89PNG\r\n\x1a\n" + b"x" * 250_000)).status_code == 422            # massa gran


def test_permisos_i_aillament(ctx):
    client, factory, sec = ctx
    enc, disp, admin = token(client, sec, "enc"), token(client, sec, "disp"), token(client, sec, "admin")
    mid = client.post("/socis", json=SOCI, headers=enc).json()["id"]
    body = {"png_base64": b64(png_bytes())}
    assert client.post(f"/socis/{mid}/signatura", json=body, headers=disp).status_code == 403
    assert client.get(f"/socis/{mid}/signatura", headers=enc).status_code == 404    # encara sense signatura
    assert client.post(f"/socis/{mid}/signatura", json=body, headers=enc).status_code == 201
    assert client.get(f"/socis/{mid}/signatura", headers=disp).status_code == 403
    m2 = client.post("/socis", json={**SOCI, "local_id": 2}, headers=admin).json()["id"]
    assert client.post(f"/socis/{m2}/signatura", json=body, headers=enc).status_code == 403    # altre local


def test_signatura_alterada_es_detecta_i_es_immutable(ctx):
    client, factory, sec = ctx
    enc = token(client, sec, "enc")
    mid = client.post("/socis", json=SOCI, headers=enc).json()["id"]
    client.post(f"/socis/{mid}/signatura", json={"png_base64": b64(png_bytes())}, headers=enc)
    s = factory()
    sig = s.scalars(select(Signature)).one()
    sig.kind = "altre"
    with pytest.raises(ImmutableError):
        s.commit()
    s.rollback(); s.close()
    assert client.get("/auditoria/verificar", headers=token(client, sec, "admin")).json()["integra"] is True

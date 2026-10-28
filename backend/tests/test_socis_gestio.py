import base64
import json

import pytest
from sqlalchemy import select, text

from app.models import AuditLog, ImmutableError, MemberPhoto
from tests.test_api import SOCI, ctx, env, token  # noqa: F401

# Imatges mínimes però amb la capçalera real i prou bytes per passar el filtre de «buida».
JPEG = b"\xff\xd8\xff\xe0" + b"\x00\x10JFIF" + bytes(range(256)) * 2 + b"\xff\xd9"
PNG = b"\x89PNG\r\n\x1a\n" + bytes(range(256)) * 2
b64 = lambda b: base64.b64encode(b).decode()


def soci(client, h, **extra):
    r = client.post("/socis", json={**SOCI, **extra}, headers=h)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def ultima_auditoria(factory):
    s = factory()
    try:
        return json.loads(s.scalars(select(AuditLog).order_by(AuditLog.seq.desc()).limit(1)).first().payload)
    finally:
        s.close()


# ---------- edició ----------

def test_editar_dades_del_soci_i_auditar_nomes_els_camps(ctx):
    client, factory, sec = ctx
    enc = token(client, sec, "enc")
    mid = soci(client, enc)
    r = client.patch(f"/socis/{mid}", json={"nom": "Anna Nova", "telefon": "611222333", "email": "nova@example.com"}, headers=enc)
    assert r.status_code == 200
    a = ultima_auditoria(factory)  # abans de llegir: el GET també deixa rastre a l'auditoria
    v = client.get(f"/socis/{mid}", headers=enc).json()
    assert (v["nom"], v["telefon"], v["email"]) == ("Anna Nova", "611222333", "nova@example.com")
    assert a["accio"] == "edita_soci" and sorted(a["camps"]) == ["email", "nom", "telefon"]
    assert "Anna" not in json.dumps(a) and "611" not in json.dumps(a)  # l'auditoria no porta dades personals
    s = factory()
    raw = s.execute(text("select nom_enc, telefon_enc, email_enc from members")).one()
    s.close()
    assert all("Nova" not in x and "611" not in x for x in raw)


def test_buidar_telefon_i_correu(ctx):
    client, factory, sec = ctx
    enc = token(client, sec, "enc")
    mid = soci(client, enc)
    assert client.patch(f"/socis/{mid}", json={"telefon": None, "email": ""}, headers=enc).status_code == 200
    v = client.get(f"/socis/{mid}", headers=enc).json()
    assert v["telefon"] is None and v["email"] is None


def test_editar_document_comprova_duplicats_i_actualitza_la_cerca(ctx):
    client, factory, sec = ctx
    enc = token(client, sec, "enc")
    a = soci(client, enc)
    b = soci(client, enc, document="87654321X")
    assert client.patch(f"/socis/{b}", json={"document": "12345678Z"}, headers=enc).status_code == 422  # ja existeix
    assert client.patch(f"/socis/{b}", json={"document": " 11111111h "}, headers=enc).status_code == 200
    assert client.get("/locals/1/socis/cerca?document=11111111H", headers=enc).json()["id"] == b
    assert client.get("/locals/1/socis/cerca?document=87654321X", headers=enc).status_code == 404
    assert a != b


def test_editar_valida_majoria_dedat_i_buit(ctx):
    client, factory, sec = ctx
    enc = token(client, sec, "enc")
    mid = soci(client, enc)
    assert client.patch(f"/socis/{mid}", json={"naixement": "2015-01-01"}, headers=enc).status_code == 422
    assert client.patch(f"/socis/{mid}", json={}, headers=enc).status_code == 422
    assert client.patch(f"/socis/{mid}", json={"nom": "A"}, headers=enc).status_code == 422
    assert client.patch(f"/socis/{mid}", json={"naixement": "1985-03-04"}, headers=enc).status_code == 200
    assert client.get(f"/socis/{mid}", headers=enc).json()["naixement"] == "1985-03-04"


def test_editar_nomes_responsables_i_del_seu_local(ctx):
    client, factory, sec = ctx
    enc, disp, admin = token(client, sec, "enc"), token(client, sec, "disp"), token(client, sec, "admin")
    mid = soci(client, enc)
    assert client.patch(f"/socis/{mid}", json={"nom": "Altre nom"}, headers=disp).status_code == 403
    altre = soci(client, admin, local_id=2, document="99999999R")
    assert client.patch(f"/socis/{altre}", json={"nom": "Altre nom"}, headers=enc).status_code == 403
    assert client.patch("/socis/9999", json={"nom": "Altre nom"}, headers=enc).status_code == 404


# ---------- llista ----------

def test_llista_de_socis_amb_filtre_per_nom_i_estat(ctx):
    client, factory, sec = ctx
    enc, disp = token(client, sec, "enc"), token(client, sec, "disp")
    a = soci(client, enc, nom="Anna Prova")
    b = soci(client, enc, nom="Bernat Pons", document="87654321X")
    soci(client, enc, nom="Carla Roca", document="11111111H")
    client.post(f"/socis/{b}/estat", json={"estat": "suspes"}, headers=enc)
    r = client.get("/locals/1/socis", headers=enc).json()
    assert [x["nom"] for x in r] == ["Anna Prova", "Bernat Pons", "Carla Roca"]  # ordre alfabètic
    assert {"id", "nom", "estat", "quota"} <= set(r[0]) and "document" not in r[0]
    assert [x["id"] for x in client.get("/locals/1/socis?q=pons", headers=enc).json()] == [b]
    assert [x["id"] for x in client.get("/locals/1/socis?estat=suspes", headers=enc).json()] == [b]
    assert client.get("/locals/1/socis?estat=inventat", headers=enc).status_code == 422
    assert client.get("/locals/1/socis", headers=disp).status_code == 403
    assert client.get("/locals/2/socis", headers=enc).status_code == 403
    a_ = ultima_auditoria(factory)
    assert a_["accio"] == "llista_socis" and a_["n"] == 1
    assert a != b


# ---------- foto ----------

def test_foto_es_desa_xifrada_es_pot_canviar_i_queda_historial(ctx):
    client, factory, sec = ctx
    enc, disp = token(client, sec, "enc"), token(client, sec, "disp")
    mid = soci(client, enc)
    assert client.get(f"/socis/{mid}", headers=enc).json()["te_foto"] is False
    assert client.get(f"/socis/{mid}/foto", headers=enc).status_code == 404
    assert client.post(f"/socis/{mid}/foto", json={"image_base64": b64(JPEG)}, headers=enc).status_code == 201
    assert client.get(f"/socis/{mid}", headers=enc).json()["te_foto"] is True
    f = client.get(f"/socis/{mid}/foto", headers=disp).json()  # el dispensador la veu per identificar el soci
    assert f["mime"] == "image/jpeg" and base64.b64decode(f["image_base64"]) == JPEG
    assert client.post(f"/socis/{mid}/foto", json={"image_base64": b64(PNG)}, headers=enc).status_code == 201
    assert client.get(f"/socis/{mid}/foto", headers=enc).json()["mime"] == "image/png"  # la més recent
    s = factory()
    assert len(s.scalars(select(MemberPhoto)).all()) == 2  # la primera es conserva
    raw = s.execute(text("select img_enc from member_photos")).scalars().all()
    s.close()
    assert all("JFIF" not in x and b64(JPEG)[:20] not in x for x in raw)
    assert ultima_auditoria(factory)["accio"] == "consulta_foto"


def test_foto_invalida_massa_gran_o_sense_permis(ctx):
    client, factory, sec = ctx
    enc, disp = token(client, sec, "enc"), token(client, sec, "disp")
    mid = soci(client, enc)
    post = lambda b, h=enc: client.post(f"/socis/{mid}/foto", json={"image_base64": b}, headers=h).status_code
    assert post("això no és base64!!") == 422
    assert post(b64(b"GIF89a" + bytes(500))) == 422  # ni JPEG ni PNG
    assert post(b64(b"\xff\xd8\xff" + b"x")) == 422  # massa petita
    assert post(b64(b"\xff\xd8\xff" + bytes(300_000))) == 422  # massa gran
    assert post(b64(JPEG), disp) == 403
    assert client.post("/socis/9999/foto", json={"image_base64": b64(JPEG)}, headers=enc).status_code == 404


def test_les_fotos_no_es_poden_editar_ni_esborrar(ctx):
    client, factory, sec = ctx
    enc = token(client, sec, "enc")
    mid = soci(client, enc)
    client.post(f"/socis/{mid}/foto", json={"image_base64": b64(JPEG)}, headers=enc)
    s = factory()
    s.scalar(select(MemberPhoto)).mime = "image/png"
    with pytest.raises(ImmutableError):
        s.commit()
    s.rollback()
    s.delete(s.scalar(select(MemberPhoto)))
    with pytest.raises(ImmutableError):
        s.commit()
    s.close()


# ---------- carnet / RFID ----------

def test_assignar_carnet_i_trobar_el_soci_amb_el_lector(ctx):
    client, factory, sec = ctx
    enc, disp = token(client, sec, "enc"), token(client, sec, "disp")
    mid = soci(client, enc)
    assert client.get(f"/socis/{mid}", headers=enc).json()["te_carnet"] is False
    assert client.post(f"/socis/{mid}/carnet", json={"codi": "04A1B2C3"}, headers=enc).status_code == 201
    assert client.get(f"/socis/{mid}", headers=enc).json()["te_carnet"] is True
    r = client.get("/locals/1/socis/carnet?codi=04a1b2c3", headers=disp)  # el lector pot enviar minúscules
    assert r.status_code == 200 and r.json()["id"] == mid and "quota" in r.json()
    assert client.get("/locals/1/socis/carnet?codi=NOEXISTEIX", headers=disp).status_code == 404
    a = ultima_auditoria(factory)
    assert a["accio"] == "cerca_carnet" and "04A1" not in json.dumps(a)
    s = factory()
    assert "04A1B2C3" not in " ".join(str(x) for x in s.execute(text("select * from member_cards")).one())
    s.close()


def test_carnet_duplicat_canvi_i_retirada(ctx):
    client, factory, sec = ctx
    enc = token(client, sec, "enc")
    a = soci(client, enc)
    b = soci(client, enc, document="87654321X")
    assert client.post(f"/socis/{a}/carnet", json={"codi": "CARNET-A"}, headers=enc).status_code == 201
    assert client.post(f"/socis/{b}/carnet", json={"codi": "carnet-a"}, headers=enc).status_code == 422  # ja és d'un altre soci
    assert client.post(f"/socis/{a}/carnet", json={"codi": "CARNET-A"}, headers=enc).status_code == 422  # ja el té
    # un carnet nou substitueix l'anterior
    assert client.post(f"/socis/{a}/carnet", json={"codi": "CARNET-A2"}, headers=enc).status_code == 201
    assert client.get("/locals/1/socis/carnet?codi=CARNET-A", headers=enc).status_code == 404
    assert client.get("/locals/1/socis/carnet?codi=CARNET-A2", headers=enc).json()["id"] == a
    # el carnet antic queda lliure i es pot reassignar a un altre soci
    assert client.post(f"/socis/{b}/carnet", json={"codi": "CARNET-A"}, headers=enc).status_code == 201
    assert client.delete(f"/socis/{b}/carnet", headers=enc).status_code == 200
    assert client.get("/locals/1/socis/carnet?codi=CARNET-A", headers=enc).status_code == 404
    assert client.delete(f"/socis/{b}/carnet", headers=enc).status_code == 422  # no en té


def test_carnet_valida_format_permisos_i_locals(ctx):
    client, factory, sec = ctx
    enc, disp, admin = token(client, sec, "enc"), token(client, sec, "disp"), token(client, sec, "admin")
    mid = soci(client, enc)
    for mal in ["ab", "x" * 65, "amb espai", "ñandú", "<script>"]:
        assert client.post(f"/socis/{mid}/carnet", json={"codi": mal}, headers=enc).status_code == 422, mal
    assert client.post(f"/socis/{mid}/carnet", json={"codi": "CARNET1"}, headers=disp).status_code == 403
    altre = soci(client, admin, local_id=2, document="99999999R")
    assert client.post(f"/socis/{altre}/carnet", json={"codi": "CARNET2"}, headers=enc).status_code == 403
    # el mateix codi físic en un altre local és un altre carnet
    assert client.post(f"/socis/{altre}/carnet", json={"codi": "CARNET1"}, headers=admin).status_code == 201
    assert client.get("/locals/1/socis/carnet?codi=CARNET1", headers=enc).status_code == 404

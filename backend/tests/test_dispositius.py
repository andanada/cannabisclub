import re

import pytest

from app import dispositius, socis
from tests.test_api import SOCI, ctx, env, token  # noqa: F401

BASCULA = {"baud_rate": 9600, "data_bits": 8, "parity": "none", "stop_bits": 1, "flow": "none",
           "read": ["IP", "P", "SP"], "tare": "T", "zero": "Z", "unit": "g"}
SIGNATURA = {"mode": "llenc", "amplada": 600, "alcada": 220, "gruix": 3, "color": "#000000", "fons": "#ffffff", "pressio": True, "tracos_min": 3}
LECTOR = {"mode": "teclat", "terminador": "enter", "prefix": "", "longitud_min": 4, "majuscules": True, "prefix_generat": "CLB"}


def crea(client, h, kind, config, nom="Principal", local=1, **extra):
    return client.post(f"/locals/{local}/dispositius", json={"kind": kind, "nom": nom, "config": config, **extra}, headers=h)


def test_crear_llistar_editar_i_esborrar_perfils(ctx):
    client, factory, sec = ctx
    admin, enc, disp = token(client, sec, "admin"), token(client, sec, "enc"), token(client, sec, "disp")
    r = crea(client, admin, "bascula", BASCULA, "OHAUS Navigator")
    assert r.status_code == 201
    did = r.json()["id"]
    crea(client, admin, "signatura", SIGNATURA, "Tauleta recepció")
    crea(client, admin, "lector", LECTOR, "Lector USB")
    # qualsevol rol del local els pot llegir (la tauleta els necessita per treballar)
    tots = client.get("/locals/1/dispositius", headers=disp).json()
    assert {d["kind"] for d in tots} == {"bascula", "signatura", "lector"}
    assert [d["nom"] for d in client.get("/locals/1/dispositius?kind=bascula", headers=disp).json()] == ["OHAUS Navigator"]
    # només l'administrador els canvia
    assert crea(client, enc, "bascula", BASCULA, "Altra").status_code == 403
    assert client.put(f"/dispositius/{did}", json={"nom": "Nou nom"}, headers=enc).status_code == 403
    assert client.put(f"/dispositius/{did}", json={"nom": "Nou nom", "config": {**BASCULA, "baud_rate": 19200}}, headers=admin).status_code == 200
    d = client.get("/locals/1/dispositius?kind=bascula", headers=disp).json()[0]
    assert d["nom"] == "Nou nom" and d["config"]["baud_rate"] == 19200
    assert client.delete(f"/dispositius/{did}", headers=admin).status_code == 200
    assert client.get("/locals/1/dispositius?kind=bascula", headers=disp).json() == []
    assert client.delete(f"/dispositius/{did}", headers=admin).status_code == 404


def test_aillament_entre_locals(ctx):
    client, factory, sec = ctx
    admin, enc = token(client, sec, "admin"), token(client, sec, "enc")
    crea(client, admin, "bascula", BASCULA, "Només local 2", local=2)
    assert client.get("/locals/2/dispositius", headers=enc).status_code == 403
    assert client.get("/locals/1/dispositius", headers=enc).json() == []


def test_nomes_un_per_defecte_per_local_i_tipus(ctx):
    client, factory, sec = ctx
    admin = token(client, sec, "admin")
    a = crea(client, admin, "bascula", BASCULA, "A").json()["id"]
    b = crea(client, admin, "bascula", BASCULA, "B", per_defecte=True).json()["id"]
    assert client.put(f"/dispositius/{a}", json={"per_defecte": True}, headers=admin).status_code == 200
    llista = {d["nom"]: d["per_defecte"] for d in client.get("/locals/1/dispositius?kind=bascula", headers=admin).json()}
    assert llista == {"A": True, "B": False} and b


def test_nom_duplicat_i_tipus_desconegut(ctx):
    client, factory, sec = ctx
    admin = token(client, sec, "admin")
    assert crea(client, admin, "bascula", BASCULA, "A").status_code == 201
    r = crea(client, admin, "bascula", BASCULA, "A")
    assert r.status_code == 422 and "Ja existeix" in r.json()["detail"]
    assert crea(client, admin, "impressora", {}, "X").status_code == 422
    assert crea(client, admin, "bascula", BASCULA, " ").status_code == 422


@pytest.mark.parametrize("kind,canvi", [
    ("bascula", {"baud_rate": 1234}), ("bascula", {"data_bits": 9}), ("bascula", {"parity": "mark"}), ("bascula", {"read": []}),
    ("bascula", {"read": ["IP;rm -rf"]}), ("bascula", {"read": ["A"] * 9}), ("bascula", {"unit": "stone"}), ("bascula", {"extra": 1}),
    ("signatura", {"amplada": 50}), ("signatura", {"color": "red"}), ("signatura", {"gruix": 0}), ("signatura", {"tracos_min": 99}),
    ("lector", {"terminador": "res"}), ("lector", {"longitud_min": 2}), ("lector", {"prefix_generat": "no vàlid!"}), ("lector", {"mode": "bluetooth"}),
])
def test_configuracions_invalides_es_rebutgen(ctx, kind, canvi):
    client, factory, sec = ctx
    base = {"bascula": BASCULA, "signatura": SIGNATURA, "lector": LECTOR}[kind]
    r = crea(client, token(client, sec, "admin"), kind, {**base, **canvi})
    assert r.status_code == 422, canvi


def test_configuracio_incompleta_agafa_els_valors_per_defecte():
    cfg = dispositius.validate("bascula", {})
    assert cfg["baud_rate"] == 9600 and cfg["read"] == ["IP", "P", "SP"] and cfg["unit"] == "g"
    assert dispositius.validate("lector", {})["terminador"] == "enter"


def test_els_canvis_queden_a_lauditoria_sense_la_configuracio(ctx):
    import json
    from sqlalchemy import select
    from app.models import AuditLog
    client, factory, sec = ctx
    crea(client, token(client, sec, "admin"), "bascula", BASCULA, "Auditada")
    s = factory()
    a = json.loads(s.scalars(select(AuditLog).order_by(AuditLog.seq.desc())).first().payload)
    s.close()
    assert a["accio"] == "alta_dispositiu" and a["kind"] == "bascula"


# ---------- generador de carnets ----------

def test_codi_de_carnet_generat_te_format_i_digit_de_control():
    codis = {socis.generate_card_code("CLB") for _ in range(200)}
    assert len(codis) == 200
    for c in codis:
        assert re.fullmatch(r"CLB-[0-9A-HJKMNP-TV-Z]{10}", c) and socis.card_code_valid(c)
    c = next(iter(codis))
    mal = c[:-1] + ("0" if c[-1] != "0" else "1")
    assert not socis.card_code_valid(mal)  # un error de lectura/teclat es detecta


def test_generar_carnet_el_dona_una_vegada_i_queda_assignat(ctx):
    client, factory, sec = ctx
    enc, disp = token(client, sec, "enc"), token(client, sec, "disp")
    mid = client.post("/socis", json=SOCI, headers=enc).json()["id"]
    r = client.post(f"/socis/{mid}/carnet/generar", json={"prefix": "CLB"}, headers=enc)
    assert r.status_code == 201
    codi = r.json()["codi"]
    assert re.fullmatch(r"CLB-[0-9A-Z]{10}", codi)
    assert client.get(f"/locals/1/socis/carnet?codi={codi}", headers=disp).json()["id"] == mid
    # un segon carnet substitueix el primer
    codi2 = client.post(f"/socis/{mid}/carnet/generar", json={}, headers=enc).json()["codi"]
    assert codi2 != codi
    assert client.get(f"/locals/1/socis/carnet?codi={codi}", headers=disp).status_code == 404
    assert client.post(f"/socis/{mid}/carnet/generar", json={}, headers=disp).status_code == 403
    assert client.post(f"/socis/{mid}/carnet/generar", json={"prefix": "no vàlid"}, headers=enc).status_code == 422

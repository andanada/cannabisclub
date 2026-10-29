import json

import pytest
from sqlalchemy import select

from app import carnet_login
from app.models import AuditLog
from app.socis import ALFABET, _control
from tests.test_api import SOCI, ctx, env, token  # noqa: F401

PIN = "4821"


def codi(n: int) -> str:
    """Un codi vàlid amb el format dels carnets generats pel programa (determinista per a les proves)."""
    cos = ("ABCDEFGHJ" + ALFABET)[n:n + 8] + ALFABET[n % 30]
    cos = (cos + "ABCDEFGHJ")[:9]
    return f"STF-{cos}{_control(cos)}"


def uid(client, h, nom):
    return next(u["id"] for u in client.get("/usuaris", headers=h).json() if u["username"] == nom)


def posa(client, h, usuari_id, c, pin=PIN):
    return client.put(f"/usuaris/{usuari_id}/carnet", json={"codi": c, "pin": pin}, headers=h)


def entra(client, c, pin=PIN):
    return client.post("/auth/login-carnet", json={"codi": c, "pin": pin})


def test_carnet_i_pin_obren_sessio_i_el_pin_dolent_no(ctx):
    client, factory, sec = ctx
    admin = token(client, sec, "admin")
    assert posa(client, admin, uid(client, admin, "disp"), codi(1)).status_code == 200
    assert entra(client, codi(1).lower(), "0000").status_code == 401           # PIN erroni
    assert entra(client, codi(1), "").status_code == 401                       # sense PIN
    r = entra(client, codi(1).lower())                                          # el lector pot canviar majúscules
    assert r.status_code == 200
    me = client.get("/me", headers={"Authorization": "Bearer " + r.json()["token"]}).json()
    assert me["username"] == "disp" and me["role"] == "dispensador"


def test_nomes_carnets_llargs_generats_pel_programa_i_pins_forts(ctx):
    client, factory, sec = ctx
    admin = token(client, sec, "admin")
    did = uid(client, admin, "disp")
    assert posa(client, admin, did, "WRK-0001").status_code == 422             # codi curt (UID d'un xip qualsevol)
    assert posa(client, admin, did, "STF-AAAAAAAAAA").status_code == 422       # dígit de control incorrecte
    for pin_dolent in ["", "12", "abcd", "123456789", "0000", "7777", "1234", "4321", "56789"]:
        assert posa(client, admin, did, codi(1), pin_dolent).status_code == 422, pin_dolent
    assert posa(client, admin, did, codi(1), "13579").status_code == 200


def test_els_administradors_no_poden_tenir_carnet(ctx):
    client, factory, sec = ctx
    admin = token(client, sec, "admin")
    assert posa(client, admin, uid(client, admin, "admin"), codi(2)).status_code == 422
    assert entra(client, codi(2)).status_code == 401


def test_bloqueig_per_usuari_despres_de_5_pins_erronis(ctx):
    client, factory, sec = ctx
    admin = token(client, sec, "admin")
    posa(client, admin, uid(client, admin, "disp"), codi(1))
    posa(client, admin, uid(client, admin, "enc"), codi(5), "9632")
    for _ in range(5):
        assert entra(client, codi(1), "0001").status_code == 401
    assert entra(client, codi(1), PIN).status_code == 429                       # ni amb el PIN bo: bloquejat
    assert entra(client, codi(5), "9632").status_code == 200                    # un altre treballador no es veu afectat
    assert client.post("/auth/login", json={"username": "disp", "password": "mala-contrasenya", "totp": "000000"}).status_code == 401
    s = factory()
    accions = [json.loads(a.payload)["accio"] for a in s.scalars(select(AuditLog))]
    s.close()
    assert accions.count("carnet_bloquejat") == 1
    for _ in range(3):
        entra(client, codi(1), PIN)
    s = factory()
    assert [json.loads(a.payload)["accio"] for a in s.scalars(select(AuditLog))].count("carnet_bloquejat") == 1   # un anònim no infla l'auditoria
    s.close()


def test_limit_global_amb_carnets_desconeguts(ctx):
    client, factory, sec = ctx
    admin = token(client, sec, "admin")
    posa(client, admin, uid(client, admin, "disp"), codi(1))
    for i in range(carnet_login.MAX_DESCONEGUTS):
        assert entra(client, f"ZZZ-{i:010d}").status_code == 401
    assert entra(client, codi(1)).status_code == 429


def test_generar_carnet_el_codi_surt_una_vegada_i_serveix_per_entrar(ctx):
    client, factory, sec = ctx
    admin = token(client, sec, "admin")
    did = uid(client, admin, "disp")
    r = client.post(f"/usuaris/{did}/carnet/generar", json={"pin": PIN, "prefix": "STF"}, headers=admin)
    assert r.status_code == 201
    c = r.json()["codi"]
    assert c.startswith("STF-") and len(c) == 14
    assert entra(client, c).status_code == 200
    nou = client.post(f"/usuaris/{did}/carnet/generar", json={"pin": PIN}, headers=admin).json()["codi"]
    assert nou != c and entra(client, c).status_code == 401 and entra(client, nou).status_code == 200   # el nou substitueix l'antic
    assert client.post(f"/usuaris/{did}/carnet/generar", json={"pin": "1111"}, headers=admin).status_code == 422
    assert client.post(f"/usuaris/{uid(client, admin, 'admin')}/carnet/generar", json={"pin": PIN}, headers=admin).status_code == 422


def test_el_treballador_canvia_el_seu_pin(ctx):
    client, factory, sec = ctx
    admin = token(client, sec, "admin")
    posa(client, admin, uid(client, admin, "disp"), codi(1))
    h = {"Authorization": "Bearer " + entra(client, codi(1)).json()["token"]}
    assert client.post("/auth/carnet-pin", json={"actual": "0000", "nova": "9632"}, headers=h).status_code == 422   # PIN actual erroni
    assert client.post("/auth/carnet-pin", json={"actual": PIN, "nova": "1234"}, headers=h).status_code == 422      # massa fàcil
    assert client.post("/auth/carnet-pin", json={"actual": PIN, "nova": "9632"}, headers=h).status_code == 200
    assert entra(client, codi(1), PIN).status_code == 401 and entra(client, codi(1), "9632").status_code == 200
    enc = token(client, sec, "enc")
    assert client.post("/auth/carnet-pin", json={"actual": PIN, "nova": "9632"}, headers=enc).status_code == 422    # sense carnet


def test_usuari_desactivat_carnet_retirat_i_conflicte_amb_socis(ctx):
    client, factory, sec = ctx
    enc, admin = token(client, sec, "enc"), token(client, sec, "admin")
    did = uid(client, admin, "disp")
    posa(client, admin, did, codi(1))
    assert posa(client, admin, uid(client, admin, "enc"), codi(1)).status_code == 422        # ja és d'un altre usuari
    m = client.post("/socis", json=SOCI, headers=enc).json()["id"]
    client.post(f"/socis/{m}/carnet", json={"codi": codi(7)}, headers=enc)
    assert posa(client, admin, uid(client, admin, "enc"), codi(7)).status_code == 422        # és d'un soci
    assert entra(client, codi(7)).status_code == 401                                          # un carnet de soci no obre sessió
    assert client.delete(f"/usuaris/{did}/carnet", headers=admin).status_code == 200
    assert entra(client, codi(1)).status_code == 401
    posa(client, admin, did, codi(1))
    client.patch(f"/usuaris/{did}", json={"active": False}, headers=admin)
    assert entra(client, codi(1)).status_code == 401
    assert client.delete(f"/usuaris/{did}/carnet", headers=admin).status_code == 200
    assert client.delete(f"/usuaris/{did}/carnet", headers=admin).status_code == 404


def test_xarxa_permesa_i_interruptor(ctx, monkeypatch):
    client, factory, sec = ctx
    enc, admin = token(client, sec, "enc"), token(client, sec, "admin")
    did = uid(client, admin, "disp")
    assert posa(client, enc, did, codi(1)).status_code == 403                                 # només l'administrador
    posa(client, admin, did, codi(1))
    assert client.get("/auth/opcions").json()["carnet"] is True
    monkeypatch.setenv("CLUB_CARNET_XARXES", "10.0.0.0/8, 192.168.1.0/24")
    assert entra(client, codi(1)).status_code == 403                                           # IP de proves fora de les xarxes
    monkeypatch.setenv("CLUB_TRUST_PROXY", "1")
    dins = client.post("/auth/login-carnet", json={"codi": codi(1), "pin": PIN}, headers={"X-Forwarded-For": "8.8.8.8, 192.168.1.40"})
    assert dins.status_code == 200                                                              # només compta l'última entrada (la del proxy)
    fora = client.post("/auth/login-carnet", json={"codi": codi(1), "pin": PIN}, headers={"X-Forwarded-For": "192.168.1.40, 8.8.8.8"})
    assert fora.status_code == 403                                                              # una IP falsificada al davant no serveix
    monkeypatch.delenv("CLUB_CARNET_XARXES")
    monkeypatch.setenv("CLUB_LOGIN_CARNET", "0")
    assert client.get("/auth/opcions").json()["carnet"] is False
    assert entra(client, codi(1)).status_code == 403


def test_el_pin_no_es_desa_en_clar_i_les_entrades_queden_a_l_auditoria(ctx):
    from app.models import UserCard
    client, factory, sec = ctx
    admin = token(client, sec, "admin")
    posa(client, admin, uid(client, admin, "disp"), codi(1))
    entra(client, codi(1))
    s = factory()
    fila = s.scalars(select(UserCard)).one()
    registres = [json.loads(a.payload) for a in s.scalars(select(AuditLog))]
    s.close()
    assert PIN not in fila.pin_hash and fila.pin_hash.startswith("$argon2")
    assert PIN not in json.dumps(registres) and codi(1) not in json.dumps(registres)
    assert any(r.get("accio") == "login" and r.get("metode") == "carnet+pin" and r["usuari"] == "disp" for r in registres)

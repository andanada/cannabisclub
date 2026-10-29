import json

from sqlalchemy import select

from app.models import AuditLog
from tests.test_api import SOCI, ctx, env, token  # noqa: F401


def uid(client, h, nom):
    return next(u["id"] for u in client.get("/usuaris", headers=h).json() if u["username"] == nom)


def posa_carnet(client, h, usuari_id, codi):
    return client.put(f"/usuaris/{usuari_id}/carnet", json={"codi": codi}, headers=h)


def entra(client, codi):
    return client.post("/auth/login-carnet", json={"codi": codi})


def test_un_treballador_entra_passant_el_carnet_i_la_sessio_funciona(ctx):
    client, factory, sec = ctx
    admin = token(client, sec, "admin")
    assert posa_carnet(client, admin, uid(client, admin, "disp"), "WRK-0001").status_code == 200
    r = entra(client, "wrk-0001")                                     # el lector pot canviar majúscules
    assert r.status_code == 200
    me = client.get("/me", headers={"Authorization": "Bearer " + r.json()["token"]}).json()
    assert me["username"] == "disp" and me["role"] == "dispensador"


def test_els_administradors_no_poden_tenir_carnet_ni_entrar_amb_ell(ctx):
    client, factory, sec = ctx
    admin = token(client, sec, "admin")
    assert posa_carnet(client, admin, uid(client, admin, "admin"), "ADM-0001").status_code == 422
    assert entra(client, "ADM-0001").status_code == 401


def test_carnet_desconegut_usuari_desactivat_i_carnet_retirat(ctx):
    client, factory, sec = ctx
    admin = token(client, sec, "admin")
    did = uid(client, admin, "disp")
    posa_carnet(client, admin, did, "WRK-0001")
    assert entra(client, "WRK-9999").status_code == 401
    assert client.delete(f"/usuaris/{did}/carnet", headers=admin).status_code == 200
    assert entra(client, "WRK-0001").status_code == 401                              # retirat
    posa_carnet(client, admin, did, "WRK-0001")
    client.patch(f"/usuaris/{did}", json={"active": False}, headers=admin)
    assert entra(client, "WRK-0001").status_code == 401                              # usuari desactivat
    assert client.delete(f"/usuaris/{did}/carnet", headers=admin).status_code == 200
    assert client.delete(f"/usuaris/{did}/carnet", headers=admin).status_code == 404  # ja no en té


def test_un_carnet_no_es_pot_repetir_ni_ser_d_un_soci(ctx):
    client, factory, sec = ctx
    enc, admin = token(client, sec, "enc"), token(client, sec, "admin")
    posa_carnet(client, admin, uid(client, admin, "disp"), "WRK-0001")
    assert posa_carnet(client, admin, uid(client, admin, "enc"), "WRK-0001").status_code == 422   # ja és d'un altre usuari
    m = client.post("/socis", json=SOCI, headers=enc).json()["id"]
    client.post(f"/socis/{m}/carnet", json={"codi": "SOC-0001"}, headers=enc)
    assert posa_carnet(client, admin, uid(client, admin, "enc"), "SOC-0001").status_code == 422   # és d'un soci
    assert posa_carnet(client, admin, uid(client, admin, "enc"), "x").status_code == 422           # massa curt
    assert entra(client, "SOC-0001").status_code == 401                                            # un carnet de soci no obre sessió


def test_bloqueig_per_intents_fallits_i_auditoria(ctx):
    client, factory, sec = ctx
    admin = token(client, sec, "admin")
    posa_carnet(client, admin, uid(client, admin, "disp"), "WRK-0001")
    for i in range(10):
        assert entra(client, f"MAL-{i:04d}").status_code == 401
    assert entra(client, "MAL-9999").status_code == 429
    assert entra(client, "WRK-0001").status_code == 429                               # bloquejat per a tothom uns minuts
    assert client.post("/auth/login", json={"username": "disp", "password": "mala-contrasenya", "totp": "000000"}).status_code == 401  # la contrasenya segueix al seu compte


def test_nomes_l_administrador_gestiona_carnets_i_es_pot_desactivar(ctx, monkeypatch):
    client, factory, sec = ctx
    enc, admin = token(client, sec, "enc"), token(client, sec, "admin")
    did = uid(client, admin, "disp")
    assert posa_carnet(client, enc, did, "WRK-0001").status_code == 403
    assert client.delete(f"/usuaris/{did}/carnet", headers=enc).status_code == 403
    assert client.get("/auth/opcions").json()["carnet"] is True
    posa_carnet(client, admin, did, "WRK-0001")
    assert next(u for u in client.get("/usuaris", headers=admin).json() if u["id"] == did)["te_carnet"] is True
    monkeypatch.setenv("CLUB_LOGIN_CARNET", "0")
    assert client.get("/auth/opcions").json()["carnet"] is False
    assert entra(client, "WRK-0001").status_code == 403                               # funció apagada al servidor
    s = factory()
    accions = {json.loads(a.payload)["accio"] for a in s.scalars(select(AuditLog))}
    s.close()
    assert "assigna_carnet_usuari" in accions


def test_les_entrades_amb_carnet_queden_a_l_auditoria(ctx):
    client, factory, sec = ctx
    admin = token(client, sec, "admin")
    posa_carnet(client, admin, uid(client, admin, "disp"), "WRK-0001")
    entra(client, "WRK-0001")
    s = factory()
    logins = [json.loads(a.payload) for a in s.scalars(select(AuditLog)) if json.loads(a.payload).get("accio") == "login" and json.loads(a.payload).get("metode") == "carnet"]
    s.close()
    assert logins and logins[-1]["usuari"] == "disp" and logins[-1]["ok"] is True

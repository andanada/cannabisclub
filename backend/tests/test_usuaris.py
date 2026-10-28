import pyotp
from sqlalchemy import select

from app import service
from app.models import LoginAttempt, SessionToken, User
from tests.test_api import PASS, ctx, env, token  # noqa: F401


def uid(factory, nom):
    s = factory()
    try:
        return s.scalars(select(User).where(User.username == nom)).one().id
    finally:
        s.close()


def login_ok(client, sec, nom):
    return client.post("/auth/login", json={"username": nom, "password": PASS, "totp": pyotp.TOTP(sec[nom]).now()})


# ---------- llista ----------

def test_llista_dusuaris_nomes_per_a_admin(ctx):
    client, factory, sec = ctx
    r = client.get("/usuaris", headers=token(client, sec, "admin")).json()
    per = {u["username"]: u for u in r}
    assert set(per) == {"admin", "enc", "disp"}
    assert per["enc"]["role"] == "encarregat" and per["enc"]["local_ids"] == [1] and per["enc"]["active"] is True
    assert "password_hash" not in per["enc"] and "totp_secret_enc" not in per["enc"]
    assert client.get("/usuaris", headers=token(client, sec, "enc")).status_code == 403
    assert client.get("/usuaris").status_code == 401


# ---------- desactivar / reactivar ----------

def test_desactivar_usuari_tanca_les_seves_sessions_i_impedeix_entrar(ctx):
    client, factory, sec = ctx
    admin, disp = token(client, sec, "admin"), token(client, sec, "disp")
    assert client.get("/me", headers=disp).status_code == 200
    assert client.patch(f"/usuaris/{uid(factory, 'disp')}", json={"active": False}, headers=admin).status_code == 200
    assert client.get("/me", headers=disp).status_code == 401  # la sessió oberta ja no val
    assert login_ok(client, sec, "disp").status_code == 401
    assert client.patch(f"/usuaris/{uid(factory, 'disp')}", json={"active": True}, headers=admin).status_code == 200
    assert login_ok(client, sec, "disp").status_code == 200


def test_no_es_pot_desactivar_ni_degradar_un_mateix_ni_lultim_admin(ctx):
    client, factory, sec = ctx
    admin = token(client, sec, "admin")
    me = uid(factory, "admin")
    r = client.patch(f"/usuaris/{me}", json={"active": False}, headers=admin)
    assert r.status_code == 422 and "tu mateix" in r.json()["detail"]
    assert client.patch(f"/usuaris/{me}", json={"role": "encarregat"}, headers=admin).status_code == 422
    # amb un segon admin sí que es pot canviar l'altre, però mai deixar el sistema sense admins actius
    r = client.post("/usuaris", json={"username": "admin2", "password": PASS, "role": "admin", "local_ids": []}, headers=admin)
    assert r.status_code == 201
    a2 = r.json()["id"]
    assert client.patch(f"/usuaris/{a2}", json={"active": False}, headers=admin).status_code == 200
    assert client.patch(f"/usuaris/{a2}", json={"active": True}, headers=admin).status_code == 200


def test_canvi_de_rol_i_locals(ctx):
    client, factory, sec = ctx
    admin = token(client, sec, "admin")
    d = uid(factory, "disp")
    assert client.patch(f"/usuaris/{d}", json={"role": "encarregat", "local_ids": [1, 2]}, headers=admin).status_code == 200
    u = [x for x in client.get("/usuaris", headers=admin).json() if x["username"] == "disp"][0]
    assert u["role"] == "encarregat" and u["local_ids"] == [1, 2]
    assert client.patch(f"/usuaris/{d}", json={"local_ids": [1]}, headers=admin).status_code == 200
    assert [x for x in client.get("/usuaris", headers=admin).json() if x["username"] == "disp"][0]["local_ids"] == [1]
    assert client.patch(f"/usuaris/{d}", json={"role": "superman"}, headers=admin).status_code == 422
    assert client.patch(f"/usuaris/{d}", json={"local_ids": [99]}, headers=admin).status_code == 422
    assert client.patch(f"/usuaris/{d}", json={}, headers=admin).status_code == 422
    assert client.patch("/usuaris/9999", json={"active": False}, headers=admin).status_code == 404
    assert client.patch(f"/usuaris/{d}", json={"active": False}, headers=token(client, sec, "enc")).status_code == 403


# ---------- TOTP i contrasenya ----------

def test_reiniciar_totp_dona_secret_nou_i_invalida_el_vell(ctx):
    client, factory, sec = ctx
    admin = token(client, sec, "admin")
    vell = sec["enc"]
    r = client.post(f"/usuaris/{uid(factory, 'enc')}/totp", headers=admin)
    assert r.status_code == 200
    nou = r.json()["totp_secret"]
    assert nou != vell
    assert client.post("/auth/login", json={"username": "enc", "password": PASS, "totp": pyotp.TOTP(vell).now()}).status_code == 401
    assert client.post("/auth/login", json={"username": "enc", "password": PASS, "totp": pyotp.TOTP(nou).now()}).status_code == 200
    assert client.post(f"/usuaris/{uid(factory, 'enc')}/totp", headers=token(client, sec, "disp")).status_code == 403


def test_admin_posa_contrasenya_nova_i_les_sessions_antigues_cauen(ctx):
    client, factory, sec = ctx
    admin, enc = token(client, sec, "admin"), token(client, sec, "enc")
    e = uid(factory, "enc")
    assert client.post(f"/usuaris/{e}/contrasenya", json={"password": "curta"}, headers=admin).status_code == 422
    assert client.post(f"/usuaris/{e}/contrasenya", json={"password": "una-contrasenya-nova-1"}, headers=admin).status_code == 200
    assert client.get("/me", headers=enc).status_code == 401
    assert client.post("/auth/login", json={"username": "enc", "password": PASS, "totp": pyotp.TOTP(sec["enc"]).now()}).status_code == 401
    assert client.post("/auth/login", json={"username": "enc", "password": "una-contrasenya-nova-1", "totp": pyotp.TOTP(sec["enc"]).now()}).status_code == 200


def test_canvi_de_la_propia_contrasenya(ctx):
    client, factory, sec = ctx
    enc = token(client, sec, "enc")
    post = lambda **b: client.post("/auth/canvi-contrasenya", json=b, headers=enc)
    assert post(actual="no-es-aquesta-1", nova="una-contrasenya-nova-1").status_code == 403
    assert post(actual=PASS, nova="curta").status_code == 422
    assert post(actual=PASS, nova=PASS).status_code == 422  # ha de ser diferent
    assert post(actual=PASS, nova="una-contrasenya-nova-1").status_code == 200
    assert client.post("/auth/login", json={"username": "enc", "password": PASS, "totp": pyotp.TOTP(sec["enc"]).now()}).status_code == 401
    assert client.post("/auth/login", json={"username": "enc", "password": "una-contrasenya-nova-1", "totp": pyotp.TOTP(sec["enc"]).now()}).status_code == 200
    assert client.post("/auth/canvi-contrasenya", json={"actual": PASS, "nova": "x" * 20}).status_code == 401


# ---------- bloqueig per intents fallits ----------

def fallar(client, nom, n):
    for _ in range(n):
        client.post("/auth/login", json={"username": nom, "password": "contrasenya-equivocada", "totp": "000000"})


def test_bloqueig_temporal_despres_de_cinc_intents_fallits(ctx):
    client, factory, sec = ctx
    fallar(client, "enc", service.MAX_FAILED_LOGINS)
    r = login_ok(client, sec, "enc")  # amb les credencials CORRECTES continua bloquejat
    assert r.status_code == 429 and "bloquejat" in r.json()["detail"].lower()
    assert login_ok(client, sec, "disp").status_code == 200  # un altre usuari no es veu afectat


def test_el_bloqueig_caduca_i_un_login_correcte_reinicia_el_compte(ctx):
    client, factory, sec = ctx
    fallar(client, "enc", service.MAX_FAILED_LOGINS - 1)
    assert login_ok(client, sec, "enc").status_code == 200  # un intent bo reinicia el compte
    fallar(client, "enc", service.MAX_FAILED_LOGINS - 1)
    assert login_ok(client, sec, "enc").status_code == 200
    # envelliment: si els intents tenen més de la finestra, deixen de comptar
    fallar(client, "enc", service.MAX_FAILED_LOGINS)
    s = factory()
    from datetime import timedelta
    for a in s.scalars(select(LoginAttempt)):
        a.ts = a.ts - timedelta(minutes=service.LOCKOUT_MINUTES + 1)
    s.commit()
    s.close()
    assert login_ok(client, sec, "enc").status_code == 200


def test_el_bloqueig_tambe_protegeix_noms_dusuari_inexistents_sense_revelar_res(ctx):
    client, factory, sec = ctx
    fallar(client, "no-existeix", service.MAX_FAILED_LOGINS)
    r = client.post("/auth/login", json={"username": "no-existeix", "password": PASS, "totp": "123456"})
    assert r.status_code == 429  # mateix comportament que amb un usuari real: no es pot saber si existeix

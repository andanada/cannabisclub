"""Bloqueig per intents: es registra ABANS de verificar, auditoria sense text lliure, límit per IP i Argon2 acotat."""
import json
import os
import threading

import pytest

from sqlalchemy import func, select

from app import ratelimit, security, service
from app.models import AuditLog, LoginAttempt, User
from tests.test_api import PASS, ctx, env, token  # noqa: F401


def audits(factory):
    s = factory()
    try:
        return [json.loads(a.payload) for a in s.scalars(select(AuditLog).order_by(AuditLog.seq))]
    finally:
        s.close()


def test_l_intent_es_registra_abans_de_verificar(ctx, monkeypatch):
    """Si la verificació triga (peticions en paral·lel), l'intent ja és visible per a les altres peticions."""
    client, factory, sec = ctx
    vist = []
    original = security.verify_password

    def espia(p, h):
        s = factory()
        vist.append(s.scalar(select(func.count()).select_from(LoginAttempt)))
        s.close()
        return original(p, h)
    monkeypatch.setattr(security, "verify_password", espia)
    client.post("/auth/login", json={"username": "enc", "password": "mala-contrasenya", "totp": "000000"})
    assert vist == [1]


pg_only = pytest.mark.skipif(not os.environ.get("CLUB_TEST_PG_URL"), reason="Cal PostgreSQL (SQLite compartit no admet fils reals)")


@pg_only
def test_exces_de_peticions_simultanies_no_salta_el_bloqueig(ctx):
    client, factory, sec = ctx
    codis = []

    def prova():
        codis.append(client.post("/auth/login", json={"username": "enc", "password": "mala-contrasenya", "totp": "000000"}).status_code)
    fils = [threading.Thread(target=prova) for _ in range(12)]
    [f.start() for f in fils]
    [f.join() for f in fils]
    assert codis.count(401) <= service.MAX_FAILED_LOGINS
    assert 429 in codis


def test_un_exit_neteja_els_intents(ctx):
    client, factory, sec = ctx
    for _ in range(2):
        client.post("/auth/login", json={"username": "enc", "password": "mala-contrasenya", "totp": "000000"})
    token(client, sec, "enc")
    s = factory()
    assert s.scalar(select(func.count()).select_from(LoginAttempt).where(LoginAttempt.username == "enc")) == 0
    s.close()


def test_usuari_inexistent_no_s_audita_i_existent_s_audita_l_id(ctx):
    client, factory, sec = ctx
    client.post("/auth/login", json={"username": "fantasma <script>", "password": "x" * 20, "totp": "1"})
    assert not any("fantasma" in json.dumps(a) for a in audits(factory))
    n = len(audits(factory))
    client.post("/auth/login", json={"username": "enc", "password": "mala-contrasenya", "totp": "000000"})
    nou = audits(factory)[n:]
    s = factory()
    uid = s.scalar(select(User.id).where(User.username == "enc"))
    s.close()
    assert nou == [{"accio": "login", "usuari": uid, "ok": False}]


def test_bloqueig_d_inexistent_no_audita(ctx):
    client, factory, sec = ctx
    for _ in range(8):
        client.post("/auth/login", json={"username": "ningu", "password": "mala-contrasenya", "totp": "000000"})
    assert audits(factory) == []


def test_limit_per_ip_a_login(ctx, monkeypatch):
    monkeypatch.setenv("CLUB_LOGIN_IP_LIMIT", "3")
    from app.main import create_app
    client, factory, sec = ctx
    from fastapi.testclient import TestClient
    c = TestClient(create_app(factory))
    cods = [c.post("/auth/login", json={"username": f"u{i}", "password": "mala-contrasenya", "totp": "0"}).status_code for i in range(5)]
    assert cods == [401, 401, 401, 429, 429]


def test_ratelimiter_finestra():
    r = ratelimit.RateLimiter(2, 10)
    assert r.allow("a", 0) and r.allow("a", 1) and not r.allow("a", 2)
    assert r.allow("b", 2) and r.allow("a", 11)


def test_argon2_te_concurrencia_limitada():
    assert security._gate._value <= 64 and isinstance(security.Overloaded(), Exception)

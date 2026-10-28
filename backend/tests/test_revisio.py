"""Correccions de la revisió de codi: auditoria no inflable des de fora, login sense revelar usuaris, cobrament de quota segur."""
import json
import time

import pyotp
from sqlalchemy import func, select

from app import quotes, security, service
from app.models import AuditLog, Quota
from tests.test_api import PASS, SOCI, ctx, env, token  # noqa: F401


def n_auditoria(factory):
    s = factory()
    try:
        return s.scalar(select(func.count()).select_from(AuditLog))
    finally:
        s.close()


def test_login_rebutja_camps_enormes_i_no_els_desa_a_lauditoria(ctx):
    client, factory, sec = ctx
    abans = n_auditoria(factory)
    for body in [{"username": "x" * 61, "password": "a", "totp": "1"},
                 {"username": "enc", "password": "a" * 201, "totp": "1"},
                 {"username": "enc", "password": "a", "totp": "1" * 11}]:
        assert client.post("/auth/login", json=body).status_code == 422
    assert n_auditoria(factory) == abans  # res d'això arriba a l'auditoria només d'afegir


def test_el_bloqueig_no_omple_lauditoria_amb_cada_peticio(ctx):
    client, factory, sec = ctx
    for _ in range(service.MAX_FAILED_LOGINS):
        client.post("/auth/login", json={"username": "enc", "password": "mala-contrasenya", "totp": "000000"})
    abans = n_auditoria(factory)
    for _ in range(20):
        assert client.post("/auth/login", json={"username": "enc", "password": PASS, "totp": "000000"}).status_code == 429
    assert n_auditoria(factory) - abans <= 1  # com a màxim una entrada «login_bloquejat»


def test_la_cadena_dauditoria_es_verifica_despres_de_molta_activitat(ctx):
    client, factory, sec = ctx
    admin = token(client, sec, "admin")
    for i in range(15):
        client.post("/socis", json={**SOCI, "document": f"{10000000 + i}"[:8] + service.LLETRES_DNI[(10000000 + i) % 23]}, headers=token(client, sec, "enc"))
    assert client.get("/auditoria/verificar", headers=admin).json()["integra"] is True


def test_login_dun_usuari_inexistent_triga_com_un_dexistent(ctx):
    """Es fa la mateixa feina (hash de contrasenya) tant si l'usuari existeix com si no."""
    client, factory, sec = ctx
    def mesura(nom):
        t0 = time.perf_counter()
        for _ in range(3):
            client.post("/auth/login", json={"username": nom, "password": "contrasenya-equivocada", "totp": "000000"})
        return time.perf_counter() - t0
    existent, inexistent = mesura("disp"), mesura("no-existeix-gens")
    assert inexistent > existent * 0.4  # abans era ordres de magnitud més ràpid


def test_cobrar_la_quota_bloqueja_el_soci_per_evitar_doble_cobrament(ctx):
    """charge() ha de llegir l'estat de la quota DESPRÉS d'agafar el bloqueig del soci."""
    import inspect
    assert "with_for_update" in inspect.getsource(quotes.charge)
    client, factory, sec = ctx
    enc = token(client, sec, "enc")
    mid = client.post("/socis", json=SOCI, headers=enc).json()["id"]
    client.post("/caixa/obrir", json={"local_id": 1, "opening_cent": 0}, headers=enc)
    for _ in range(2):
        assert client.post(f"/socis/{mid}/quotes", json={"import_cent": 1000, "metode": "efectiu", "mesos": 1}, headers=enc).status_code == 201
    s = factory()
    q = s.scalars(select(Quota).order_by(Quota.id)).all()
    s.close()
    assert q[1].valid_des == q[0].valid_fins.replace(day=q[0].valid_fins.day) + (q[1].valid_des - q[0].valid_fins)  # trams consecutius
    assert (q[1].valid_des - q[0].valid_fins).days == 1


import os
import threading

import pytest

pg_only = pytest.mark.skipif(not os.environ.get("CLUB_TEST_PG_URL"), reason="Cal PostgreSQL (CLUB_TEST_PG_URL)")


@pg_only
def test_auditoria_concurrent_no_bifurca_la_cadena(ctx):
    """Vint transaccions simultànies afegint a l'auditoria: la cadena ha de seguir verificant-se."""
    client, factory, sec = ctx
    errors = []

    def treballa(i):
        try:
            s = factory()
            service.audit_append(s, {"accio": "prova_concurrencia", "n": i})
            s.commit()
            s.close()
        except Exception as e:  # pragma: no cover
            errors.append(e)

    fils = [threading.Thread(target=treballa, args=(i,)) for i in range(20)]
    [f.start() for f in fils]
    [f.join() for f in fils]
    assert not errors
    s = factory()
    assert service.audit_verify(s) == (True, None)
    assert s.scalar(select(func.count()).select_from(AuditLog).where(AuditLog.payload.like("%prova_concurrencia%"))) == 20
    s.close()

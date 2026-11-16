"""Doble enviament: la mateixa operació (mateix `client_ref`) no es registra dues vegades."""
from datetime import timedelta
from decimal import Decimal

from sqlalchemy import func, select

from app import idempotencia
from app.models import CashEntry, IdempotencyKey, Quota, StockMovement, now
from tests.test_api import ctx, env, token  # noqa: F401
from tests.test_stock import estoc, setup_data

REF = "3f2b8c1e-0d4a-4b6f-9a51-7c2e9d1f0a11"


def n(factory, model, *where):
    with factory() as s:
        return s.scalar(select(func.count()).select_from(model).where(*where))


def test_dispensacio_repetida_amb_la_mateixa_referencia_es_fa_una_sola_vegada(ctx):
    client, factory, sec = ctx
    enc = token(client, sec, "enc")
    mid, pid = setup_data(client, enc, factory)
    assert client.post("/caixa/obrir", json={"local_id": 1, "opening_cent": 0}, headers=enc).status_code == 201
    cos = {"member_id": mid, "product_id": pid, "grams": "2", "metode": "efectiu", "client_ref": REF}
    a = client.post("/dispensacions", json=cos, headers=enc)
    b = client.post("/dispensacions", json=cos, headers=enc)      # Intro després del clic, o reintent per tall de xarxa
    assert a.status_code == 201 and b.status_code == 201
    assert a.json() == b.json()                                    # la mateixa resposta, el mateix moviment
    assert n(factory, StockMovement, StockMovement.tipus == "dispensacio") == 1
    assert n(factory, CashEntry, CashEntry.tipus == "cobrament") == 1
    assert Decimal(estoc(client, enc)) == Decimal("8")
    # una referència nova és una operació nova
    assert client.post("/dispensacions", json={**cos, "client_ref": REF[:-1] + "2"}, headers=enc).status_code == 201
    assert Decimal(estoc(client, enc)) == Decimal("6")
    # sense referència tot funciona com abans
    assert client.post("/dispensacions", json={k: v for k, v in cos.items() if k != "client_ref"}, headers=enc).status_code == 201


def test_la_mateixa_referencia_amb_altres_dades_o_d_un_altre_usuari_es_rebutja(ctx):
    client, factory, sec = ctx
    enc, dsp = token(client, sec, "enc"), token(client, sec, "disp")
    mid, pid = setup_data(client, enc, factory)
    cos = {"member_id": mid, "product_id": pid, "grams": "1", "client_ref": REF}
    assert client.post("/dispensacions", json=cos, headers=enc).status_code == 201
    r = client.post("/dispensacions", json={**cos, "grams": "3"}, headers=enc)
    assert r.status_code == 409 and "ja s'havia registrat" in r.json()["detail"]
    assert client.post("/dispensacions", json=cos, headers=dsp).status_code == 409
    assert n(factory, StockMovement, StockMovement.tipus == "dispensacio") == 1


def test_un_intent_fallit_no_gasta_la_referencia(ctx):
    client, factory, sec = ctx
    enc = token(client, sec, "enc")
    mid, pid = setup_data(client, enc, factory, gprod="1")
    cos = {"member_id": mid, "product_id": pid, "grams": "5", "client_ref": REF}
    assert client.post("/dispensacions", json=cos, headers=enc).status_code == 422      # estoc insuficient
    assert n(factory, IdempotencyKey) == 0
    assert client.post("/moviments/entrada", json={"product_id": pid, "grams": "10"}, headers=enc).status_code == 201
    assert client.post("/dispensacions", json=cos, headers=enc).status_code == 201      # corregit: ara sí


def test_quota_repetida_no_cobra_dos_periodes(ctx):
    client, factory, sec = ctx
    enc = token(client, sec, "enc")
    mid, _ = setup_data(client, enc, factory)
    assert client.post("/caixa/obrir", json={"local_id": 1, "opening_cent": 0}, headers=enc).status_code == 201
    cos = {"import_cent": 2500, "metode": "efectiu", "mesos": 1, "client_ref": REF}
    a = client.post(f"/socis/{mid}/quotes", json=cos, headers=enc)
    b = client.post(f"/socis/{mid}/quotes", json=cos, headers=enc)
    assert a.status_code == 201 and b.status_code == 201 and a.json() == b.json()
    assert n(factory, Quota) == 1 and n(factory, CashEntry, CashEntry.tipus == "quota") == 1


def test_despesa_repetida_es_registra_una_vegada(ctx):
    client, factory, sec = ctx
    enc = token(client, sec, "enc")
    assert client.post("/caixa/obrir", json={"local_id": 1, "opening_cent": 10000}, headers=enc).status_code == 201
    cos = {"local_id": 1, "cent": 500, "metode": "efectiu", "categoria": "neteja", "concepte": "bosses", "client_ref": REF}
    a = client.post("/despeses", json=cos, headers=enc)
    b = client.post("/despeses", json=cos, headers=enc)
    assert a.status_code == 201 and b.status_code == 201 and a.json() == b.json()
    assert n(factory, CashEntry, CashEntry.tipus == "despesa") == 1


def test_referencia_mal_formada_es_rebutja_i_les_velles_es_netegen(ctx):
    client, factory, sec = ctx
    enc = token(client, sec, "enc")
    mid, pid = setup_data(client, enc, factory)
    cos = {"member_id": mid, "product_id": pid, "grams": "1"}
    assert client.post("/dispensacions", json={**cos, "client_ref": "curta"}, headers=enc).status_code == 422
    assert client.post("/dispensacions", json={**cos, "client_ref": "x" * 80}, headers=enc).status_code == 422
    assert client.post("/dispensacions", json={**cos, "client_ref": REF}, headers=enc).status_code == 201
    with factory() as s:   # envelleix la clau: la següent operació amb referència la neteja
        s.scalar(select(IdempotencyKey)).creat = now() - timedelta(days=idempotencia.DIES + 1)
        s.commit()
    assert client.post("/dispensacions", json={**cos, "client_ref": REF[:-1] + "9"}, headers=enc).status_code == 201
    with factory() as s:
        assert [k.clau for k in s.scalars(select(IdempotencyKey))] == [REF[:-1] + "9"]

"""Cadena d'auditoria amb HMAC, compatibilitat amb entrades SHA-256 antigues, ancoratge i detecció de retall."""
import json

import pytest
from sqlalchemy import select, text

from app import audit, service
from app.models import AuditLog
from tests.test_api import ctx, env, token  # noqa: F401


def omple(db, n, abans=0):
    for i in range(n):
        service.audit_append(db, {"accio": "prova", "i": abans + i})
    db.commit()


def permet_manipular(db):
    """En PostgreSQL l'auditoria és només d'afegir (disparador): per simular un atacant amb accés a la BD es desactiva."""
    if db.get_bind().dialect.name == "postgresql":
        db.execute(text("ALTER TABLE audit_log DISABLE TRIGGER USER"))


def afegeix_antiga(db, payload):
    """Una entrada com les d'abans de l'HMAC: SHA-256 pla i sense marca d'algorisme."""
    last = db.scalar(select(AuditLog).order_by(AuditLog.seq.desc()).limit(1))
    prev = last.hash if last else audit.GENESIS
    db.add(AuditLog(payload=service._canon(payload), prev_hash=prev, hash=audit._digest(prev, payload)))
    db.commit()


def test_les_entrades_noves_porten_hmac_i_no_es_poden_recalcular_sense_la_clau(ctx):
    client, factory, sec = ctx
    s = factory()
    omple(s, 3)
    fila = s.scalar(select(AuditLog).order_by(AuditLog.seq.desc()).limit(1))
    p = json.loads(fila.payload)
    assert p["_alg"] == "h1" and len(fila.hash) == 64
    assert fila.hash != audit._digest(fila.prev_hash, p)               # no és el SHA-256 pla
    assert service.audit_verify(s) == (True, None)
    s.close()


def test_cadena_barrejada_antiga_mes_hmac_verifica(ctx):
    client, factory, sec = ctx
    s = factory()
    afegeix_antiga(s, {"accio": "vella", "n": 1})
    afegeix_antiga(s, {"accio": "vella", "n": 2})
    omple(s, 3)
    assert service.audit_verify(s) == (True, None)
    s.close()


def test_reescriure_amb_sha256_sense_clau_es_detecta(ctx, monkeypatch):
    """Un atacant amb accés a la BD refà tota la cadena amb SHA-256 pla traient la marca: ha de fallar."""
    client, factory, sec = ctx
    s = factory()
    omple(s, 4)
    ancora = service.audit_anchor(s)
    permet_manipular(s)
    prev = audit.GENESIS
    for f in s.scalars(select(AuditLog).order_by(AuditLog.seq)).all():
        p = {k: v for k, v in json.loads(f.payload).items() if k != "_alg"}
        f.payload, f.prev_hash, f.hash = service._canon(p), prev, audit._digest(prev, p)
        prev = f.hash
    s.commit()
    ok2, _ = service.audit_verify(s, anchor=ancora)                    # l'ancoratge extern ho delata sempre
    assert ok2 is False
    monkeypatch.setenv("CLUB_AUDIT_HMAC_DES_DE", "1")                  # i també el punt de tall fixat fora de la BD
    assert service.audit_verify(s) == (False, 1)
    s.close()


def test_alterar_el_payload_o_el_hash_es_detecta(ctx):
    client, factory, sec = ctx
    s = factory()
    omple(s, 4)
    permet_manipular(s)
    fila = s.scalars(select(AuditLog).order_by(AuditLog.seq)).all()[1]
    fila.payload = fila.payload.replace('"i":1', '"i":9')
    s.commit()
    assert service.audit_verify(s) == (False, fila.seq)
    s.close()


def test_ancoratge_detecta_retall_del_final(ctx):
    client, factory, sec = ctx
    s = factory()
    omple(s, 5)
    ancora = service.audit_anchor(s)
    assert set(ancora) == {"seq", "hash"} and ancora["seq"] == 5
    assert service.audit_verify(s, anchor=ancora) == (True, None)
    permet_manipular(s)
    for f in s.scalars(select(AuditLog).where(AuditLog.seq > 3)).all():
        s.delete(f)
    s.commit()
    assert service.audit_verify(s) == (True, None)                      # sense ancoratge no es veu
    ok, seq = service.audit_verify(s, anchor=ancora)
    assert ok is False and seq == 4
    s.close()


def test_verificacio_per_lots_i_avis_sense_ancoratge(ctx):
    client, factory, sec = ctx
    s = factory()
    omple(s, 25)
    d = service.audit_verify_detail(s, batch=7)
    assert d["integra"] is True and d["ultim_seq"] == 25 and "sense_ancoratge" in d["avisos"]
    d2 = service.audit_verify_detail(s, anchor=service.audit_anchor(s), batch=7)
    assert d2["integra"] is True and "sense_ancoratge" not in d2["avisos"]
    s.close()


def test_endpoint_verificar_accepta_ancora_i_avisa(ctx):
    client, factory, sec = ctx
    admin = token(client, sec, "admin")
    r = client.get("/auditoria/verificar", headers=admin).json()
    assert r["integra"] is True and "sense_ancoratge" in r["avisos"]
    a = client.get("/auditoria/ancoratge", headers=admin).json()
    r2 = client.post("/auditoria/verificar", json={"seq": a["seq"], "hash": a["hash"]}, headers=admin).json()
    assert r2["integra"] is True and "sense_ancoratge" not in r2["avisos"]
    r3 = client.post("/auditoria/verificar", json={"seq": a["seq"] + 50, "hash": "0" * 64}, headers=admin).json()
    assert r3["integra"] is False
    assert client.get("/auditoria/ancoratge", headers=token(client, sec, "enc")).status_code == 403


def test_clau_pròpia_diferent_de_la_derivada(ctx, monkeypatch):
    client, factory, sec = ctx
    s = factory()
    omple(s, 2)
    monkeypatch.setenv("CLUB_AUDIT_KEY", "una-altra-clau-d-auditoria")
    assert service.audit_verify(s)[0] is False                           # amb una altra clau no valida
    s.close()


def test_degradar_nomes_la_cua_es_detecta_sense_cap_configuracio(ctx):
    client, factory, sec = ctx
    s = factory()
    omple(s, 4)
    permet_manipular(s)
    f = s.scalars(select(AuditLog).order_by(AuditLog.seq)).all()
    prev = f[2].hash
    for x in f[3:]:
        p = {k: v for k, v in json.loads(x.payload).items() if k != "_alg"}
        x.payload, x.prev_hash, x.hash = service._canon(p), prev, audit._digest(prev, p)
        prev = x.hash
    s.commit()
    assert service.audit_verify(s) == (False, f[3].seq)
    s.close()

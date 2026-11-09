import json

import pytest
from sqlalchemy import select, text

from app import service
from app.models import AuditAnchor, AuditLog
from tests.test_api import SOCI, ctx, env, token  # noqa: F401
from tests.test_audit_hmac import permet_manipular


def test_les_entrades_noves_porten_alg_h1(ctx):
    client, factory, sec = ctx
    enc = token(client, sec, "enc")
    client.post("/socis", json=SOCI, headers=enc)
    with factory() as s:
        files = s.scalars(select(AuditLog)).all()
        assert files and all(f.alg == "h1" for f in files)
        assert service.audit_verify(s) == (True, None)


def test_alg_incoherent_o_esborrat_es_detecta(ctx):
    client, factory, sec = ctx
    token(client, sec, "enc")
    with factory() as s:
        service.audit_append(s, {"accio": "x"})
        s.commit()
        ultima = s.scalars(select(AuditLog).order_by(AuditLog.seq.desc())).first().seq
        permet_manipular(s)
        s.execute(text("UPDATE audit_log SET alg = NULL WHERE seq = :q"), {"q": ultima})  # degradació: treure la marca
        s.commit()
        ok, seq = service.audit_verify(s)
        assert ok is False and seq == ultima


def test_ancoratge_intern_detecta_retall_i_canvi(ctx):
    client, factory, sec = ctx
    token(client, sec, "enc")
    with factory() as s:
        for i in range(3):
            service.audit_append(s, {"accio": "x", "i": i})
        s.commit()
        a = service.audit_anchor_save(s, "prova")
        s.commit()
        assert a.seq >= 3
        d = service.audit_verify_detail(s)
        assert d["integra"] and "ancoratge_intern" in d["avisos"] and "sense_ancoratge" not in d["avisos"]
        # retall del final de la cadena (sense tocar la resta)
        permet_manipular(s)
        s.execute(text("DELETE FROM audit_log WHERE seq = :q"), {"q": a.seq})
        s.commit()
        assert service.audit_verify(s)[0] is False


def test_ancoratge_amb_buida_no_fa_res(ctx):
    client, factory, sec = ctx
    with factory() as s:
        permet_manipular(s)
        s.execute(text("DELETE FROM audit_log"))
        s.commit()
        assert service.audit_anchor_save(s) is None

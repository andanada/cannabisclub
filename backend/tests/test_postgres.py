import os

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.models import AuditLog, CashEntry, StockMovement
from tests.test_api import ctx, env, token  # noqa: F401
from tests.test_stock import setup_data

pg_only = pytest.mark.skipif(not os.environ.get("CLUB_TEST_PG_URL"), reason="Cal PostgreSQL (CLUB_TEST_PG_URL)")


@pg_only
@pytest.mark.parametrize("sql", [
    "UPDATE stock_movements SET delta_mg = 1",
    "DELETE FROM stock_movements",
    "TRUNCATE stock_movements CASCADE",
    "UPDATE audit_log SET hash = 'x'",
    "DELETE FROM audit_log",
    "UPDATE cash_entries SET import_cent = 1",
    "DELETE FROM time_events",
    "DELETE FROM checkins",
])
def test_sql_directe_no_pot_alterar_taules_d_apunts(ctx, sql):
    client, factory, sec = ctx
    enc = token(client, sec, "enc")
    mid, _ = setup_data(client, enc, factory)
    assert client.post(f"/socis/{mid}/entrada", headers=enc).status_code == 201
    client.post("/caixa/obrir", json={"local_id": 1, "opening_cent": 0}, headers=enc)
    client.post("/despeses", json={"local_id": 1, "cent": 100, "metode": "efectiu", "categoria": "x", "concepte": "abc"}, headers=enc)
    client.post("/fitxatge", json={"local_id": 1, "tipus": "entrada"}, headers=enc)
    s = factory()
    with pytest.raises(DBAPIError) as e:
        s.execute(text(sql))
        s.commit()
    assert "només d'afegir" in str(e.value)
    s.rollback()
    s.close()
    # i les dades segueixen intactes
    assert client.get("/auditoria/verificar", headers=token(client, sec, "admin")).json()["integra"] is True


@pg_only
def test_taules_normals_si_es_poden_actualitzar(ctx):
    client, factory, sec = ctx
    enc = token(client, sec, "enc")
    mid, _ = setup_data(client, enc, factory)
    assert client.post(f"/socis/{mid}/estat", json={"estat": "suspes"}, headers=enc).status_code == 200

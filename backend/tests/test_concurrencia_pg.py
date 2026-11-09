"""Concurrència real contra PostgreSQL (fils amb sessions pròpies). Cal CLUB_TEST_PG_URL."""
import os
import threading
from decimal import Decimal

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from app import cash, inventaris, magatzems, stock
from app.models import CashSession, Local, Product, StockMovement, User
from tests.test_api import ctx, env, token  # noqa: F401
from tests.test_stock import setup_data

pg_only = pytest.mark.skipif(not os.environ.get("CLUB_TEST_PG_URL"), reason="Cal PostgreSQL (CLUB_TEST_PG_URL)")


def correr_junts(factory, *tasques, timeout=30):
    """Executa cada tasca(session, user) en un fil propi, arrencant-les a l'hora. Retorna [resultat | excepció]."""
    barrera = threading.Barrier(len(tasques))
    out = [None] * len(tasques)

    def fil(i, tasca):
        s = factory()
        try:
            user = s.scalar(select(User).where(User.username == "enc"))
            barrera.wait(10)
            out[i] = tasca(s, user)
        except Exception as e:  # noqa: BLE001  (el test inspecciona l'excepció)
            s.rollback()
            out[i] = e
        finally:
            s.close()

    fils = [threading.Thread(target=fil, args=(i, t)) for i, t in enumerate(tasques)]
    for f in fils:
        f.start()
    for f in fils:
        f.join(timeout)
    assert not any(f.is_alive() for f in fils), "interbloqueig o fil penjat"
    return out


def nous_productes(client, enc, noms, gprod="10", genetic=True):
    ids = []
    for n in noms:
        pid = client.post("/productes", json={"local_id": 1, "nom": n, "preu_cent_per_g": 100, "es_genetic": genetic}, headers=enc).json()["id"]
        client.post("/moviments/entrada", json={"product_id": pid, "grams": gprod}, headers=enc)
        ids.append(pid)
    return ids


@pg_only
def test_dos_fils_dispensant_productes_diferents_al_mateix_soci_respecten_el_limit_diari(ctx):
    client, factory, sec = ctx
    enc = token(client, sec, "enc")
    s = factory(); s.get(Local, 1).limit_diari_mg = 5000; s.commit(); s.close()
    mid, _ = setup_data(client, enc, factory)
    a, b = nous_productes(client, enc, ["P1", "P2"])
    res = correr_junts(factory,
                       lambda s, u: stock.dispense(s, u, mid, a, Decimal("4"), None),
                       lambda s, u: stock.dispense(s, u, mid, b, Decimal("4"), None))
    errors = [r for r in res if isinstance(r, Exception)]
    assert len(errors) == 1 and isinstance(errors[0], ValueError) and "límit diari" in str(errors[0])
    s = factory()
    assert stock.dispensed_mg(s, mid, "dia", stock.datetime.now(stock.timezone.utc)) == 4000
    s.close()


@pg_only
def test_dos_fils_amb_una_regla_per_soci_no_la_superen(ctx):
    client, factory, sec = ctx
    enc, admin = token(client, sec, "enc"), token(client, sec, "admin")
    mid, _ = setup_data(client, enc, factory)
    a, b = nous_productes(client, enc, ["P1", "P2"])
    client.post("/locals/1/regles", json={"nom": "R", "ambit": "tot", "periode": "dia", "max_g": "5"}, headers=admin)
    res = correr_junts(factory,
                       lambda s, u: stock.dispense(s, u, mid, a, Decimal("3"), None),
                       lambda s, u: stock.dispense(s, u, mid, b, Decimal("3"), None))
    assert sum(isinstance(r, ValueError) for r in res) == 1


@pg_only
def test_traspas_i_dispensacio_simultanis_no_deixen_l_estoc_negatiu(ctx):
    client, factory, sec = ctx
    enc = token(client, sec, "enc")
    mid, pid = setup_data(client, enc, factory, gprod="5")
    wid = client.post("/locals/1/magatzems", json={"nom": "Safata"}, headers=enc).json()["id"]
    for _ in range(3):  # diverses voltes per donar opcions a la carrera
        client.post("/moviments/entrada", json={"product_id": pid, "grams": "5"}, headers=enc)  # principal: tornem a tenir-ne
        s = factory()
        prod = s.get(Product, pid)
        actual = Decimal(stock.stock_mg(s, pid)) / 1000
        s.close()

        def transfer(s, u):
            return magatzems.transfer(s, u, s.get(Product, pid), None, wid, actual)

        def dispensa(s, u):
            return stock.dispense(s, u, mid, pid, actual, None)

        res = correr_junts(factory, transfer, dispensa)
        assert sum(isinstance(r, ValueError) for r in res) == 1, res
        s = factory()
        assert stock.stock_mg(s, pid) >= 0
        s.close()
        # buida la safata de tornada per a la volta següent
        s = factory()
        u = s.scalar(select(User).where(User.username == "enc"))
        dins = stock.stock_in_mg(s, pid, wid)
        if dins:
            magatzems.transfer(s, u, s.get(Product, pid), wid, None, Decimal(dins) / 1000)
        s.close()


@pg_only
def test_dues_obertures_de_caixa_simultanies_en_deixen_una(ctx):
    client, factory, sec = ctx
    res = correr_junts(factory,
                       lambda s, u: cash.open_session(s, u, 1, 0),
                       lambda s, u: cash.open_session(s, u, 1, 0),
                       lambda s, u: cash.open_session(s, u, 1, 0))
    errors = [r for r in res if isinstance(r, Exception)]
    assert len(errors) == 2 and all(isinstance(e, ValueError) and "caixa oberta" in str(e) for e in errors)
    s = factory()
    assert len(list(s.scalars(select(CashSession).where(CashSession.closed_at.is_(None))))) == 1
    s.close()


@pg_only
def test_dos_cobraments_simultanis_de_la_mateixa_dispensacio_en_creen_un(ctx):
    client, factory, sec = ctx
    enc = token(client, sec, "enc")
    mid, pid = setup_data(client, enc, factory)
    client.post("/caixa/obrir", json={"local_id": 1, "opening_cent": 0}, headers=enc)
    d = client.post("/dispensacions", json={"member_id": mid, "product_id": pid, "grams": "1"}, headers=enc).json()["id"]
    res = correr_junts(factory, lambda s, u: cash.charge(s, u, d, "efectiu"), lambda s, u: cash.charge(s, u, d, "targeta"))
    assert sum(isinstance(r, ValueError) for r in res) == 1


@pg_only
def test_tancar_inventari_i_dispensar_a_la_vegada_no_s_interbloquegen(ctx):
    client, factory, sec = ctx
    enc = token(client, sec, "enc")
    mid, _ = setup_data(client, enc, factory)
    prods = nous_productes(client, enc, ["P1", "P2", "P3"], gprod="50")
    sid = client.post("/locals/1/inventaris", json={}, headers=enc).json()["id"]
    for p in prods:
        client.put(f"/inventaris/{sid}/linies/{p}", json={"grams": "40"}, headers=enc)

    def tanca(s, u):
        return inventaris.tancar(s, u, s.get(inventaris.InventorySession, sid))

    def dispensa(s, u):
        for p in reversed(prods):
            stock.dispense(s, u, mid, p, Decimal("1"), None)

    res = correr_junts(factory, tanca, dispensa, timeout=60)
    assert not any(isinstance(r, Exception) for r in res), res
    s = factory()
    assert all(stock.stock_mg(s, p) >= 0 for p in prods)
    s.close()


@pg_only
def test_una_sessio_de_caixa_tancada_no_es_pot_tornar_a_tocar_ni_esborrar(ctx):
    client, factory, sec = ctx
    enc = token(client, sec, "enc")
    client.post("/caixa/obrir", json={"local_id": 1, "opening_cent": 0}, headers=enc)
    s = factory()
    sid = s.scalar(select(CashSession.id))
    s.execute(text("UPDATE cash_sessions SET opening_cent = 5"))  # obrint-la no es poden canviar les dades d'obertura
    with pytest.raises(DBAPIError):
        s.commit()
    s.rollback()
    assert client.post("/caixa/tancar", json={"local_id": 1, "counted_cent": 0}, headers=enc).status_code == 200
    for sql in ("UPDATE cash_sessions SET counted_cent = 99", "UPDATE cash_sessions SET closed_at = NULL", "DELETE FROM cash_sessions"):
        with pytest.raises(DBAPIError):
            s.execute(text(sql))
            s.commit()
        s.rollback()
    s.close()

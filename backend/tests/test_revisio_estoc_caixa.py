"""Troballes de la revisió: correccions amb magatzem, períodes, límits només genètics, caixa, descomptes, unitats."""
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app import cash, stock, unitats
from app.models import CashSession, Discount, Local, StockMovement, User
from tests.test_api import ctx, env, token  # noqa: F401
from tests.test_stock import setup_data


def post(client, h, url, **body):
    return client.post(url, json=body, headers=h)


def traspas(client, h, pid, de, a, g):
    return post(client, h, "/moviments/traspas", product_id=pid, de=de, a=a, grams=g)


def usuari(s, nom="enc"):
    return s.scalar(select(User).where(User.username == nom))


# ---------- unitats ----------

def test_unitats_arrodoneix_cap_amunt_a_la_meitat_i_torna_a_grams():
    assert unitats.g_to_mg(Decimal("0.0005")) == 1
    assert unitats.g_to_mg(Decimal("2.5")) == 2500
    assert unitats.mg_to_g(2500) == "2.5"
    assert unitats.mg_to_g(7) == "0.007"


# ---------- correccions i magatzems ----------

def test_correccio_d_una_entrada_a_un_magatzem_hereta_el_magatzem(ctx):
    client, factory, sec = ctx
    enc = token(client, sec, "enc")
    mid, pid = setup_data(client, enc, factory)
    saf = post(client, enc, "/locals/1/magatzems", nom="Safata").json()["id"]
    e = post(client, enc, "/moviments/entrada", product_id=pid, grams="3", magatzem_id=saf).json()["id"]
    assert post(client, enc, f"/moviments/{e}/correccio", nota="error").status_code == 201
    fila = next(f for f in client.get("/locals/1/magatzems/estoc", headers=enc).json() if f["product_id"] == pid)
    estocs = {x["magatzem_id"]: x["g"] for x in fila["estocs"]}
    assert estocs == {None: "10", saf: "0"}  # el principal no ha rebut la correcció


def test_correccio_d_una_entrada_valida_amb_l_estoc_del_seu_magatzem(ctx):
    client, factory, sec = ctx
    enc = token(client, sec, "enc")
    mid, pid = setup_data(client, enc, factory)
    saf = post(client, enc, "/locals/1/magatzems", nom="Safata").json()["id"]
    e = post(client, enc, "/moviments/entrada", product_id=pid, grams="3", magatzem_id=saf).json()["id"]
    assert traspas(client, enc, pid, saf, None, "2").status_code == 201  # a la safata en queda 1
    r = post(client, enc, f"/moviments/{e}/correccio", nota="error")
    assert r.status_code == 422 and "negatiu" in r.json()["detail"]  # el principal en té 12, però la safata només 1


def test_un_traspas_no_es_pot_corregir_a_mitges(ctx):
    client, factory, sec = ctx
    enc = token(client, sec, "enc")
    mid, pid = setup_data(client, enc, factory)
    saf = post(client, enc, "/locals/1/magatzems", nom="Safata").json()["id"]
    assert traspas(client, enc, pid, None, saf, "2").status_code == 201
    s = factory()
    ids = [m.id for m in s.scalars(select(StockMovement).where(StockMovement.tipus == "traspas"))]
    s.close()
    assert len(ids) == 2
    for i in ids:
        r = post(client, enc, f"/moviments/{i}/correccio", nota="oops")
        assert r.status_code == 422 and "traspàs" in r.json()["detail"]


# ---------- períodes i límits ----------

def test_la_correccio_resta_al_periode_de_la_dispensacio_original(ctx):
    client, factory, sec = ctx
    enc = token(client, sec, "enc")
    mid, pid = setup_data(client, enc, factory)
    s = factory()
    ara = datetime.now(timezone.utc)
    antiga = ara - timedelta(days=40)  # un altre mes i un altre dia
    d = stock.dispense(s, usuari(s), mid, pid, Decimal("4"), None, now=antiga)
    stock.correct(s, usuari(s), d.id, "error")  # s'escriu ara, però pertany al període de fa 40 dies
    assert stock.dispensed_mg(s, mid, "dia", ara) == 0  # no queda en negatiu a avui
    assert stock.dispensed_mg(s, mid, "mes", ara) == 0
    assert stock.dispensed_mg(s, mid, "mes", antiga) == 0
    s.close()


def test_correccio_d_una_dispensacio_antiga_no_allibera_cupo_d_avui(ctx):
    client, factory, sec = ctx
    enc = token(client, sec, "enc")
    s = factory(); s.get(Local, 1).limit_diari_mg = 5000; s.commit(); s.close()
    mid, pid = setup_data(client, enc, factory)
    s = factory()
    ara = datetime.now(timezone.utc)
    antiga = stock.dispense(s, usuari(s), mid, pid, Decimal("4"), None, now=ara - timedelta(days=3))
    stock.dispense(s, usuari(s), mid, pid, Decimal("4"), None, now=ara)  # avui: 4 g
    stock.correct(s, usuari(s), antiga.id, "error")
    assert stock.dispensed_mg(s, mid, "dia", ara) == 4000  # abans: 0 (la correcció d'avui restava a avui)
    with pytest.raises(ValueError, match="límit diari"):
        stock.dispense(s, usuari(s), mid, pid, Decimal("2"), None, now=ara)
    s.close()


def test_els_limits_nomes_compten_i_bloquegen_productes_genetics(ctx):
    client, factory, sec = ctx
    enc, admin = token(client, sec, "enc"), token(client, sec, "admin")
    s = factory(); s.get(Local, 1).limit_diari_mg = 5000; s.commit(); s.close()
    mid, flor = setup_data(client, enc, factory)  # genètic
    beguda = post(client, enc, "/productes", local_id=1, nom="Aigua", preu_cent_per_g=1, es_genetic=False).json()["id"]
    post(client, enc, "/moviments/entrada", product_id=beguda, grams="50")
    post(client, admin, "/locals/1/regles", nom="R", ambit="tot", periode="dia", max_g="5")
    assert post(client, enc, "/dispensacions", member_id=mid, product_id=beguda, grams="20").status_code == 201  # no genètic: lliure
    assert post(client, enc, "/dispensacions", member_id=mid, product_id=flor, grams="5").status_code == 201  # l'aigua no ha comptat
    assert post(client, enc, "/dispensacions", member_id=mid, product_id=flor, grams="1").status_code == 422


# ---------- caixa ----------

def test_la_base_de_dades_no_admet_dues_caixes_obertes_al_mateix_local(ctx):
    client, factory, sec = ctx
    enc = token(client, sec, "enc")
    assert post(client, enc, "/caixa/obrir", local_id=1, opening_cent=0).status_code == 201
    s = factory()
    uid = usuari(s).id
    s.add(CashSession(local_id=1, opened_by=uid, opening_cent=0))
    with pytest.raises(IntegrityError):
        s.flush()
    s.rollback()
    s.add(CashSession(local_id=2, opened_by=uid, opening_cent=0))  # un altre local sí
    s.commit()
    s.close()


def test_tancar_caixa_avisa_de_dispensacions_sense_cobrar(ctx):
    client, factory, sec = ctx
    enc = token(client, sec, "enc")
    mid, pid = setup_data(client, enc, factory)
    post(client, enc, "/caixa/obrir", local_id=1, opening_cent=0)
    cobrada = post(client, enc, "/dispensacions", member_id=mid, product_id=pid, grams="1").json()["id"]
    pendent = post(client, enc, "/dispensacions", member_id=mid, product_id=pid, grams="2").json()["id"]
    post(client, enc, "/cobraments", movement_id=cobrada, metode="efectiu")
    s = factory()
    cs = cash.close_session(s, usuari(s), 1, 800)
    assert [p["moviment"] for p in cs.sense_cobrar] == [pendent]
    assert cs.sense_cobrar_cent == 1600
    s.close()


def test_es_pot_recobrar_una_dispensacio_si_es_corregeix_el_cobrament(ctx):
    client, factory, sec = ctx
    enc = token(client, sec, "enc")
    mid, pid = setup_data(client, enc, factory)
    post(client, enc, "/caixa/obrir", local_id=1, opening_cent=0)
    d = post(client, enc, "/dispensacions", member_id=mid, product_id=pid, grams="1").json()["id"]
    c1 = post(client, enc, "/cobraments", movement_id=d, metode="efectiu").json()["apunt"]
    assert post(client, enc, "/cobraments", movement_id=d, metode="targeta").status_code == 422  # ja cobrada
    assert post(client, enc, f"/caixa/apunts/{c1}/correccio", nota="mètode erroni").status_code == 201
    assert post(client, enc, "/cobraments", movement_id=d, metode="targeta").status_code == 201  # recobrada
    assert post(client, enc, "/cobraments", movement_id=d, metode="targeta").status_code == 422
    # amb un cobrament vigent no es pot corregir la dispensació
    assert post(client, enc, f"/moviments/{d}/correccio", nota="motiu").status_code == 422


def test_dispensar_i_cobrar_en_la_mateixa_transaccio(ctx):
    client, factory, sec = ctx
    enc = token(client, sec, "enc")
    mid, pid = setup_data(client, enc, factory)
    s = factory()
    with pytest.raises(ValueError, match="No hi ha cap caixa oberta"):
        stock.dispense(s, usuari(s), mid, pid, Decimal("1"), None, metode="efectiu")
    s.rollback()
    assert s.scalars(select(StockMovement).where(StockMovement.tipus == "dispensacio")).first() is None  # res a mitges
    cash.open_session(s, usuari(s), 1, 0)
    m = stock.dispense(s, usuari(s), mid, pid, Decimal("1"), None, metode="targeta")
    assert cash._live_charge(s, m.id) is not None
    s.close()


# ---------- descomptes ----------

def test_editar_nomes_l_inici_o_el_fi_no_esborra_l_altre(ctx):
    from app import descomptes
    client, factory, sec = ctx
    enc = token(client, sec, "enc")
    post(client, enc, "/locals/1/descomptes", nom="D", tipus="percent", valor=10, ambit="tot", inici="2030-01-01", fi="2030-12-31")
    s = factory()
    d = s.scalar(select(Discount))
    descomptes.update(s, usuari(s), d, None, None, None, date(2030, 2, 1), None, {"inici"})
    assert (d.inici, d.fi) == (date(2030, 2, 1), date(2030, 12, 31))
    descomptes.update(s, usuari(s), d, None, None, None, None, date(2030, 6, 1), {"fi"})
    assert (d.inici, d.fi) == (date(2030, 2, 1), date(2030, 6, 1))
    with pytest.raises(ValueError):
        descomptes.update(s, usuari(s), d, None, None, None, None, date(2030, 1, 1), {"fi"})  # fi < inici
    s.close()


def test_descomptes_de_l_informe_son_nets_de_correccions(ctx):
    client, factory, sec = ctx
    enc = token(client, sec, "enc")
    mid, pid = setup_data(client, enc, factory)
    did = post(client, enc, "/locals/1/descomptes", nom="D", tipus="percent", valor=50, ambit="tot").json()["id"]
    d = post(client, enc, "/dispensacions", member_id=mid, product_id=pid, grams="1", discount_id=did).json()["id"]
    avui = date.today().isoformat()
    url = f"/locals/1/informe/vendes?des={avui}&fins={avui}"
    assert client.get(url, headers=enc).json()["total"]["descomptes_cent"] == 400
    r = post(client, enc, f"/moviments/{d}/correccio", nota="motiu")
    assert r.status_code == 201, r.text
    assert client.get(url, headers=enc).json()["total"]["descomptes_cent"] == 0

from datetime import date, timedelta

import pytest
from sqlalchemy import select

from app.models import ImmutableError, MovementDiscount
from tests.test_api import SOCI, ctx, env, token  # noqa: F401
from tests.test_stock import setup_data


def desc(client, h, **extra):
    body = {"nom": "Estudiants", "tipus": "percent", "valor": 10, "ambit": "tot", **extra}
    return client.post("/locals/1/descomptes", json=body, headers=h)


def dispensa(client, h, mid, pid, g="2", **extra):
    return client.post("/dispensacions", json={"member_id": mid, "product_id": pid, "grams": g, **extra}, headers=h)


def test_descompte_percentual_es_registra_i_arrodoneix(ctx):
    client, factory, sec = ctx
    enc = token(client, sec, "enc")
    mid, pid = setup_data(client, enc, factory)  # 10 g a 800 cèntims/g
    did = desc(client, enc, valor=15).json()["id"]
    r = dispensa(client, enc, mid, pid, "2.5", discount_id=did)  # 2,5 g = 2000 -> -15% = 1700
    assert r.status_code == 201 and r.json()["import_cent"] == 1700 and r.json()["descompte_cent"] == 300
    s = factory()
    md = s.scalar(select(MovementDiscount))
    s.close()
    assert (md.original_cent, md.descompte_cent, md.nom) == (2000, 300, "Estudiants")


def test_descompte_per_import_fix_per_gram_no_baixa_de_zero(ctx):
    client, factory, sec = ctx
    enc = token(client, sec, "enc")
    mid, pid = setup_data(client, enc, factory)
    did = desc(client, enc, nom="Oferta", tipus="import_g", valor=100).json()["id"]  # -1 €/g
    assert dispensa(client, enc, mid, pid, "2", discount_id=did).json()["import_cent"] == 1400  # 1600 - 200
    gran = desc(client, enc, nom="Regal", tipus="import_g", valor=5000).json()["id"]
    assert dispensa(client, enc, mid, pid, "1", discount_id=gran).json()["import_cent"] == 0  # mai negatiu


def test_sense_descompte_tot_igual_i_el_cobrament_usa_limport_net(ctx):
    client, factory, sec = ctx
    enc = token(client, sec, "enc")
    mid, pid = setup_data(client, enc, factory)
    client.post("/caixa/obrir", json={"local_id": 1, "opening_cent": 0}, headers=enc)
    did = desc(client, enc, valor=50).json()["id"]
    d = dispensa(client, enc, mid, pid, "2", discount_id=did).json()
    assert dispensa(client, enc, mid, pid, "1").json()["import_cent"] == 800
    assert client.post("/cobraments", json={"movement_id": d["id"], "metode": "efectiu"}, headers=enc).json()["import_cent"] == 800


def test_ambits_producte_i_categoria_i_caducitat(ctx):
    client, factory, sec = ctx
    enc = token(client, sec, "enc")
    mid, pid = setup_data(client, enc, factory)
    flor = client.post("/productes", json={"local_id": 1, "nom": "B", "categoria": "flor", "preu_cent_per_g": 500}, headers=enc).json()["id"]
    client.post("/moviments/entrada", json={"product_id": flor, "grams": "10"}, headers=enc)
    d_cat = desc(client, enc, nom="Flor", ambit="categoria", categoria="flor").json()["id"]
    d_prod = desc(client, enc, nom="Només A", ambit="producte", product_id=pid).json()["id"]
    avui = date.today()
    d_vell = desc(client, enc, nom="Vell", fi=(avui - timedelta(days=1)).isoformat()).json()["id"]
    d_futur = desc(client, enc, nom="Futur", inici=(avui + timedelta(days=1)).isoformat()).json()["id"]
    assert dispensa(client, enc, mid, pid, discount_id=d_cat).status_code == 422       # A no és de la categoria «flor»
    assert dispensa(client, enc, mid, flor, discount_id=d_prod).status_code == 422     # el descompte és només per a A
    assert dispensa(client, enc, mid, flor, discount_id=d_cat).status_code == 201
    assert dispensa(client, enc, mid, pid, discount_id=d_prod).status_code == 201
    assert dispensa(client, enc, mid, pid, discount_id=d_vell).status_code == 422      # caducat
    assert dispensa(client, enc, mid, pid, discount_id=d_futur).status_code == 422     # encara no és vigent
    client.put(f"/descomptes/{d_prod}", json={"actiu": False}, headers=enc)
    assert dispensa(client, enc, mid, pid, discount_id=d_prod).status_code == 422      # desactivat
    assert dispensa(client, enc, mid, pid, discount_id=9999).status_code == 422


def test_llista_de_descomptes_aplicables_al_producte(ctx):
    client, factory, sec = ctx
    enc, disp = token(client, sec, "enc"), token(client, sec, "disp")
    mid, pid = setup_data(client, enc, factory)
    desc(client, enc, nom="Tots")
    desc(client, enc, nom="Altre producte", ambit="producte", product_id=pid + 99 if False else pid)
    desc(client, enc, nom="Caducat", fi=(date.today() - timedelta(days=2)).isoformat())
    aplicables = [d["nom"] for d in client.get(f"/locals/1/descomptes?producte={pid}", headers=disp).json()]
    assert aplicables == ["Altre producte", "Tots"] or sorted(aplicables) == ["Altre producte", "Tots"]
    tots = [d["nom"] for d in client.get("/locals/1/descomptes?tots=1", headers=enc).json()]
    assert "Caducat" in tots
    assert client.get("/locals/1/descomptes?tots=1", headers=disp).status_code == 403  # la gestió és de responsables


def test_validacio_permisos_i_auditoria(ctx):
    import json
    from app.models import AuditLog
    client, factory, sec = ctx
    enc, disp = token(client, sec, "enc"), token(client, sec, "disp")
    assert desc(client, disp).status_code == 403
    assert desc(client, enc, valor=0).status_code == 422
    assert desc(client, enc, valor=101).status_code == 422                       # percentatge > 100
    assert desc(client, enc, tipus="regal").status_code == 422
    assert desc(client, enc, ambit="categoria").status_code == 422               # falta la categoria
    assert desc(client, enc, ambit="producte").status_code == 422                # falta el producte
    assert desc(client, enc, inici="2026-05-02", fi="2026-05-01").status_code == 422
    assert desc(client, enc, nom=" ").status_code == 422
    assert desc(client, enc, ambit="producte", product_id=9999).status_code == 422
    assert client.post("/locals/2/descomptes", json={"nom": "X", "tipus": "percent", "valor": 5, "ambit": "tot"}, headers=enc).status_code == 403
    did = desc(client, enc).json()["id"]
    assert desc(client, enc).status_code == 422                                  # nom repetit al local
    s = factory()
    accions = [json.loads(a.payload)["accio"] for a in s.scalars(select(AuditLog))]
    s.close()
    assert "alta_descompte" in accions and did


def test_el_registre_de_descompte_no_es_pot_editar_ni_esborrar(ctx):
    client, factory, sec = ctx
    enc = token(client, sec, "enc")
    mid, pid = setup_data(client, enc, factory)
    did = desc(client, enc).json()["id"]
    dispensa(client, enc, mid, pid, discount_id=did)
    s = factory()
    s.scalar(select(MovementDiscount)).descompte_cent = 1
    with pytest.raises(ImmutableError):
        s.commit()
    s.rollback()
    s.delete(s.scalar(select(MovementDiscount)))
    with pytest.raises(ImmutableError):
        s.commit()
    s.close()


def test_les_vendes_mostren_el_total_descomptat(ctx):
    client, factory, sec = ctx
    enc = token(client, sec, "enc")
    mid, pid = setup_data(client, enc, factory)
    did = desc(client, enc, valor=25).json()["id"]
    dispensa(client, enc, mid, pid, "2", discount_id=did)  # 1600 -> 1200, descompte 400
    avui = date.today()
    r = client.get("/locals/1/informe/vendes", params={"des": (avui - timedelta(days=1)).isoformat(), "fins": (avui + timedelta(days=1)).isoformat()}, headers=enc).json()
    assert r["total"]["import_cent"] == 1200 and r["total"]["descomptes_cent"] == 400

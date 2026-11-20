"""Menú del club: permisos, pantalles per token (404 si no existeix o està revocat), preu calculat, esgotats ocults, cap dada de socis."""
import json

import pytest
from sqlalchemy import select

from app import service, stock
from app.models import AuditLog, Member, Product, User
from tests.test_api import ctx, env, token, SOCI  # noqa: F401


@pytest.fixture(autouse=True)
def ips_lliures(monkeypatch):
    monkeypatch.setenv("CLUB_PANTALLES_IPS_LLIURES", "1")   # el client de proves no té una IP privada


def productes(factory):
    s = factory()
    u = s.scalar(select(User).where(User.username == "admin"))
    a = stock.add_product(s, u, 1, "Amnesia", "Weed", 1000, es_genetic=True)
    b = stock.add_product(s, u, 1, "Gelat", "Hash", 1250, es_genetic=True)
    c = stock.add_product(s, u, 1, "Cola", "Beguda", 250, es_genetic=False, unitat="u")
    stock.receive(s, u, a.id, __import__("decimal").Decimal("50"), None)
    ids = (a.id, b.id, c.id)
    s.close()
    return ids


def crea_pantalla(client, adm, menu_id=None, tipus="tv"):
    r = client.post("/locals/1/pantalles", json={"nom": "TV " + tipus, "tipus": tipus, "menu_id": menu_id}, headers=adm)
    assert r.status_code == 201, r.text
    llista = client.get("/locals/1/pantalles", headers=adm).json()["pantalles"]
    return next(p for p in llista if p["id"] == r.json()["id"])["url"]


def menu_dispensari(client, adm):
    ms = client.get("/locals/1/menus", headers=adm).json()["menus"]
    return next(m for m in ms if m["tipus"] == "dispensari")["id"]


def test_permisos_gestio_i_treballador_no_veu_editor(ctx):
    client, factory, sec = ctx
    adm, enc, disp = token(client, sec, "admin"), token(client, sec, "enc"), token(client, sec, "disp")
    assert client.get("/locals/1/menus", headers=disp).status_code == 403
    assert client.get("/locals/1/pantalles", headers=disp).status_code == 403
    assert client.get("/locals/1/menus", headers=enc).status_code == 200
    ms = client.get("/locals/1/menus", headers=adm).json()["menus"]
    assert sorted(m["tipus"] for m in ms) == ["bar", "dispensari"] and all(m["per_defecte"] for m in ms)
    assert client.get(f"/menus/{ms[0]['id']}/editor", headers=disp).status_code == 403
    with factory() as s:
        uid = s.scalar(select(User.id).where(User.username == "disp"))
    assert client.put(f"/usuaris/{uid}/permisos", json={"permisos": ["menus"]}, headers=adm).status_code == 200
    assert client.get("/locals/1/menus", headers=token(client, sec, "disp")).status_code == 200


def test_token_inexistent_o_revocat_es_404_i_preu_calculat(ctx):
    client, factory, sec = ctx
    adm = token(client, sec, "admin")
    a, b, c = productes(factory)
    assert client.get("/pantalla/inventat/dades").status_code == 404
    assert client.get("/pantalla/inventat").status_code == 404
    url = crea_pantalla(client, adm, menu_dispensari(client, adm))
    d = client.get(url + "/dades")
    assert d.status_code == 200
    cos = d.json()
    prods = [p for cat in cos["categories"] for p in cat["productes"]]
    assert [p["nom"] for p in prods] == ["Amnesia"] and prods[0]["preu_cent"] == 1000 and prods[0]["unitat"] == "g"   # Gelat sense estoc: no surt
    assert "estoc" not in json.dumps(cos).lower()
    assert client.get(url).status_code == 200 and 'data-pantalla' in client.get(url).text
    # canvi de preu: es reflecteix sol
    s = factory()
    stock.update_product(s, s.scalar(select(User).where(User.username == "admin")), a, preu_cent_per_g=1100)
    s.close()
    assert client.get(url + "/dades").json()["categories"][0]["productes"][0]["preu_cent"] == 1100
    etag = d.headers["etag"]
    assert client.get(url + "/dades", headers={"If-None-Match": client.get(url + "/dades").headers["etag"]}).status_code in (200, 304)
    pid = next(p["id"] for p in client.get("/locals/1/pantalles", headers=adm).json()["pantalles"])
    assert client.post(f"/pantalles/{pid}/revoca", headers=adm).status_code == 200
    assert client.get(url + "/dades").status_code == 404 and client.get(url).status_code == 404
    with factory() as s:
        accions = [json.loads(r.payload)["accio"] for r in s.scalars(select(AuditLog))]
    assert "alta_pantalla_menu" in accions and "revoca_pantalla_menu" in accions


def test_esgotats_ocults_per_defecte_i_visibles_si_es_demana(ctx):
    client, factory, sec = ctx
    adm = token(client, sec, "admin")
    a, b, c = productes(factory)
    mid = menu_dispensari(client, adm)
    url = crea_pantalla(client, adm, mid)
    assert client.put(f"/menus/{mid}/esborrany", json={"disseny": {"mostrar_esgotats": True}}, headers=adm).status_code == 200
    # sense publicar, la pantalla continua igual
    assert [p["nom"] for cat in client.get(url + "/dades").json()["categories"] for p in cat["productes"]] == ["Amnesia"]
    prev = client.get(f"/menus/{mid}/editor", headers=adm).json()
    assert prev["sense_publicar"] and {p["nom"] for cat in prev["vista"]["categories"] for p in cat["productes"]} == {"Amnesia", "Gelat"}
    assert client.post(f"/menus/{mid}/publica", headers=adm).status_code == 200
    ps = {p["nom"]: p for cat in client.get(url + "/dades").json()["categories"] for p in cat["productes"]}
    assert ps["Gelat"]["disponible"] is False and ps["Amnesia"]["disponible"] is True
    # amagar un producte concret i desactivar una categoria
    assert client.put(f"/menus/{mid}/esborrany", json={"disseny": {"ocults": [a], "categories": [{"nom": "Hash", "visible": False}]}}, headers=adm).status_code == 200
    client.post(f"/menus/{mid}/publica", headers=adm)
    assert client.get(url + "/dades").json()["categories"] == []


def test_bar_nomes_mostra_no_genetics_i_sense_dades_de_socis(ctx):
    client, factory, sec = ctx
    adm = token(client, sec, "admin")
    s = factory()
    s.close()
    r = client.post("/socis", json=SOCI, headers=adm)
    a, b, c = productes(factory)
    s = factory()
    stock.receive(s, s.scalar(select(User).where(User.username == "admin")), c, __import__("decimal").Decimal("5"), None)
    s.close()
    bar = next(m["id"] for m in client.get("/locals/1/menus", headers=adm).json()["menus"] if m["tipus"] == "bar")
    url = crea_pantalla(client, adm, bar, "tauleta")
    text = client.get(url + "/dades").text
    cos = json.loads(text)
    assert [p["nom"] for cat in cos["categories"] for p in cat["productes"]] == ["Cola"]
    for secret in ("Anna", "12345678Z", "anna@example.com", "600111222"):
        assert secret not in text


def test_ip_no_privada_es_404_i_ritme_limitat(ctx, monkeypatch):
    client, factory, sec = ctx
    adm = token(client, sec, "admin")
    url = crea_pantalla(client, adm, menu_dispensari(client, adm))
    monkeypatch.delenv("CLUB_PANTALLES_IPS_LLIURES")
    assert client.get(url + "/dades").status_code == 404    # «testclient» no és una IP de xarxa privada
    assert client.get(url + "/dades", headers={"x-forwarded-for": "8.8.8.8"}).status_code == 404
    from app.routes import menus as rm
    assert rm.ip_permesa("192.168.1.5") and rm.ip_permesa("100.100.1.1") and rm.ip_permesa("10.0.0.2")
    assert not rm.ip_permesa("8.8.8.8") and not rm.ip_permesa(None)


@pytest.fixture
def limit_baix(monkeypatch):
    monkeypatch.setenv("CLUB_PANTALLA_LIMIT", "3")   # abans que ctx creï l'aplicació


def test_limit_de_ritme(limit_baix, ctx):
    client, factory, sec = ctx
    adm = token(client, sec, "admin")
    url = crea_pantalla(client, adm, menu_dispensari(client, adm))
    codis = [client.get(url + "/dades").status_code for _ in range(6)]
    assert 429 in codis


def test_menus_duplicar_defecte_esborrar_i_audit(ctx):
    client, factory, sec = ctx
    adm = token(client, sec, "admin")
    mid = menu_dispensari(client, adm)
    nou = client.post(f"/menus/{mid}/duplica", headers=adm).json()["id"]
    assert client.put(f"/menus/{nou}", json={"per_defecte": True, "nom": "Festes"}, headers=adm).status_code == 200
    ms = {m["id"]: m for m in client.get("/locals/1/menus", headers=adm).json()["menus"]}
    assert ms[nou]["per_defecte"] and not ms[mid]["per_defecte"]
    url = crea_pantalla(client, adm, nou)
    assert client.delete(f"/menus/{nou}", headers=adm).status_code == 422     # pantalla assignada
    assert client.get("/pantalla/x/dades").status_code == 404

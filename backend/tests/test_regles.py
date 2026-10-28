from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app import regles, stock
from app.models import User
from tests.test_api import SOCI, ctx, env, token  # noqa: F401
from tests.test_stock import setup_data


def regla(client, h, **extra):
    body = {"nom": "Límit setmanal", "ambit": "tot", "periode": "setmana", "max_g": "5", **extra}
    return client.post("/locals/1/regles", json=body, headers=h)


def dispensa(client, h, mid, pid, g):
    return client.post("/dispensacions", json={"member_id": mid, "product_id": pid, "grams": g}, headers=h)


def test_regla_global_per_setmana_bloqueja_en_superar_el_maxim(ctx):
    client, factory, sec = ctx
    enc, admin = token(client, sec, "enc"), token(client, sec, "admin")
    mid, pid = setup_data(client, enc, factory)
    assert regla(client, admin).status_code == 201
    assert dispensa(client, enc, mid, pid, "3").status_code == 201
    r = dispensa(client, enc, mid, pid, "2.5")  # 3 + 2,5 = 5,5 > 5
    assert r.status_code == 422 and "Límit setmanal" in r.json()["detail"]
    assert dispensa(client, enc, mid, pid, "2").status_code == 201  # 3 + 2 = 5: just el màxim


def test_una_correccio_allibera_gramatge(ctx):
    client, factory, sec = ctx
    enc, admin = token(client, sec, "enc"), token(client, sec, "admin")
    mid, pid = setup_data(client, enc, factory)
    regla(client, admin)
    d = dispensa(client, enc, mid, pid, "5").json()["id"]
    assert dispensa(client, enc, mid, pid, "1").status_code == 422
    assert client.post(f"/moviments/{d}/correccio", json={"nota": "error de pes"}, headers=enc).status_code == 201
    assert dispensa(client, enc, mid, pid, "4").status_code == 201


def test_regla_per_categoria_i_per_producte(ctx):
    client, factory, sec = ctx
    enc, admin = token(client, sec, "enc"), token(client, sec, "admin")
    mid, pa = setup_data(client, enc, factory)  # «Producte A», sense categoria
    flor = client.post("/productes", json={"local_id": 1, "nom": "B", "categoria": "flor", "preu_cent_per_g": 500}, headers=enc).json()["id"]
    hash_ = client.post("/productes", json={"local_id": 1, "nom": "C", "categoria": "resina", "preu_cent_per_g": 900}, headers=enc).json()["id"]
    for p in (flor, hash_):
        client.post("/moviments/entrada", json={"product_id": p, "grams": "20"}, headers=enc)
    regla(client, admin, nom="Flor 2 g", ambit="categoria", categoria="flor", periode="dia", max_g="2")
    regla(client, admin, nom="Només C", ambit="producte", product_id=hash_, periode="dia", max_g="1")
    assert dispensa(client, enc, mid, flor, "2").status_code == 201
    assert dispensa(client, enc, mid, flor, "0.5").status_code == 422        # supera la regla de la categoria
    assert dispensa(client, enc, mid, pa, "4").status_code == 201            # una altra categoria: lliure
    assert dispensa(client, enc, mid, hash_, "1.5").status_code == 422       # supera la regla del producte
    assert dispensa(client, enc, mid, hash_, "1").status_code == 201


def test_la_regla_es_per_soci_i_es_pot_desactivar(ctx):
    client, factory, sec = ctx
    enc, admin = token(client, sec, "enc"), token(client, sec, "admin")
    mid, pid = setup_data(client, enc, factory)
    altre = client.post("/socis", json={**SOCI, "document": "87654321X", "nom": "Bernat"}, headers=enc).json()["id"]
    rid = regla(client, admin, max_g="2", periode="dia").json()["id"]
    assert dispensa(client, enc, mid, pid, "2").status_code == 201
    assert dispensa(client, enc, altre, pid, "2").status_code == 201          # cada soci té el seu compte
    assert dispensa(client, enc, mid, pid, "1").status_code == 422
    assert client.put(f"/regles/{rid}", json={"actiu": False}, headers=admin).status_code == 200
    assert dispensa(client, enc, mid, pid, "1").status_code == 201
    assert client.put(f"/regles/{rid}", json={"actiu": True, "max_g": "10"}, headers=admin).status_code == 200
    assert dispensa(client, enc, mid, pid, "1").status_code == 201


def test_finestres_de_temps_dia_setmana_mes():
    madrid = stock.TZ
    dimecres = datetime(2026, 10, 28, 15, 30, tzinfo=madrid)
    assert stock._window_start("dia", dimecres) == datetime(2026, 10, 28, tzinfo=madrid).astimezone(timezone.utc)
    assert stock._window_start("setmana", dimecres) == datetime(2026, 10, 26, tzinfo=madrid).astimezone(timezone.utc)  # dilluns
    assert stock._window_start("mes", dimecres) == datetime(2026, 10, 1, tzinfo=madrid).astimezone(timezone.utc)
    diumenge = datetime(2026, 11, 1, 10, 0, tzinfo=madrid)
    assert stock._window_start("setmana", diumenge) == datetime(2026, 10, 26, tzinfo=madrid).astimezone(timezone.utc)


def test_validacio_permisos_i_llista(ctx):
    client, factory, sec = ctx
    enc, admin, disp = token(client, sec, "enc"), token(client, sec, "admin"), token(client, sec, "disp")
    assert regla(client, enc).status_code == 403                               # només l'administrador
    for mal in [{"max_g": "0"}, {"max_g": "-1"}, {"periode": "any"}, {"ambit": "tot-ho"}, {"nom": " "}, {"ambit": "categoria"},
                {"ambit": "producte"}, {"ambit": "producte", "product_id": 9999}]:
        assert regla(client, admin, **mal).status_code == 422, mal
    assert regla(client, admin).status_code == 201
    assert regla(client, admin).status_code == 422                             # nom repetit
    assert regla(client, admin, nom="Altre").status_code == 201
    llista = client.get("/locals/1/regles", headers=enc).json()
    assert [r["nom"] for r in llista] == ["Altre", "Límit setmanal"] and llista[0]["max_g"] == "5"
    assert client.get("/locals/1/regles", headers=disp).status_code == 403
    assert client.get("/locals/2/regles", headers=enc).status_code == 403
    assert client.put("/regles/9999", json={"actiu": False}, headers=admin).status_code == 404
    assert client.put("/regles/1", json={}, headers=admin).status_code == 422


def test_les_regles_queden_a_lauditoria(ctx):
    import json
    from app.models import AuditLog
    client, factory, sec = ctx
    admin = token(client, sec, "admin")
    rid = regla(client, admin).json()["id"]
    client.put(f"/regles/{rid}", json={"actiu": False}, headers=admin)
    s = factory()
    accions = [json.loads(a.payload)["accio"] for a in s.scalars(select(AuditLog))]
    s.close()
    assert "alta_regla" in accions and "edita_regla" in accions

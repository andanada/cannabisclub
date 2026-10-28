from datetime import date, timedelta

from sqlalchemy import select

from app.models import User
from tests.test_api import SOCI, ctx, env, token  # noqa: F401


def rang(**extra):
    avui = date.today()
    return {"des": (avui - timedelta(days=1)).isoformat(), "fins": (avui + timedelta(days=1)).isoformat(), **extra}


def uid(factory, nom):
    s = factory()
    try:
        return s.scalars(select(User).where(User.username == nom)).one().id
    finally:
        s.close()


def escenari(client, factory, sec):
    """enc dispensa 2 g i fa una entrada; disp dispensa 1 g i fa dues entrades."""
    enc, disp = token(client, sec, "enc"), token(client, sec, "disp")
    pid = client.post("/productes", json={"local_id": 1, "nom": "Amnesia", "categoria": "flor", "preu_cent_per_g": 800}, headers=enc).json()["id"]
    client.post("/moviments/entrada", json={"product_id": pid, "grams": "50"}, headers=enc)
    m = client.post("/socis", json=SOCI, headers=enc).json()["id"]
    client.post("/caixa/obrir", json={"local_id": 1, "opening_cent": 0}, headers=enc)
    for h, g in ((enc, "2"), (disp, "1")):
        d = client.post("/dispensacions", json={"member_id": m, "product_id": pid, "grams": g}, headers=h).json()["id"]
        client.post("/cobraments", json={"movement_id": d, "metode": "efectiu"}, headers=h)
    client.post(f"/socis/{m}/entrada", headers=enc)
    client.post(f"/socis/{m}/entrada", headers=disp)
    client.post(f"/socis/{m}/entrada", headers=disp)
    return enc, disp


def test_vendes_per_empleat(ctx):
    client, factory, sec = ctx
    enc, disp = escenari(client, factory, sec)
    tot = client.get("/locals/1/informe/vendes", params=rang(), headers=enc).json()["total"]
    d = client.get("/locals/1/informe/vendes", params=rang(usuari=uid(factory, "disp")), headers=enc).json()["total"]
    e = client.get("/locals/1/informe/vendes", params=rang(usuari=uid(factory, "enc")), headers=enc).json()["total"]
    assert tot["import_cent"] == 2400 and d == {"grams": "1", "import_cent": 800, "dispensacions": 1, "descomptes_cent": 0}
    assert e == {"grams": "2", "import_cent": 1600, "dispensacions": 1, "descomptes_cent": 0}


def test_assistencia_i_hores_per_empleat(ctx):
    client, factory, sec = ctx
    enc, disp = escenari(client, factory, sec)
    r = client.get("/locals/1/informe/assistencia", params=rang(usuari=uid(factory, "disp")), headers=enc).json()
    assert r["total_entrades"] == 2
    assert client.get("/locals/1/informe/assistencia", params=rang(), headers=enc).json()["total_entrades"] == 3
    h = client.get("/locals/1/informe/hores", params=rang(usuari=uid(factory, "disp")), headers=enc).json()
    assert all(p["usuari"] == "disp" for p in h["persones"])


def test_caixa_per_empleat(ctx):
    client, factory, sec = ctx
    enc, disp = escenari(client, factory, sec)
    tot = client.get("/locals/1/informe", params=rang(), headers=enc).json()
    d = client.get("/locals/1/informe", params=rang(usuari=uid(factory, "disp")), headers=enc).json()
    assert tot["ingressos_cent"] == 2400 and d["ingressos_cent"] == 800


def test_el_csv_tambe_filtra_i_es_valida_lempleat(ctx):
    client, factory, sec = ctx
    enc, disp = escenari(client, factory, sec)
    csv = client.get("/locals/1/informe/vendes.csv", params=rang(usuari=uid(factory, "disp")), headers=enc).text
    assert "Amnesia,flor,1,800,1" in csv.replace("\r", "")
    admin = token(client, sec, "admin")
    assert client.get("/locals/1/informe/vendes", params=rang(usuari=9999), headers=enc).status_code == 422
    # un usuari que no treballa en aquest local no es pot triar
    assert client.post("/usuaris", json={"username": "extern", "password": "una-contrasenya-llarga-1", "role": "dispensador", "local_ids": [2]}, headers=admin).status_code == 201
    assert client.get("/locals/1/informe/vendes", params=rang(usuari=uid(factory, "extern")), headers=enc).status_code == 422


def test_llista_de_personal_del_local(ctx):
    client, factory, sec = ctx
    enc, disp = token(client, sec, "enc"), token(client, sec, "disp")
    r = client.get("/locals/1/personal", headers=enc).json()
    assert {u["username"] for u in r} == {"enc", "disp", "admin"} and all(set(u) == {"id", "username", "role"} for u in r)
    assert client.get("/locals/1/personal", headers=disp).status_code == 403
    assert client.get("/locals/2/personal", headers=enc).status_code == 403

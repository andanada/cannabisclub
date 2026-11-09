from datetime import date, timedelta

from tests.test_api import SOCI, ctx, env, token  # noqa: F401
from tests.test_stock import setup_data


def rang(**extra):
    avui = date.today()
    return {"des": (avui - timedelta(days=40)).isoformat(), "fins": (avui + timedelta(days=1)).isoformat(), **extra}


def nou_soci(client, h, document, naixement, nom="Soci"):
    return client.post("/socis", json={**SOCI, "document": document, "naixement": naixement, "nom": nom}, headers=h).json()["id"]


def test_evolucio_compta_altes_baixes_i_quotes_per_mes(ctx):
    client, factory, sec = ctx
    enc = token(client, sec, "enc")
    a = nou_soci(client, enc, "12345678Z", "1990-01-01")
    b = nou_soci(client, enc, "87654321X", "1985-05-05", "Bernat")
    client.post(f"/socis/{b}/estat", json={"estat": "baixa"}, headers=enc)
    client.post("/caixa/obrir", json={"local_id": 1, "opening_cent": 0}, headers=enc)
    for _ in range(2):  # dues quotes del mateix soci: una de nova i una de renovació
        client.post(f"/socis/{a}/quotes", json={"import_cent": 2000, "metode": "efectiu", "mesos": 1}, headers=enc)
    r = client.get("/locals/1/informe/evolucio", params=rang(), headers=enc).json()
    mes = date.today().strftime("%Y-%m")
    fila = next(m for m in r["mesos"] if m["mes"] == mes)
    assert fila["altes"] == 2 and fila["baixes"] == 1 and fila["quotes_noves"] == 1 and fila["renovacions"] == 1
    assert r["total"] == {"altes": 2, "baixes": 1, "quotes_noves": 1, "renovacions": 1}
    assert r["estat_actual"] == {"actiu": 1, "suspes": 0, "baixa": 1}


def test_evolucio_csv_i_permisos(ctx):
    client, factory, sec = ctx
    enc, disp = token(client, sec, "enc"), token(client, sec, "disp")
    nou_soci(client, enc, "12345678Z", "1990-01-01")
    csv = client.get("/locals/1/informe/evolucio.csv", params=rang(), headers=enc).text.replace("\r", "")
    assert csv.splitlines()[0] == "mes,altes,baixes,quotes_noves,renovacions" and date.today().strftime("%Y-%m") + ",1,0,0,0" in csv
    assert client.get("/locals/1/informe/evolucio", params=rang(), headers=disp).status_code == 403
    assert client.get("/locals/2/informe/evolucio", params=rang(), headers=enc).status_code == 403
    assert client.get("/locals/1/informe/evolucio", params={"des": "2026-02-01", "fins": "2026-01-01"}, headers=enc).status_code == 422


def test_demografia_per_franges_dedat_sense_dades_personals(ctx):
    """Amb menys de k=5 socis res no es publica: ni franges, ni total, ni edat mitjana."""
    client, factory, sec = ctx
    enc = token(client, sec, "enc")
    avui = date.today()
    nou_soci(client, enc, "12345678Z", date(avui.year - 20, 1, 1).isoformat())           # 20 anys
    nou_soci(client, enc, "87654321X", date(avui.year - 30, 1, 1).isoformat(), "Berta")       # 30
    nou_soci(client, enc, "11111111H", date(avui.year - 31, 1, 1).isoformat(), "Carla")       # 31
    r = client.get("/locals/1/informe/demografia", headers=enc).json()
    assert r["total"] is None and r["edat_mitjana"] is None and r["k_minim"] == 5
    assert all(f["socis"] in (None, 0) for f in r["franges"]) and r["franges"][0]["suprimit"] is True
    assert "nom" not in str(r) and "Soci" not in str(r)
    csv = client.get("/locals/1/informe/demografia.csv", headers=enc).text
    assert csv.splitlines()[0] == "franja,socis" and "18-24,<5" in csv and "35-44,0" in csv


def test_anonimitzacio_k5_i_supressio_complementaria(monkeypatch):
    from app.informes_socis import anonimitza
    def r(*n):
        fr = [{"franja": str(i), "socis": x} for i, x in enumerate(n)]
        return {"total": sum(n), "edat_mitjana": 30.0, "franges": fr}
    a = anonimitza(r(2, 10, 7, 20, 0, 0))   # una cel·la petita: se'n suprimeix també la més petita restant
    assert [f["socis"] for f in a["franges"]] == [None, 10, None, 20, 0, 0] and a["total"] == 39
    b = anonimitza(r(6, 10, 7, 20, 0, 0))   # cap cel·la petita: es publica tot
    assert [f["socis"] for f in b["franges"]] == [6, 10, 7, 20, 0, 0]
    monkeypatch.setenv("CLUB_K_ANONIMAT", "3")  # no es pot baixar de 5
    assert anonimitza(r(4, 10, 7, 20, 0, 0))["franges"][0]["socis"] is None
    monkeypatch.setenv("CLUB_K_ANONIMAT", "8")
    assert anonimitza(r(6, 10, 7, 20, 0, 0))["k_minim"] == 8


def test_demografia_amb_prous_socis_publica_les_franges(ctx):
    client, factory, sec = ctx
    enc = token(client, sec, "enc")
    avui = date.today()
    docs = ["12345678Z", "87654321X", "11111111H", "22222222J", "33333333P", "44444444A"]
    for i, d in enumerate(docs):
        nou_soci(client, enc, d, date(avui.year - 30, 1, 1).isoformat(), f"Soci {i} Prova")
    r = client.get("/locals/1/informe/demografia", headers=enc).json()
    assert r["total"] == 6 and {f["franja"]: f["socis"] for f in r["franges"]}["25-34"] == 6


def test_historial_de_consum_del_soci(ctx):
    client, factory, sec = ctx
    enc, disp = token(client, sec, "enc"), token(client, sec, "disp")
    mid, pid = setup_data(client, enc, factory)
    d = client.post("/dispensacions", json={"member_id": mid, "product_id": pid, "grams": "2"}, headers=enc).json()["id"]
    client.post("/dispensacions", json={"member_id": mid, "product_id": pid, "grams": "1"}, headers=enc)
    client.post(f"/moviments/{d}/correccio", json={"nota": "error de pes"}, headers=enc)
    r = client.get(f"/socis/{mid}/consum", params=rang(), headers=enc).json()
    assert r["total"] == {"grams": "1", "import_cent": 800, "dispensacions": 1}                  # la corregida no compta
    assert [x["producte"] for x in r["productes"]] == ["Producte A"] and r["productes"][0]["grams"] == "1"
    assert len(r["dispensacions"]) == 2 and any(x["corregida"] for x in r["dispensacions"])
    assert client.get(f"/socis/{mid}/consum", params=rang(), headers=disp).status_code == 403
    assert client.get("/socis/9999/consum", params=rang(), headers=enc).status_code == 404

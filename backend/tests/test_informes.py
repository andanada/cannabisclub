import csv
import io
import json
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app import personal
from app.models import AuditLog, User
from tests.test_api import SOCI, ctx, env, token  # noqa: F401



def preparar(client, factory, sec):
    """Dos productes, dos socis i dispensacions: A 2 g + 1 g (una de les quals es corregeix), B 3 g."""
    enc = token(client, sec, "enc")
    a = client.post("/productes", json={"local_id": 1, "nom": "Amnesia", "categoria": "flor", "preu_cent_per_g": 800}, headers=enc).json()["id"]
    b = client.post("/productes", json={"local_id": 1, "nom": "Hash", "categoria": "resina", "preu_cent_per_g": 1200}, headers=enc).json()["id"]
    for pid, g in ((a, "50"), (b, "20")):
        client.post("/moviments/entrada", json={"product_id": pid, "grams": g}, headers=enc)
    m1 = client.post("/socis", json=SOCI, headers=enc).json()["id"]
    m2 = client.post("/socis", json={**SOCI, "document": "87654321X", "nom": "Bernat"}, headers=enc).json()["id"]
    d1 = client.post("/dispensacions", json={"member_id": m1, "product_id": a, "grams": "2"}, headers=enc).json()["id"]
    d2 = client.post("/dispensacions", json={"member_id": m2, "product_id": a, "grams": "1"}, headers=enc).json()["id"]
    client.post("/dispensacions", json={"member_id": m1, "product_id": b, "grams": "3"}, headers=enc)
    assert client.post(f"/moviments/{d2}/correccio", json={"nota": "error de pes"}, headers=enc).status_code == 201
    client.post(f"/socis/{m1}/entrada", headers=enc)
    client.post(f"/socis/{m1}/entrada", headers=enc)
    client.post(f"/socis/{m2}/entrada", headers=enc)
    return enc, a, b, m1, m2, d1


def rang():
    avui = date.today()
    return {"des": (avui - timedelta(days=1)).isoformat(), "fins": (avui + timedelta(days=1)).isoformat()}


def files(text):
    return list(csv.reader(io.StringIO(text)))


def test_vendes_per_producte_resten_les_correccions(ctx):
    client, factory, sec = ctx
    enc, *_ = preparar(client, factory, sec)
    r = client.get("/locals/1/informe/vendes", params=rang(), headers=enc).json()
    per = {p["nom"]: p for p in r["productes"]}
    assert per["Amnesia"]["grams"] == "2" and per["Amnesia"]["import_cent"] == 1600 and per["Amnesia"]["dispensacions"] == 1  # 2 g; la d'1 g està corregida
    assert per["Hash"]["grams"] == "3" and per["Hash"]["import_cent"] == 3600
    assert r["total"] == {"grams": "5", "import_cent": 5200, "dispensacions": 2}
    assert {c["categoria"]: c["import_cent"] for c in r["categories"]} == {"flor": 1600, "resina": 3600}


def test_vendes_fora_del_rang_i_rang_invalid(ctx):
    client, factory, sec = ctx
    enc, *_ = preparar(client, factory, sec)
    passat = {"des": "2020-01-01", "fins": "2020-01-31"}
    r = client.get("/locals/1/informe/vendes", params=passat, headers=enc).json()
    assert r["productes"] == [] and r["total"]["import_cent"] == 0
    assert client.get("/locals/1/informe/vendes", params={"des": "2026-02-01", "fins": "2026-01-01"}, headers=enc).status_code == 422


def test_estoc_valorat(ctx):
    client, factory, sec = ctx
    enc, a, b, *_ = preparar(client, factory, sec)
    r = client.get("/locals/1/informe/estoc", headers=enc).json()
    per = {p["nom"]: p for p in r["productes"]}
    # Amnesia: 50 - 2 - 1 + 1 (correcció) = 48 g a 8 €/g; Hash: 20 - 3 = 17 g a 12 €/g
    assert per["Amnesia"]["estoc_g"] == "48" and per["Amnesia"]["valor_cent"] == 38400
    assert per["Hash"]["estoc_g"] == "17" and per["Hash"]["valor_cent"] == 20400
    assert r["total_cent"] == 58800 and r["total_g"] == "65"


def test_estoc_valorat_ignora_productes_inactius(ctx):
    client, factory, sec = ctx
    enc = token(client, sec, "enc")
    pid = client.post("/productes", json={"local_id": 1, "nom": "Vell", "preu_cent_per_g": 100}, headers=enc).json()["id"]
    client.patch(f"/productes/{pid}", json={"actiu": False}, headers=enc)
    assert client.get("/locals/1/informe/estoc", headers=enc).json()["productes"] == []


def test_assistencia_per_dia(ctx):
    client, factory, sec = ctx
    enc, *_ = preparar(client, factory, sec)
    r = client.get("/locals/1/informe/assistencia", params=rang(), headers=enc).json()
    assert r["total_entrades"] == 3 and r["socis_diferents"] == 2
    assert len(r["per_dia"]) == 1  # les tres entrades són d'avui
    assert r["per_dia"][0]["entrades"] == 3 and r["per_dia"][0]["socis"] == 2


def test_hores_amb_nom_dusuari(ctx):
    client, factory, sec = ctx
    s = factory()
    u = s.scalars(select(User).where(User.username == "disp")).one()
    base = datetime.now(timezone.utc).replace(hour=8, minute=0, second=0, microsecond=0)
    for dt, t in [(0, "entrada"), (4 * 3600, "pausa_inici"), (4 * 3600 + 1800, "pausa_fi"), (9 * 3600, "sortida")]:
        personal.clock(s, u, 1, t, now=base + timedelta(seconds=dt))
    s.close()
    enc = token(client, sec, "enc")
    r = client.get("/locals/1/informe/hores", params=rang(), headers=enc).json()
    fila = [x for x in r["persones"] if x["usuari"] == "disp"][0]
    assert fila["hores"] == 8.5 and fila["torns"] == 1 and fila["torn_obert"] is False
    assert r["total_hores"] == 8.5


def test_csv_de_cada_informe_i_auditoria(ctx):
    client, factory, sec = ctx
    enc, *_ = preparar(client, factory, sec)
    for ruta, capcalera in [("vendes", "producte"), ("estoc", "producte"), ("assistencia", "dia"), ("hores", "usuari")]:
        r = client.get(f"/locals/1/informe/{ruta}.csv", params=rang(), headers=enc)
        assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
        assert files(r.text)[0][0] == capcalera, ruta
    v = files(client.get("/locals/1/informe/vendes.csv", params=rang(), headers=enc).text)
    assert ["Amnesia", "flor", "2", "1600", "1"] in [f[:5] for f in v]
    s = factory()
    accions = [json.loads(a.payload) for a in s.scalars(select(AuditLog))]
    s.close()
    assert any(a["accio"] == "exportar_csv" and a.get("informe") == "vendes" for a in accions)


def test_csv_neutralitza_formules_de_full_de_calcul(ctx):
    client, factory, sec = ctx
    enc = token(client, sec, "enc")
    pid = client.post("/productes", json={"local_id": 1, "nom": "=HYPERLINK(\"http://x\")", "categoria": "+cmd", "preu_cent_per_g": 100}, headers=enc).json()["id"]
    client.post("/moviments/entrada", json={"product_id": pid, "grams": "1"}, headers=enc)
    f = files(client.get("/locals/1/informe/estoc.csv", headers=enc).text)
    assert f[1][0].startswith("'=") and f[1][1].startswith("'+")


def test_permisos_i_aillament_dels_informes(ctx):
    client, factory, sec = ctx
    enc, disp = token(client, sec, "enc"), token(client, sec, "disp")
    for ruta in ["vendes", "estoc", "assistencia", "hores", "vendes.csv", "estoc.csv"]:
        assert client.get(f"/locals/1/informe/{ruta}", params=rang(), headers=disp).status_code == 403, ruta
        assert client.get(f"/locals/2/informe/{ruta}", params=rang(), headers=enc).status_code == 403, ruta
        assert client.get(f"/locals/1/informe/{ruta}", params=rang()).status_code == 401, ruta

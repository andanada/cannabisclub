import json

from sqlalchemy import select

from app.models import AuditLog, StockMovement
from tests.test_api import ctx, env, token  # noqa: F401
from tests.test_stock import setup_data


def obre(client, h, **extra):
    return client.post("/locals/1/inventaris", json=extra, headers=h)


def compta(client, h, sid, pid, g):
    return client.put(f"/inventaris/{sid}/linies/{pid}", json={"grams": g}, headers=h)


def prep(client, factory, sec):
    enc = token(client, sec, "enc")
    mid, pa = setup_data(client, enc, factory)  # «Producte A» amb 10 g
    pb = client.post("/productes", json={"local_id": 1, "nom": "B", "categoria": "flor", "preu_cent_per_g": 500}, headers=enc).json()["id"]
    client.post("/moviments/entrada", json={"product_id": pb, "grams": "20"}, headers=enc)
    return enc, pa, pb


def test_sessio_mostra_lestoc_esperat_i_les_diferencies(ctx):
    client, factory, sec = ctx
    enc, pa, pb = prep(client, factory, sec)
    sid = obre(client, enc, nom="Setembre").json()["id"]
    d = client.get(f"/inventaris/{sid}", headers=enc).json()
    assert d["estat"] == "obert" and d["nom"] == "Setembre"
    linies = {l["product_id"]: l for l in d["linies"]}
    assert linies[pa]["esperat_g"] == "10" and linies[pa]["comptat_g"] is None and linies[pa]["diferencia_g"] is None
    assert compta(client, enc, sid, pa, "9.5").status_code == 200
    assert compta(client, enc, sid, pa, "9.25").status_code == 200  # es pot tornar a comptar
    linies = {l["product_id"]: l for l in client.get(f"/inventaris/{sid}", headers=enc).json()["linies"]}
    assert linies[pa]["comptat_g"] == "9.25" and linies[pa]["diferencia_g"] == "-0.75"
    assert d["total"] == 2 and client.get(f"/inventaris/{sid}", headers=enc).json()["comptats"] == 1


def test_tancar_aplica_nomes_els_productes_comptats_amb_diferencia(ctx):
    client, factory, sec = ctx
    enc, pa, pb = prep(client, factory, sec)
    sid = obre(client, enc).json()["id"]
    compta(client, enc, sid, pa, "9")      # -1 g
    compta(client, enc, sid, pb, "20")     # igual: sense ajust
    r = client.post(f"/inventaris/{sid}/tancar", headers=enc)
    assert r.status_code == 200 and r.json() == {"ajustos": 1, "sense_canvis": 1, "pendents": 0}
    s = factory()
    ajusts = list(s.scalars(select(StockMovement).where(StockMovement.tipus == "ajust")))
    accions = [json.loads(a.payload)["accio"] for a in s.scalars(select(AuditLog))]
    s.close()
    assert len(ajusts) == 1 and ajusts[0].delta_mg == -1000 and ajusts[0].product_id == pa and f"#{sid}" in ajusts[0].nota
    assert "tanca_inventari" in accions
    assert client.get(f"/inventaris/{sid}", headers=enc).json()["estat"] == "tancat"
    # una sessió tancada ja no es pot tocar
    assert compta(client, enc, sid, pa, "5").status_code == 422
    assert client.post(f"/inventaris/{sid}/tancar", headers=enc).status_code == 422


def test_tancar_ajusta_a_lo_comptat_encara_que_lestoc_hagi_canviat(ctx):
    client, factory, sec = ctx
    enc, pa, pb = prep(client, factory, sec)
    sid = obre(client, enc).json()["id"]
    compta(client, enc, sid, pb, "18")
    client.post("/moviments/merma", json={"product_id": pb, "grams": "1", "nota": "pols"}, headers=enc)  # 20 -> 19 durant el recompte
    assert client.post(f"/inventaris/{sid}/tancar", headers=enc).json()["ajustos"] == 1
    s = factory()
    aj = s.scalars(select(StockMovement).where(StockMovement.tipus == "ajust")).one()
    s.close()
    assert aj.delta_mg == -1000  # 19 -> 18


def test_una_sola_sessio_oberta_i_cancellar(ctx):
    client, factory, sec = ctx
    enc, pa, pb = prep(client, factory, sec)
    sid = obre(client, enc).json()["id"]
    assert obre(client, enc).status_code == 422
    compta(client, enc, sid, pa, "1")
    assert client.post(f"/inventaris/{sid}/cancelar", headers=enc).status_code == 200
    s = factory()
    assert s.scalars(select(StockMovement).where(StockMovement.tipus == "ajust")).first() is None  # cancel·lar no toca l'estoc
    s.close()
    assert client.get(f"/inventaris/{sid}", headers=enc).json()["estat"] == "cancel·lat"
    assert obre(client, enc).status_code == 201                                  # ja se'n pot obrir una altra
    llista = client.get("/locals/1/inventaris", headers=enc).json()
    assert [x["estat"] for x in llista] == ["obert", "cancel·lat"]


def test_validacio_permisos_i_aillament(ctx):
    client, factory, sec = ctx
    enc, pa, pb = prep(client, factory, sec)
    disp = token(client, sec, "disp")
    assert obre(client, disp).status_code == 403
    assert client.get("/locals/1/inventaris", headers=disp).status_code == 403
    assert client.post("/locals/2/inventaris", json={}, headers=enc).status_code == 403
    sid = obre(client, enc).json()["id"]
    for g in ["-1", "abc", "0.0001", "100000000"]:
        assert compta(client, enc, sid, pa, g).status_code == 422, g
    assert compta(client, enc, sid, 9999, "1").status_code == 422
    assert compta(client, enc, sid, pa, "0").status_code == 200                  # zero és un recompte vàlid
    assert client.get("/inventaris/9999", headers=enc).status_code == 404
    assert client.get(f"/inventaris/{sid}", headers=disp).status_code == 403
    assert client.post(f"/inventaris/{sid}/tancar", headers=disp).status_code == 403

"""Inventaris: dispensari (amb tara), magatzem i no genètics; control complet o d'un sol producte; es guarda sense tocar l'estoc
i la gerència consulta els resultats i, si vol, ajusta."""
import json

from sqlalchemy import select

from app.models import AuditLog, StockMovement
from tests.test_api import ctx, env, token  # noqa: F401
from tests.test_stock import setup_data


def obre(client, h, **extra):
    return client.post("/locals/1/inventaris", json=extra, headers=h)


def compta(client, h, sid, pid, g, nota=None):
    return client.put(f"/inventaris/{sid}/linies/{pid}", json={"grams": g, **({"nota": nota} if nota else {})}, headers=h)


def prep(client, factory, sec):
    enc = token(client, sec, "enc")
    mid, pa = setup_data(client, enc, factory)  # «Producte A» genètic amb 10 g
    pb = client.post("/productes", json={"local_id": 1, "nom": "B", "categoria": "flor", "preu_cent_per_g": 500, "es_genetic": True}, headers=enc).json()["id"]
    client.post("/moviments/entrada", json={"product_id": pb, "grams": "20"}, headers=enc)
    return enc, pa, pb


def test_sessio_mostra_lestoc_esperat_i_les_diferencies(ctx):
    client, factory, sec = ctx
    enc, pa, pb = prep(client, factory, sec)
    sid = obre(client, enc, nom="Setembre").json()["id"]
    d = client.get(f"/inventaris/{sid}", headers=enc).json()
    assert d["estat"] == "obert" and d["nom"] == "Setembre" and d["tipus"] == "dispensari" and d["control"] == "complet"
    linies = {l["product_id"]: l for l in d["linies"]}
    assert linies[pa]["esperat_g"] == "10" and linies[pa]["comptat_g"] is None and linies[pa]["diferencia_g"] is None
    r = compta(client, enc, sid, pa, "9.5")
    assert r.status_code == 200 and r.json() == {"comptat_g": "9.5", "esperat_g": "10", "diferencia_g": "-0.5", "coincideix": False}
    assert compta(client, enc, sid, pa, "10").json()["coincideix"] is True  # es pot tornar a pesar
    compta(client, enc, sid, pa, "9.25", "m'ha caigut una mica")
    linies = {l["product_id"]: l for l in client.get(f"/inventaris/{sid}", headers=enc).json()["linies"]}
    assert linies[pa]["comptat_g"] == "9.25" and linies[pa]["diferencia_g"] == "-0.75" and linies[pa]["nota"] == "m'ha caigut una mica"
    assert d["total"] == 2 and client.get(f"/inventaris/{sid}", headers=enc).json()["comptats"] == 1


def test_la_tara_del_pot_es_resta_del_pes_al_dispensari(ctx):
    client, factory, sec = ctx
    enc, pa, pb = prep(client, factory, sec)
    assert client.patch(f"/productes/{pa}", json={"tara_g": "120"}, headers=enc).status_code == 200
    sid = obre(client, enc).json()["id"]
    linia = {l["product_id"]: l for l in client.get(f"/inventaris/{sid}", headers=enc).json()["linies"]}[pa]
    assert linia["tara_g"] == "120"
    assert compta(client, enc, sid, pa, "100").status_code == 422          # menys que el pot buit
    r = compta(client, enc, sid, pa, "130")                                 # 130 - 120 = 10 g: coincideix
    assert r.json() == {"comptat_g": "10", "esperat_g": "10", "diferencia_g": "0", "coincideix": True}
    # al magatzem no hi ha tara
    assert client.post(f"/inventaris/{sid}/cancelar", headers=enc).status_code == 200


def test_guardar_no_toca_l_estoc_i_nomes_la_gerencia_veu_els_resultats(ctx):
    client, factory, sec = ctx
    enc, pa, pb = prep(client, factory, sec)
    assert client.put("/locals/1/config", json={"perdua_maxima_mg": 500}, headers=token(client, sec, "admin")).status_code == 200
    sid = obre(client, enc).json()["id"]
    assert client.post(f"/inventaris/{sid}/guardar", headers=enc).status_code == 422   # encara no s'ha pesat res
    compta(client, enc, sid, pa, "9", "falta un gram")   # -1 g: per sobre dels 0,5 g
    compta(client, enc, sid, pb, "20")                   # igual
    r = client.post(f"/inventaris/{sid}/guardar", headers=enc)
    assert r.status_code == 200 and r.json() == {"comptats": 2, "pendents": 0, "diferencies": 1, "alertes": [{"producte": "Producte A", "diferencia_mg": -1000}]}
    s = factory()
    assert s.scalars(select(StockMovement).where(StockMovement.tipus == "ajust")).first() is None   # guardar no ajusta
    accions = [json.loads(a.payload)["accio"] for a in s.scalars(select(AuditLog))]
    s.close()
    assert "guarda_inventari" in accions
    assert client.get(f"/inventaris/{sid}", headers=enc).json()["estat"] == "tancat"
    assert compta(client, enc, sid, pa, "5").status_code == 422        # un inventari guardat ja no es toca
    # resultats: només amb accés complet; la línia amb diferència gran porta l'avís
    disp = token(client, sec, "disp")
    client.post("/auth/rol-dia", json={"rol": "dispensari"}, headers=disp)
    assert client.get("/locals/1/inventaris/resultats", headers=disp).status_code == 403
    res = client.get("/locals/1/inventaris/resultats", headers=enc).json()
    assert len(res) == 1 and res[0]["alertes"] == 1 and res[0]["ajustat"] is False
    linies = {l["producte"]: l for l in res[0]["linies"]}
    assert linies["Producte A"]["alerta"] is True and linies["Producte A"]["nota"] == "falta un gram" and linies["B"]["alerta"] is False


def test_ajustar_deixa_l_estoc_com_s_ha_comptat_una_sola_vegada(ctx):
    client, factory, sec = ctx
    enc, pa, pb = prep(client, factory, sec)
    sid = obre(client, enc).json()["id"]
    compta(client, enc, sid, pa, "9")      # -1 g
    compta(client, enc, sid, pb, "20")     # igual: sense ajust
    assert client.post(f"/inventaris/{sid}/ajustar", headers=enc).status_code == 422   # primer cal guardar
    client.post(f"/inventaris/{sid}/guardar", headers=enc)
    r = client.post(f"/inventaris/{sid}/ajustar", headers=enc)
    assert r.status_code == 200 and r.json() == {"ajustos": 1}
    s = factory()
    ajusts = list(s.scalars(select(StockMovement).where(StockMovement.tipus == "ajust")))
    s.close()
    assert len(ajusts) == 1 and ajusts[0].delta_mg == -1000 and ajusts[0].product_id == pa and f"#{sid}" in ajusts[0].nota
    assert client.post(f"/inventaris/{sid}/ajustar", headers=enc).status_code == 422   # ja ajustat
    estocs = {p["nom"]: p["estoc_g"] for p in client.get("/locals/1/estoc", headers=enc).json()}
    assert estocs["Producte A"] == "9"


def test_ajustar_no_esborra_els_moviments_posteriors_ni_deixa_estoc_negatiu(ctx):
    """L'ajust és comptat - teòric del moment del recompte: la merma feta després es conserva i l'estoc mai queda negatiu."""
    client, factory, sec = ctx
    enc, pa, pb = prep(client, factory, sec)
    sid = obre(client, enc).json()["id"]
    compta(client, enc, sid, pb, "18")  # teòric 20 -> ajust -2
    client.post("/moviments/merma", json={"product_id": pb, "grams": "1", "nota": "pols"}, headers=enc)
    client.post(f"/inventaris/{sid}/guardar", headers=enc)
    assert client.post(f"/inventaris/{sid}/ajustar", headers=enc).json()["ajustos"] == 1
    estocs = {p["nom"]: p["estoc_g"] for p in client.get("/locals/1/estoc", headers=enc).json()}
    assert estocs["B"] == "17"  # 20 - 2 (recompte) - 1 (merma posterior)
    sid2 = obre(client, enc).json()["id"]
    compta(client, enc, sid2, pb, "2")  # teòric 17 -> -15
    client.post("/moviments/merma", json={"product_id": pb, "grams": "16", "nota": "pols"}, headers=enc)  # queda 1
    client.post(f"/inventaris/{sid2}/guardar", headers=enc)
    assert client.post(f"/inventaris/{sid2}/ajustar", headers=enc).status_code == 200
    assert {p["nom"]: p["estoc_g"] for p in client.get("/locals/1/estoc", headers=enc).json()}["B"] == "0"


def test_magatzem_i_no_genetics_i_control_d_un_sol_producte(ctx):
    client, factory, sec = ctx
    enc, pa, pb = prep(client, factory, sec)
    ex = client.get("/locals/1/existencies", headers=enc).json()          # crea el magatzem únic
    mag = ex["magatzem_id"]
    assert client.post("/moviments/traspas", json={"product_id": pa, "de": None, "a": mag, "grams": "4"}, headers=enc).status_code == 201
    # inventari del magatzem: només genètics, amb el que hi ha al magatzem
    sid = obre(client, enc, tipus="magatzem").json()["id"]
    d = client.get(f"/inventaris/{sid}", headers=enc).json()
    assert {l["product_id"]: l["esperat_g"] for l in d["linies"]} == {pa: "4", pb: "0"}
    assert compta(client, enc, sid, pa, "3").json()["diferencia_g"] == "-1"
    client.post(f"/inventaris/{sid}/guardar", headers=enc)
    client.post(f"/inventaris/{sid}/ajustar", headers=enc)
    ex = {p["id"]: p for p in client.get("/locals/1/existencies", headers=enc).json()["productes"]}
    assert ex[pa]["magatzem_g"] == "3" and ex[pa]["dispensari_g"] == "6"       # l'ajust va al magatzem, no al dispensari
    # control d'un sol producte
    sid = obre(client, enc, control="producte", product_id=pa).json()["id"]
    assert [l["product_id"] for l in client.get(f"/inventaris/{sid}", headers=enc).json()["linies"]] == [pa]
    assert compta(client, enc, sid, pb, "1").status_code == 422               # B no és d'aquest control
    client.post(f"/inventaris/{sid}/cancelar", headers=enc)
    assert obre(client, enc, control="producte").status_code == 422           # falta el producte
    # no genètics: per unitats, a tot el local
    beguda = client.post("/productes", json={"local_id": 1, "nom": "Aigua", "preu_cent_per_g": 200, "es_genetic": False, "unitat": "u", "categoria": "Beguda", "estricte": True}, headers=enc).json()["id"]
    client.post("/moviments/entrada", json={"product_id": beguda, "grams": "12"}, headers=enc)
    sid = obre(client, enc, tipus="no_genetiques").json()["id"]
    assert [(l["nom"], l["esperat_g"]) for l in client.get(f"/inventaris/{sid}", headers=enc).json()["linies"]] == [("Aigua", "12")]


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
    client.post("/auth/rol-dia", json={"rol": "recepcio"}, headers=disp)
    assert obre(client, disp).status_code == 403                                 # recepció no fa inventaris
    assert client.get("/locals/1/inventaris", headers=disp).status_code == 403
    client.post("/auth/rol-dia", json={"rol": "dispensari"}, headers=disp)
    assert obre(client, disp).status_code == 201                                 # el dispensari sí
    assert obre(client, enc).status_code == 422                                  # ja n'hi ha un d'obert (el del dispensari)
    assert client.post("/locals/2/inventaris", json={}, headers=enc).status_code == 403
    assert obre(client, enc, tipus="inventat").status_code == 422
    sid = client.get("/locals/1/inventaris", headers=enc).json()[0]["id"]
    for g in ["-1", "abc", "0.0001", "100000000"]:
        assert compta(client, enc, sid, pa, g).status_code == 422, g

"""Mòdul 6 (preu de compra a cada entrada) i 9.4 (despeses automàtiques pendents de revisió, despeses de caixa a Gastos)."""
from datetime import date

from tests.test_api import ctx, env, token  # noqa: F401

AVUI = date.today().isoformat()
RANG = {"des": AVUI, "fins": AVUI}


def _prod(client, h, nom="Fulla", genetic=False, **extra):
    return client.post("/productes", json={"local_id": 1, "nom": nom, "preu_cent_per_g": 800, "es_genetic": genetic, **extra}, headers=h).json()["id"]


def _entrada(client, h, pid, grams="10", cost=None):
    body = {"product_id": pid, "grams": grams}
    if cost is not None:
        body["cost_cent"] = cost
    return client.post("/moviments/entrada", json=body, headers=h)


def test_cada_entrada_guarda_el_seu_preu_i_el_producte_no_en_depen(ctx):
    client, _, sec = ctx
    enc = token(client, sec, "enc")
    pid = _prod(client, enc, preu_entrada_cent=300)
    assert _entrada(client, enc, pid, "10", 3500).status_code == 201
    assert _entrada(client, enc, pid, "5", 2000).status_code == 201
    assert _entrada(client, enc, pid, "1").status_code == 201   # sense preu: cap despesa
    mov = client.get("/locals/1/moviments", params=RANG, headers=enc).json()
    costos = sorted(m["cost_cent"] for m in mov if m["tipus"] == "entrada" and m["cost_cent"])
    assert costos == [2000, 3500]
    assert client.get(f"/productes/{pid}/moviments", headers=enc).json()[0]["cost_cent"] is None
    assert _entrada(client, enc, pid, "1", -5).status_code == 422


def test_entrada_amb_preu_crea_la_despesa_pendent_de_revisio(ctx):
    client, _, sec = ctx
    enc = token(client, sec, "enc")
    pid = _prod(client, enc, "Sativa", genetic=True)
    assert _entrada(client, enc, pid, "10", 4000).status_code == 201
    _entrada(client, enc, pid, "2")   # sense preu: no en crea
    pend = client.get("/locals/1/gastos/pendents", headers=enc).json()
    assert len(pend) == 1 and pend[0]["import_cent"] == 4000 and pend[0]["producte"] == "Sativa"
    llista = client.get("/locals/1/gastos", params=RANG, headers=enc).json()
    assert len(llista) == 1 and llista[0]["categoria"] == "Proveïdors" and llista[0]["tipus"] == "Compres"
    assert llista[0]["estat"] == "pendent" and llista[0]["origen"] == "estoc"


def test_un_dispensador_no_veu_ni_revisa_les_despeses_pendents(ctx):
    client, _, sec = ctx
    enc, disp = token(client, sec, "enc"), token(client, sec, "disp")
    pid = _prod(client, enc)
    assert _entrada(client, enc, pid, "3", 900).status_code == 201
    gid = client.get("/locals/1/gastos/pendents", headers=enc).json()[0]["id"]
    assert client.post(f"/gastos/{gid}/revisio", json={"accio": "confirma"}, headers=disp).status_code == 403
    assert client.get("/locals/1/gastos/pendents", headers=disp).status_code == 403
    assert len(client.get("/locals/1/gastos/pendents", headers=enc).json()) == 1


def test_confirmar_treu_la_despesa_de_pendents_i_no_es_repeteix(ctx):
    client, _, sec = ctx
    enc = token(client, sec, "enc")
    pid = _prod(client, enc)
    _entrada(client, enc, pid, "10", 4000)
    gid = client.get("/locals/1/gastos/pendents", headers=enc).json()[0]["id"]
    assert client.post(f"/gastos/{gid}/revisio", json={"accio": "confirma", "comentari": "d'acord"}, headers=enc).status_code == 201
    assert client.get("/locals/1/gastos/pendents", headers=enc).json() == []
    assert client.post(f"/gastos/{gid}/revisio", json={"accio": "confirma"}, headers=enc).status_code == 422
    l = client.get("/locals/1/gastos", params=RANG, headers=enc).json()
    assert l[0]["estat"] == "confirmada"
    assert client.get(f"/gastos/{gid}/revisions", headers=enc).json()[0]["comentari"] == "d'acord"


def test_corregir_anula_l_original_i_crea_la_despesa_bona(ctx):
    client, _, sec = ctx
    enc = token(client, sec, "enc")
    pid = _prod(client, enc)
    _entrada(client, enc, pid, "10", 4000)
    gid = client.get("/locals/1/gastos/pendents", headers=enc).json()[0]["id"]
    assert client.post(f"/gastos/{gid}/revisio", json={"accio": "corregeix", "import_cent": 3600}, headers=enc).status_code == 422  # cal motiu
    assert client.post(f"/gastos/{gid}/revisio", json={"accio": "corregeix", "comentari": "descompte"}, headers=enc).status_code == 422  # cal import
    r = client.post(f"/gastos/{gid}/revisio", json={"accio": "corregeix", "import_cent": 3600, "comentari": "descompte del proveïdor"}, headers=enc)
    assert r.status_code == 201
    assert client.get("/locals/1/gastos/pendents", headers=enc).json() == []
    l = client.get("/locals/1/gastos", params=RANG, headers=enc).json()
    vigent = sum(0 if x["anulacio"] or x["anulada"] else x["import_cent"] for x in l)
    assert vigent == 3600


def test_comentar_no_la_treu_de_pendents(ctx):
    client, _, sec = ctx
    enc = token(client, sec, "enc")
    pid = _prod(client, enc)
    _entrada(client, enc, pid, "10", 4000)
    gid = client.get("/locals/1/gastos/pendents", headers=enc).json()[0]["id"]
    assert client.post(f"/gastos/{gid}/revisio", json={"accio": "comenta"}, headers=enc).status_code == 422
    assert client.post(f"/gastos/{gid}/revisio", json={"accio": "comenta", "comentari": "falta la factura"}, headers=enc).status_code == 201
    p = client.get("/locals/1/gastos/pendents", headers=enc).json()
    assert len(p) == 1 and p[0]["revisions"][0]["comentari"] == "falta la factura"


def test_corregir_l_entrada_d_estoc_anul_la_la_despesa(ctx):
    client, _, sec = ctx
    enc = token(client, sec, "enc")
    pid = _prod(client, enc)
    mid = _entrada(client, enc, pid, "10", 4000).json()["id"]
    assert client.post(f"/moviments/{mid}/correccio", json={"nota": "error d'entrada"}, headers=enc).status_code == 201
    assert client.get("/locals/1/gastos/pendents", headers=enc).json() == []
    l = client.get("/locals/1/gastos", params=RANG, headers=enc).json()
    assert sum(0 if x["anulacio"] or x["anulada"] else x["import_cent"] for x in l) == 0


def test_entrada_d_un_lot_tambe_porta_preu(ctx):
    client, _, sec = ctx
    enc = token(client, sec, "enc")
    pid = _prod(client, enc, "Lot", genetic=True)
    lot = client.post(f"/productes/{pid}/lots", json={"codi": "L1"}, headers=enc).json()["id"]
    assert client.post(f"/lots/{lot}/entrada", json={"grams": "5", "cost_cent": 1500}, headers=enc).status_code == 201
    assert client.get("/locals/1/gastos/pendents", headers=enc).json()[0]["import_cent"] == 1500


def test_despesa_de_la_caixa_apareix_a_gastos_sense_escriure_la_dues_vegades(ctx):
    client, _, sec = ctx
    enc = token(client, sec, "enc")
    client.post("/caixa/obrir", json={"local_id": 1, "opening_cent": 10000}, headers=enc)
    r = client.post("/despeses", json={"local_id": 1, "cent": 700, "metode": "efectiu", "categoria": "neteja", "concepte": "lleixiu"}, headers=enc)
    assert r.status_code == 201 and r.json()["gasto"]
    l = client.get("/locals/1/gastos", params=RANG, headers=enc).json()
    assert len(l) == 1 and l[0]["import_cent"] == 700 and l[0]["categoria"] == "neteja" and l[0]["caixa"] is True and l[0]["estat"] == ""
    assert client.get("/locals/1/gastos/pendents", headers=enc).json() == []
    # una anul·lació des de Gastos també corregeix l'apunt de caixa
    assert client.post(f"/gastos/{l[0]['id']}/anulacio", json={"nota": "duplicada"}, headers=enc).status_code == 201
    t = client.post("/caixa/tancar", json={"local_id": 1, "counted_cent": 10000}, headers=enc).json()
    assert t["esperat_cent"] == 10000


def test_despesa_de_caixa_sense_caixa_oberta_no_deixa_res_a_mitges(ctx):
    client, _, sec = ctx
    enc = token(client, sec, "enc")
    assert client.post("/despeses", json={"local_id": 1, "cent": 700, "metode": "efectiu", "categoria": "x", "concepte": "abc"}, headers=enc).status_code == 422
    assert client.get("/locals/1/gastos", params=RANG, headers=enc).json() == []


def test_columnes_i_taula_de_revisio_son_d_nomes_afegir(ctx):
    from app import schema
    from app.models import ExpenseReview, ImmutableError  # noqa: F401
    assert "expense_reviews" in schema.APPEND_ONLY
    assert {"cost_cent"} <= {c for c, _ in schema.COLUMNES_NOVES["stock_movements"]}
    assert {"origen", "movement_id"} <= {c for c, _ in schema.COLUMNES_NOVES["expenses"]}

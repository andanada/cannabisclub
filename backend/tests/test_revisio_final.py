"""Regressions de la revisió final: dispensació amb lot, quota amb monedero, apunts de despesa, estadístiques, avançaments."""
from datetime import date

from sqlalchemy import select

from app import cash, estadistiques_comu
from app.models import CashEntry, Expense, ExpenseCategory
from tests.ajuda_caixa import activa_targeta
from tests.test_api import SOCI, ctx, env, token  # noqa: F401
from tests.test_stock import setup_data

AVUI = date.today().isoformat()
RANG = {"des": AVUI, "fins": AVUI}


def obrir(client, h, cent=0):
    assert client.post("/caixa/obrir", json={"local_id": 1, "opening_cent": cent}, headers=h).status_code == 201


def _despesa(client, h, cent=500, metode="efectiu"):
    r = client.post("/despeses", json={"local_id": 1, "cent": cent, "metode": metode, "categoria": "neteja", "concepte": "lleixiu"}, headers=h)
    assert r.status_code == 201, r.text
    return r.json()


# 1. dispensació amb lot: mateixes regles de rol que /dispensacions
def test_dispensa_amb_lot_exigeix_rol_i_genetica(ctx):
    client, factory, sec = ctx
    enc = token(client, sec, "enc")
    mid, pid = setup_data(client, enc, factory, genetic=True)
    lot = client.post(f"/productes/{pid}/lots", json={"codi": "L1"}, headers=enc).json()["id"]
    assert client.post(f"/lots/{lot}/entrada", json={"grams": "5"}, headers=enc).status_code == 201
    cos = {"member_id": mid, "product_id": pid, "grams": "1", "batch_id": lot}
    rec = token(client, sec, "disp", rol="recepcio")
    assert client.post("/dispensacions/amb-lot", json=cos, headers=rec).status_code == 403   # genètica des de recepció
    sense_rol = token(client, sec, "disp", rol=False)
    assert client.post("/dispensacions/amb-lot", json=cos, headers=sense_rol).status_code == 403   # sense rol del dia
    dis = token(client, sec, "disp")
    assert client.post("/dispensacions/amb-lot", json=cos, headers=dis).status_code == 201


# 2. quota amb monedero: saldo real, sense deute
def test_quota_amb_monedero_no_es_pot_pagar_amb_deute(ctx):
    client, factory, sec = ctx
    enc = token(client, sec, "enc")
    adm = token(client, sec, "admin")
    assert client.put("/locals/1/config", json={"moneder_limit_cent": 10000}, headers=adm).status_code == 200
    obrir(client, enc)
    mid = client.post("/socis", json=SOCI, headers=enc).json()["id"]
    r = client.post(f"/socis/{mid}/quotes", json={"import_cent": 2000, "metode": "monedero", "mesos": 1}, headers=enc)
    assert r.status_code == 422 and "insuficient" in r.json()["detail"]


# 3. corregir l'apunt d'una despesa anul·la també la despesa (mateixa transacció)
def test_correccio_d_apunt_de_despesa_anul_la_la_despesa(ctx):
    client, factory, sec = ctx
    enc = token(client, sec, "enc")
    obrir(client, enc)
    apunt = _despesa(client, enc)["apunt"]
    assert client.post(f"/caixa/apunts/{apunt}/correccio", json={"nota": "error"}, headers=enc).status_code == 201
    llista = client.get("/locals/1/gastos", params=RANG, headers=enc).json()
    assert [x["anulada"] for x in llista if not x["anulacio"]] == [True]
    vigent = sum(0 if x["anulacio"] or x["anulada"] else x["import_cent"] for x in llista)
    assert vigent == 0
    assert client.post(f"/caixa/apunts/{apunt}/correccio", json={"nota": "altra"}, headers=enc).status_code == 422


# 4. estadístiques: l'anul·lació es classifica com l'original
def test_estadistiques_classifiquen_l_anulacio_segons_l_original(ctx):
    client, factory, sec = ctx
    enc = token(client, sec, "enc")
    obrir(client, enc)
    apunt = _despesa(client, enc)["apunt"]
    assert client.post(f"/caixa/apunts/{apunt}/correccio", json={"nota": "error"}, headers=enc).status_code == 201
    s = factory()
    d = estadistiques_comu.despeses(s, 1, date.today(), date.today())
    s.close()
    assert sum(d["caixa"].values()) == 0 and sum(d["final_mes"].values()) == 0


# 5. anul·lar totes les files vigents d'una entrada (entrada -> revisió que corregeix -> correcció)
def test_corregir_entrada_anul_la_totes_les_despeses_vigents(ctx):
    client, factory, sec = ctx
    enc = token(client, sec, "enc")
    pid = client.post("/productes", json={"local_id": 1, "nom": "Fulla", "preu_cent_per_g": 800, "es_genetic": False}, headers=enc).json()["id"]
    mov = client.post("/moviments/entrada", json={"product_id": pid, "grams": "10", "cost_cent": 4000}, headers=enc).json()["id"]
    gid = client.get("/locals/1/gastos/pendents", headers=enc).json()[0]["id"]
    assert client.post(f"/gastos/{gid}/revisio", json={"accio": "corregeix", "import_cent": 3600, "comentari": "descompte"}, headers=enc).status_code == 201
    assert client.post(f"/moviments/{mov}/correccio", json={"nota": "error"}, headers=enc).status_code == 201
    llista = client.get("/locals/1/gastos", params=RANG, headers=enc).json()
    assert sum(0 if x["anulacio"] or x["anulada"] else x["import_cent"] for x in llista) == 0


# 6. avançament fallit: no deixa catàlegs creats a mig
def test_avanc_fallit_no_deixa_catalegs_a_mig(ctx):
    client, factory, sec = ctx
    enc = token(client, sec, "enc")
    uid = next(u["id"] for u in client.get("/locals/1/horaris/mes", params={"any": 2031, "mes": 3}, headers=enc).json()["treballadors"] if u["username"] == "disp")
    cos = {"data": AVUI, "user_id": uid, "import_cent": 5000, "de_caixa": True, "metode": "efectiu"}
    assert client.post("/locals/1/horaris/avancos", json=cos, headers=enc).status_code == 422   # sense caixa oberta
    cats = client.get("/locals/1/gastos/categories", headers=enc).json()
    assert "Sous/avançaments" not in [c["nom"] for c in cats]


# 9. targeta/Bizum a les despeses de caixa només si el local els té activats
def test_despeses_de_caixa_nomes_efectiu_sense_targeta(ctx):
    client, factory, sec = ctx
    enc = token(client, sec, "enc")
    obrir(client, enc)
    cos = {"local_id": 1, "cent": 300, "metode": "targeta", "categoria": "oficina", "concepte": "paper"}
    assert client.post("/despeses", json=cos, headers=enc).status_code == 422
    uid = next(u["id"] for u in client.get("/locals/1/horaris/mes", params={"any": 2031, "mes": 3}, headers=enc).json()["treballadors"] if u["username"] == "disp")
    av = {"data": AVUI, "user_id": uid, "import_cent": 500, "de_caixa": True, "metode": "bizum"}
    assert client.post("/locals/1/horaris/avancos", json=av, headers=enc).status_code == 422
    activa_targeta(client, sec)
    assert client.post("/despeses", json=cos, headers=enc).status_code == 201
    assert client.post("/locals/1/horaris/avancos", json=av, headers=enc).status_code == 201


# 10. límits superiors a la caixa
def test_tancar_i_obrir_caixa_amb_imports_absurds(ctx):
    client, factory, sec = ctx
    enc = token(client, sec, "enc")
    assert client.post("/caixa/obrir", json={"local_id": 1, "opening_cent": 10**12}, headers=enc).status_code == 422
    obrir(client, enc)
    for camp in ("counted_cent", "fons_cent", "billets_cent", "monedes_cent"):
        cos = {"local_id": 1, "counted_cent": 100, camp: 10**12}
        assert client.post("/caixa/tancar", json=cos, headers=enc).status_code == 422, camp


# 11. tpv_totals descompta els cobraments corregits
def test_tpv_recompte_descompta_els_anullats(ctx):
    client, factory, sec = ctx
    enc = token(client, sec, "enc")
    activa_targeta(client, sec)
    obrir(client, enc)
    mid, pid = setup_data(client, enc, factory)
    r = client.post("/dispensacions", json={"member_id": mid, "product_id": pid, "grams": "1", "metode": "targeta"}, headers=enc)
    assert r.status_code == 201
    s = factory()
    sessio = s.scalar(select(CashEntry.session_id).where(CashEntry.metode == "targeta"))
    entrada = s.scalar(select(CashEntry.id).where(CashEntry.metode == "targeta"))
    assert cash.tpv_totals(s, sessio)["targeta_n"] == 1
    s.close()
    assert client.post(f"/caixa/apunts/{entrada}/correccio", json={"nota": "error"}, headers=enc).status_code == 201
    s = factory()
    t = cash.tpv_totals(s, sessio)
    s.close()
    assert t["targeta_n"] == 0 and t["targeta_cent"] == 0


# 13. una categoria desactivada no es reactiva en silenci
def test_categoria_automatica_desactivada_no_es_reactiva(ctx):
    client, factory, sec = ctx
    enc = token(client, sec, "enc")
    pid = client.post("/productes", json={"local_id": 1, "nom": "Fulla", "preu_cent_per_g": 800, "es_genetic": False}, headers=enc).json()["id"]
    assert client.post("/moviments/entrada", json={"product_id": pid, "grams": "1", "cost_cent": 100}, headers=enc).status_code == 201
    s = factory()
    cat = s.scalar(select(ExpenseCategory).where(ExpenseCategory.nom == "Proveïdors"))
    cat_id = cat.id
    s.close()
    assert client.put(f"/gastos/categories/{cat_id}", json={"actiu": False}, headers=enc).status_code == 200
    assert client.post("/moviments/entrada", json={"product_id": pid, "grams": "1", "cost_cent": 200}, headers=enc).status_code == 201
    s = factory()
    assert s.get(ExpenseCategory, cat_id).actiu is False
    assert len(s.scalars(select(Expense)).all()) == 2
    s.close()

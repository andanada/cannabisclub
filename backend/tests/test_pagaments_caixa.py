"""Pagaments i caixa: genètiques/no genètiques per rol, quota amb monedero, targeta/Bizum separats de l'efectiu,
fons de caixa i tancament amb billets i monedes, fulla del TPV."""
from datetime import date

from tests.ajuda_caixa import activa_targeta
from tests.test_api import SOCI, ctx, env, token  # noqa: F401
from tests.test_stock import setup_data

AVUI = date.today().isoformat()


def _obre(client, h, ini=0):
    assert client.post("/caixa/obrir", json={"local_id": 1, "opening_cent": ini}, headers=h).status_code == 201


def _no_genetic(client, enc, nom="Cervesa"):
    pid = client.post("/productes", json={"local_id": 1, "nom": nom, "preu_cent_per_g": 300, "es_genetic": False, "unitat": "u"}, headers=enc).json()["id"]
    assert client.post("/moviments/entrada", json={"product_id": pid, "grams": "10"}, headers=enc).status_code == 201
    return pid


def _admin_cfg(client, sec, **cfg):
    assert client.put("/locals/1/config", json=cfg, headers=token(client, sec, "admin")).status_code == 200


# ---------- genètiques i no genètiques segons el rol del dia ----------

def test_recepcio_dispensa_nomes_no_genetiques(ctx):
    client, factory, sec = ctx
    enc = token(client, sec, "enc")
    mid, gen = setup_data(client, enc, factory)          # genètic
    bar = _no_genetic(client, enc)
    rec = token(client, sec, "disp", rol="recepcio")
    _obre(client, rec)
    cobra = {"member_id": mid, "grams": "1", "metode": "efectiu"}
    r = client.post("/dispensacions", json={**cobra, "product_id": gen}, headers=rec)
    assert r.status_code == 403 and "Dispensari" in r.json()["detail"]
    assert client.post("/dispensacions", json={**cobra, "product_id": bar}, headers=rec).status_code == 201
    # carret: una sola línia genètica el refusa sencer
    r = client.post("/dispensacions/carret", json={"member_id": mid, "linies": [{"product_id": bar, "grams": "1"}, {"product_id": gen, "grams": "1"}]}, headers=rec)
    assert r.status_code == 403


def test_recepcio_nomes_veu_les_no_genetiques_a_l_estoc(ctx):
    client, factory, sec = ctx
    enc = token(client, sec, "enc")
    _, gen = setup_data(client, enc, factory)
    bar = _no_genetic(client, enc)
    rec = token(client, sec, "disp", rol="recepcio")
    assert [p["id"] for p in client.get("/locals/1/estoc", headers=rec).json()] == [bar]
    assert {p["id"] for p in client.get("/locals/1/estoc", headers=enc).json()} == {gen, bar}      # accés complet: tot
    dsp = token(client, sec, "disp", rol="dispensari")
    assert {p["id"] for p in client.get("/locals/1/estoc", headers=dsp).json()} == {gen, bar}


def test_dispensari_i_acces_complet_dispensen_genetiques(ctx):
    client, factory, sec = ctx
    enc = token(client, sec, "enc")
    mid, gen = setup_data(client, enc, factory)
    _obre(client, enc)
    body = {"member_id": mid, "product_id": gen, "grams": "1", "metode": "efectiu"}
    assert client.post("/dispensacions", json=body, headers=enc).status_code == 201
    dsp = token(client, sec, "disp", rol="dispensari")
    assert client.post("/dispensacions", json={**body, "metode": None}, headers=dsp).status_code == 201


def test_sense_rol_del_dia_no_dispensa(ctx):
    client, factory, sec = ctx
    enc = token(client, sec, "enc")
    mid, _ = setup_data(client, enc, factory)
    bar = _no_genetic(client, enc)
    sense = token(client, sec, "disp", rol=False)
    assert client.post("/dispensacions", json={"member_id": mid, "product_id": bar, "grams": "1"}, headers=sense).status_code == 403


# ---------- quota: efectiu, targeta o crèdits ----------

def test_quota_amb_credits_del_monedero(ctx):
    client, factory, sec = ctx
    enc = token(client, sec, "enc")
    mid, _ = setup_data(client, enc, factory)
    _obre(client, enc)
    q = {"import_cent": 3000, "metode": "monedero", "mesos": 1}
    # soci nou: sense crèdits no pot pagar amb crèdits
    assert client.post(f"/socis/{mid}/quotes", json=q, headers=enc).status_code == 422
    assert client.post(f"/socis/{mid}/moneder/recarrega", json={"import_cent": 5000, "metode": "efectiu"}, headers=enc).status_code == 201
    r = client.post(f"/socis/{mid}/quotes", json=q, headers=enc)
    assert r.status_code == 201
    assert client.get(f"/socis/{mid}/moneder", headers=enc).json()["saldo_cent"] == 2000
    # els crèdits gastats no són un ingrés nou: l'efectiu esperat només és la recàrrega
    assert client.get("/locals/1/caixa", headers=enc).json()["esperat_cent"] == 5000
    # anul·lar la quota torna els crèdits
    assert client.post(f"/caixa/apunts/{r.json()['apunt']}/correccio", json={"nota": "error de cobrament"}, headers=enc).status_code == 201
    assert client.get(f"/socis/{mid}/moneder", headers=enc).json()["saldo_cent"] == 5000


def test_quota_amb_credits_insuficients(ctx):
    client, factory, sec = ctx
    enc = token(client, sec, "enc")
    mid, _ = setup_data(client, enc, factory)
    _obre(client, enc)
    client.post(f"/socis/{mid}/moneder/recarrega", json={"import_cent": 1000, "metode": "efectiu"}, headers=enc)
    r = client.post(f"/socis/{mid}/quotes", json={"import_cent": 3000, "metode": "monedero"}, headers=enc)
    assert r.status_code == 422 and "insuficient" in r.json()["detail"]


def test_soci_nou_ha_de_pagar_la_quota_abans_de_tenir_compte_de_donacions(ctx):
    client, factory, sec = ctx
    enc = token(client, sec, "enc")
    mid, _ = setup_data(client, enc, factory)
    _obre(client, enc)
    _admin_cfg(client, sec, quota_obligatoria=True, quota_cent=3000)
    rec = {"import_cent": 1000, "metode": "efectiu"}
    r = client.post(f"/socis/{mid}/moneder/recarrega", json=rec, headers=enc)
    assert r.status_code == 422 and "quota" in r.json()["detail"]
    assert client.post(f"/socis/{mid}/quotes", json={"import_cent": 3000, "metode": "efectiu"}, headers=enc).status_code == 201
    assert client.post(f"/socis/{mid}/moneder/recarrega", json=rec, headers=enc).status_code == 201


# ---------- targeta i Bizum: activació i separació de l'efectiu ----------

def test_targeta_i_bizum_necessiten_activar_l_ajust(ctx):
    client, factory, sec = ctx
    enc = token(client, sec, "enc")
    mid, _ = setup_data(client, enc, factory)
    _obre(client, enc)
    for metode in ("targeta", "bizum"):
        assert client.post(f"/socis/{mid}/moneder/recarrega", json={"import_cent": 500, "metode": metode}, headers=enc).status_code == 422
        assert client.post(f"/socis/{mid}/quotes", json={"import_cent": 500, "metode": metode}, headers=enc).status_code == 422
    assert client.post(f"/socis/{mid}/moneder/recarrega", json={"import_cent": 500, "metode": "efectiu"}, headers=enc).status_code == 201
    activa_targeta(client, sec)
    assert client.get("/me", headers=enc).json()["locals"][0]["targeta_activa"] is True
    for metode in ("targeta", "bizum"):
        assert client.post(f"/socis/{mid}/moneder/recarrega", json={"import_cent": 500, "metode": metode}, headers=enc).status_code == 201


def test_targeta_i_bizum_separats_de_l_efectiu_a_caixa_i_comptabilitat(ctx):
    client, factory, sec = ctx
    enc = token(client, sec, "enc")
    activa_targeta(client, sec)
    mid, _ = setup_data(client, enc, factory)
    _obre(client, enc, 1000)
    for cent, metode in ((2000, "efectiu"), (700, "targeta"), (300, "bizum")):
        assert client.post(f"/socis/{mid}/moneder/recarrega", json={"import_cent": cent, "metode": metode}, headers=enc).status_code == 201
    assert client.post(f"/socis/{mid}/quotes", json={"import_cent": 900, "metode": "targeta"}, headers=enc).status_code == 201
    st = client.get("/locals/1/caixa", headers=enc).json()
    assert st["esperat_cent"] == 3000                                   # obertura + efectiu: només efectiu
    assert st["tpv"]["targeta_cent"] == 1600 and st["tpv"]["bizum_cent"] == 300
    c = client.get("/locals/1/caixa/sessions", params={"des": AVUI, "fins": AVUI}, headers=enc).json()[0]
    assert c["efectiu_cent"] == 2000 and c["targeta_cent"] == 1600 and c["bizum_cent"] == 300


def test_report_de_caixa_separa_metodes(ctx):
    from datetime import date as d
    from app import cash
    client, factory, sec = ctx
    enc = token(client, sec, "enc")
    activa_targeta(client, sec)
    mid, _ = setup_data(client, enc, factory)
    _obre(client, enc)
    for cent, metode in ((2000, "efectiu"), (700, "targeta"), (300, "bizum")):
        client.post(f"/socis/{mid}/moneder/recarrega", json={"import_cent": cent, "metode": metode}, headers=enc)
    s = factory()
    r = cash.report(s, 1, d.today(), d.today())
    s.close()
    assert (r["ingressos_efectiu_cent"], r["ingressos_targeta_cent"], r["ingressos_bizum_cent"], r["ingressos_cent"]) == (2000, 700, 300, 3000)
    dia = r["per_dia"][d.today().isoformat()]
    assert dia["efectiu_cent"] == 2000 and dia["targeta_cent"] == 700 and dia["bizum_cent"] == 300


def test_tancament_calcula_nomes_amb_efectiu_i_dona_la_fulla_del_tpv(ctx):
    client, factory, sec = ctx
    enc = token(client, sec, "enc")
    activa_targeta(client, sec)
    mid, _ = setup_data(client, enc, factory)
    _obre(client, enc, 1000)
    client.post(f"/socis/{mid}/moneder/recarrega", json={"import_cent": 2000, "metode": "efectiu"}, headers=enc)
    client.post(f"/socis/{mid}/moneder/recarrega", json={"import_cent": 700, "metode": "targeta"}, headers=enc)
    client.post(f"/socis/{mid}/moneder/recarrega", json={"import_cent": 300, "metode": "bizum"}, headers=enc)
    r = client.post("/caixa/tancar", json={"local_id": 1, "counted_cent": 3000}, headers=enc).json()
    assert r["esperat_cent"] == 3000 and r["diferencia_cent"] == 0
    assert r["tpv"]["targeta_cent"] == 700 and r["tpv"]["bizum_cent"] == 300 and r["tpv"]["total_cent"] == 1000 and r["tpv"]["targeta_n"] == 1
    f = client.get(f"/caixa/sessions/{r['sessio']}/tpv", headers=enc)
    assert f.status_code == 200 and f.json()["targeta_cent"] == 700 and f.json()["tancament"] is not None
    assert client.get("/caixa/sessions/9999/tpv", headers=enc).status_code == 404
    assert client.get(f"/caixa/sessions/{r['sessio']}/tpv", headers=token(client, sec, "disp", rol="dispensari")).status_code == 403


# ---------- tancament amb fons de caixa, billets i monedes ----------

def test_tancament_amb_fons_billets_i_monedes(ctx):
    client, factory, sec = ctx
    enc = token(client, sec, "enc")
    mid, _ = setup_data(client, enc, factory)
    _obre(client, enc, 10000)
    client.post(f"/socis/{mid}/moneder/recarrega", json={"import_cent": 5050, "metode": "efectiu"}, headers=enc)
    # comptat 15050, fons 10000: surten 5050 = 5000 en billets + 50 en monedes
    r = client.post("/caixa/tancar", json={"local_id": 1, "counted_cent": 15050, "fons_cent": 10000, "billets_cent": 5000, "monedes_cent": 50}, headers=enc)
    assert r.status_code == 200
    j = r.json()
    assert (j["fons_deixat_cent"], j["sortida_billets_cent"], j["sortida_monedes_cent"]) == (10000, 5000, 50)
    ses = client.get("/locals/1/caixa/sessions", params={"des": AVUI, "fins": AVUI}, headers=enc).json()[0]
    assert (ses["fons_deixat_cent"], ses["sortida_billets_cent"], ses["sortida_monedes_cent"]) == (10000, 5000, 50)


def test_tancament_valida_que_billets_mes_monedes_quadren(ctx):
    client, factory, sec = ctx
    enc = token(client, sec, "enc")
    setup_data(client, enc, factory)
    _obre(client, enc, 10000)
    base = {"local_id": 1, "counted_cent": 10000, "fons_cent": 4000}
    assert client.post("/caixa/tancar", json={**base, "billets_cent": 5000, "monedes_cent": 500}, headers=enc).status_code == 422   # 5500 != 6000
    assert client.post("/caixa/tancar", json={**base, "billets_cent": 5000}, headers=enc).status_code == 422                    # falten monedes
    assert client.post("/caixa/tancar", json={**base, "fons_cent": 20000, "billets_cent": 0, "monedes_cent": 0}, headers=enc).status_code == 422  # fons > comptat
    assert client.post("/caixa/tancar", json={**base, "billets_cent": -1, "monedes_cent": 6001}, headers=enc).status_code == 422
    assert client.get("/locals/1/caixa", headers=enc).json()["oberta"] is True       # cap dels intents l'ha tancada
    assert client.post("/caixa/tancar", json={**base, "billets_cent": 6000, "monedes_cent": 0}, headers=enc).status_code == 200


def test_fons_per_defecte_es_l_ultim_deixat(ctx):
    client, factory, sec = ctx
    enc = token(client, sec, "enc")
    setup_data(client, enc, factory)
    assert client.get("/locals/1/caixa", headers=enc).json()["fons_darrer_cent"] is None
    _obre(client, enc, 5000)
    assert client.get("/locals/1/caixa", headers=enc).json()["fons_darrer_cent"] is None
    client.post("/caixa/tancar", json={"local_id": 1, "counted_cent": 5000, "fons_cent": 3000, "billets_cent": 2000, "monedes_cent": 0}, headers=enc)
    assert client.get("/locals/1/caixa", headers=enc).json()["fons_darrer_cent"] == 3000   # amb la caixa tancada, per obrir-ne la propera
    _obre(client, enc, 3000)
    assert client.get("/locals/1/caixa", headers=enc).json()["fons_darrer_cent"] == 3000
    # un tancament sense desglossament (com abans) no esborra l'últim fons conegut
    client.post("/caixa/tancar", json={"local_id": 1, "counted_cent": 3000}, headers=enc)
    assert client.get("/locals/1/caixa", headers=enc).json()["fons_darrer_cent"] == 3000


def test_tancament_sense_desglossament_continua_funcionant(ctx):
    client, factory, sec = ctx
    enc = token(client, sec, "enc")
    setup_data(client, enc, factory)
    _obre(client, enc, 100)
    j = client.post("/caixa/tancar", json={"local_id": 1, "counted_cent": 100}, headers=enc).json()
    assert j["fons_deixat_cent"] is None and j["tpv"]["total_cent"] == 0

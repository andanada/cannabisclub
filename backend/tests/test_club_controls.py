"""Controls de club (espera, aval, pendent, excepcions de límit), lots/traçabilitat i llibres signats."""
import hashlib
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app import lots
from app.models import Batch, Member, MovementBatch
from tests.test_api import SOCI, ctx, env, token  # noqa: F401
from tests.test_stock import setup_data


def cfg(client, adm, **c):
    r = client.put("/locals/1/club-config", json=c, headers=adm)
    assert r.status_code == 200, r.text
    return r.json()


def disp(client, h, mid, pid, g="1"):
    return client.post("/dispensacions", json={"member_id": mid, "product_id": pid, "grams": g}, headers=h)


def test_per_defecte_res_no_canvia(ctx):
    client, factory, sec = ctx
    enc, adm = token(client, sec, "enc"), token(client, sec, "admin")
    assert client.get("/locals/1/club-config", headers=enc).json() == {"espera_dies": 0, "aval": "no", "alta_pendent": False}
    mid, pid = setup_data(client, enc, factory)
    assert disp(client, enc, mid, pid).status_code == 201
    assert client.get("/me", headers=enc).json()["locals"][0]["espera_dies"] == 0


def test_config_nomes_admin_i_validada(ctx):
    client, _, sec = ctx
    enc, adm = token(client, sec, "enc"), token(client, sec, "admin")
    assert client.put("/locals/1/club-config", json={"aval": "obligatori"}, headers=enc).status_code == 403
    assert client.put("/locals/1/club-config", json={"aval": "molt"}, headers=adm).status_code == 422
    assert client.put("/locals/1/club-config", json={"espera_dies": 999}, headers=adm).status_code == 422
    assert cfg(client, adm, espera_dies=7, aval="opcional")["espera_dies"] == 7


def test_periode_d_espera_des_de_l_alta(ctx):
    client, factory, sec = ctx
    enc, adm = token(client, sec, "enc"), token(client, sec, "admin")
    mid, pid = setup_data(client, enc, factory)
    cfg(client, adm, espera_dies=7)
    r = disp(client, enc, mid, pid)
    assert r.status_code == 422 and "període d'espera" in r.json()["detail"]
    with factory() as s:
        s.get(Member, mid).creat = datetime.now(timezone.utc) - timedelta(days=8)
        s.commit()
    assert disp(client, enc, mid, pid).status_code == 201


def test_aval_obligatori_i_validacio_de_l_avalador(ctx):
    client, factory, sec = ctx
    enc, adm = token(client, sec, "enc"), token(client, sec, "admin")
    mid, pid = setup_data(client, enc, factory)
    aval = client.post("/socis", json={**SOCI, "document": "87654321X", "nom": "Berta Aval"}, headers=enc).json()["id"]
    cfg(client, adm, aval="obligatori")
    assert "avalador" in disp(client, enc, mid, pid).json()["detail"]
    cos = {"versio": "v1", "text_sha256": __import__("app.textos", fromlist=["x"]).sha256("v1", "ca"), "finalitats": ["basic"], "doc_verificat": True}
    assert client.post(f"/socis/{mid}/alta-rgpd", json=cos, headers=enc).status_code == 422                     # falta l'avalador
    assert client.post(f"/socis/{mid}/alta-rgpd", json={**cos, "avalador_id": mid}, headers=enc).status_code == 422  # ell mateix
    assert client.post(f"/socis/{mid}/alta-rgpd", json={**cos, "avalador_id": 9999}, headers=enc).status_code == 422
    assert client.post(f"/socis/{mid}/alta-rgpd", json={**cos, "avalador_id": aval}, headers=enc).status_code == 201
    assert disp(client, enc, mid, pid).status_code == 201


def test_alta_pendent_i_aprovacio_per_un_altre_gestor(ctx):
    client, factory, sec = ctx
    enc, adm = token(client, sec, "enc"), token(client, sec, "admin")
    cfg(client, adm, alta_pendent=True)
    mid = client.post("/socis", json=SOCI, headers=enc).json()["id"]
    pid = client.post("/productes", json={"local_id": 1, "nom": "P", "preu_cent_per_g": 100}, headers=enc).json()["id"]
    client.post("/moviments/entrada", json={"product_id": pid, "grams": "5"}, headers=enc)
    assert client.get(f"/socis/{mid}", headers=enc).json()["estat"] == "pendent"
    assert "pendent d'aprovació" in disp(client, enc, mid, pid).json()["detail"]
    assert client.post(f"/socis/{mid}/entrada", headers=enc).status_code == 422                  # tampoc pot entrar
    r = client.post(f"/socis/{mid}/aprovar", headers=enc)                                          # el mateix gestor que l'ha creat
    assert r.status_code == 422 and "altre gestor" in r.json()["detail"]
    assert client.post(f"/socis/{mid}/aprovar", headers=adm).status_code == 200
    assert client.post(f"/socis/{mid}/aprovar", headers=adm).status_code == 422                  # ja no és pendent
    assert disp(client, enc, mid, pid).status_code == 201


def test_excepcio_de_limit_per_soci_amb_motiu_i_auditoria(ctx):
    client, factory, sec = ctx
    enc, adm = token(client, sec, "enc"), token(client, sec, "admin")
    mid, pid = setup_data(client, enc, factory)
    assert client.put("/locals/1/limits", json={"limit_diari_g": "2", "limit_mensual_g": "50"}, headers=adm).status_code == 200
    assert disp(client, enc, mid, pid, "3").status_code == 422                                   # límit del local
    assert client.put(f"/socis/{mid}/limits", json={"periode": "dia", "max_g": "5", "motiu": "ok"}, headers=enc).status_code == 422  # motiu massa curt
    r = client.put(f"/socis/{mid}/limits", json={"periode": "dia", "max_g": "5", "motiu": "Pacient amb recepta"}, headers=enc)
    assert r.status_code == 200 and r.json()[0]["max_mg"] == 5000 and r.json()[0]["motiu"] == "Pacient amb recepta"
    assert disp(client, enc, mid, pid, "3").status_code == 201                                   # l'excepció puja el límit
    assert disp(client, enc, mid, pid, "2.5").status_code == 422                                 # 3 + 2,5 > 5
    ac = client.get("/auditoria/consulta", params={"soci": mid, "accio": "excepcio_limit"}, headers=adm).json()["entrades"]
    assert ac[0]["detall"]["motiu"] == "Pacient amb recepta" and ac[0]["detall"]["despres"] == 5000
    assert client.put(f"/socis/{mid}/limits", json={"periode": "dia", "max_g": None, "motiu": "revocada"}, headers=enc).status_code == 200
    assert client.get(f"/socis/{mid}/limits", headers=enc).json() == []
    assert client.put(f"/socis/{mid}/limits", json={"periode": "dia", "max_g": None, "motiu": "revocada"}, headers=enc).status_code == 422


def test_baixa_amb_motiu_queda_al_llibre_de_socis_sense_dades_personals(ctx):
    client, factory, sec = ctx
    enc = token(client, sec, "enc")
    mid = client.post("/socis", json=SOCI, headers=enc).json()["id"]
    assert client.post(f"/socis/{mid}/baixa", json={"motiu": "=cmd|' /C calc'!A0"}, headers=enc).status_code == 200
    r = client.get("/locals/1/llibres/socis.csv", params={"des": "2020-01-01", "fins": "2099-01-01"}, headers=enc)
    assert r.status_code == 200 and r.headers["x-content-sha256"] == hashlib.sha256(r.text.encode()).hexdigest()
    lin = r.text.splitlines()
    assert lin[0] == "seq_auditoria,data,soci_id,esdeveniment,usuari,motiu" and len(lin) == 3
    assert "alta" in lin[1] and "estat actiu -> baixa" in lin[2] and "enc" in lin[2]
    assert "Anna" not in r.text and "12345678Z" not in r.text
    assert ",\"'=cmd" in r.text or ",'=cmd" in r.text                                              # fórmula neutralitzada


def test_llibre_d_estoc_signat_i_verificable(ctx):
    client, factory, sec = ctx
    enc, disp_h = token(client, sec, "enc"), token(client, sec, "disp")
    mid, pid = setup_data(client, enc, factory)
    client.post("/moviments/entrada", json={"product_id": pid, "grams": "1", "nota": "=HYPERLINK(\"x\")"}, headers=enc)
    p = {"des": "2020-01-01", "fins": "2099-01-01"}
    assert client.get("/locals/1/llibres/estoc.csv", params=p, headers=disp_h).status_code == 403
    assert client.get("/locals/2/llibres/estoc.csv", params=p, headers=enc).status_code == 403
    assert client.get("/locals/1/llibres/estoc.csv", params={"des": "2030-01-01", "fins": "2020-01-01"}, headers=enc).status_code == 422
    r = client.get("/locals/1/llibres/estoc.csv", params=p, headers=enc)
    h = r.headers["x-content-sha256"]
    assert "'=HYPERLINK" in r.text and r.text.count("\n") >= 3
    assert client.post("/llibres/verificar", json={"sha256": h}, headers=enc).json()["coincidencies"][0]["llibre"] == "estoc"
    assert client.post("/llibres/verificar", json={"sha256": "0" * 64}, headers=enc).json()["coincidencies"] == []
    assert client.post("/llibres/verificar", json={"sha256": "x' OR '1"}, headers=enc).status_code == 422


# ---------- lots ----------

def lot(client, h, pid, codi, **x):
    r = client.post(f"/productes/{pid}/lots", json={"codi": codi, **x}, headers=h)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def test_lot_amb_entrada_fifo_i_traçabilitat(ctx):
    client, factory, sec = ctx
    enc = token(client, sec, "enc")
    mid, pid = setup_data(client, enc, factory, gprod="1")     # 1 g sense lot
    a = lot(client, enc, pid, "L-001", proveidor="Cultiu X", origen="ES", data_entrada="2026-01-01", analisi="THC 18%")
    b = lot(client, enc, pid, "L-002", data_entrada="2026-02-01")
    assert client.post(f"/productes/{pid}/lots", json={"codi": "L-001"}, headers=enc).status_code == 422
    assert client.post(f"/productes/{pid}/lots", json={"codi": "mal codi!"}, headers=enc).status_code == 422
    assert client.post(f"/lots/{a}/entrada", json={"grams": "3"}, headers=enc).status_code == 201
    assert client.post(f"/lots/{b}/entrada", json={"grams": "4"}, headers=enc).status_code == 201
    d = disp(client, enc, mid, pid, "5").json()["id"]          # FIFO: 3 g de L-001 + 2 g de L-002
    with factory() as s:
        assert {mb.batch_id: mb.mg for mb in s.scalars(select(MovementBatch).where(MovementBatch.movement_id == d))} == {a: -3000, b: -2000}
        assert lots.remaining_mg(s, a) == 0 and lots.remaining_mg(s, b) == 2000
    t = client.get(f"/lots/{a}/tracabilitat", headers=enc).json()
    assert t["entrat_mg"] == 3000 and t["dispensat_mg"] == 3000 and t["existencies_mg"] == 0 and t["socis_afectats"] == [mid]
    assert t["lot"]["proveidor"] == "Cultiu X" and "Anna" not in str(t)
    csv = client.get(f"/lots/{a}/tracabilitat.csv", headers=enc).text
    assert csv.splitlines()[0].startswith("moviment,data,tipus,mg,soci_id")
    # la correcció retorna els mg als lots
    assert client.post(f"/moviments/{d}/correccio", json={"nota": "error"}, headers=enc).status_code == 201
    with factory() as s:
        assert lots.remaining_mg(s, a) == 3000 and lots.remaining_mg(s, b) == 4000
    assert client.get(f"/lots/{a}/tracabilitat", headers=enc).json()["socis_afectats"] == []


def test_lot_manual_i_limits(ctx):
    client, factory, sec = ctx
    enc = token(client, sec, "enc")
    mid, pid = setup_data(client, enc, factory, gprod="0.001")
    a, b = lot(client, enc, pid, "A"), lot(client, enc, pid, "B")
    client.post(f"/lots/{a}/entrada", json={"grams": "2"}, headers=enc)
    client.post(f"/lots/{b}/entrada", json={"grams": "2"}, headers=enc)
    cos = {"member_id": mid, "product_id": pid}
    r = client.post("/dispensacions/amb-lot", json={**cos, "grams": "3", "batch_id": b}, headers=enc)
    assert r.status_code == 422 and "prou existències" in r.json()["detail"]
    assert client.post("/dispensacions/amb-lot", json={**cos, "grams": "1.5", "batch_id": b}, headers=enc).status_code == 201
    with factory() as s:
        assert lots.remaining_mg(s, b) == 500 and lots.remaining_mg(s, a) == 2000
    other = client.post("/productes", json={"local_id": 1, "nom": "Altre", "preu_cent_per_g": 1}, headers=enc).json()["id"]
    assert client.post(f"/lots/{a}/entrada", json={"grams": "1"}, headers=enc).status_code == 201
    assert client.post("/dispensacions/amb-lot", json={**cos, "product_id": other, "grams": "1", "batch_id": a}, headers=enc).status_code == 422
    assert client.post(f"/lots/{b}/tancar", headers=enc).status_code == 200
    assert client.post(f"/lots/{b}/entrada", json={"grams": "1"}, headers=enc).status_code == 422   # lot tancat
    assert client.get("/lots/9999/tracabilitat", headers=enc).status_code == 404


def test_producte_sense_lots_funciona_com_abans_i_fifo_no_assigna_el_que_falta(ctx):
    client, factory, sec = ctx
    enc = token(client, sec, "enc")
    mid, pid = setup_data(client, enc, factory, gprod="10")
    d = disp(client, enc, mid, pid, "2").json()["id"]
    with factory() as s:
        assert s.scalar(select(MovementBatch).where(MovementBatch.movement_id == d)) is None
    a = lot(client, enc, pid, "A")
    client.post(f"/lots/{a}/entrada", json={"grams": "1"}, headers=enc)
    d2 = disp(client, enc, mid, pid, "3").json()["id"]     # 1 g del lot + 2 g sense lot
    with factory() as s:
        assert {mb.batch_id: mb.mg for mb in s.scalars(select(MovementBatch).where(MovementBatch.movement_id == d2))} == {a: -1000}


def test_s3_estat_no_es_pot_canviar_des_de_o_cap_a_pendent_fora_de_l_aprovacio(ctx):
    """Control de dues persones: ni /estat ni set_member_status poden saltar-se controls.approve."""
    client, factory, sec = ctx
    enc, adm = token(client, sec, "enc"), token(client, sec, "admin")
    cfg(client, adm, alta_pendent=True)
    mid = client.post("/socis", json=SOCI, headers=enc).json()["id"]
    for h in (enc, adm):  # ni el mateix gestor ni l'administrador
        for estat in ("actiu", "suspes", "baixa"):
            r = client.post(f"/socis/{mid}/estat", json={"estat": estat}, headers=h)
            assert r.status_code == 422 and "aprov" in r.json()["detail"].lower(), (estat, r.text)
    with factory() as s:
        assert s.get(Member, mid).estat == "pendent"
    assert client.post(f"/socis/{mid}/aprovar", headers=adm).status_code == 200
    assert client.post(f"/socis/{mid}/estat", json={"estat": "pendent"}, headers=adm).status_code == 422  # tampoc cap a pendent
    assert client.post(f"/socis/{mid}/estat", json={"estat": "suspes"}, headers=enc).status_code == 200

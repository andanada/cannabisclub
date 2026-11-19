"""Document de funcionalitats: rol del dia, expulsat, tipus de membre, inactivitat, donacions + monedero, carret de dispensar,
regles de producte, existències i historial de moviments."""
from datetime import datetime, timedelta, timezone

from app.models import Member
from tests.test_api import SOCI, ctx, env, token  # noqa: F401


def _escena(client, sec):
    enc = token(client, sec, "enc")
    client.post("/caixa/obrir", json={"local_id": 1, "opening_cent": 0}, headers=enc)
    flor = client.post("/productes", json={"local_id": 1, "nom": "Flor", "categoria": "Weed", "preu_cent_per_g": 1000, "es_genetic": True,
                                           "estricte": True}, headers=enc).json()["id"]
    aigua = client.post("/productes", json={"local_id": 1, "nom": "Aigua", "categoria": "Beguda", "preu_cent_per_g": 200, "es_genetic": False,
                                            "unitat": "u", "estricte": True}, headers=enc).json()["id"]
    for p in (flor, aigua):
        client.post("/moviments/entrada", json={"product_id": p, "grams": "50"}, headers=enc)
    mid = client.post("/socis", json=SOCI, headers=enc).json()["id"]
    return enc, flor, aigua, mid


def _recarrega(client, h, mid, cent):
    return client.post(f"/socis/{mid}/moneder/recarrega", json={"import_cent": cent, "metode": "efectiu"}, headers=h)


# ---------- 1. rol del dia ----------

def test_rol_del_dia_i_les_donacions_son_de_recepcio(ctx):
    client, _, sec = ctx
    enc, flor, aigua, mid = _escena(client, sec)
    disp = token(client, sec, "disp")
    assert client.post("/auth/rol-dia", json={"rol": "pirata"}, headers=disp).status_code == 422
    assert client.post("/auth/rol-dia", json={"rol": "dispensari"}, headers=enc).status_code == 422     # la gerència no tria rol
    assert client.post("/auth/rol-dia", json={"rol": "dispensari"}, headers=disp).json() == {"rol_dia": "dispensari"}
    assert client.get("/me", headers=disp).json()["rol_dia"] == "dispensari"
    assert _recarrega(client, disp, mid, 500).status_code == 403          # el dispensari no afegeix fons: descuadraria la caixa
    client.post("/auth/rol-dia", json={"rol": "recepcio"}, headers=disp)
    assert _recarrega(client, disp, mid, 500).status_code == 201          # recepció sí; entra a la caixa
    assert _recarrega(client, enc, mid, 500).status_code == 201           # la gerència sempre
    assert client.get(f"/socis/{mid}/moneder", headers=enc).json()["saldo_cent"] == 1000
    # recepció pot treballar amb la caixa; el dispensari no
    assert client.post("/caixa/tancar", json={"local_id": 1, "counted_cent": 1000}, headers=disp).status_code == 200
    assert client.post("/caixa/obrir", json={"local_id": 1, "opening_cent": 0}, headers=disp).status_code == 201
    client.post("/auth/rol-dia", json={"rol": "dispensari"}, headers=disp)
    assert client.post("/caixa/tancar", json={"local_id": 1, "counted_cent": 1000}, headers=disp).status_code == 403
    # el dispensari sí gestiona productes i estoc; recepció no
    assert client.post("/productes", json={"local_id": 1, "nom": "Nou", "preu_cent_per_g": 5, "es_genetic": True}, headers=disp).status_code == 201
    client.post("/auth/rol-dia", json={"rol": "recepcio"}, headers=disp)
    assert client.post("/productes", json={"local_id": 1, "nom": "Nou2", "preu_cent_per_g": 5}, headers=disp).status_code == 403


# ---------- 2. socis: expulsat, tipus, inactivitat ----------

def test_un_soci_expulsat_no_pot_entrar_ni_dispensar(ctx):
    client, _, sec = ctx
    enc, flor, aigua, mid = _escena(client, sec)
    assert client.post(f"/socis/{mid}/entrada", headers=enc).status_code == 201
    assert client.post(f"/socis/{mid}/estat", json={"estat": "expulsat"}, headers=enc).status_code == 200
    r = client.post(f"/socis/{mid}/entrada", headers=enc)
    assert r.status_code == 422 and "expulsat" in r.text.lower()
    _recarrega(client, enc, mid, 1000)
    assert client.post("/dispensacions", json={"member_id": mid, "product_id": flor, "grams": "1", "metode": "monedero"}, headers=enc).status_code == 422


def test_el_tipus_de_membre_fixa_el_descompte_i_el_producte_sense_descomptes_no_el_rep(ctx):
    client, _, sec = ctx
    enc, flor, aigua, mid = _escena(client, sec)
    _recarrega(client, enc, mid, 10000)
    sd = client.post("/productes", json={"local_id": 1, "nom": "Preu fix", "categoria": "Weed", "preu_cent_per_g": 1000, "es_genetic": True,
                                         "sense_descomptes": True, "estricte": True}, headers=enc).json()["id"]
    client.post("/moviments/entrada", json={"product_id": sd, "grams": "50"}, headers=enc)
    assert client.get(f"/socis/{mid}", headers=enc).json()["tipus"] == "Ordinari"
    for tipus, pct in (("terapeutico", 20), ("Família", 30), ("Ordinari", 0)):
        assert client.patch(f"/socis/{mid}", json={"tipus": tipus}, headers=enc).status_code == 200
        assert client.get(f"/socis/{mid}", headers=enc).json()["descompte_pct"] == pct, tipus
    client.patch(f"/socis/{mid}", json={"tipus": "Terapèutic"}, headers=enc)
    r = client.post("/dispensacions", json={"member_id": mid, "product_id": flor, "grams": "1", "metode": "monedero"}, headers=enc).json()
    assert r["import_cent"] == 800                                                    # 10 € amb el 20 % de descompte
    r = client.post("/dispensacions", json={"member_id": mid, "product_id": sd, "grams": "1", "metode": "monedero"}, headers=enc).json()
    assert r["import_cent"] == 1000                                                   # «no aplicar descomptes»: el preu no canvia per a ningú
    nou = client.post("/socis", json={**SOCI, "document": "87654321X", "nom": "Berta", "tipus": "Família"}, headers=enc).json()["id"]
    assert client.get(f"/socis/{nou}", headers=enc).json()["descompte_pct"] == 30


def test_inactivitat_demana_cobrar_la_quota_en_fer_l_entrada(ctx):
    client, factory, sec = ctx
    enc, flor, aigua, mid = _escena(client, sec)
    with factory() as s:
        s.get(Member, mid).creat = datetime.now(timezone.utc) - timedelta(days=200)
        s.commit()
    r = client.post(f"/socis/{mid}/entrada", headers=enc).json()
    assert r["inactivitat"]["dies"] >= 199 and r["inactivitat"]["limit"] == 90 and r["inactivitat"]["ultima"] is None
    client.post(f"/socis/{mid}/sortida", headers=enc)
    _recarrega(client, enc, mid, 2000)
    assert client.post("/dispensacions", json={"member_id": mid, "product_id": aigua, "grams": "1", "metode": "monedero"}, headers=enc).status_code == 201
    assert client.post(f"/socis/{mid}/entrada", headers=enc).json()["inactivitat"] is not None   # un no genètic no compta
    client.post(f"/socis/{mid}/sortida", headers=enc)
    assert client.post("/dispensacions", json={"member_id": mid, "product_id": flor, "grams": "1", "metode": "monedero"}, headers=enc).status_code == 201
    assert client.post(f"/socis/{mid}/entrada", headers=enc).json()["inactivitat"] is None        # retirada de genètica recent
    client.post(f"/socis/{mid}/sortida", headers=enc)
    assert client.put("/locals/1/config", json={"cuota_inactivitat_dies": 0}, headers=token(client, sec, "admin")).status_code == 200


# ---------- 3. carret ----------

def test_carret_paga_del_monedero_amb_regal_i_es_tot_o_res(ctx):
    client, _, sec = ctx
    enc, flor, aigua, mid = _escena(client, sec)
    client.patch(f"/productes/{aigua}", json={"regalable": True}, headers=enc)
    _recarrega(client, enc, mid, 3000)
    cos = {"member_id": mid, "linies": [{"product_id": flor, "grams": "2"}, {"product_id": aigua, "grams": "3", "regal": True}]}
    r = client.post("/dispensacions/carret", json=cos, headers=enc)
    assert r.status_code == 201
    d = r.json()
    assert d["total_cent"] == 2000 and d["subtotal_cent"] == 2000 and d["saldo_cent"] == 1000
    assert [(l["producte"], l["quantitat"], l["import_cent"], l["regal"]) for l in d["linies"]] == [("Flor", "2", 2000, False), ("Aigua", "3", 0, True)]
    # sense saldo suficient: no es dispensa res (ni la línia que sí hi cabia)
    antes = client.get("/locals/1/estoc", headers=enc).json()
    r = client.post("/dispensacions/carret", json={"member_id": mid, "linies": [{"product_id": aigua, "grams": "1"}, {"product_id": flor, "grams": "5"}]}, headers=enc)
    assert r.status_code == 422 and "insuficient" in r.text.lower()
    assert client.get("/locals/1/estoc", headers=enc).json() == antes
    assert client.get(f"/socis/{mid}/moneder", headers=enc).json()["saldo_cent"] == 1000
    # producte repetit i carret buit
    assert client.post("/dispensacions/carret", json={"member_id": mid, "linies": [{"product_id": flor, "grams": "1"}, {"product_id": flor, "grams": "1"}]}, headers=enc).status_code == 422
    assert client.post("/dispensacions/carret", json={"member_id": mid, "linies": []}, headers=enc).status_code == 422
    # repetir amb la mateixa referència no dispensa dues vegades
    ref = {"client_ref": "abcdef0123456789abcd", **{"member_id": mid, "linies": [{"product_id": flor, "grams": "1"}]}}
    a, b = client.post("/dispensacions/carret", json=ref, headers=enc), client.post("/dispensacions/carret", json=ref, headers=enc)
    assert a.json() == b.json() and client.get(f"/socis/{mid}/moneder", headers=enc).json()["saldo_cent"] == 0


def test_resum_de_dispensar_consum_del_mes_saldo_i_darreres_retirades(ctx):
    client, _, sec = ctx
    enc, flor, aigua, mid = _escena(client, sec)
    _recarrega(client, enc, mid, 5000)
    client.post("/dispensacions/carret", json={"member_id": mid, "linies": [{"product_id": flor, "grams": "1.5"}, {"product_id": aigua, "grams": "2"}]}, headers=enc)
    r = client.get(f"/socis/{mid}/resum-dispensar", headers=token(client, sec, "disp")).json()
    assert r["mes_g"] == "1.5" and r["saldo_cent"] == 5000 - 1500 - 400                 # només els genètics compten al consum del mes
    assert [(x["producte"], x["quantitat"]) for x in r["darreres"]] == [("Aigua", "2"), ("Flor", "1.5")]   # de la més recent a la més antiga


# ---------- 4. productes ----------

def test_regles_del_producte_no_genetic_per_unitat_categories_i_tara(ctx):
    client, _, sec = ctx
    enc = token(client, sec, "enc")
    nou = lambda **k: client.post("/productes", json={"local_id": 1, "preu_cent_per_g": 100, "estricte": True, **k}, headers=enc)  # noqa: E731
    assert nou(nom="A", es_genetic=False, unitat="g", categoria="Beguda").status_code == 422         # un no genètic sempre per unitat
    assert nou(nom="B", es_genetic=False, unitat="u", categoria="Weed").status_code == 422           # Weed és de genètiques
    assert nou(nom="C", es_genetic=True, unitat="g", categoria="Beguda").status_code == 422
    assert nou(nom="D", es_genetic=False, unitat="u", categoria="Merch", tara_g="5").status_code == 422   # la tara és de genètics
    ok = nou(nom="E", es_genetic=True, unitat="g", categoria="Hash", tara_g="120.5", preu_entrada_cent=400, regalable=True)
    assert ok.status_code == 201
    p = {x["id"]: x for x in client.get("/locals/1/productes", headers=enc).json()}[ok.json()["id"]]
    assert p["tara_g"] == "120.5" and p["preu_entrada_cent"] == 400 and p["granel"] is True and p["sense_descomptes"] is False
    pre = nou(nom="F", es_genetic=True, unitat="u", categoria="Preroll")                             # un genètic també es pot vendre per unitat
    assert pre.status_code == 201
    p = {x["id"]: x for x in client.get("/locals/1/productes", headers=enc).json()}[pre.json()["id"]]
    assert p["granel"] is False                                                                      # «a granel» és sinònim de vendre en grams


def test_esborrar_productes_nomes_la_gerencia_i_sense_moviments(ctx):
    client, _, sec = ctx
    enc, flor, aigua, mid = _escena(client, sec)
    disp = token(client, sec, "disp")
    client.post("/auth/rol-dia", json={"rol": "dispensari"}, headers=disp)
    lliure = client.post("/productes", json={"local_id": 1, "nom": "Lliure", "preu_cent_per_g": 5}, headers=enc).json()["id"]
    assert client.delete(f"/productes/{lliure}", headers=disp).status_code == 403                    # els treballadors només activen/desactiven
    assert client.patch(f"/productes/{lliure}", json={"actiu": False}, headers=disp).status_code == 200
    assert client.delete(f"/productes/{flor}", headers=enc).status_code == 422                       # ja té moviments: es desactiva
    assert client.delete(f"/productes/{lliure}", headers=enc).status_code == 200
    assert lliure not in [p["id"] for p in client.get("/locals/1/productes", headers=enc).json()]


# ---------- 5. existències i moviments ----------

def test_existencies_per_lloc_avis_d_estoc_baix_i_moviments_amb_historial(ctx):
    client, _, sec = ctx
    enc, flor, aigua, mid = _escena(client, sec)
    ex = client.get("/locals/1/existencies", headers=enc).json()
    mag = ex["magatzem_id"]
    assert ex["baix_g"] == "5" and {p["nom"]: (p["dispensari_g"], p["magatzem_g"], p["estat"]) for p in ex["productes"]} == {"Flor": ("50", "0", "ok"), "Aigua": ("50", "0", "ok")}
    # entrada directa al magatzem, traspàs al dispensari i sortida des del magatzem
    assert client.post("/moviments/entrada", json={"product_id": flor, "grams": "30", "magatzem_id": mag, "nota": "compra"}, headers=enc).status_code == 201
    assert client.post("/moviments/traspas", json={"product_id": flor, "de": mag, "a": None, "grams": "5"}, headers=enc).status_code == 201
    assert client.post("/moviments/merma", json={"product_id": flor, "grams": "2", "nota": "humitat", "magatzem_id": mag}, headers=enc).status_code == 201
    assert client.post("/moviments/merma", json={"product_id": flor, "grams": "100", "nota": "massa", "magatzem_id": mag}, headers=enc).status_code == 422
    f = {p["nom"]: p for p in client.get("/locals/1/existencies", headers=enc).json()["productes"]}["Flor"]
    assert (f["dispensari_g"], f["magatzem_g"]) == ("55", "23")
    h = client.get(f"/productes/{flor}/moviments", headers=enc).json()
    assert [(x["tipus"], x["lloc"], x["nota"]) for x in h][:2] == [("merma", "Magatzem", "humitat"), ("traspas", "Magatzem", None)] or h[0]["tipus"] == "merma"
    assert h[0]["usuari"] == "enc" and len(h) <= 10
    # avís: baix al dispensari i esgotat
    client.post("/moviments/merma", json={"product_id": aigua, "grams": "47", "nota": "ús intern"}, headers=enc)   # queden 3 u (< 5)
    client.post("/moviments/merma", json={"product_id": flor, "grams": "55", "nota": "tot"}, headers=enc)           # dispensari buit, magatzem 23
    estat = {p["nom"]: p["estat"] for p in client.get("/locals/1/existencies", headers=enc).json()["productes"]}
    assert estat == {"Flor": "baix", "Aigua": "baix"}
    client.put("/locals/1/config", json={"estoc_baix_mg": 1000}, headers=token(client, sec, "admin"))
    estat = {p["nom"]: p["estat"] for p in client.get("/locals/1/existencies", headers=enc).json()["productes"]}
    assert estat == {"Flor": "baix", "Aigua": "ok"}                                                      # límit personalitzable


# ---------- revisió independent: mínim privilegi ----------

def test_sense_rol_del_dia_un_treballador_no_te_acces_ni_a_recepcio_ni_al_dispensari(ctx):
    client, _, sec = ctx
    enc, flor, aigua, mid = _escena(client, sec)
    _recarrega(client, enc, mid, 2000)
    sense = token(client, sec, "disp", rol=False)                                    # no ha triat rol
    assert _recarrega(client, sense, mid, 100).status_code == 403
    assert client.post("/caixa/tancar", json={"local_id": 1, "counted_cent": 0}, headers=sense).status_code == 403
    assert client.post("/productes", json={"local_id": 1, "nom": "X", "preu_cent_per_g": 1}, headers=sense).status_code == 403
    assert client.post("/dispensacions/carret", json={"member_id": mid, "linies": [{"product_id": flor, "grams": "1"}]}, headers=sense).status_code == 403
    assert client.post("/dispensacions", json={"member_id": mid, "product_id": flor, "grams": "1", "metode": "monedero"}, headers=sense).status_code == 403
    rec = token(client, sec, "disp", rol="recepcio")                                 # recepció no dispensa
    assert client.post("/dispensacions/carret", json={"member_id": mid, "linies": [{"product_id": flor, "grams": "1"}]}, headers=rec).status_code == 403


def test_les_correccions_de_caixa_son_de_la_gerencia_i_les_observacions_les_tanca_qui_les_va_crear(ctx):
    client, _, sec = ctx
    enc, flor, aigua, mid = _escena(client, sec)
    rec = token(client, sec, "disp", rol="recepcio")
    ap = client.post("/despeses", json={"local_id": 1, "cent": 500, "metode": "efectiu", "categoria": "neteja", "concepte": "lleixiu"}, headers=rec)
    assert ap.status_code == 201                                                     # recepció registra despeses
    assert client.post(f"/caixa/apunts/{ap.json()['apunt']}/correccio", json={"nota": "m'ho quedo"}, headers=rec).status_code == 403
    assert client.post(f"/caixa/apunts/{ap.json()['apunt']}/correccio", json={"nota": "import equivocat"}, headers=enc).status_code == 201
    disp = token(client, sec, "disp")
    altre = client.post(f"/socis/{mid}/incidencies", json={"descripcio": "Mal comportament", "tipus": "comportament", "alerta": True}, headers=enc).json()["id"]
    propia = client.post(f"/socis/{mid}/incidencies", json={"descripcio": "Ha deixat les claus", "tipus": "objecte"}, headers=disp).json()["id"]
    assert client.post(f"/incidencies/{altre}/tanca", headers=disp).status_code == 403   # no pot esborrar l'avís d'un altre
    assert client.post(f"/incidencies/{propia}/tanca", headers=disp).status_code == 200  # la seva sí
    assert client.post(f"/incidencies/{altre}/tanca", headers=enc).status_code == 200


def test_ajustar_un_inventari_de_no_genetics_reparteix_la_falta_entre_dispensari_i_magatzem(ctx):
    client, _, sec = ctx
    enc, flor, aigua, mid = _escena(client, sec)                                     # Aigua: 50 u al dispensari
    mag = client.get("/locals/1/existencies", headers=enc).json()["magatzem_id"]
    client.post("/moviments/traspas", json={"product_id": aigua, "de": None, "a": mag, "grams": "45"}, headers=enc)   # 5 u al dispensari, 45 al magatzem
    sid = client.post("/locals/1/inventaris", json={"tipus": "no_genetiques"}, headers=enc).json()["id"]
    assert client.put(f"/inventaris/{sid}/linies/{aigua}", json={"grams": "40"}, headers=enc).status_code == 200      # falten 10 u
    assert client.put(f"/inventaris/{sid}/linies/{aigua}", json={"grams": "40.5"}, headers=enc).status_code == 422    # unitats senceres
    client.post(f"/inventaris/{sid}/guardar", headers=enc)
    assert client.post(f"/inventaris/{sid}/ajustar", headers=enc).json() == {"ajustos": 1}
    ex = {p["id"]: p for p in client.get("/locals/1/existencies", headers=enc).json()["productes"]}[aigua]
    assert (ex["dispensari_g"], ex["magatzem_g"]) == ("0", "40")                     # primer surt del dispensari i la resta del magatzem


# ---------- permisos per usuari ----------

def test_permisos_per_usuari_informes_historial_i_esborrar_productes(ctx):
    client, factory, sec = ctx
    enc, flor, aigua, mid = _escena(client, sec)
    adm = token(client, sec, "admin")
    disp = token(client, sec, "disp")
    uid = [u["id"] for u in client.get("/usuaris", headers=adm).json() if u["username"] == "disp"][0]
    rang = {"des": "2020-01-01", "fins": "2099-01-01"}
    lliure = client.post("/productes", json={"local_id": 1, "nom": "Lliure", "preu_cent_per_g": 5}, headers=enc).json()["id"]
    # sense permisos addicionals
    assert client.get("/locals/1/informe", params=rang, headers=disp).status_code == 403
    assert client.get("/locals/1/moviments", params=rang, headers=disp).status_code == 403
    assert client.delete(f"/productes/{lliure}", headers=disp).status_code == 403
    assert client.get("/me", headers=disp).json()["permisos"] == []
    # només l'administrador els assigna, i només claus conegudes
    assert client.put(f"/usuaris/{uid}/permisos", json={"permisos": ["informes"]}, headers=enc).status_code == 403
    assert client.put(f"/usuaris/{uid}/permisos", json={"permisos": ["volar"]}, headers=adm).status_code == 422
    uid_enc = [u["id"] for u in client.get("/usuaris", headers=adm).json() if u["username"] == "enc"][0]
    assert client.put(f"/usuaris/{uid_enc}/permisos", json={"permisos": ["informes"]}, headers=adm).status_code == 422   # la gerència ja ho pot tot
    r = client.put(f"/usuaris/{uid}/permisos", json={"permisos": ["informes", "esborrar_productes", "informes"]}, headers=adm)
    assert r.status_code == 200 and r.json() == {"permisos": ["esborrar_productes", "informes"]}
    disp = token(client, sec, "disp")                                                  # nova sessió amb els permisos
    assert client.get("/me", headers=disp).json()["permisos"] == ["esborrar_productes", "informes"]
    assert client.get("/locals/1/informe", params=rang, headers=disp).status_code == 200
    assert client.get("/locals/1/moviments", params=rang, headers=disp).status_code == 403       # no li'n va donar
    assert client.delete(f"/productes/{lliure}", headers=disp).status_code == 200
    assert [x["clau"] for x in client.get("/permisos", headers=disp).json()][0] == "informes"
    assert client.get("/me", headers=enc).json()["permisos"] == sorted(x["clau"] for x in client.get("/permisos", headers=enc).json())   # la gerència els té tots


def test_migracio_aplica_el_descompte_del_tipus_als_socis_antics(ctx):
    from app import service
    client, factory, sec = ctx
    enc, flor, aigua, mid = _escena(client, sec)
    altre = client.post("/socis", json={**SOCI, "document": "87654321X", "nom": "Berta"}, headers=enc).json()["id"]
    with factory() as s:
        s.get(Member, mid).tipus, s.get(Member, mid).descompte_pct = "Terapèutic", 0      # soci d'abans del descompte automàtic
        s.get(Member, altre).tipus, s.get(Member, altre).descompte_pct = "Família", 10     # amb un descompte propi: no es toca
        s.commit()
        assert service.sincronitza_descomptes_tipus(s) == 1
        assert (s.get(Member, mid).descompte_pct, s.get(Member, altre).descompte_pct) == (20, 10)
        assert service.sincronitza_descomptes_tipus(s) == 0                              # idempotent


def test_tope_de_donacions_per_treballador_i_dia(ctx):
    client, _, sec = ctx
    enc, flor, aigua, mid = _escena(client, sec)
    adm = token(client, sec, "admin")
    rec = token(client, sec, "disp", rol="recepcio")
    assert client.put("/locals/1/config", json={"donacions_dia_max_cent": 5000}, headers=adm).status_code == 200
    assert _recarrega(client, rec, mid, 3000).status_code == 201
    r = _recarrega(client, rec, mid, 2500)                                    # 30 + 25 > 50 €
    assert r.status_code == 422 and "màxim per dia" in r.text
    assert _recarrega(client, rec, mid, 2000).status_code == 201              # justa el límit
    assert _recarrega(client, enc, mid, 9000).status_code == 201              # la gerència no té tope


def test_mermes_entrades_i_preus_del_dispensari_requereixen_permis_i_l_inventari_es_a_cegues(ctx):
    client, _, sec = ctx
    enc, flor, aigua, mid = _escena(client, sec)
    adm = token(client, sec, "admin")
    disp = token(client, sec, "disp")                                                     # dispensari sense permisos addicionals
    uid = [u["id"] for u in client.get("/usuaris", headers=adm).json() if u["username"] == "disp"][0]
    assert client.post("/moviments/entrada", json={"product_id": flor, "grams": "5"}, headers=disp).status_code == 403
    assert client.post("/moviments/merma", json={"product_id": flor, "grams": "1", "nota": "tapar un forat"}, headers=disp).status_code == 403
    assert client.patch(f"/productes/{flor}", json={"preu_cent_per_g": 0}, headers=disp).status_code == 403
    assert client.patch(f"/productes/{flor}", json={"regalable": True}, headers=disp).status_code == 403
    assert client.patch(f"/productes/{flor}", json={"nom": "Flor premium"}, headers=disp).status_code == 200     # el nom sí
    assert client.post("/productes", json={"local_id": 1, "nom": "Gratis", "preu_cent_per_g": 0}, headers=disp).status_code == 403
    assert client.post("/productes", json={"local_id": 1, "nom": "Nou", "preu_cent_per_g": 100}, headers=disp).status_code == 201
    # inventari a cegues: qui pesa no veu l'estoc del sistema ni la diferència
    sid = client.post("/locals/1/inventaris", json={}, headers=disp).json()["id"]
    linia = [l for l in client.get(f"/inventaris/{sid}", headers=disp).json()["linies"] if l["product_id"] == flor][0]
    assert "esperat_g" not in linia and "diferencia_g" not in linia
    assert client.put(f"/inventaris/{sid}/linies/{flor}", json={"grams": "7"}, headers=disp).json() == {"comptat_g": "7", "a_cegues": True}
    assert "esperat_g" in client.get(f"/inventaris/{sid}", headers=enc).json()["linies"][0]                       # la gerència sí
    # amb els permisos, sí
    assert client.put(f"/usuaris/{uid}/permisos", json={"permisos": ["moviments_estoc", "editar_preus", "resultats_inventari"]}, headers=adm).status_code == 200
    disp = token(client, sec, "disp")
    assert client.post("/moviments/entrada", json={"product_id": flor, "grams": "5"}, headers=disp).status_code == 201
    assert client.patch(f"/productes/{flor}", json={"regalable": True}, headers=disp).status_code == 200
    assert client.put(f"/inventaris/{sid}/linies/{flor}", json={"grams": "7"}, headers=disp).json()["diferencia_g"] is not None

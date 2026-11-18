"""Endpoints RGPD: alta amb consentiments, exportació, supressió, retenció, consulta d'auditoria i ancoratges."""
import base64

from app import textos
from tests.test_api import SOCI, ctx, env, token  # noqa: F401
from tests.test_rgpd_nucli import _sync_ret
from tests.test_stock import setup_data

PNG = base64.b64encode(b"\x89PNG\r\n\x1a\n" + bytes(range(256)) * 2).decode()
H = textos.sha256("v1", "ca")


def alta(client, h, **extra):
    mid = client.post("/socis", json=SOCI, headers=h).json()["id"]
    body = {"versio": "v1", "text_sha256": H, "finalitats": ["basic", "foto"], "doc_verificat": True, "png_base64": PNG, **extra}
    return mid, client.post(f"/socis/{mid}/alta-rgpd", json=body, headers=h)


def test_text_informatiu_en_tres_idiomes(ctx):
    client, _, sec = ctx
    enc = token(client, sec, "enc")
    hs = set()
    for idioma in ("ca", "es", "en"):
        r = client.get("/textos/informatiu", params={"idioma": idioma}, headers=enc).json()
        assert r["versio"] == textos.VERSIO_ACTUAL and r["sha256"] == textos.sha256(textos.VERSIO_ACTUAL, idioma) and len(r["text"]) > 200
        hs.add(r["sha256"])
    assert len(hs) == 3
    assert client.get("/textos/informatiu", params={"idioma": "fr"}, headers=enc).status_code == 404
    assert client.get("/textos/informatiu").status_code == 401


def test_alta_desa_consentiments_signatura_amb_hash_i_document(ctx):
    client, factory, sec = ctx
    enc = token(client, sec, "enc")
    mid, r = alta(client, enc)
    assert r.status_code == 201 and r.json()["consentiments"] == {"basic": True, "foto": True, "contacte": False, "consum": False}
    c = client.get(f"/socis/{mid}/consentiments", headers=enc).json()
    assert [(x["finalitat"], x["versio"], x["text_sha256"]) for x in c["historial"]] == [("basic", "v1", H), ("foto", "v1", H)]
    assert all(x["signature_id"] == r.json()["signatura"] for x in c["historial"])
    ex = client.get(f"/socis/{mid}/exportacio", headers=enc).json()
    assert ex["fitxa"]["doc_verificat"] is True and ex["signatures"][0]["text_sha256"] == H


def test_alta_exigeix_basic_i_text_conegut(ctx):
    client, _, sec = ctx
    enc = token(client, sec, "enc")
    mid = client.post("/socis", json=SOCI, headers=enc).json()["id"]
    cos = {"versio": "v1", "text_sha256": H, "finalitats": ["foto"]}
    assert client.post(f"/socis/{mid}/alta-rgpd", json=cos, headers=enc).status_code == 422
    assert client.post(f"/socis/{mid}/alta-rgpd", json={**cos, "finalitats": ["basic"], "text_sha256": "a" * 64}, headers=enc).status_code == 422
    assert client.post(f"/socis/{mid}/alta-rgpd", json={**cos, "finalitats": ["basic"]}, headers=token(client, sec, "disp")).status_code == 403


def test_retirada_de_consentiment_i_foto_bloquejada(ctx):
    import base64 as b
    client, _, sec = ctx
    enc = token(client, sec, "enc")
    mid, _ = alta(client, enc)
    jpeg = b.b64encode(b"\xff\xd8\xff\xe0" + bytes(range(256)) * 2).decode()
    assert client.post(f"/socis/{mid}/foto", json={"image_base64": jpeg}, headers=enc).status_code == 201
    assert client.post(f"/socis/{mid}/consentiments/retirada", json={"finalitat": "foto"}, headers=enc).json()["vigents"]["foto"] is False
    assert client.post(f"/socis/{mid}/foto", json={"image_base64": jpeg}, headers=enc).status_code == 422
    assert client.post(f"/socis/{mid}/consentiments/retirada", json={"finalitat": "basic"}, headers=enc).status_code == 422
    assert client.post(f"/socis/{mid}/consentiments", json={"versio": "v1", "text_sha256": H, "finalitats": ["foto"]}, headers=enc).status_code == 201
    assert client.post(f"/socis/{mid}/foto", json={"image_base64": jpeg}, headers=enc).status_code == 201


def test_exportacio_nomes_gestors_amb_dades_i_auditada(ctx):
    client, factory, sec = ctx
    enc, disp = token(client, sec, "enc"), token(client, sec, "disp")
    mid, pid = setup_data(client, enc, factory)
    client.post("/caixa/obrir", json={"local_id": 1, "opening_cent": 0}, headers=enc)
    client.post("/dispensacions", json={"member_id": mid, "product_id": pid, "grams": "2"}, headers=enc)
    client.post(f"/socis/{mid}/entrada", headers=enc)
    client.post(f"/socis/{mid}/quotes", json={"import_cent": 2000, "metode": "efectiu", "mesos": 1}, headers=enc)
    assert client.get(f"/socis/{mid}/exportacio", headers=disp).status_code == 403
    ex = client.get(f"/socis/{mid}/exportacio", headers=enc).json()
    assert ex["fitxa"]["nom"] == "Anna Prova" and ex["fitxa"]["document"] == "12345678Z" and ex["fitxa"]["email"] == "anna@example.com"
    assert len(ex["entrades"]) == 1 and len(ex["quotes"]) == 1 and ex["dispensacions"]["total"]["dispensacions"] == 1
    assert any(e["accio"] == "dispensacio" for e in ex["auditoria"])
    assert "image_base64" not in str(ex) and "png_enc" not in str(ex)
    csv = client.get(f"/socis/{mid}/exportacio/consum.csv", headers=enc)
    assert csv.status_code == 200 and csv.text.splitlines()[0] == "id,data,producte,grams,import_cent,corregida" and "Producte A" in csv.text
    adm = token(client, sec, "admin")
    acc = client.get(f"/socis/{mid}/accessos", headers=adm).json()["accessos"]
    assert [a["accio"] for a in acc].count("exporta_soci") == 1 and any(a["per_usuari"] == "enc" for a in acc)
    assert client.get(f"/socis/{mid}/accessos", headers=enc).status_code == 403


def test_consulta_de_consum_i_quotes_queden_auditades(ctx):
    client, factory, sec = ctx
    enc, adm = token(client, sec, "enc"), token(client, sec, "admin")
    mid, _ = setup_data(client, enc, factory)
    client.get(f"/socis/{mid}/consum", params={"des": "2020-01-01", "fins": "2099-01-01"}, headers=enc)
    client.get(f"/socis/{mid}/quotes", headers=enc)
    client.get(f"/socis/{mid}", headers=enc)
    acc = [a["accio"] for a in client.get(f"/socis/{mid}/accessos", headers=adm).json()["accessos"]]
    assert {"consulta_consum", "consulta_quotes", "consulta_soci"} <= set(acc)
    csv = client.get(f"/socis/{mid}/accessos.csv", headers=adm).text
    assert csv.splitlines()[0].startswith("seq,data,accio") and "consulta_consum" in csv


def test_consulta_d_auditoria_filtrada_i_paginada_nomes_admin(ctx):
    client, factory, sec = ctx
    enc, adm = token(client, sec, "enc"), token(client, sec, "admin")
    mid, _ = setup_data(client, enc, factory)
    for _ in range(3):
        client.get(f"/socis/{mid}", headers=enc)
    assert client.get("/auditoria/consulta", headers=enc).status_code == 403
    r = client.get("/auditoria/consulta", params={"soci": mid, "accio": "consulta_soci"}, headers=adm).json()
    assert len(r["entrades"]) == 3 and all(e["accio"] == "consulta_soci" and e["soci"] == mid for e in r["entrades"])
    p1 = client.get("/auditoria/consulta", params={"soci": mid, "limit": 2}, headers=adm).json()
    p2 = client.get("/auditoria/consulta", params={"soci": mid, "limit": 2, "offset": 2}, headers=adm).json()
    assert len(p1["entrades"]) == 2 and p1["hi_ha_mes"] is True
    assert {e["seq"] for e in p1["entrades"]}.isdisjoint({e["seq"] for e in p2["entrades"]})
    enc_id = client.get("/me", headers=enc).json()["id"]
    r = client.get("/auditoria/consulta", params={"usuari": enc_id, "des": "2020-01-01", "fins": "2099-01-01"}, headers=adm).json()
    assert r["entrades"] and all(e["per"] == enc_id for e in r["entrades"])
    assert client.get("/auditoria/consulta", params={"accio": "x'; DROP"}, headers=adm).status_code == 422


def test_supressio_endpoint_confirma_i_bloqueja_per_retencio(ctx, monkeypatch):
    client, factory, sec = ctx
    enc, adm = token(client, sec, "enc"), token(client, sec, "admin")
    mid, _ = alta(client, enc)
    assert client.post(f"/socis/{mid}/supressio", json={"confirmar": True}, headers=enc).status_code == 403
    monkeypatch.setenv("CLUB_RETENCIO_MIN_DIES", "30")
    client.post(f"/socis/{mid}/baixa", json={"motiu": "peticio del soci"}, headers=enc)
    assert client.post(f"/socis/{mid}/supressio", json={}, headers=adm).json() == {"aplicat": False, "bloqueig": "retencio", "min_dies": 30}
    assert client.post(f"/socis/{mid}/supressio", json={"confirmar": True}, headers=adm).status_code == 422
    monkeypatch.setenv("CLUB_RETENCIO_MIN_DIES", "0")
    _sync_ret(factory)
    r = client.post(f"/socis/{mid}/supressio", json={"confirmar": True, "motiu": "art. 17"}, headers=adm)
    assert r.status_code == 200 and r.json()["binaris_buidats"] == 1
    assert client.get(f"/socis/{mid}", headers=adm).json()["nom"] == f"Soci suprimit #{mid}"
    assert client.get("/auditoria/verificar", headers=adm).json()["integra"] is True


def test_retencio_endpoint_simula_i_exigeix_confirmacio(ctx, monkeypatch):
    monkeypatch.setenv("CLUB_RETENCIO_MIN_DIES", "0")
    client, factory, sec = ctx
    _sync_ret(factory)
    enc, adm = token(client, sec, "enc"), token(client, sec, "admin")
    mid = client.post("/socis", json=SOCI, headers=enc).json()["id"]
    client.post(f"/socis/{mid}/estat", json={"estat": "baixa"}, headers=enc)
    sim = client.get("/locals/1/retencio", headers=adm).json()
    assert sim["aplicat"] is False and sim["suprimibles"] == 1 and "Anna" not in str(sim)
    assert client.get(f"/socis/{mid}", headers=adm).json()["nom"] == "Anna Prova"  # la simulació no ha tocat res
    assert client.post("/locals/1/retencio/aplicar", json={}, headers=adm).status_code == 422
    assert client.post("/locals/1/retencio/aplicar", json={"confirmar": True}, headers=adm).json()["suprimits"][0]["soci"] == mid
    assert client.get("/locals/1/retencio", headers=enc).status_code == 403


def test_ancoratges_endpoint(ctx):
    client, _, sec = ctx
    adm, enc = token(client, sec, "admin"), token(client, sec, "enc")
    assert client.post("/auditoria/ancoratges", headers=enc).status_code == 403
    a = client.post("/auditoria/ancoratges", headers=adm).json()
    assert a["seq"] >= 1 and len(a["hash"]) == 64
    assert client.get("/auditoria/ancoratges", headers=adm).json()[0]["hash"] == a["hash"]
    v = client.get("/auditoria/verificar", headers=adm).json()
    assert v["integra"] is True and "ancoratge_intern" in v["avisos"]


def test_alta_enllaca_la_signatura_ja_desada(ctx):
    client, _, sec = ctx
    enc = token(client, sec, "enc")
    mid = client.post("/socis", json=SOCI, headers=enc).json()["id"]
    cos = {"versio": "v1", "text_sha256": H, "finalitats": ["basic", "contacte"], "sig_ultima": True}
    assert client.post(f"/socis/{mid}/alta-rgpd", json=cos, headers=enc).status_code == 422  # sense signatura
    sid = client.post(f"/socis/{mid}/signatura", json={"png_base64": PNG, "text_sha256": H}, headers=enc).json()["id"]
    assert client.post(f"/socis/{mid}/alta-rgpd", json=cos, headers=enc).status_code == 201
    h = client.get(f"/socis/{mid}/consentiments", headers=enc).json()["historial"]
    assert {x["signature_id"] for x in h} == {sid} and {x["text_sha256"] for x in h} == {H}


def test_s7_sig_ultima_exigeix_signatura_del_mateix_text_i_recent(ctx):
    from datetime import datetime, timedelta, timezone
    from sqlalchemy import update
    from app.models import Signature
    client, factory, sec = ctx
    enc = token(client, sec, "enc")
    mid = client.post("/socis", json=SOCI, headers=enc).json()["id"]
    cos = {"versio": "v1", "text_sha256": H, "finalitats": ["basic"], "sig_ultima": True}
    altre = textos.sha256("v1", "es")
    assert altre != H
    # signatura sense hash de text (o d'un altre text): no serveix per lligar aquest consentiment
    client.post(f"/socis/{mid}/signatura", json={"png_base64": PNG}, headers=enc)
    assert client.post(f"/socis/{mid}/alta-rgpd", json=cos, headers=enc).status_code == 422
    client.post(f"/socis/{mid}/signatura", json={"png_base64": PNG, "text_sha256": altre}, headers=enc)
    assert client.post(f"/socis/{mid}/alta-rgpd", json=cos, headers=enc).status_code == 422
    assert client.post(f"/socis/{mid}/signatura", json={"png_base64": PNG, "text_sha256": "x"}, headers=enc).status_code == 422
    # signatura del text correcte però vella
    sid = client.post(f"/socis/{mid}/signatura", json={"png_base64": PNG, "text_sha256": H}, headers=enc).json()["id"]
    with factory() as s:
        if s.get_bind().dialect.name == "sqlite":
            s.execute(update(Signature.__table__).where(Signature.id == sid).values(ts=datetime.now(timezone.utc) - timedelta(days=2)))
            s.commit()
            assert client.post(f"/socis/{mid}/alta-rgpd", json=cos, headers=enc).status_code == 422
            s.execute(update(Signature.__table__).where(Signature.id == sid).values(ts=datetime.now(timezone.utc)))
            s.commit()
    assert client.post(f"/socis/{mid}/alta-rgpd", json=cos, headers=enc).status_code == 201


def test_s6_retencio_per_local_no_toca_altres_locals_ni_dades_globals(ctx, monkeypatch):
    """La purga d'un local només afecta aquest local; intents de login i sessions són globals i només els compta/purga l'endpoint global."""
    from datetime import datetime, timedelta, timezone
    from sqlalchemy import select
    from app import service
    from app.models import LoginAttempt, MemberPhoto
    monkeypatch.setenv("CLUB_RETENCIO_FOTOS_DIES", "0")
    monkeypatch.setenv("CLUB_RETENCIO_INTENTS_DIES", "1")
    client, factory, sec = ctx
    _sync_ret(factory)
    adm, enc = token(client, sec, "admin"), token(client, sec, "enc")  # els inicis de sessió esborren intents vells: abans de crear-ne
    jpeg = base64.b64encode(b"\xff\xd8\xff\xe0" + bytes(range(256)) * 2).decode()
    m1 = client.post("/socis", json=SOCI, headers=adm).json()["id"]
    m2 = client.post("/socis", json={**SOCI, "local_id": 2, "document": "87654321X"}, headers=adm).json()["id"]
    for m in (m1, m1, m2, m2):
        assert client.post(f"/socis/{m}/foto", json={"image_base64": jpeg}, headers=adm).status_code in (200, 201)
    with factory() as s:
        s.add(LoginAttempt(username="vell", ts=datetime.now(timezone.utc) - timedelta(days=5)))
        s.commit()
    r = client.post("/locals/1/retencio/aplicar", json={"confirmar": True}, headers=adm).json()
    assert r["fotos_velles"] == 1 and r["intents_login"] == 0 and r["sessions_caducades"] == 0
    with factory() as s:
        bui = {m: sum(1 for f in s.scalars(select(MemberPhoto).where(MemberPhoto.member_id == m)) if f.img_enc == "") for m in (m1, m2)}
        assert bui == {m1: 1, m2: 0}
        assert s.scalar(select(LoginAttempt.id).where(LoginAttempt.username == "vell")) is not None
    # endpoint global explícit (només admin)
    assert client.get("/retencio", headers=enc).status_code == 403
    assert client.post("/retencio/aplicar", json={"confirmar": True}, headers=enc).status_code == 403
    assert client.post("/retencio/aplicar", json={}, headers=adm).status_code == 422
    g = client.post("/retencio/aplicar", json={"confirmar": True}, headers=adm).json()
    assert g["fotos_velles"] == 1 and g["intents_login"] >= 1
    with factory() as s:
        assert s.scalar(select(LoginAttempt.id).where(LoginAttempt.username == "vell")) is None


def test_alta_amb_canal_o_finalitat_no_valids_no_deixa_res_desat(ctx):
    """Si el consentiment ha de fallar, la signatura i els controls de l'alta tampoc es desen (tot o res)."""
    from sqlalchemy import func, select
    from app.models import Consent, Signature
    client, factory, sec = ctx
    enc = token(client, sec, "enc")
    mid = client.post("/socis", json=SOCI, headers=enc).json()["id"]
    cos = {"versio": "v1", "text_sha256": H, "finalitats": ["basic", "foto"], "doc_verificat": True, "png_base64": PNG}
    for extra in ({"canal": "xyz"}, {"finalitats": ["basic", "x"]}):
        r = client.post(f"/socis/{mid}/alta-rgpd", json={**cos, **extra}, headers=enc)
        assert r.status_code == 422, r.text
        with factory() as s:
            assert s.scalar(select(func.count()).select_from(Signature).where(Signature.member_id == mid)) == 0
            assert s.scalar(select(func.count()).select_from(Consent).where(Consent.member_id == mid)) == 0
    ok = client.post(f"/socis/{mid}/alta-rgpd", json=cos, headers=enc)       # amb dades correctes sí que es desa
    assert ok.status_code == 201, ok.text
    with factory() as s:
        assert s.scalar(select(func.count()).select_from(Signature).where(Signature.member_id == mid)) == 1

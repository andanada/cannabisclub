"""Consentiments, supressió per seudonimització i retenció (capa de servei; els endpoints, a test_rgpd_api.py)."""
import base64
import os
import secrets
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.exc import DBAPIError

from app import consentiments, crypto, retencio, schema, service, supressio, textos
from app.db import make_session_factory
from app.models import Consent, ImmutableError, Member, MemberCard, MemberPhoto, Signature, User
from tests.test_api import SOCI, ctx, env, token  # noqa: F401

pg_only = pytest.mark.skipif(not os.environ.get("CLUB_TEST_PG_URL"), reason="Cal PostgreSQL (CLUB_TEST_PG_URL)")
PNG = base64.b64encode(b"\x89PNG\r\n\x1a\n" + bytes(range(256)) * 2).decode()
JPEG = base64.b64encode(b"\xff\xd8\xff\xe0" + bytes(range(256)) * 2).decode()


def _soci(client, enc, **extra):
    return client.post("/socis", json={**SOCI, **extra}, headers=enc).json()["id"]


def _sync_ret(factory):
    """A PostgreSQL la funció de buidatge llegeix la retenció de la BD (no de l'entorn): la sincronitzem com ho fa actualitzar-bd."""
    with factory() as s:
        if s.get_bind().dialect.name == "postgresql":
            schema.set_retention(s.get_bind())


def _admin(s):
    return s.scalar(select(User).where(User.username == "admin"))


def _dades_personals(client, enc, mid):
    client.post(f"/socis/{mid}/signatura", json={"png_base64": PNG}, headers=enc)
    client.post(f"/socis/{mid}/foto", json={"image_base64": JPEG}, headers=enc)
    client.post(f"/socis/{mid}/carnet", json={"codi": "CARNET-1"}, headers=enc)


def test_textos_versionats_amb_hash_per_idioma():
    assert textos.VERSIO_ACTUAL in textos.versions()
    h = textos.hashes("v1")
    assert set(h) == {"ca", "es", "en"} and len(set(h.values())) == 3
    assert textos.idioma_del_hash("v1", h["es"]) == "es" and textos.idioma_del_hash("v1", "0" * 64) is None


def test_consentiment_append_only_i_retirada_com_a_registre_nou(ctx):
    client, factory, sec = ctx
    enc = token(client, sec, "enc")
    mid = _soci(client, enc)
    with factory() as s:
        m, u = s.get(Member, mid), _admin(s)
        h = textos.sha256("v1", "ca")
        with pytest.raises(ValueError):
            consentiments.grant(s, u, m, ["foto"], "v1", "0" * 64)  # text desconegut
        with pytest.raises(ValueError):
            consentiments.grant(s, u, m, ["altres"], "v1", h)
        consentiments.grant(s, u, m, ["basic", "foto"], "v1", h)
        assert consentiments.status(s, mid) == {"basic": True, "foto": True, "contacte": False}
        consentiments.withdraw(s, u, m, "foto")
        assert consentiments.status(s, mid)["foto"] is False
        assert [(c["finalitat"], c["accio"]) for c in consentiments.history(s, mid)] == [("basic", "atorgat"), ("foto", "atorgat"), ("foto", "retirat")]
        with pytest.raises(ValueError):
            consentiments.withdraw(s, u, m, "foto")  # ja retirat
        with pytest.raises(ValueError):
            consentiments.withdraw(s, u, m, "basic")
        c = s.scalar(select(Consent))
        c.canal = "web"
        with pytest.raises(ImmutableError):
            s.flush()
        s.rollback()
        assert service.audit_verify(s) == (True, None)


def test_la_foto_exigeix_consentiment_nomes_si_el_soci_te_registre(ctx):
    client, factory, sec = ctx
    enc = token(client, sec, "enc")
    antic = _soci(client, enc)
    assert client.post(f"/socis/{antic}/foto", json={"image_base64": JPEG}, headers=enc).status_code == 201  # sense registre: com abans
    nou = _soci(client, enc, document="87654321X", nom="Berta Prova")
    with factory() as s:
        consentiments.grant(s, _admin(s), s.get(Member, nou), ["basic"], "v1", textos.sha256("v1", "ca"))
    assert client.post(f"/socis/{nou}/foto", json={"image_base64": JPEG}, headers=enc).status_code == 422
    with factory() as s:
        consentiments.grant(s, _admin(s), s.get(Member, nou), ["foto"], "v1", textos.sha256("v1", "ca"))
    assert client.post(f"/socis/{nou}/foto", json={"image_base64": JPEG}, headers=enc).status_code == 201


def test_signatura_queda_lligada_al_hash_del_text(ctx):
    client, factory, sec = ctx
    enc = token(client, sec, "enc")
    mid = _soci(client, enc)
    with factory() as s:
        h = textos.sha256("v1", "es")
        sig = service.save_signature(s, _admin(s), s.get(Member, mid), PNG, h)
        assert s.get(Signature, sig.id).text_sha256 == h


def test_supressio_bloquejada_si_no_es_de_baixa_o_no_ha_vencut_la_retencio(ctx, monkeypatch):
    client, factory, sec = ctx
    enc = token(client, sec, "enc")
    mid = _soci(client, enc)
    with factory() as s:
        m, u = s.get(Member, mid), _admin(s)
        with pytest.raises(ValueError, match="de baixa"):
            supressio.pseudonymize(s, u.id, m)
        service.set_member_status(s, u, m, "baixa")
        assert m.baixa_en is not None
        monkeypatch.setenv("CLUB_RETENCIO_MIN_DIES", "30")
        with pytest.raises(ValueError, match="conservació"):
            supressio.pseudonymize(s, u.id, m)
        assert supressio.bloqueig(s, m) == "retencio"
        monkeypatch.setenv("CLUB_RETENCIO_MIN_DIES", "0")
        assert supressio.bloqueig(s, m) is None


def test_supressio_buida_dades_personals_i_conserva_els_llibres(ctx, monkeypatch):
    monkeypatch.setenv("CLUB_RETENCIO_MIN_DIES", "0")
    client, factory, sec = ctx
    _sync_ret(factory)
    enc = token(client, sec, "enc")
    mid = _soci(client, enc)
    _dades_personals(client, enc, mid)
    client.post("/caixa/obrir", json={"local_id": 1, "opening_cent": 0}, headers=enc)
    pid = client.post("/productes", json={"local_id": 1, "nom": "P", "preu_cent_per_g": 500, "es_genetic": True}, headers=enc).json()["id"]
    client.post("/moviments/entrada", json={"product_id": pid, "grams": "10"}, headers=enc)
    client.post("/dispensacions", json={"member_id": mid, "product_id": pid, "grams": "2"}, headers=enc)
    with factory() as s:
        m, u = s.get(Member, mid), _admin(s)
        service.set_member_status(s, u, m, "baixa")
        r = supressio.pseudonymize(s, u.id, m, "peticio")
        assert r["binaris_buidats"] == 2 and r["carnets_esborrats"] == 1
    with factory() as s:
        m = s.get(Member, mid)
        assert crypto.decrypt(m.nom_enc) == f"Soci suprimit #{mid}" and crypto.decrypt(m.document_enc) == "SUPRIMIT"
        assert m.telefon_enc is None and m.email_enc is None and m.suprimit_en is not None
        assert m.document_idx == supressio.pseudo_index(mid) and service.find_member_by_document(s, 1, SOCI["document"]) is None
        assert all(f.img_enc == "" for f in s.scalars(select(MemberPhoto)))
        assert all(f.png_enc == "" for f in s.scalars(select(Signature)))
        assert s.scalar(select(MemberCard.id).where(MemberCard.member_id == mid)) is None
        with pytest.raises(ValueError):
            service.set_member_status(s, _admin(s), m, "actiu")  # no es pot reactivar
        with pytest.raises(ValueError, match="ja està suprimit"):
            supressio.pseudonymize(s, u.id, m)
        assert service.audit_verify(s) == (True, None)
    # els moviments conserven el member_id (seudònim)
    mov = client.get("/locals/1/moviments", params={"des": "2020-01-01", "fins": "2099-01-01"}, headers=enc).json()
    assert any(x["soci_id"] == mid for x in mov)


def test_retencio_simula_per_defecte_i_aplica_nomes_amb_aplicar(ctx, monkeypatch):
    monkeypatch.setenv("CLUB_RETENCIO_MIN_DIES", "10")
    client, factory, sec = ctx
    _sync_ret(factory)
    enc = token(client, sec, "enc")
    vell, recent = _soci(client, enc), _soci(client, enc, document="87654321X", nom="Berta Prova")
    for i in (vell, recent):
        client.post(f"/socis/{i}/foto", json={"image_base64": JPEG}, headers=enc)
    with factory() as s:
        u = _admin(s)
        service.set_member_status(s, u, s.get(Member, vell), "baixa")
        service.set_member_status(s, u, s.get(Member, recent), "baixa")
        s.get(Member, vell).baixa_en = datetime.now(timezone.utc) - timedelta(days=11)
        s.commit()
        service.register_failure(s, "x")
        s.commit()
        r = retencio.run(s)
        assert r["aplicat"] is False and r["suprimibles"] == 1 and r["suprimits"] == []
        assert {c["soci"]: c["bloqueig"] for c in r["candidats"]} == {vell: None, recent: "retencio"}
        assert s.get(Member, vell).suprimit_en is None  # simulació: res canviat
        r = retencio.run(s, None, aplicar=True)
        assert [x["soci"] for x in r["suprimits"]] == [vell]
        assert s.get(Member, vell).suprimit_en is not None and s.get(Member, recent).suprimit_en is None


def test_purga_de_fotos_velles_deixa_la_darrera(ctx, monkeypatch):
    monkeypatch.setenv("CLUB_RETENCIO_FOTOS_DIES", "0")
    client, factory, sec = ctx
    _sync_ret(factory)
    enc = token(client, sec, "enc")
    mid = _soci(client, enc)
    for _ in range(3):
        client.post(f"/socis/{mid}/foto", json={"image_base64": JPEG}, headers=enc)
    with factory() as s:
        assert retencio.run(s)["fotos_velles"] == 2
        retencio.run(s, None, aplicar=True)
        fotos = s.scalars(select(MemberPhoto).order_by(MemberPhoto.id)).all()
        assert [bool(f.img_enc) for f in fotos] == [False, False, True]


# ---------- PostgreSQL: el rol de l'aplicació només pot buidar mitjançant la funció ----------

@pytest.fixture
def app_pg(ctx):
    client, owner_factory, sec = ctx
    with owner_factory() as s:
        owner_engine = s.get_bind()
        nom = s.execute(text("SELECT current_schema()")).scalar()
    pw = secrets.token_urlsafe(16)
    schema.create_app_role(owner_engine, "club_app_rgpd", pw)
    schema.grant_app_role(owner_engine, "club_app_rgpd")
    eng = create_engine(owner_engine.url.set(username="club_app_rgpd", password=pw), connect_args={"options": f"-csearch_path={nom}"})
    yield eng, client, sec, owner_factory
    eng.dispose()


@pg_only
def test_pg_el_rol_de_l_aplicacio_no_pot_buidar_amb_sql_directe(app_pg, monkeypatch):
    monkeypatch.setenv("CLUB_RETENCIO_MIN_DIES", "0")
    eng, client, sec, owner_factory = app_pg
    _sync_ret(owner_factory)
    enc = token(client, sec, "enc")
    mid = _soci(client, enc)
    _dades_personals(client, enc, mid)
    with make_session_factory(eng)() as s:
        for sql in ("UPDATE member_photos SET img_enc = ''", "UPDATE signatures SET png_enc = ''", "DELETE FROM member_photos",
                    "UPDATE member_photos SET mime = 'x'"):
            with pytest.raises(DBAPIError):
                s.execute(text(sql))
            s.rollback()
        # ni tan sols amb el «flag» posat per l'aplicació: el trigger exigeix venir de la funció del propietari
        with pytest.raises(DBAPIError):
            s.execute(text("SELECT set_config('club.supr_ok', '1', true)"))
            s.execute(text("UPDATE member_photos SET img_enc = ''"))
        s.rollback()
        # la funció exigeix que el soci estigui de baixa
        with pytest.raises(DBAPIError):
            s.execute(text("SELECT club_buida_binaris(:m, 'tot')"), {"m": mid})
        s.rollback()
    with owner_factory() as s:
        service.set_member_status(s, _admin(s), s.get(Member, mid), "baixa")
    with make_session_factory(eng)() as s:  # amb el rol restringit, el camí normal funciona
        u = _admin(s)
        r = supressio.pseudonymize(s, u.id, s.get(Member, mid))
        assert r["binaris_buidats"] == 2
        assert all(f.img_enc == "" for f in s.scalars(select(MemberPhoto)))
        assert service.audit_verify(s) == (True, None)
        with pytest.raises(DBAPIError):  # i seguim sense poder tocar les files directament
            s.execute(text("UPDATE member_photos SET img_enc = 'x'"))
        s.rollback()
        # fora de la funció: l'aplicació mai pot canviar mime ni esborrar
        with pytest.raises(DBAPIError):
            s.execute(text("DELETE FROM signatures"))
        s.rollback()


@pg_only
def test_pg_rol_de_l_aplicacio_fa_servir_les_funcions_rgpd_i_de_club(app_pg, monkeypatch):
    """Consentiments, lots, excepcions, ancoratges, TOTP persistent i exportació amb el rol sense privilegis."""
    import pyotp
    from fastapi.testclient import TestClient
    from app.main import create_app
    eng, owner_client, sec, owner_factory = app_pg
    client = TestClient(create_app(make_session_factory(eng)))
    monkeypatch.setenv("CLUB_TOTP_REPLAY", "1")
    codi = pyotp.TOTP(sec["enc"]).now()
    login = {"username": "enc", "password": "contrasenya-molt-llarga", "totp": codi}
    r = client.post("/auth/login", json=login)
    assert r.status_code == 200
    assert client.post("/auth/login", json=login).status_code == 401  # reutilitzar el codi: UPDATE de users.last_totp_step
    enc = {"Authorization": "Bearer " + r.json()["token"]}
    adm = token(client, sec, "admin")
    mid = _soci(client, enc)
    h = textos.sha256("v1", "ca")
    assert client.post(f"/socis/{mid}/signatura", json={"png_base64": PNG, "text_sha256": h}, headers=enc).status_code == 201
    assert client.post(f"/socis/{mid}/alta-rgpd", json={"versio": "v1", "text_sha256": h, "finalitats": ["basic", "foto"], "sig_ultima": True, "doc_verificat": True}, headers=enc).status_code == 201
    assert client.post(f"/socis/{mid}/consentiments/retirada", json={"finalitat": "foto"}, headers=enc).status_code == 200
    pid = client.post("/productes", json={"local_id": 1, "nom": "P", "preu_cent_per_g": 100, "es_genetic": True}, headers=enc).json()["id"]
    lot = client.post(f"/productes/{pid}/lots", json={"codi": "L1"}, headers=enc).json()["id"]
    assert client.post(f"/lots/{lot}/entrada", json={"grams": "5"}, headers=enc).status_code == 201
    assert client.put(f"/socis/{mid}/limits", json={"periode": "dia", "max_g": "4", "motiu": "recepta"}, headers=enc).status_code == 200
    assert client.post("/dispensacions", json={"member_id": mid, "product_id": pid, "grams": "2"}, headers=enc).status_code == 201
    assert client.get(f"/lots/{lot}/tracabilitat", headers=enc).json()["dispensat_mg"] == 2000
    assert client.put("/locals/1/club-config", json={"espera_dies": 1, "aval": "opcional", "alta_pendent": True}, headers=adm).status_code == 200
    assert client.get(f"/socis/{mid}/exportacio", headers=enc).status_code == 200
    assert client.get("/locals/1/llibres/estoc.csv", params={"des": "2020-01-01", "fins": "2099-01-01"}, headers=enc).status_code == 200
    assert client.post("/auditoria/ancoratges", headers=adm).status_code == 201
    assert client.get("/auditoria/verificar", headers=adm).json()["integra"] is True


def test_script_club_retencio_simula_i_nomes_aplica_amb_flag(tmp_path, monkeypatch, env, capsys):
    import importlib.util
    from pathlib import Path
    url = f"sqlite:///{tmp_path / 'r.db'}"
    monkeypatch.setenv("CLUB_DATABASE_URL", url)
    monkeypatch.setenv("CLUB_RETENCIO_MIN_DIES", "0")
    eng = create_engine(url)
    schema.install(eng)
    f = make_session_factory(eng)
    with f() as s:
        from app.models import Local
        s.add(Local(id=1, nom="L"))
        s.commit()
        u, _ = service.create_user(s, None, "adm", "contrasenya-molt-llarga", "admin", [])
        m = service.create_member(s, u, 1, "Anna Prova", "12345678Z", __import__("datetime").date(1990, 1, 1), None, None)
        service.set_member_status(s, u, m, "baixa")
        mid = m.id
    spec = importlib.util.spec_from_file_location("club_retencio", Path(__file__).resolve().parents[2] / "scripts" / "club-retencio.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.main([]) == 0
    assert '"aplicat": false' in capsys.readouterr().out
    with f() as s:
        assert s.get(Member, mid).suprimit_en is None
    assert mod.main(["--aplicar"]) == 0
    with f() as s:
        assert s.get(Member, mid).suprimit_en is not None

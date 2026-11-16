"""Avisos de configuració insegura a l'arrencada i reinici del segon factor d'un usuari."""
import logging

import pyotp
from sqlalchemy import select

from app import avisos, cli, crypto, service
from app.models import AuditLog, User
from tests.test_api import ctx, env, token  # noqa: F401


def neteja(monkeypatch):
    for v in ("CLUB_TOTP", "CLUB_TOTP_REPLAY", "CLUB_LOGIN_CARNET", "CLUB_CARNET_XARXES"):
        monkeypatch.delenv(v, raising=False)


def test_configuracio_per_defecte_no_dona_avisos_excepte_el_carnet_sense_xarxa(monkeypatch):
    neteja(monkeypatch)
    a = avisos.configuracio()
    assert not any("segon factor" in x for x in a)
    assert any("CLUB_CARNET_XARXES" in x and "100.64.0.0/10" in x for x in a)     # carnet actiu sense restricció de xarxa
    monkeypatch.setenv("CLUB_CARNET_XARXES", "100.64.0.0/10")
    assert avisos.configuracio() == []
    monkeypatch.setenv("CLUB_LOGIN_CARNET", "0")
    monkeypatch.delenv("CLUB_CARNET_XARXES")
    assert avisos.configuracio() == []                                            # carnet desactivat: res a avisar


def test_totp_desactivat_o_sense_antireus_avisa_en_gran(monkeypatch):
    neteja(monkeypatch)
    monkeypatch.setenv("CLUB_CARNET_XARXES", "100.64.0.0/10")
    monkeypatch.setenv("CLUB_TOTP", "0")
    monkeypatch.setenv("CLUB_TOTP_REPLAY", "0")
    a = avisos.configuracio()
    assert len(a) == 2 and all(x.startswith("ATENCIÓ") for x in a)
    assert any("CLUB_TOTP=0" in x for x in a) and any("CLUB_TOTP_REPLAY=0" in x for x in a)


def test_l_arrencada_escriu_els_avisos_al_registre(ctx, monkeypatch, caplog):
    from app.main import create_app
    neteja(monkeypatch)
    monkeypatch.setenv("CLUB_TOTP", "0")
    _, factory, _ = ctx
    with caplog.at_level(logging.WARNING):
        create_app(factory)
    assert any("CLUB_TOTP=0" in r.getMessage() for r in caplog.records)


def test_opcions_de_login_diu_si_el_segon_factor_esta_desactivat(ctx, monkeypatch):
    client, _, _ = ctx
    neteja(monkeypatch)
    assert client.get("/auth/opcions").json()["totp"] is True
    monkeypatch.setenv("CLUB_TOTP", "0")
    assert client.get("/auth/opcions").json()["totp"] is False


def test_reiniciar_totp_dona_un_secret_nou_i_el_vell_deixa_de_servir(ctx, capsys):
    client, factory, sec = ctx
    vell = sec["enc"]
    with factory() as s:
        n = cli.reiniciar_totp(s, "enc")
    out = capsys.readouterr().out
    nou = [l for l in out.splitlines() if l and " " not in l and l.isalnum() and len(l) >= 16][0]
    assert nou != vell and "otpauth://totp/" in out and nou in out
    with factory() as s:
        u = s.scalar(select(User).where(User.username == "enc"))
        assert crypto.decrypt(u.totp_secret_enc) == nou
        assert any('"accio":"reinici_totp"' in r.payload.replace(" ", "") for r in s.scalars(select(AuditLog)))
        assert "enc" not in "".join(r.payload for r in s.scalars(select(AuditLog)) if "reinici_totp" in r.payload)   # el nom no va a l'auditoria: l'id sí
    r = client.post("/auth/login", json={"username": "enc", "password": "bona-contrasenya-1" if False else __import__("tests.test_api", fromlist=["PASS"]).PASS,
                                          "totp": pyotp.TOTP(vell).now()})
    assert r.status_code == 401                                                   # el codi de l'app antiga ja no val
    r = client.post("/auth/login", json={"username": "enc", "password": __import__("tests.test_api", fromlist=["PASS"]).PASS,
                                          "totp": pyotp.TOTP(nou).now()})
    assert r.status_code == 200


def test_reiniciar_totp_d_un_usuari_inexistent_o_baixa_dona_error(ctx):
    client, factory, sec = ctx
    with factory() as s:
        try:
            cli.reiniciar_totp(s, "no-existeix")
            assert False, "havia de fallar"
        except ValueError as e:
            assert "no existeix" in str(e)

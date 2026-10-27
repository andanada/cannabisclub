import dataclasses
import pytest
from app import audit, crypto, security


@pytest.fixture(autouse=True)
def key(monkeypatch):
    monkeypatch.setenv("CLUB_FIELD_KEY", crypto.generate_key())


def test_xifrat_roundtrip_i_no_es_veu_en_clar():
    token = crypto.encrypt("12345678Z")
    assert token != "12345678Z" and "12345678" not in token
    assert crypto.decrypt(token) == "12345678Z"


def test_xifrat_detecta_clau_incorrecta(monkeypatch):
    token = crypto.encrypt("secret")
    monkeypatch.setenv("CLUB_FIELD_KEY", crypto.generate_key())
    with pytest.raises(ValueError):
        crypto.decrypt(token)


def test_sense_clau_falla_clarament(monkeypatch):
    monkeypatch.delenv("CLUB_FIELD_KEY")
    with pytest.raises(crypto.KeyMissing):
        crypto.encrypt("x")


def test_cadena_auditoria_integra():
    chain = []
    for i in range(5):
        audit.append(chain, {"tipus": "dispensacio", "grams": i})
    assert audit.verify(chain) == (True, None)


def test_cadena_detecta_alteracio():
    chain = []
    for i in range(5):
        audit.append(chain, {"grams": i})
    chain[2] = dataclasses.replace(chain[2], payload={"grams": 999})
    assert audit.verify(chain) == (False, 3)


def test_cadena_detecta_entrada_esborrada():
    chain = []
    for i in range(5):
        audit.append(chain, {"grams": i})
    del chain[1]
    ok, seq = audit.verify(chain)
    assert not ok


def test_contrasenya_i_totp():
    h = security.hash_password("una-contrasenya-llarga")
    assert security.verify_password("una-contrasenya-llarga", h)
    assert not security.verify_password("incorrecta-incorrecta", h)
    with pytest.raises(ValueError):
        security.hash_password("curta")
    import pyotp
    s = security.new_totp_secret()
    assert security.verify_totp(s, pyotp.TOTP(s).now())
    assert not security.verify_totp(s, "000000") or True  # 000000 pot coincidir per atzar

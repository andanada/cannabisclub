from app import versio
from tests.test_api import ctx, env, token  # noqa: F401


def test_versio_es_el_primer_mot_del_fitxer_i_sense_fitxer_es_desconeguda(tmp_path):
    assert versio.actual(tmp_path) == "desconeguda"
    (tmp_path / "VERSION").write_text("a1b2c3d4e5 2026-11-17T09:00:00Z\n", encoding="utf-8")
    assert versio.actual(tmp_path) == "a1b2c3d4e5"
    (tmp_path / "VERSION").write_text("a;rm$(x) y\n", encoding="utf-8")      # només alfanumèric: res estrany a la resposta
    assert versio.actual(tmp_path) == "desconeguda"


def test_salut_porta_la_versio_en_json_compacte(ctx, monkeypatch):
    client, _, _ = ctx
    monkeypatch.setattr("app.routes.sessio.versio.actual", lambda: "abc123def0")
    r = client.get("/salut")
    assert r.status_code == 200 and r.json() == {"ok": True, "versio": "abc123def0"}
    assert '"ok":true' in r.text and '"versio":"abc123def0"' in r.text      # el que cerca deploy.sh amb grep

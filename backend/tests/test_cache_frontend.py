"""Cache-Control: tot el que serveix el frontend es revalida sempre (no-cache); l'API i els errors, mai a la caché (no-store)."""
from pathlib import Path

from tests.test_api import ctx, env, token  # noqa: F401

FRONT = Path(__file__).resolve().parents[2] / "frontend"


def test_tots_els_fitxers_del_frontend_es_revaliden_sempre(ctx):
    client, _, _ = ctx
    fitxers = sorted(p.name for p in FRONT.iterdir() if p.is_file() and p.suffix in {".js", ".css", ".html", ".png", ".svg", ".webmanifest"})
    assert "views-club.js" in fitxers and "views-rgpd.js" in fitxers          # els que la llista a mà s'havia deixat
    for nom in fitxers:
        r = client.get("/" + nom)
        assert r.status_code == 200, nom
        assert r.headers["cache-control"] == "no-cache", (nom, r.headers["cache-control"])
    assert client.get("/").headers["cache-control"] == "no-cache"


def test_api_errors_i_inexistents_mai_a_la_cache(ctx):
    client, _, sec = ctx
    enc = token(client, sec, "enc")
    assert client.get("/salut").headers["cache-control"] == "no-store"
    assert client.get("/locals/1/estoc", headers=enc).headers["cache-control"] == "no-store"
    assert client.get("/no-existeix.js").headers["cache-control"] == "no-store"
    assert client.get("/locals/1/estoc").headers["cache-control"] == "no-store"     # 401
    assert client.get("/test/carnets.test.js").headers["cache-control"] == "no-store"   # carpeta bloquejada (404)

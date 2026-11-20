"""Ajudes de prova per a la caixa: activar targeta/Bizum al local (per defecte desactivats)."""
from tests.test_api import token


def activa_targeta(client, sec, local_id=1, actiu=True):
    adm = token(client, sec, "admin")
    r = client.put(f"/locals/{local_id}/config", json={"targeta_activa": actiu}, headers=adm)
    assert r.status_code == 200, r.text

"""Incidències (text xifrat) i avalats d'un soci."""
from app import crypto
from app.models import MemberIncident
from sqlalchemy import select

from tests.test_api import SOCI, ctx, env, token  # noqa: F401


def test_incidencia_xifrada_oberta_i_tancada(ctx):
    client, factory, sec = ctx
    enc, disp = token(client, sec, "enc"), token(client, sec, "disp")
    mid = client.post("/socis", json=SOCI, headers=enc).json()["id"]
    assert client.post(f"/socis/{mid}/incidencies", json={"descripcio": "Discussió amb un altre soci"}, headers=disp).status_code == 403
    r = client.post(f"/socis/{mid}/incidencies", json={"descripcio": "Discussió amb un altre soci"}, headers=enc)  # només els responsables
    assert r.status_code == 201
    assert client.get(f"/socis/{mid}/incidencies", headers=disp).status_code == 403  # però només els responsables les llegeixen
    l = client.get(f"/socis/{mid}/incidencies", headers=enc).json()
    assert l[0]["descripcio"] == "Discussió amb un altre soci" and l[0]["estat"] == "oberta" and l[0]["creat_per"] == "enc"
    with factory() as s:
        brut = s.scalar(select(MemberIncident.descripcio_enc))
        assert "Discussió" not in brut and "Discussió" in crypto.decrypt(brut)
    assert client.post(f"/incidencies/{r.json()['id']}/tanca", headers=disp).status_code == 403
    assert client.post(f"/incidencies/{r.json()['id']}/tanca", headers=enc).status_code == 200
    assert client.post(f"/incidencies/{r.json()['id']}/tanca", headers=enc).status_code == 422
    assert client.get(f"/socis/{mid}/incidencies", headers=enc).json()[0]["estat"] == "tancada"
    assert client.post(f"/socis/{mid}/incidencies", json={"descripcio": "x"}, headers=enc).status_code == 422


def test_avalats_i_exportacio(ctx):
    client, factory, sec = ctx
    enc = token(client, sec, "enc")
    av = client.post("/socis", json=SOCI, headers=enc).json()["id"]
    assert client.get(f"/socis/{av}/avalats", headers=enc).json() == []
    nou = client.post("/socis", json={**SOCI, "document": "87654321X", "nom": "Berta Prova"}, headers=enc).json()["id"]
    from app.models import Member
    with factory() as s:
        s.get(Member, nou).avalador_id = av
        s.commit()
    assert [x["nom"] for x in client.get(f"/socis/{av}/avalats", headers=enc).json()] == ["Berta Prova"]
    client.post(f"/socis/{av}/incidencies", json={"descripcio": "Nota interna"}, headers=enc)
    ex = client.get(f"/socis/{av}/exportacio", headers=enc).json()
    assert ex["incidencies"][0]["descripcio"] == "Nota interna"

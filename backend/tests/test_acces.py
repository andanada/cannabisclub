"""Control d'accés: entrada, sortida, «dins» i «fora», sortir-ne tots, quiosc RFID i informe de visites."""
from datetime import date

from tests.test_api import SOCI, ctx, env, token  # noqa: F401


def _soci(client, enc, doc="12345678Z", nom="Anna Prova"):
    return client.post("/socis", json={**SOCI, "document": doc, "nom": nom}, headers=enc).json()["id"]


def test_entrada_sortida_i_estat_dins_fora(ctx):
    client, _, sec = ctx
    enc = token(client, sec, "enc")
    a, b = _soci(client, enc), _soci(client, enc, "87654321X", "Berta Prova")
    e = client.get("/locals/1/acces", headers=enc).json()
    assert e["dins"] == [] and {x["nom"] for x in e["fora"]} == {"Anna Prova", "Berta Prova"}
    assert client.post(f"/socis/{a}/entrada", headers=enc).status_code == 201
    e = client.get("/locals/1/acces", headers=enc).json()
    assert [x["nom"] for x in e["dins"]] == ["Anna Prova"] and [x["nom"] for x in e["fora"]] == ["Berta Prova"]
    assert client.post(f"/socis/{b}/sortida", headers=enc).status_code == 422  # no hi és
    assert client.post(f"/socis/{a}/sortida", headers=enc).status_code == 201
    assert client.get("/locals/1/acces", headers=enc).json()["dins"] == []
    assert client.post(f"/socis/{a}/sortida", headers=enc).status_code == 422  # ja ha sortit


def test_sortir_tots_nomes_per_a_responsables(ctx):
    client, _, sec = ctx
    enc, disp = token(client, sec, "enc"), token(client, sec, "disp")
    a, b = _soci(client, enc), _soci(client, enc, "87654321X", "Berta Prova")
    client.post(f"/socis/{a}/entrada", headers=disp)
    client.post(f"/socis/{b}/entrada", headers=disp)
    assert client.get("/locals/1/acces", headers=disp).status_code == 200  # el dispensador veu la pantalla
    assert client.post("/locals/1/acces/sortir-tots", headers=disp).status_code == 403
    assert client.post("/locals/1/acces/sortir-tots", headers=enc).json() == {"sortits": 2}
    assert client.get("/locals/1/acces", headers=enc).json()["dins"] == []


def test_quiosc_carnet_alterna_entrada_i_sortida(ctx):
    client, _, sec = ctx
    enc = token(client, sec, "enc")
    a = _soci(client, enc)
    client.post(f"/socis/{a}/carnet", json={"codi": "CARNET-77"}, headers=enc)
    r1 = client.post("/locals/1/acces/carnet", json={"codi": "CARNET-77"}, headers=enc).json()
    r2 = client.post("/locals/1/acces/carnet", json={"codi": "CARNET-77"}, headers=enc).json()
    assert (r1["accio"], r2["accio"], r1["nom"]) == ("entrada", "sortida", "Anna Prova")
    assert client.post("/locals/1/acces/carnet", json={"codi": "NO-EXISTEIX"}, headers=enc).status_code == 404
    client.post(f"/socis/{a}/estat", json={"estat": "suspes"}, headers=enc)
    assert client.post("/locals/1/acces/carnet", json={"codi": "CARNET-77"}, headers=enc).status_code == 422


def test_visites_amb_sortida_i_assistencia_nomes_compta_entrades(ctx):
    client, _, sec = ctx
    enc = token(client, sec, "enc")
    a = _soci(client, enc)
    client.post(f"/socis/{a}/entrada", headers=enc)
    client.post(f"/socis/{a}/sortida", headers=enc)
    client.post(f"/socis/{a}/entrada", headers=enc)
    avui = date.today().isoformat()
    v = client.get("/locals/1/informe/visites", params={"des": avui, "fins": avui}, headers=enc).json()["visites"]
    assert len(v) == 2 and v[0]["sortida"] is not None and v[1]["sortida"] is None and v[0]["tipus"] == "Ordinari"
    at = client.get("/locals/1/informe/assistencia", params={"des": avui, "fins": avui}, headers=enc).json()
    assert at["total_entrades"] == 2  # les sortides no compten com a entrades
    assert "Anna Prova" in client.get("/locals/1/informe/visites.csv", params={"des": avui, "fins": avui}, headers=enc).text

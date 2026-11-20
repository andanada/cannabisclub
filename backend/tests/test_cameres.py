"""Càmeres IP en directe: adreces només de xarxa privada, adreça xifrada, permís, auditoria i, si hi ha ffmpeg, un flux real de prova."""
import json

import pytest
from sqlalchemy import select

from app import cameres, crypto
from app.models import AuditLog, Camera
from tests.test_api import ctx, env, token  # noqa: F401

JPEG = b"\xff\xd8\xff\xe0" + b"x" * 200 + b"\xff\xd9"


@pytest.fixture(autouse=True)
def sense_ffmpeg_real(monkeypatch):
    """Els tests no arrenquen ffmpeg: el fotograma es simula (el flux real té el seu test, si hi ha ffmpeg)."""
    cameres.atura_totes()
    monkeypatch.setattr(cameres, "frame", lambda camera_id, url: JPEG)
    monkeypatch.setattr(cameres, "ffmpeg_path", lambda: "/usr/bin/ffmpeg")
    yield
    cameres.atura_totes()


def test_nomes_adreces_rtsp_de_xarxa_privada_o_tailscale():
    ok = ["rtsp://admin:clau@192.168.1.20:554/stream1", "rtsp://10.0.0.5/live", "rtsps://172.16.4.9/x", "rtsp://100.101.102.103:554/a", "test://patro"]
    for u in ok:
        assert cameres.valida_url(u) == u
    for u in ["http://192.168.1.20/video", "rtsp://8.8.8.8/stream", "rtsp://127.0.0.1/x", "rtsp://169.254.169.254/latest", "rtsp://[::1]/x",
              "rtsp:///sense-servidor", "ftp://192.168.1.2/x", "rtsp://192.168.1.2/a b", "", "rtsp://100.63.0.1/x", "rtsp://172.32.0.1/x"]:
        with pytest.raises(ValueError):
            cameres.valida_url(u)


def test_alta_xifrada_llista_sense_credencials_i_frame_amb_permis(ctx):
    client, factory, sec = ctx
    adm, enc, disp = token(client, sec, "admin"), token(client, sec, "enc"), token(client, sec, "disp")
    secret = "rtsp://admin:CLAU-SECRETA@192.168.1.20:554/stream1"
    assert client.post("/locals/1/cameres", json={"nom": "Entrada", "url": secret}, headers=enc).status_code == 403      # només l'administrador
    assert client.post("/locals/1/cameres", json={"nom": "Mala", "url": "rtsp://8.8.8.8/x"}, headers=adm).status_code == 422
    cid = client.post("/locals/1/cameres", json={"nom": "Entrada", "url": secret}, headers=adm).json()["id"]
    assert client.post("/locals/1/cameres", json={"nom": "Entrada", "url": secret}, headers=adm).status_code == 422       # nom repetit
    with factory() as s:
        brut = s.scalar(select(Camera.url_enc))
        assert "CLAU-SECRETA" not in brut and "192.168" not in brut and crypto.decrypt(brut) == secret                  # xifrada a la BD
    llista = client.get("/locals/1/cameres", headers=enc)
    assert llista.status_code == 200 and llista.json()["cameres"] == [{"id": cid, "nom": "Entrada", "actiu": True, "ordre": 1, "servidor": "192.168.1.20:554"}]
    assert "CLAU-SECRETA" not in llista.text and "admin:" not in llista.text                                              # mai cap a la pantalla
    f = client.get(f"/cameres/{cid}/frame", headers=enc)
    assert f.status_code == 200 and f.headers["content-type"] == "image/jpeg" and f.content == JPEG and f.headers["cache-control"] == "no-store"
    # un treballador no hi té accés fins que l'administrador li dona el permís
    assert client.get("/locals/1/cameres", headers=disp).status_code == 403
    assert client.get(f"/cameres/{cid}/frame", headers=disp).status_code == 403
    uid = [u["id"] for u in client.get("/usuaris", headers=adm).json() if u["username"] == "disp"][0]
    assert client.put(f"/usuaris/{uid}/permisos", json={"permisos": ["cameres"]}, headers=adm).status_code == 200
    disp = token(client, sec, "disp")
    assert client.get(f"/cameres/{cid}/frame", headers=disp).status_code == 200
    assert client.get("/locals/2/cameres", headers=disp).status_code == 403                                               # un altre local
    # desactivada: no hi ha imatge; esborrada: 404
    assert client.put(f"/cameres/{cid}", json={"actiu": False}, headers=adm).status_code == 200
    assert client.get(f"/cameres/{cid}/frame", headers=enc).status_code == 409
    assert client.delete(f"/cameres/{cid}", headers=adm).status_code == 200
    assert client.get(f"/cameres/{cid}/frame", headers=enc).status_code == 404
    with factory() as s:
        accions = [json.loads(a.payload)["accio"] for a in s.scalars(select(AuditLog))]
    assert {"alta_camera", "veure_cameres", "edita_camera", "esborra_camera"} <= set(accions)
    with factory() as s:
        assert "CLAU-SECRETA" not in " ".join(a.payload for a in s.scalars(select(AuditLog)))                           # ni a l'auditoria


def test_si_no_arriba_imatge_es_503_amb_missatge_clar(ctx, monkeypatch):
    client, _, sec = ctx
    adm = token(client, sec, "admin")
    cid = client.post("/locals/1/cameres", json={"nom": "Pati", "url": "rtsp://192.168.1.30/x"}, headers=adm).json()["id"]
    def cau(camera_id, url):
        raise ValueError("No arriba imatge de la càmera")
    monkeypatch.setattr(cameres, "frame", cau)
    r = client.get(f"/cameres/{cid}/frame", headers=adm)
    assert r.status_code == 503 and "No arriba imatge" in r.text
    assert client.post(f"/cameres/{cid}/prova", headers=adm).json() == {"ok": False, "motiu": "No arriba imatge de la càmera"}


@pytest.mark.skipif(not __import__("shutil").which("ffmpeg"), reason="Cal ffmpeg")
def test_flux_real_amb_la_camera_de_prova(monkeypatch):
    monkeypatch.undo()   # sense simulacions: ffmpeg de veritat
    monkeypatch.setattr(cameres, "PRIMER_FRAME_S", 20)
    try:
        jpg = cameres.frame(999, "test://patro")
        assert jpg[:2] == b"\xff\xd8" and jpg[-2:] == b"\xff\xd9" and len(jpg) > 1000
        assert cameres.frame(999, "test://patro")[:2] == b"\xff\xd8"           # reutilitza el flux en marxa
    finally:
        cameres.atura_totes()

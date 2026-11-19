"""Càmeres IP (RTSP) en directe.

El navegador no sap llegir RTSP: el servidor del club llança `ffmpeg` per a cada càmera que algú està mirant, en treu fotogrames JPEG
(uns 2 per segon, 640 px d'ample) i els serveix amb autenticació. Quan ningú en demana durant 30 s, `ffmpeg` s'atura.

Seguretat:
  - L'adreça RTSP (amb l'usuari i la contrasenya de la càmera) es desa XIFRADA i mai no torna al navegador.
  - Només es permeten adreces de xarxa privada (192.168/16, 10/8, 172.16/12) o de Tailscale (100.64/10): el servidor no es pot fer servir per
    arribar a Internet (SSRF). `CLUB_CAMERES_HOSTS_LLIURES=1` ho desactiva (no recomanat).
  - `ffmpeg` s'executa sense shell, amb la llista d'arguments, i l'adreça no es registra enlloc.
  - Mirar les càmeres queda a l'auditoria (una entrada en obrir la pantalla)."""
import ipaddress
import os
import shutil
import socket
import subprocess
import threading
import time
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import crypto, service
from .models import Camera, User

MAX_PER_LOCAL = 16
MAX_ACTIVES = 8            # fluxos ffmpeg simultanis al servidor
INACTIVITAT_S = 30         # sense peticions, ffmpeg s'atura
PRIMER_FRAME_S = 8         # temps màxim d'espera del primer fotograma
ESQUEMES = {"rtsp", "rtsps", "test"}   # «test://» genera una imatge sintètica (per provar el programa sense càmera)
TAILSCALE = ipaddress.ip_network("100.64.0.0/10")


def ffmpeg_path() -> str | None:
    return os.environ.get("CLUB_FFMPEG") or shutil.which("ffmpeg")


def _ip_permesa(ip: str) -> bool:
    a = ipaddress.ip_address(ip)
    if a.is_loopback or a.is_link_local or a.is_multicast or a.is_unspecified:
        return False
    return a.is_private or a in TAILSCALE


def valida_url(url: str) -> str:
    """Torna l'adreça neta o llança ValueError. Cal rtsp://, rtsps:// (o test://) i un servidor de la xarxa privada."""
    url = (url or "").strip()
    p = urlparse(url)
    if p.scheme not in ESQUEMES:
        raise ValueError("L'adreça ha de començar per rtsp:// (o rtsps://)")
    if p.scheme == "test":
        return url
    if not p.hostname:
        raise ValueError("L'adreça no té servidor")
    if any(c in url for c in ("\n", "\r", "\0", " ")):
        raise ValueError("L'adreça no és vàlida")
    if os.environ.get("CLUB_CAMERES_HOSTS_LLIURES") == "1":
        return url
    try:
        ips = [p.hostname] if _es_ip(p.hostname) else sorted({i[4][0] for i in socket.getaddrinfo(p.hostname, p.port or 554, proto=socket.IPPROTO_TCP)})
    except OSError:
        raise ValueError("No es troba el servidor de la càmera")
    if not ips or not all(_ip_permesa(i) for i in ips):
        raise ValueError("La càmera ha de ser a la xarxa del club (192.168.x.x, 10.x.x.x, 172.16-31.x.x) o de Tailscale (100.64-127.x.x)")
    return url


def _es_ip(h: str) -> bool:
    try:
        ipaddress.ip_address(h)
        return True
    except ValueError:
        return False


def host_visible(url: str) -> str:
    p = urlparse(url)
    return "prova (imatge sintètica)" if p.scheme == "test" else (p.hostname or "?") + (f":{p.port}" if p.port else "")


def ordre_ffmpeg(url: str) -> list[str]:
    ff = ffmpeg_path()
    if not ff:
        raise RuntimeError("ffmpeg no està instal·lat al servidor (sudo apt install ffmpeg)")
    sortida = ["-an", "-vf", "fps=2,scale=640:-2", "-q:v", "6", "-f", "image2pipe", "-vcodec", "mjpeg", "-"]
    base = [ff, "-hide_banner", "-loglevel", "error"]
    if urlparse(url).scheme == "test":
        return base + ["-f", "lavfi", "-i", "testsrc2=size=640x360:rate=5"] + sortida
    return base + ["-rtsp_transport", "tcp", "-timeout", "8000000", "-i", url] + sortida


class Font:
    """Un fil per càmera: llegeix els JPEG de ffmpeg i guarda l'últim. S'atura sol quan ningú el mira."""

    def __init__(self, camera_id: int, url: str):
        self.id, self.url = camera_id, url
        self.ultim: bytes | None = None
        self.ts = 0.0
        self.peticio = time.time()
        self.error: str | None = None
        self.viu = True
        self.proc: subprocess.Popen | None = None
        self.fil = threading.Thread(target=self._corre, daemon=True, name=f"camera-{camera_id}")
        self.fil.start()

    def _corre(self) -> None:
        while self.viu and time.time() - self.peticio < INACTIVITAT_S:
            try:
                self.proc = subprocess.Popen(ordre_ffmpeg(self.url), stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL)
                buf = b""
                while self.viu and time.time() - self.peticio < INACTIVITAT_S:
                    tros = self.proc.stdout.read(65536)
                    if not tros:
                        break
                    buf += tros
                    while True:   # un JPEG va de FFD8 a FFD9
                        a = buf.find(b"\xff\xd8")
                        b = buf.find(b"\xff\xd9", a + 2) if a >= 0 else -1
                        if a < 0 or b < 0:
                            break
                        self.ultim, self.ts, self.error = buf[a:b + 2], time.time(), None
                        buf = buf[b + 2:]
                    buf = buf[-2_000_000:]
            except RuntimeError as e:
                self.error = str(e)
                break
            except OSError:
                self.error = "No s'ha pogut arrencar ffmpeg"
            finally:
                if self.proc and self.proc.poll() is None:
                    self.proc.kill()
            if self.viu and time.time() - self.peticio < INACTIVITAT_S:
                self.error = self.error or "La càmera no respon"
                time.sleep(2)   # reintent
        self.viu = False

    def para(self) -> None:
        self.viu = False
        if self.proc and self.proc.poll() is None:
            self.proc.kill()


_fonts: dict[int, Font] = {}
_pany = threading.Lock()


def frame(camera_id: int, url: str) -> bytes:
    """Últim fotograma de la càmera (arrenca la font si cal). ValueError si no n'arriba cap."""
    with _pany:
        f = _fonts.get(camera_id)
        if f is not None and (not f.viu or f.url != url):
            f.para()
            f = None
        if f is None:
            if sum(1 for x in _fonts.values() if x.viu) >= MAX_ACTIVES:
                raise ValueError("Hi ha massa càmeres obertes alhora")
            f = _fonts[camera_id] = Font(camera_id, url)
        f.peticio = time.time()
    limit = time.time() + PRIMER_FRAME_S
    while f.ultim is None and time.time() < limit and f.viu:
        time.sleep(0.1)
    if f.ultim is None:
        raise ValueError(f.error or "No arriba imatge de la càmera")
    return f.ultim


def atura_totes() -> None:
    with _pany:
        for f in _fonts.values():
            f.para()
        _fonts.clear()


# ---------- accés a dades ----------

def llista(db: Session, actor: User, local_id: int) -> list[dict]:
    service.audit_append(db, {"accio": "veure_cameres", "local": local_id, "per": actor.id})
    db.commit()
    return [{"id": c.id, "nom": c.nom, "actiu": c.actiu, "ordre": c.ordre, "servidor": host_visible(crypto.decrypt(c.url_enc))}
            for c in db.scalars(select(Camera).where(Camera.local_id == local_id).order_by(Camera.ordre, Camera.id))]


def crea(db: Session, actor: User, local_id: int, nom: str, url: str) -> Camera:
    nom = (nom or "").strip()
    if not 1 <= len(nom) <= 60:
        raise ValueError("El nom ha de tenir entre 1 i 60 caràcters")
    if db.scalar(select(Camera.id).where(Camera.local_id == local_id, Camera.nom == nom)):
        raise ValueError("Ja hi ha una càmera amb aquest nom")
    n = len(list(db.scalars(select(Camera.id).where(Camera.local_id == local_id))))
    if n >= MAX_PER_LOCAL:
        raise ValueError(f"Màxim {MAX_PER_LOCAL} càmeres per local")
    c = Camera(local_id=local_id, nom=nom, url_enc=crypto.encrypt(valida_url(url)), ordre=n + 1)
    db.add(c)
    db.flush()
    service.audit_append(db, {"accio": "alta_camera", "camera": c.id, "local": local_id, "per": actor.id})
    db.commit()
    return c


def edita(db: Session, actor: User, c: Camera, nom: str | None, url: str | None, actiu: bool | None, ordre: int | None) -> None:
    canvis = []
    if nom is not None and nom.strip() != c.nom:
        if not 1 <= len(nom.strip()) <= 60:
            raise ValueError("El nom ha de tenir entre 1 i 60 caràcters")
        c.nom = nom.strip()
        canvis.append("nom")
    if url:
        c.url_enc = crypto.encrypt(valida_url(url))
        canvis.append("adreça")
        atura_totes()
    if actiu is not None and actiu != c.actiu:
        c.actiu = actiu
        canvis.append("actiu")
    if ordre is not None and ordre != c.ordre:
        c.ordre = ordre
        canvis.append("ordre")
    if not canvis:
        raise ValueError("No hi ha cap canvi")
    service.audit_append(db, {"accio": "edita_camera", "camera": c.id, "camps": canvis, "per": actor.id})
    db.commit()


def esborra(db: Session, actor: User, c: Camera) -> None:
    service.audit_append(db, {"accio": "esborra_camera", "camera": c.id, "per": actor.id})
    db.delete(c)
    db.commit()
    atura_totes()


def url_de(c: Camera) -> str:
    return crypto.decrypt(c.url_enc)

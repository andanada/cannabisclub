"""Rutes: menú del club i pantalles (vegeu menus.py). Les rutes /pantalla/<token>… són públiques (sense sessió), de només lectura,
amb límit de ritme i només des de xarxa privada o Tailscale (CLUB_PANTALLES_IPS_LLIURES=1 ho desactiva)."""
import base64
import hashlib
import ipaddress
import json
import os
from datetime import datetime, timezone

from fastapi import Depends, HTTPException, Request, Response
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .. import carnet_login, menus
from ..models import Menu, MenuScreen, User
from ..ratelimit import RateLimiter
from .comu import need_permis

TAILSCALE = ipaddress.ip_network("100.64.0.0/10")
SENSE_CACHE = {"Cache-Control": "no-store", "X-Robots-Tag": "noindex", "Referrer-Policy": "no-referrer"}


def ip_permesa(ip: str | None) -> bool:
    """Xarxa del club: privada, loopback (proxy local / proves en local) o Tailscale."""
    if os.environ.get("CLUB_PANTALLES_IPS_LLIURES") == "1":
        return True
    try:
        a = ipaddress.ip_address(ip or "")
    except ValueError:
        return False
    return a.is_loopback or a.is_private or a in TAILSCALE


PAGINA = """<!doctype html>
<html lang="ca"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow"><meta name="referrer" content="no-referrer"><title>Menú</title>
<link rel="stylesheet" href="/pantalla.css"></head>
<body class="pt-body" data-pantalla="1"><div id="pt-arrel" class="pt-arrel"></div><script src="/pantalla.js" defer></script></body></html>
"""


def register(app, db, current_user, check_local, run):
    limiter = RateLimiter(int(os.environ.get("CLUB_PANTALLA_LIMIT", "120")), 60)

    class MenuIn(BaseModel):
        tipus: str = Field(max_length=10)
        nom: str = Field(min_length=1, max_length=60)

    class MenuUpdateIn(BaseModel):
        nom: str | None = Field(default=None, max_length=60)
        actiu: bool | None = None
        per_defecte: bool | None = None

    class EsborranyIn(BaseModel):
        disseny: dict | None = None
        logo: str | None = None
        fons: str | None = None
        canvia_logo: bool = False
        canvia_fons: bool = False

    class PantallaIn(BaseModel):
        nom: str = Field(min_length=1, max_length=60)
        tipus: str = Field(max_length=10)
        menu_id: int | None = None

    class PantallaUpdateIn(BaseModel):
        nom: str | None = Field(default=None, max_length=60)
        tipus: str | None = Field(default=None, max_length=10)
        menu_id: int | None = None

    def menu_or_404(s: Session, user: User, menu_id: int) -> Menu:
        m = s.get(Menu, menu_id)
        if not m:
            raise HTTPException(404, "Menú inexistent")
        check_local(s, user, m.local_id)
        return m

    def pantalla_or_404(s: Session, user: User, pid: int) -> MenuScreen:
        p = s.get(MenuScreen, pid)
        if not p:
            raise HTTPException(404, "Pantalla inexistent")
        check_local(s, user, p.local_id)
        return p

    def gestor(user: User) -> None:
        need_permis(user, "menus")

    # ---------- gestió (sessió + permís «menus») ----------

    @app.get("/locals/{local_id}/menus")
    def llista_menus(local_id: int, user: User = Depends(current_user), s: Session = Depends(db)):
        gestor(user)
        check_local(s, user, local_id)
        menus.assegura_defecte(s, user, local_id)
        return {"menus": menus.llista(s, local_id), "categories": {t: list(menus.categories_de(t)) + ["Altres"] for t in menus.TIPUS_MENU}}

    @app.post("/locals/{local_id}/menus", status_code=201)
    def alta_menu(local_id: int, body: MenuIn, user: User = Depends(current_user), s: Session = Depends(db)):
        gestor(user)
        check_local(s, user, local_id)
        return {"id": run(menus.crea, s, user, local_id, body.tipus, body.nom).id}

    @app.put("/menus/{menu_id}")
    def edita_menu(menu_id: int, body: MenuUpdateIn, user: User = Depends(current_user), s: Session = Depends(db)):
        gestor(user)
        run(menus.edita, s, user, menu_or_404(s, user, menu_id), body.nom, body.actiu, body.per_defecte)
        return {"ok": True}

    @app.delete("/menus/{menu_id}")
    def esborra_menu(menu_id: int, user: User = Depends(current_user), s: Session = Depends(db)):
        gestor(user)
        run(menus.esborra, s, user, menu_or_404(s, user, menu_id))
        return {"ok": True}

    @app.post("/menus/{menu_id}/duplica", status_code=201)
    def duplica_menu(menu_id: int, user: User = Depends(current_user), s: Session = Depends(db)):
        gestor(user)
        return {"id": run(menus.duplica, s, user, menu_or_404(s, user, menu_id)).id}

    @app.get("/menus/{menu_id}/editor")
    def editor_menu(menu_id: int, user: User = Depends(current_user), s: Session = Depends(db)):
        """Tot el que cal per editar: disseny (esborrany o publicat), imatges, productes (per amagar-ne) i la vista prèvia amb dades reals."""
        gestor(user)
        m = menu_or_404(s, user, menu_id)
        cfg, img = menus.configuracio_editable(m)
        prev = {k: v for k, v in (("logo", img["logo"]), ("fons", img["fons"])) if v}
        return {"menu": {"id": m.id, "nom": m.nom, "tipus": m.tipus, "actiu": m.actiu, "per_defecte": m.per_defecte},
                "sense_publicar": m.esborrany is not None, "disseny": cfg, "logo": img["logo"], "fons": img["fons"],
                "categories_possibles": list(menus.categories_de(m.tipus)) + ["Altres"],
                "productes": menus.llista_productes(s, m, cfg), "vista": menus.vista(s, m, cfg, prev)}

    @app.put("/menus/{menu_id}/esborrany")
    def desa_esborrany(menu_id: int, body: EsborranyIn, user: User = Depends(current_user), s: Session = Depends(db)):
        gestor(user)
        run(menus.desa_esborrany, s, menu_or_404(s, user, menu_id), body.disseny, body.logo, body.fons, body.canvia_logo, body.canvia_fons)
        return {"ok": True}

    @app.post("/menus/{menu_id}/publica")
    def publica_menu(menu_id: int, user: User = Depends(current_user), s: Session = Depends(db)):
        gestor(user)
        run(menus.publica, s, user, menu_or_404(s, user, menu_id))
        return {"ok": True}

    @app.post("/menus/{menu_id}/descarta")
    def descarta_menu(menu_id: int, user: User = Depends(current_user), s: Session = Depends(db)):
        gestor(user)
        menus.descarta(s, menu_or_404(s, user, menu_id))
        return {"ok": True}

    @app.get("/locals/{local_id}/pantalles")
    def llista_pantalles(local_id: int, user: User = Depends(current_user), s: Session = Depends(db)):
        gestor(user)
        check_local(s, user, local_id)
        return {"pantalles": menus.llista_pantalles(s, local_id)}

    @app.post("/locals/{local_id}/pantalles", status_code=201)
    def alta_pantalla(local_id: int, body: PantallaIn, user: User = Depends(current_user), s: Session = Depends(db)):
        gestor(user)
        check_local(s, user, local_id)
        return {"id": run(menus.crea_pantalla, s, user, local_id, body.nom, body.tipus, body.menu_id).id}

    @app.put("/pantalles/{pantalla_id}")
    def edita_pantalla(pantalla_id: int, body: PantallaUpdateIn, user: User = Depends(current_user), s: Session = Depends(db)):
        gestor(user)
        run(menus.edita_pantalla, s, user, pantalla_or_404(s, user, pantalla_id), body.nom, body.tipus, body.menu_id, "menu_id" in body.model_fields_set)
        return {"ok": True}

    @app.post("/pantalles/{pantalla_id}/revoca")
    def revoca_pantalla(pantalla_id: int, user: User = Depends(current_user), s: Session = Depends(db)):
        gestor(user)
        run(menus.revoca_pantalla, s, user, pantalla_or_404(s, user, pantalla_id))
        return {"ok": True}

    # ---------- públic (només lectura, token secret) ----------

    def accedeix(request: Request, s: Session, token: str) -> MenuScreen:
        """429 si abusa; 404 (igual que un token inexistent) si no ve de la xarxa del club o el token no val o està revocat."""
        ip = carnet_login.client_ip(request.client.host if request.client else None, request.headers.get("x-forwarded-for"))
        if not limiter.allow("pantalla:" + (ip or "?")):
            raise HTTPException(429, "Massa peticions", headers={"Retry-After": "30"})
        pan = menus.pantalla_per_token(s, token) if ip_permesa(ip) else None
        if not pan:
            raise HTTPException(404, "No trobat")
        return pan

    def menu_de(s: Session, pan: MenuScreen) -> Menu | None:
        m = s.get(Menu, pan.menu_id) if pan.menu_id else None
        return m if m and m.actiu else None

    @app.get("/pantalla/{token}", response_class=HTMLResponse)
    def pantalla_pagina(token: str, request: Request, s: Session = Depends(db)):
        accedeix(request, s, token)
        return HTMLResponse(PAGINA, headers=SENSE_CACHE)

    @app.get("/pantalla/{token}/dades")
    def pantalla_dades(token: str, request: Request, s: Session = Depends(db)):
        pan = accedeix(request, s, token)
        pan.darrera_connexio = datetime.now(timezone.utc)
        s.commit()
        m = menu_de(s, pan)
        cos = {"pantalla": {"nom": pan.nom, "tipus": pan.tipus}, "menu": None}
        if m:
            cos = {**menus.vista(s, m, menus.disseny_publicat(m), menus.imatges_publiques(m, token)), "pantalla": {"nom": pan.nom, "tipus": pan.tipus}}
        brut = json.dumps(cos, separators=(",", ":"), sort_keys=True).encode()
        etag = '"' + hashlib.sha256(brut).hexdigest()[:20] + '"'
        if request.headers.get("if-none-match") == etag:
            return Response(status_code=304, headers={**SENSE_CACHE, "ETag": etag})
        return Response(brut, media_type="application/json", headers={**SENSE_CACHE, "ETag": etag})

    def imatge(token: str, request: Request, s: Session, quina: str) -> Response:
        pan = accedeix(request, s, token)
        m = menu_de(s, pan)
        data = (m.logo_img if quina == "logo" else m.fons_img) if m else None
        if not data:
            raise HTTPException(404, "No trobat")
        capcal, _, b64 = data.partition(",")
        return Response(base64.b64decode(b64), media_type=capcal[5:].split(";")[0],
                        headers={**SENSE_CACHE, "Cache-Control": "private, max-age=3600"})

    @app.get("/pantalla/{token}/logo")
    def pantalla_logo(token: str, request: Request, s: Session = Depends(db)):
        return imatge(token, request, s, "logo")

    @app.get("/pantalla/{token}/fons")
    def pantalla_fons(token: str, request: Request, s: Session = Depends(db)):
        return imatge(token, request, s, "fons")

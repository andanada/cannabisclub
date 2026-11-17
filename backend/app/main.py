import inspect
import logging
import os
import time
import uuid
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from . import avisos, canari, schema, security, service
from .db import make_engine, make_session_factory
from .http_guard import BodyLimitMiddleware, FrontendFiles
from .models import ImmutableError, User
from .ratelimit import RateLimiter
from .routes import auditoria, caixa, club, productes, rgpd, sessio
from .routes import contenidors as routes_contenidors
from .routes import descomptes as routes_descomptes
from .routes import catalegs as routes_catalegs
from .routes import dispositius as routes_dispositius
from .routes import gastos as routes_gastos
from .routes import informes as informes_r
from .routes import inventaris as routes_inventaris
from .routes import linies_preu as routes_linies_preu
from .routes import magatzems as routes_magatzems
from .routes import quotes as quotes_r
from .routes import regles as routes_regles
from .routes import socis as socis_r
from .routes import usuaris as usuaris_r
from .routes.comu import (check_local, empleat_valid, member_or_404, member_payload, need_admin, need_manager,  # noqa: F401
                          personal_del_local, product_or_404, rang, run, usuari_or_404)

log = logging.getLogger("club")


def get_db_factory():
    engine = make_engine()
    falten = schema.missing_tables(engine) + schema.missing_columns(engine)
    if falten:
        # Millor aturar-se aquí que donar errors 500 críptics a mig servei després d'actualitzar el programa.
        raise RuntimeError(f"Falten taules a la base de dades ({', '.join(falten)}). "
                           "Executa, amb l'usuari propietari: python -m app.cli actualitzar-bd")
    sense_index = schema.missing_indexes(engine)
    if sense_index:  # no impedeix arrencar, però les consultes anirien lentes
        logging.getLogger("club").warning("Falten índexs (%s). Executa: python -m app.cli actualitzar-bd", ", ".join(sense_index))
    factory = make_session_factory(engine)
    if canari.comprova(factory) == "creat":
        logging.getLogger("club").warning("Canari de claus creat: d'ara endavant el servei només arrencarà amb aquestes mateixes "
                                          "claus (CLUB_FIELD_KEY, CLUB_INDEX_KEY, CLUB_AUDIT_KEY). Guarda'n còpia (docs/COPIES.md).")
    return factory


def _configura_logs() -> None:
    """Logs del programa (no dels accessos de uvicorn) cap a la sortida estàndard, que systemd desa al journal."""
    logger = logging.getLogger("club")
    if logger.handlers:
        return
    h = logging.StreamHandler()
    h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    logger.addHandler(h)
    logger.setLevel(os.environ.get("CLUB_LOG_LEVEL", "INFO").upper())
    logger.propagate = False


def create_app(session_factory=None) -> FastAPI:
    _configura_logs()
    for avis in avisos.configuracio():   # configuració insegura (segon factor desactivat…): queda escrit a cada arrencada
        log.warning(avis)
    # Sense /docs, /redoc ni /openapi.json: no regalem el mapa complet de l'API a qui no té sessió.
    app = FastAPI(title="club-gestio", docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(BodyLimitMiddleware)

    ip_limiter = RateLimiter(int(os.environ.get("CLUB_LOGIN_IP_LIMIT", "60")), 60)

    @app.exception_handler(security.Overloaded)
    async def massa_feina(request, exc):
        return JSONResponse({"detail": "El servidor està ocupat. Torna-ho a provar d'aquí a un moment."}, status_code=503,
                            headers={"Retry-After": "5", "Cache-Control": "no-store"})

    @app.exception_handler(ImmutableError)
    async def immutable(request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=409, headers={"Cache-Control": "no-store"})

    @app.exception_handler(IntegrityError)
    async def integritat(request, exc):
        # Carrera residual (dues peticions a l'hora xoquen amb una restricció): conflicte, no error intern. Cap detall de SQL.
        log.warning("conflicte_integritat %s %s", request.method, request.url.path)
        return JSONResponse({"detail": "Conflicte amb una altra operació simultània. Torna-ho a provar."}, status_code=409,
                            headers={"Cache-Control": "no-store"})

    @app.exception_handler(Exception)
    async def error_inesperat(request, exc):
        # Cap detall intern (camins, SQL, valors) arriba al client: només un identificador per buscar-lo al log.
        rid = uuid.uuid4().hex[:12]
        log.error("error_no_controlat id=%s %s %s", rid, request.method, request.url.path, exc_info=exc)
        return JSONResponse({"detail": "Error intern del servidor. Si es repeteix, comunica aquest codi a l'administrador.", "id": rid},
                            status_code=500, headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})

    @app.middleware("http")
    async def security_headers(request, call_next):
        t0 = time.perf_counter()
        resp = await call_next(request)
        # Es registra el camí SENSE la query string: hi pot haver documents o codis de carnet (dades personals).
        log.info("%s %s %s %.0fms", request.method, request.url.path, resp.status_code, (time.perf_counter() - t0) * 1000)
        if os.environ.get("CLUB_HSTS") == "1":
            resp.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        resp.headers["Content-Security-Policy"] = (
            "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; "
            "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        resp.headers["X-Frame-Options"] = "DENY"
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["Referrer-Policy"] = "no-referrer"
        # Només els fitxers del frontend (els serveix StaticFiles, que hi posa Last-Modified) es poden guardar, i sempre amb
        # revalidació: mai es barregen fitxers vells i nous. Tota la resta (API, errors, 401/404) no es guarda mai.
        # (Abans era una llista escrita a mà de fitxers: s'oblidava d'index.html i dels fitxers nous.)
        estatic = request.method in ("GET", "HEAD") and resp.status_code in (200, 304) and "last-modified" in resp.headers
        resp.headers["Cache-Control"] = "no-cache" if estatic else "no-store"
        return resp
    factory = session_factory or get_db_factory()

    def db():
        s = factory()
        try:
            yield s
        finally:
            s.close()

    def current_user(authorization: str = Header(default=""), s: Session = Depends(db)) -> User:
        scheme, _, token = authorization.partition(" ")
        user = service.user_from_token(s, token) if scheme.lower() == "bearer" and token else None
        if not user:
            raise HTTPException(401, "No autenticat")
        return user

    # Cada mòdul de rutes demana pel nom només les ajudes que fa servir (vegeu routes/comu.py).
    disponibles = dict(db=db, current_user=current_user, ip_limiter=ip_limiter, check_local=check_local, need_manager=need_manager,
                       need_admin=need_admin, run=run, member_or_404=member_or_404, member_payload=member_payload,
                       product_or_404=product_or_404, usuari_or_404=usuari_or_404, empleat_valid=empleat_valid,
                       personal_del_local=personal_del_local, rang=rang)
    for modul in (sessio, socis_r, auditoria, productes, caixa, informes_r, usuaris_r, quotes_r, routes_dispositius, routes_descomptes,
                  routes_magatzems, routes_contenidors, routes_linies_preu, routes_inventaris, routes_regles, routes_gastos, routes_catalegs):
        demanats = inspect.signature(modul.register).parameters
        modul.register(app, **{k: v for k, v in disponibles.items() if k in demanats})
    for _r in (rgpd, club): app.include_router(_r.router(db, current_user))  # RGPD i controls de club (routes/rgpd.py, club.py)

    front = Path(__file__).resolve().parents[2] / "frontend"
    if front.is_dir():
        app.mount("/", FrontendFiles(directory=front, html=True), name="front")
    return app

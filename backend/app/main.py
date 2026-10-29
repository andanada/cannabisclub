import logging
import os
import time
import uuid
from datetime import date
from decimal import Decimal
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Response
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from . import ajustos, cash, contenidors, descomptes, dispositius, informes, inventaris, linies_preu, magatzems, personal, quotes, regles, schema, service, socis, stock, usuaris
from .db import make_engine, make_session_factory
from .models import CashEntry, Container, ContainerType, DeviceProfile, Discount, Local, InventorySession, Member, PriceLine, Product, Regla, StockMovement, User, UserLocal, Warehouse

CAN_CREATE_MEMBER = {"admin", "encarregat"}
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
    return make_session_factory(engine)


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
    app = FastAPI(title="club-gestio")

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
        if not request.url.path.startswith("/static-"):
            if request.url.path not in ("/", "/sw.js", "/i18n-es.js", "/i18n-en.js", "/i18n.js", "/util.js", "/bascula.js", "/app.js", "/views-dispensar.js", "/views-gestio.js",
                                        "/views-socis.js", "/views-descomptes.js", "/views-regles.js", "/views-linies-preu.js", "/views-contenidors.js", "/views-magatzems.js", "/views-inventari.js", "/views-informes.js", "/views-historial.js", "/views-config.js", "/diagnostic.js", "/views-dispositius.js", "/views-diagnostic.js", "/views-carnets.js", "/views-admin.js", "/style.css", "/manifest.webmanifest", "/icon.svg"):
                resp.headers["Cache-Control"] = "no-store"
            else:
                resp.headers["Cache-Control"] = "no-cache"  # el navegador revalida sempre: mai barreja fitxers vells i nous
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

    def check_local(s: Session, user: User, local_id: int) -> None:
        if user.role == "admin":
            return
        if not s.get(UserLocal, (user.id, local_id)):
            raise HTTPException(403, "Sense accés a aquest local")

    class LoginIn(BaseModel):
        # Límits: aquests valors poden acabar a l'auditoria, que és només d'afegir i no es pot netejar.
        username: str = Field(max_length=60)
        password: str = Field(max_length=200)
        totp: str = Field(default="", max_length=10)

    class MemberIn(BaseModel):
        local_id: int
        nom: str = Field(min_length=2, max_length=120)
        document: str = Field(min_length=5, max_length=30)
        naixement: date
        telefon: str | None = None
        email: str | None = None

    @app.get("/auth/opcions")
    def opcions_login():
        """Públic: la pantalla d'entrada hi consulta si ha de demanar el codi de l'app d'autenticació."""
        return {"totp": service.totp_required()}

    @app.get("/salut")
    def salut(s: Session = Depends(db)):
        """Per a monitoratge (systemd, Tailscale, un curl des de cron): 200 si la base de dades respon, 503 si no."""
        try:
            s.execute(text("SELECT 1"))
        except Exception:
            log.exception("salut: la base de dades no respon")
            return JSONResponse({"ok": False}, status_code=503)
        return {"ok": True}

    def member_payload(s: Session, m: Member) -> dict:
        return {**service.member_view(m), "quota": quotes.status(s, m.id),
                "te_foto": socis.has_photo(s, m.id), "te_carnet": socis.has_card(s, m.id)}

    @app.post("/auth/login")
    def login(body: LoginIn, s: Session = Depends(db)):
        try:
            token = service.login(s, body.username, body.password, body.totp)
        except service.LoginLocked:
            raise HTTPException(429, "Massa intents fallits: l'accés queda bloquejat uns minuts. Torna-ho a provar més tard.")
        if not token:
            raise HTTPException(401, "Credencials incorrectes")
        return {"token": token}

    @app.post("/socis", status_code=201)
    def alta_soci(body: MemberIn, user: User = Depends(current_user), s: Session = Depends(db)):
        if user.role not in CAN_CREATE_MEMBER:
            raise HTTPException(403, "El teu rol no pot donar d'alta socis")
        check_local(s, user, body.local_id)
        try:
            m = service.create_member(s, user, body.local_id, body.nom, body.document,
                                      body.naixement, body.telefon, body.email)
        except ValueError as e:
            raise HTTPException(422, str(e))
        return {"id": m.id}

    @app.get("/socis/{member_id}")
    def veure_soci(member_id: int, user: User = Depends(current_user), s: Session = Depends(db)):
        m = s.get(Member, member_id)
        if not m:
            raise HTTPException(404, "No existeix")
        check_local(s, user, m.local_id)
        service.audit_append(s, {"accio": "consulta_soci", "soci": m.id, "per": user.id})
        s.commit()
        return member_payload(s, m)

    @app.get("/auditoria/verificar")
    def verificar(user: User = Depends(current_user), s: Session = Depends(db)):
        if user.role != "admin":
            raise HTTPException(403, "Només administradors")
        ok, seq = service.audit_verify(s)
        return {"integra": ok, "primera_alterada": seq}

    class ProductIn(BaseModel):
        local_id: int
        nom: str = Field(min_length=1, max_length=120)
        categoria: str = Field(default="", max_length=60)
        preu_cent_per_g: int = Field(ge=0, le=10_000_000)
        es_genetic: bool = False

    class EntradaIn(BaseModel):
        product_id: int
        grams: Decimal = Field(gt=0, max_digits=9, decimal_places=3)
        nota: str | None = Field(default=None, max_length=300)
        magatzem_id: int | None = None  # buit = magatzem principal

    class DispensacioIn(BaseModel):
        member_id: int
        product_id: int
        grams: Decimal = Field(gt=0, max_digits=9, decimal_places=3)
        pes_bascula_g: Decimal | None = Field(default=None, gt=0, max_digits=9, decimal_places=3)
        discount_id: int | None = None

    class CorreccioIn(BaseModel):
        nota: str = Field(min_length=3, max_length=300)

    def product_or_404(s: Session, user: User, product_id: int) -> Product:
        p = s.get(Product, product_id)
        if not p:
            raise HTTPException(404, "Producte inexistent")
        check_local(s, user, p.local_id)
        return p

    def run(fn, *a, **kw):
        try:
            return fn(*a, **kw)
        except ValueError as e:
            raise HTTPException(422, str(e))

    @app.post("/productes", status_code=201)
    def alta_producte(body: ProductIn, user: User = Depends(current_user), s: Session = Depends(db)):
        if user.role not in CAN_CREATE_MEMBER:
            raise HTTPException(403, "El teu rol no pot crear productes")
        check_local(s, user, body.local_id)
        p = run(stock.add_product, s, user, body.local_id, body.nom, body.categoria, body.preu_cent_per_g, body.es_genetic)
        return {"id": p.id}

    class ProductUpdateIn(BaseModel):
        nom: str | None = Field(default=None, min_length=1, max_length=120)
        categoria: str | None = Field(default=None, max_length=60)
        preu_cent_per_g: int | None = Field(default=None, ge=0, le=10_000_000)
        actiu: bool | None = None
        es_genetic: bool | None = None

    @app.patch("/productes/{product_id}")
    def edita_producte(product_id: int, body: ProductUpdateIn, user: User = Depends(current_user), s: Session = Depends(db)):
        if user.role not in CAN_CREATE_MEMBER:
            raise HTTPException(403, "El teu rol no pot editar productes")
        product_or_404(s, user, product_id)
        run(stock.update_product, s, user, product_id, body.nom, body.categoria, body.preu_cent_per_g, body.actiu, body.es_genetic)
        return {"ok": True}

    class ImatgeIn(BaseModel):
        image_base64: str = Field(max_length=60_000)

    @app.put("/productes/{product_id}/imatge")
    def posa_imatge(product_id: int, body: ImatgeIn, user: User = Depends(current_user), s: Session = Depends(db)):
        need_manager(user)
        run(stock.set_image, s, user, product_or_404(s, user, product_id), body.image_base64)
        return {"ok": True}

    @app.delete("/productes/{product_id}/imatge")
    def treu_imatge(product_id: int, user: User = Depends(current_user), s: Session = Depends(db)):
        need_manager(user)
        run(stock.remove_image, s, user, product_or_404(s, user, product_id))
        return {"ok": True}

    @app.get("/locals/{local_id}/productes")
    def tots_els_productes(local_id: int, user: User = Depends(current_user), s: Session = Depends(db)):
        """Catàleg complet (també els inactius) per a la gestió; el dispensador només veu els actius a /estoc."""
        if user.role not in CAN_CREATE_MEMBER:
            raise HTTPException(403, "El teu rol no pot gestionar productes")
        check_local(s, user, local_id)
        prods = s.scalars(select(Product).where(Product.local_id == local_id).order_by(Product.actiu.desc(), Product.nom)).all()
        mg = stock.stock_by_product(s, [p.id for p in prods])
        imatges = stock.images_for(s, [p.id for p in prods])
        return [{"id": p.id, "nom": p.nom, "categoria": p.categoria, "preu_cent_per_g": p.preu_cent_per_g, "actiu": p.actiu, "es_genetic": p.es_genetic,
                 "estoc_g": str(Decimal(mg[p.id]) / 1000), "imatge": imatges.get(p.id)} for p in prods]

    @app.get("/locals/{local_id}/estoc")
    def veure_estoc(local_id: int, soci: int | None = None, user: User = Depends(current_user), s: Session = Depends(db)):
        check_local(s, user, local_id)
        prods = s.scalars(select(Product).where(Product.local_id == local_id, Product.actiu.is_(True)).order_by(Product.nom)).all()
        mg = stock.stock_by_product(s, [p.id for p in prods])
        imatges = stock.images_for(s, [p.id for p in prods])
        # Amb ?soci= els preus són els que paga aquest soci (la seva línia de preu, si en té)
        preus = linies_preu.effective_prices(s, member_or_404(s, user, soci).id, prods) if soci else {p.id: p.preu_cent_per_g for p in prods}
        return [{"id": p.id, "nom": p.nom, "categoria": p.categoria, "preu_cent_per_g": preus[p.id],
                 "estoc_g": str(Decimal(mg[p.id]) / 1000), "imatge": imatges.get(p.id)} for p in prods]

    @app.post("/moviments/entrada", status_code=201)
    def entrada(body: EntradaIn, user: User = Depends(current_user), s: Session = Depends(db)):
        if user.role not in CAN_CREATE_MEMBER:
            raise HTTPException(403, "El teu rol no pot registrar entrades")
        product_or_404(s, user, body.product_id)
        m = run(stock.receive, s, user, body.product_id, body.grams, body.nota, body.magatzem_id)
        return {"id": m.id}

    @app.post("/dispensacions", status_code=201)
    def dispensacio(body: DispensacioIn, user: User = Depends(current_user), s: Session = Depends(db)):
        product_or_404(s, user, body.product_id)
        m = run(stock.dispense, s, user, body.member_id, body.product_id, body.grams, body.pes_bascula_g, None, body.discount_id)
        return {"id": m.id, "import_cent": m.import_cent, "descompte_cent": getattr(m, "descompte_cent", 0)}

    @app.post("/moviments/{movement_id}/correccio", status_code=201)
    def correccio(movement_id: int, body: CorreccioIn, user: User = Depends(current_user), s: Session = Depends(db)):
        if user.role not in CAN_CREATE_MEMBER:
            raise HTTPException(403, "El teu rol no pot corregir moviments")
        orig = s.get(StockMovement, movement_id)
        if not orig:
            raise HTTPException(404, "Moviment inexistent")
        check_local(s, user, orig.local_id)
        m = run(stock.correct, s, user, movement_id, body.nota)
        return {"id": m.id}

    class ObrirIn(BaseModel):
        local_id: int
        opening_cent: int = Field(ge=0)

    class TancarIn(BaseModel):
        local_id: int
        counted_cent: int = Field(ge=0)

    class CobramentIn(BaseModel):
        movement_id: int
        metode: str

    class DespesaIn(BaseModel):
        local_id: int
        cent: int = Field(gt=0)
        metode: str
        categoria: str = Field(min_length=1, max_length=60)
        concepte: str = Field(min_length=3, max_length=300)

    def need_manager(user: User):
        if user.role not in CAN_CREATE_MEMBER:
            raise HTTPException(403, "El teu rol no pot fer aquesta operació")

    @app.post("/caixa/obrir", status_code=201)
    def obrir_caixa(body: ObrirIn, user: User = Depends(current_user), s: Session = Depends(db)):
        need_manager(user)
        check_local(s, user, body.local_id)
        cs = run(cash.open_session, s, user, body.local_id, body.opening_cent)
        return {"sessio": cs.id}

    @app.post("/caixa/tancar")
    def tancar_caixa(body: TancarIn, user: User = Depends(current_user), s: Session = Depends(db)):
        need_manager(user)
        check_local(s, user, body.local_id)
        cs = run(cash.close_session, s, user, body.local_id, body.counted_cent)
        return {"sessio": cs.id, "esperat_cent": cs.expected_cent, "comptat_cent": cs.counted_cent, "diferencia_cent": cs.diff_cent}

    @app.post("/cobraments", status_code=201)
    def cobrament(body: CobramentIn, user: User = Depends(current_user), s: Session = Depends(db)):
        mv = s.get(StockMovement, body.movement_id)
        if not mv:
            raise HTTPException(404, "Moviment inexistent")
        check_local(s, user, mv.local_id)
        e = run(cash.charge, s, user, body.movement_id, body.metode)
        return {"apunt": e.id, "import_cent": e.import_cent}

    @app.post("/despeses", status_code=201)
    def despesa(body: DespesaIn, user: User = Depends(current_user), s: Session = Depends(db)):
        need_manager(user)
        check_local(s, user, body.local_id)
        e = run(cash.expense, s, user, body.local_id, body.cent, body.metode, body.categoria, body.concepte)
        return {"apunt": e.id}

    @app.post("/caixa/apunts/{entry_id}/correccio", status_code=201)
    def correccio_apunt(entry_id: int, body: CorreccioIn, user: User = Depends(current_user), s: Session = Depends(db)):
        need_manager(user)
        orig = s.get(CashEntry, entry_id)
        if not orig:
            raise HTTPException(404, "Apunt inexistent")
        check_local(s, user, orig.local_id)
        e = run(cash.correct_entry, s, user, entry_id, body.nota)
        return {"apunt": e.id}

    @app.get("/locals/{local_id}/informe")
    def informe(local_id: int, des: date, fins: date, usuari: int | None = None, user: User = Depends(current_user), s: Session = Depends(db)):
        need_manager(user)
        check_local(s, user, local_id)
        if fins < des:
            raise HTTPException(422, "Rang de dates invàlid")
        empleat_valid(s, local_id, usuari)
        return cash.report(s, local_id, des, fins, usuari)

    @app.get("/locals/{local_id}/apunts.csv")
    def apunts_csv(local_id: int, des: date, fins: date, user: User = Depends(current_user), s: Session = Depends(db)):
        need_manager(user)
        check_local(s, user, local_id)
        service.audit_append(s, {"accio": "exportar_csv", "informe": "apunts", "local": local_id, "per": user.id})
        s.commit()
        return Response(cash.entries_csv(s, local_id, des, fins), media_type="text/csv")

    def personal_del_local(s: Session, local_id: int) -> list[User]:
        ids = set(s.scalars(select(UserLocal.user_id).where(UserLocal.local_id == local_id)))
        return [u for u in s.scalars(select(User).where(User.active.is_(True)).order_by(User.username)) if u.role == "admin" or u.id in ids]

    def empleat_valid(s: Session, local_id: int, usuari: int | None) -> None:
        """El filtre per empleat només admet gent que treballa en aquest local (o administradors)."""
        if usuari is not None and usuari not in {u.id for u in personal_del_local(s, local_id)}:
            raise HTTPException(422, "Aquest empleat no treballa en aquest local")

    @app.get("/locals/{local_id}/personal")
    def llista_personal(local_id: int, user: User = Depends(current_user), s: Session = Depends(db)):
        need_manager(user)
        check_local(s, user, local_id)
        return [{"id": u.id, "username": u.username, "role": u.role} for u in personal_del_local(s, local_id)]

    def _rang(des: date, fins: date) -> None:
        if fins < des:
            raise HTTPException(422, "Rang de dates invàlid")

    @app.get("/locals/{local_id}/apunts")
    def llista_apunts(local_id: int, des: date, fins: date, limit: int = Query(default=100, ge=1, le=500),
                      user: User = Depends(current_user), s: Session = Depends(db)):
        need_manager(user)
        check_local(s, user, local_id)
        _rang(des, fins)
        return cash.entries_list(s, local_id, des, fins, limit)

    @app.get("/locals/{local_id}/moviments")
    def llista_moviments(local_id: int, des: date, fins: date, limit: int = Query(default=100, ge=1, le=500),
                         user: User = Depends(current_user), s: Session = Depends(db)):
        need_manager(user)
        check_local(s, user, local_id)
        _rang(des, fins)
        return stock.movements_list(s, local_id, des, fins, limit)

    # Informes de gestió (JSON i CSV). Només responsables; el CSV queda a l'auditoria.
    def registra_informe(nom: str, fn, csv_fn, amb_rang: bool):
        def calcula(local_id: int, des: date | None, fins: date | None, user: User, s: Session, usuari: int | None = None):
            need_manager(user)
            check_local(s, user, local_id)
            if not amb_rang:
                return fn(s, local_id)
            empleat_valid(s, local_id, usuari)
            if des is None or fins is None:
                raise HTTPException(422, "Cal indicar des de i fins a")
            if fins < des:
                raise HTTPException(422, "Rang de dates invàlid")
            return fn(s, local_id, des, fins, usuari)

        @app.get(f"/locals/{{local_id}}/informe/{nom}", name=f"informe_{nom}")
        def veure(local_id: int, des: date | None = None, fins: date | None = None, usuari: int | None = None,
                  user: User = Depends(current_user), s: Session = Depends(db)):
            return calcula(local_id, des, fins, user, s, usuari)

        @app.get(f"/locals/{{local_id}}/informe/{nom}.csv", name=f"informe_{nom}_csv")
        def exporta(local_id: int, des: date | None = None, fins: date | None = None, usuari: int | None = None,
                    user: User = Depends(current_user), s: Session = Depends(db)):
            r = calcula(local_id, des, fins, user, s, usuari)
            service.audit_append(s, {"accio": "exportar_csv", "informe": nom, "local": local_id, "per": user.id})
            s.commit()
            return Response(csv_fn(r), media_type="text/csv")

    registra_informe("vendes", informes.sales, informes.sales_csv, True)
    registra_informe("estoc", informes.valued_stock, informes.stock_csv, False)
    registra_informe("assistencia", informes.attendance, informes.attendance_csv, True)
    registra_informe("hores", informes.staff_hours, informes.hours_csv, True)

    class EstatIn(BaseModel):
        estat: str

    class MermaIn(BaseModel):
        product_id: int
        grams: Decimal = Field(gt=0, max_digits=9, decimal_places=3)
        nota: str = Field(min_length=3, max_length=300)

    class AjustIn(BaseModel):
        product_id: int
        grams_reals: Decimal = Field(ge=0, max_digits=9, decimal_places=3)
        nota: str = Field(min_length=3, max_length=300)

    class FitxatgeIn(BaseModel):
        local_id: int
        tipus: str

    class LocalIn(BaseModel):
        nom: str = Field(min_length=2, max_length=120)

    class UsuariIn(BaseModel):
        username: str = Field(min_length=3, max_length=60)
        password: str
        role: str
        local_ids: list[int] = []

    class LimitsIn(BaseModel):
        limit_diari_g: Decimal | None = Field(default=None, ge=0)
        limit_mensual_g: Decimal | None = Field(default=None, ge=0)
        tolerancia_bascula_g: Decimal | None = Field(default=None, ge=0)

    def need_admin(user: User):
        if user.role != "admin":
            raise HTTPException(403, "Només administradors")

    def member_or_404(s: Session, user: User, member_id: int) -> Member:
        m = s.get(Member, member_id)
        if not m:
            raise HTTPException(404, "No existeix")
        check_local(s, user, m.local_id)
        return m

    class SignaturaIn(BaseModel):
        png_base64: str = Field(max_length=300_000)

    @app.post("/socis/{member_id}/signatura", status_code=201)
    def signar(member_id: int, body: SignaturaIn, user: User = Depends(current_user), s: Session = Depends(db)):
        need_manager(user)
        sig = run(service.save_signature, s, user, member_or_404(s, user, member_id), body.png_base64)
        return {"id": sig.id, "sha256": sig.sha256}

    @app.get("/socis/{member_id}/signatura")
    def veure_signatura(member_id: int, user: User = Depends(current_user), s: Session = Depends(db)):
        need_manager(user)
        r = service.read_signature(s, user, member_or_404(s, user, member_id))
        if not r:
            raise HTTPException(404, "Sense signatura")
        return r

    @app.post("/socis/{member_id}/estat")
    def canvi_estat(member_id: int, body: EstatIn, user: User = Depends(current_user), s: Session = Depends(db)):
        need_manager(user)
        run(service.set_member_status, s, user, member_or_404(s, user, member_id), body.estat)
        return {"ok": True}

    @app.post("/socis/{member_id}/entrada", status_code=201)
    def entrada_soci(member_id: int, user: User = Depends(current_user), s: Session = Depends(db)):
        c = run(service.check_in, s, user, member_or_404(s, user, member_id))
        return {"id": c.id}

    @app.get("/locals/{local_id}/socis/cerca")
    def cerca_soci(local_id: int, document: str, user: User = Depends(current_user), s: Session = Depends(db)):
        check_local(s, user, local_id)
        m = service.find_member_by_document(s, local_id, document)
        service.audit_append(s, {"accio": "cerca_soci", "local": local_id, "trobat": bool(m), "per": user.id})
        s.commit()
        if not m:
            raise HTTPException(404, "No existeix")
        return member_payload(s, m)

    @app.get("/locals/{local_id}/socis/carnet")
    def cerca_carnet(local_id: int, codi: str, user: User = Depends(current_user), s: Session = Depends(db)):
        check_local(s, user, local_id)
        m = socis.find_by_card(s, local_id, codi)
        service.audit_append(s, {"accio": "cerca_carnet", "local": local_id, "trobat": bool(m), "per": user.id})
        s.commit()
        if not m:
            raise HTTPException(404, "No existeix")
        return member_payload(s, m)

    @app.get("/locals/{local_id}/socis")
    def llista_socis(local_id: int, q: str | None = None, estat: str | None = None, user: User = Depends(current_user), s: Session = Depends(db)):
        need_manager(user)
        check_local(s, user, local_id)
        return run(socis.list_members, s, user, local_id, q, estat)

    class MemberUpdateIn(BaseModel):
        nom: str | None = Field(default=None, max_length=120)
        document: str | None = Field(default=None, max_length=30)
        naixement: date | None = None
        telefon: str | None = Field(default=None, max_length=30)
        email: str | None = Field(default=None, max_length=120)

    @app.patch("/socis/{member_id}")
    def edita_soci(member_id: int, body: MemberUpdateIn, user: User = Depends(current_user), s: Session = Depends(db)):
        need_manager(user)
        m = member_or_404(s, user, member_id)
        # només els camps enviats: un camp enviat com a null buida el telèfon o el correu
        run(socis.update_member, s, user, m, {k: getattr(body, k) for k in body.model_fields_set})
        return {"ok": True}

    class FotoIn(BaseModel):
        image_base64: str = Field(max_length=400_000)

    @app.post("/socis/{member_id}/foto", status_code=201)
    def pujar_foto(member_id: int, body: FotoIn, user: User = Depends(current_user), s: Session = Depends(db)):
        need_manager(user)
        f = run(socis.save_photo, s, user, member_or_404(s, user, member_id), body.image_base64)
        return {"id": f.id, "sha256": f.sha256}

    @app.get("/socis/{member_id}/foto")
    def veure_foto(member_id: int, user: User = Depends(current_user), s: Session = Depends(db)):
        f = socis.read_photo(s, user, member_or_404(s, user, member_id))
        if not f:
            raise HTTPException(404, "Sense foto")
        return f

    class CarnetIn(BaseModel):
        codi: str = Field(max_length=100)

    @app.post("/socis/{member_id}/carnet", status_code=201)
    def assignar_carnet(member_id: int, body: CarnetIn, user: User = Depends(current_user), s: Session = Depends(db)):
        need_manager(user)
        c = run(socis.assign_card, s, user, member_or_404(s, user, member_id), body.codi)
        return {"id": c.id}

    @app.delete("/socis/{member_id}/carnet")
    def retirar_carnet(member_id: int, user: User = Depends(current_user), s: Session = Depends(db)):
        need_manager(user)
        run(socis.revoke_card, s, user, member_or_404(s, user, member_id))
        return {"ok": True}

    class CarnetGenerarIn(BaseModel):
        prefix: str = Field(default="CLB", pattern=r"^[A-Z0-9]{2,6}$")

    @app.post("/socis/{member_id}/carnet/generar", status_code=201)
    def generar_carnet(member_id: int, body: CarnetGenerarIn, user: User = Depends(current_user), s: Session = Depends(db)):
        need_manager(user)
        codi = run(socis.generate_and_assign_card, s, user, member_or_404(s, user, member_id), body.prefix)
        return {"codi": codi}  # l'única vegada que es mostra: a la base de dades només queda l'empremta

    class DispositiuIn(BaseModel):
        kind: str
        nom: str = Field(max_length=60)
        config: dict = {}
        per_defecte: bool = False

    class DispositiuUpdateIn(BaseModel):
        nom: str | None = Field(default=None, max_length=60)
        config: dict | None = None
        per_defecte: bool | None = None

    def dispositiu_or_404(s: Session, did: int) -> DeviceProfile:
        d = s.get(DeviceProfile, did)
        if not d:
            raise HTTPException(404, "Dispositiu inexistent")
        return d

    @app.get("/locals/{local_id}/dispositius")
    def llista_dispositius(local_id: int, kind: str | None = None, user: User = Depends(current_user), s: Session = Depends(db)):
        check_local(s, user, local_id)  # qualsevol rol del local: la tauleta necessita el seu perfil per treballar
        return dispositius.list_profiles(s, local_id, kind)

    @app.post("/locals/{local_id}/dispositius", status_code=201)
    def alta_dispositiu(local_id: int, body: DispositiuIn, user: User = Depends(current_user), s: Session = Depends(db)):
        need_admin(user)
        if not s.get(Local, local_id):
            raise HTTPException(404, "Local inexistent")
        d = run(dispositius.create, s, user, local_id, body.kind, body.nom, body.config, body.per_defecte)
        return {"id": d.id}

    @app.put("/dispositius/{device_id}")
    def edita_dispositiu(device_id: int, body: DispositiuUpdateIn, user: User = Depends(current_user), s: Session = Depends(db)):
        need_admin(user)
        run(dispositius.update, s, user, dispositiu_or_404(s, device_id), body.nom, body.config, body.per_defecte)
        return {"ok": True}

    @app.delete("/dispositius/{device_id}")
    def esborra_dispositiu(device_id: int, user: User = Depends(current_user), s: Session = Depends(db)):
        need_admin(user)
        run(dispositius.delete, s, user, dispositiu_or_404(s, device_id))
        return {"ok": True}

    class DescompteIn(BaseModel):
        nom: str = Field(max_length=60)
        tipus: str
        valor: int
        ambit: str
        categoria: str | None = Field(default=None, max_length=60)
        product_id: int | None = None
        inici: date | None = None
        fi: date | None = None

    class DescompteUpdateIn(BaseModel):
        nom: str | None = Field(default=None, max_length=60)
        valor: int | None = None
        actiu: bool | None = None
        inici: date | None = None
        fi: date | None = None

    @app.get("/locals/{local_id}/descomptes")
    def llista_descomptes(local_id: int, producte: int | None = None, tots: bool = False, user: User = Depends(current_user), s: Session = Depends(db)):
        check_local(s, user, local_id)
        if tots:
            need_manager(user)
        p = product_or_404(s, user, producte) if producte else None
        return descomptes.list_discounts(s, local_id, quotes.avui(), p, tots)

    @app.post("/locals/{local_id}/descomptes", status_code=201)
    def alta_descompte(local_id: int, body: DescompteIn, user: User = Depends(current_user), s: Session = Depends(db)):
        need_manager(user)
        check_local(s, user, local_id)
        d = run(descomptes.create, s, user, local_id, body.nom, body.tipus, body.valor, body.ambit, body.categoria, body.product_id, body.inici, body.fi)
        return {"id": d.id}

    @app.put("/descomptes/{discount_id}")
    def edita_descompte(discount_id: int, body: DescompteUpdateIn, user: User = Depends(current_user), s: Session = Depends(db)):
        need_manager(user)
        d = s.get(Discount, discount_id)
        if not d:
            raise HTTPException(404, "Descompte inexistent")
        check_local(s, user, d.local_id)
        run(descomptes.update, s, user, d, body.actiu, body.nom, body.valor, body.inici, body.fi, bool({"inici", "fi"} & body.model_fields_set))
        return {"ok": True}

    class MagatzemIn(BaseModel):
        nom: str = Field(max_length=60)

    class MagatzemUpdateIn(BaseModel):
        nom: str | None = Field(default=None, max_length=60)
        actiu: bool | None = None

    class TraspasIn(BaseModel):
        product_id: int
        de: int | None = None  # buit = magatzem principal
        a: int | None = None
        grams: Decimal = Field(gt=0, max_digits=9, decimal_places=3)

    @app.get("/locals/{local_id}/magatzems")
    def llista_magatzems(local_id: int, user: User = Depends(current_user), s: Session = Depends(db)):
        need_manager(user)
        check_local(s, user, local_id)
        return magatzems.llista(s, local_id)

    @app.post("/locals/{local_id}/magatzems", status_code=201)
    def alta_magatzem(local_id: int, body: MagatzemIn, user: User = Depends(current_user), s: Session = Depends(db)):
        need_manager(user)
        check_local(s, user, local_id)
        return {"id": run(magatzems.create, s, user, local_id, body.nom).id}

    @app.put("/magatzems/{magatzem_id}")
    def edita_magatzem(magatzem_id: int, body: MagatzemUpdateIn, user: User = Depends(current_user), s: Session = Depends(db)):
        need_manager(user)
        w = s.get(Warehouse, magatzem_id)
        if not w:
            raise HTTPException(404, "Magatzem inexistent")
        check_local(s, user, w.local_id)
        run(magatzems.update, s, user, w, body.nom, body.actiu)
        return {"ok": True}

    @app.get("/locals/{local_id}/magatzems/estoc")
    def estoc_per_magatzem(local_id: int, user: User = Depends(current_user), s: Session = Depends(db)):
        need_manager(user)
        check_local(s, user, local_id)
        return magatzems.estoc(s, local_id)

    @app.post("/moviments/traspas", status_code=201)
    def traspas_estoc(body: TraspasIn, user: User = Depends(current_user), s: Session = Depends(db)):
        need_manager(user)
        p = product_or_404(s, user, body.product_id)
        run(magatzems.transfer, s, user, p, body.de, body.a, body.grams)
        return {"ok": True}

    class TipusContenidorIn(BaseModel):
        nom: str = Field(max_length=60)
        tara_g: Decimal = Field(ge=0, le=50_000, decimal_places=3)

    class TipusContenidorUpdateIn(BaseModel):
        nom: str | None = Field(default=None, max_length=60)
        tara_g: Decimal | None = Field(default=None, ge=0, le=50_000, decimal_places=3)
        actiu: bool | None = None

    class ContenidorIn(BaseModel):
        codi: str = Field(max_length=40)
        type_id: int
        product_id: int | None = None
        brut_g: Decimal | None = Field(default=None, ge=0, le=50_000, decimal_places=3)

    class ContenidorUpdateIn(BaseModel):
        codi: str | None = Field(default=None, max_length=40)
        type_id: int | None = None
        product_id: int | None = None
        brut_g: Decimal | None = Field(default=None, ge=0, le=50_000, decimal_places=3)
        actiu: bool | None = None

    @app.get("/locals/{local_id}/tipus-contenidor")
    def llista_tipus_contenidor(local_id: int, user: User = Depends(current_user), s: Session = Depends(db)):
        need_manager(user)
        check_local(s, user, local_id)
        return contenidors.llista_tipus(s, local_id)

    @app.post("/locals/{local_id}/tipus-contenidor", status_code=201)
    def alta_tipus_contenidor(local_id: int, body: TipusContenidorIn, user: User = Depends(current_user), s: Session = Depends(db)):
        need_manager(user)
        check_local(s, user, local_id)
        return {"id": run(contenidors.create_type, s, user, local_id, body.nom, body.tara_g).id}

    @app.put("/tipus-contenidor/{tipus_id}")
    def edita_tipus_contenidor(tipus_id: int, body: TipusContenidorUpdateIn, user: User = Depends(current_user), s: Session = Depends(db)):
        need_manager(user)
        t = s.get(ContainerType, tipus_id)
        if not t:
            raise HTTPException(404, "Tipus de contenidor inexistent")
        check_local(s, user, t.local_id)
        run(contenidors.update_type, s, user, t, body.nom, body.tara_g, body.actiu)
        return {"ok": True}

    @app.get("/locals/{local_id}/contenidors")
    def llista_contenidors(local_id: int, user: User = Depends(current_user), s: Session = Depends(db)):
        need_manager(user)
        check_local(s, user, local_id)
        return contenidors.llista(s, local_id)

    @app.post("/locals/{local_id}/contenidors", status_code=201)
    def alta_contenidor(local_id: int, body: ContenidorIn, user: User = Depends(current_user), s: Session = Depends(db)):
        need_manager(user)
        check_local(s, user, local_id)
        return {"id": run(contenidors.create, s, user, local_id, body.codi, body.type_id, body.product_id, body.brut_g).id}

    @app.put("/contenidors/{contenidor_id}")
    def edita_contenidor(contenidor_id: int, body: ContenidorUpdateIn, user: User = Depends(current_user), s: Session = Depends(db)):
        need_manager(user)
        c = s.get(Container, contenidor_id)
        if not c:
            raise HTTPException(404, "Contenidor inexistent")
        check_local(s, user, c.local_id)
        run(contenidors.update, s, user, c, {k: getattr(body, k) for k in body.model_fields_set})
        return {"ok": True}

    class LiniaPreuIn(BaseModel):
        nom: str = Field(max_length=60)

    class LiniaPreuUpdateIn(BaseModel):
        nom: str | None = Field(default=None, max_length=60)
        actiu: bool | None = None

    class PreuLiniaIn(BaseModel):
        preu_cent_per_g: int = Field(ge=0, le=linies_preu.MAX_PREU)

    class AssignaLiniaIn(BaseModel):
        price_line_id: int | None = None

    def linia_or_404(s: Session, user: User, linia_id: int) -> PriceLine:
        need_manager(user)
        l = s.get(PriceLine, linia_id)
        if not l:
            raise HTTPException(404, "Línia de preu inexistent")
        check_local(s, user, l.local_id)
        return l

    @app.get("/locals/{local_id}/linies-preu")
    def llista_linies_preu(local_id: int, user: User = Depends(current_user), s: Session = Depends(db)):
        need_manager(user)
        check_local(s, user, local_id)
        return linies_preu.llista(s, local_id)

    @app.post("/locals/{local_id}/linies-preu", status_code=201)
    def alta_linia_preu(local_id: int, body: LiniaPreuIn, user: User = Depends(current_user), s: Session = Depends(db)):
        need_manager(user)
        check_local(s, user, local_id)
        return {"id": run(linies_preu.create, s, user, local_id, body.nom).id}

    @app.get("/linies-preu/{linia_id}")
    def detall_linia_preu(linia_id: int, user: User = Depends(current_user), s: Session = Depends(db)):
        return linies_preu.detall(s, linia_or_404(s, user, linia_id))

    @app.put("/linies-preu/{linia_id}")
    def edita_linia_preu(linia_id: int, body: LiniaPreuUpdateIn, user: User = Depends(current_user), s: Session = Depends(db)):
        run(linies_preu.update, s, user, linia_or_404(s, user, linia_id), body.nom, body.actiu)
        return {"ok": True}

    @app.put("/linies-preu/{linia_id}/preus/{product_id}")
    def posa_preu_linia(linia_id: int, product_id: int, body: PreuLiniaIn, user: User = Depends(current_user), s: Session = Depends(db)):
        run(linies_preu.set_price, s, user, linia_or_404(s, user, linia_id), product_id, body.preu_cent_per_g)
        return {"ok": True}

    @app.delete("/linies-preu/{linia_id}/preus/{product_id}")
    def esborra_preu_linia(linia_id: int, product_id: int, user: User = Depends(current_user), s: Session = Depends(db)):
        if not linies_preu.remove_price(s, user, linia_or_404(s, user, linia_id), product_id):
            raise HTTPException(404, "Aquest producte no té preu a la línia")
        return {"ok": True}

    @app.get("/socis/{member_id}/linia-preu")
    def linia_preu_del_soci(member_id: int, user: User = Depends(current_user), s: Session = Depends(db)):
        return linies_preu.member_line(s, member_or_404(s, user, member_id).id)

    @app.put("/socis/{member_id}/linia-preu")
    def assigna_linia_preu(member_id: int, body: AssignaLiniaIn, user: User = Depends(current_user), s: Session = Depends(db)):
        need_manager(user)
        run(linies_preu.assign, s, user, member_or_404(s, user, member_id), body.price_line_id)
        return {"ok": True}

    class InventariIn(BaseModel):
        nom: str | None = Field(default=None, max_length=60)

    class RecompteIn(BaseModel):
        grams: Decimal = Field(ge=0, le=1_000_000, decimal_places=3)

    def inventari_or_404(s: Session, user: User, inventari_id: int) -> InventorySession:
        need_manager(user)
        inv = s.get(InventorySession, inventari_id)
        if not inv:
            raise HTTPException(404, "Inventari inexistent")
        check_local(s, user, inv.local_id)
        return inv

    @app.get("/locals/{local_id}/inventaris")
    def llista_inventaris(local_id: int, user: User = Depends(current_user), s: Session = Depends(db)):
        need_manager(user)
        check_local(s, user, local_id)
        return inventaris.llista(s, local_id)

    @app.post("/locals/{local_id}/inventaris", status_code=201)
    def obre_inventari(local_id: int, body: InventariIn, user: User = Depends(current_user), s: Session = Depends(db)):
        need_manager(user)
        check_local(s, user, local_id)
        return {"id": run(inventaris.obrir, s, user, local_id, body.nom).id}

    @app.get("/inventaris/{inventari_id}")
    def detall_inventari(inventari_id: int, user: User = Depends(current_user), s: Session = Depends(db)):
        return inventaris.detall(s, inventari_or_404(s, user, inventari_id))

    @app.put("/inventaris/{inventari_id}/linies/{product_id}")
    def compta_producte(inventari_id: int, product_id: int, body: RecompteIn, user: User = Depends(current_user), s: Session = Depends(db)):
        run(inventaris.comptar, s, user, inventari_or_404(s, user, inventari_id), product_id, body.grams)
        return {"ok": True}

    @app.post("/inventaris/{inventari_id}/tancar")
    def tanca_inventari(inventari_id: int, user: User = Depends(current_user), s: Session = Depends(db)):
        return run(inventaris.tancar, s, user, inventari_or_404(s, user, inventari_id))

    @app.post("/inventaris/{inventari_id}/cancelar")
    def cancella_inventari(inventari_id: int, user: User = Depends(current_user), s: Session = Depends(db)):
        run(inventaris.cancellar, s, user, inventari_or_404(s, user, inventari_id))
        return {"ok": True}

    class ReglaIn(BaseModel):
        nom: str = Field(max_length=60)
        ambit: str
        categoria: str | None = Field(default=None, max_length=60)
        product_id: int | None = None
        periode: str
        max_g: Decimal

    class ReglaUpdateIn(BaseModel):
        nom: str | None = Field(default=None, max_length=60)
        max_g: Decimal | None = None
        actiu: bool | None = None

    @app.get("/locals/{local_id}/regles")
    def llista_regles(local_id: int, user: User = Depends(current_user), s: Session = Depends(db)):
        need_manager(user)
        check_local(s, user, local_id)
        return regles.list_rules(s, local_id)

    @app.post("/locals/{local_id}/regles", status_code=201)
    def alta_regla(local_id: int, body: ReglaIn, user: User = Depends(current_user), s: Session = Depends(db)):
        need_admin(user)
        check_local(s, user, local_id)
        r = run(regles.create, s, user, local_id, body.nom, body.ambit, body.categoria, body.product_id, body.periode, body.max_g)
        return {"id": r.id}

    @app.put("/regles/{regla_id}")
    def edita_regla(regla_id: int, body: ReglaUpdateIn, user: User = Depends(current_user), s: Session = Depends(db)):
        need_admin(user)
        r = s.get(Regla, regla_id)
        if not r:
            raise HTTPException(404, "Regla inexistent")
        check_local(s, user, r.local_id)
        run(regles.update, s, user, r, body.actiu, body.nom, body.max_g)
        return {"ok": True}

    class QuotaIn(BaseModel):
        import_cent: int = Field(gt=0, le=quotes.MAX_IMPORT_CENT)
        metode: str
        mesos: int = Field(default=1, ge=1, le=quotes.MAX_MESOS)

    @app.post("/socis/{member_id}/quotes", status_code=201)
    def cobrar_quota(member_id: int, body: QuotaIn, user: User = Depends(current_user), s: Session = Depends(db)):
        q = run(quotes.charge, s, user, member_or_404(s, user, member_id), body.import_cent, body.metode, body.mesos)
        return {"id": q.id, "valid_des": q.valid_des.isoformat(), "valid_fins": q.valid_fins.isoformat(), "apunt": q.cash_entry_id}

    @app.get("/socis/{member_id}/quotes")
    def historial_quotes(member_id: int, user: User = Depends(current_user), s: Session = Depends(db)):
        m = member_or_404(s, user, member_id)
        service.audit_append(s, {"accio": "consulta_quotes", "soci": m.id, "per": user.id})
        s.commit()
        return {"estat": quotes.status(s, m.id), "historial": quotes.history(s, m.id)}

    class AjustosIn(BaseModel):
        quota_obligatoria: bool | None = None
        quota_cent: int | None = Field(default=None, ge=0, le=quotes.MAX_IMPORT_CENT)
        quota_mesos: int | None = Field(default=None, ge=1, le=quotes.MAX_MESOS)

    @app.put("/locals/{local_id}/config")
    def canvia_config(local_id: int, body: AjustosIn, user: User = Depends(current_user), s: Session = Depends(db)):
        need_admin(user)
        if not s.get(Local, local_id):
            raise HTTPException(404, "Local inexistent")
        return run(ajustos.set_, s, user, local_id, body.model_dump())

    @app.post("/moviments/merma", status_code=201)
    def merma(body: MermaIn, user: User = Depends(current_user), s: Session = Depends(db)):
        need_manager(user)
        product_or_404(s, user, body.product_id)
        return {"id": run(stock.shrink, s, user, body.product_id, body.grams, body.nota).id}

    @app.post("/moviments/ajust", status_code=201)
    def ajust(body: AjustIn, user: User = Depends(current_user), s: Session = Depends(db)):
        need_manager(user)
        product_or_404(s, user, body.product_id)
        return {"id": run(stock.adjust, s, user, body.product_id, body.grams_reals, body.nota).id}

    @app.post("/fitxatge", status_code=201)
    def fitxar(body: FitxatgeIn, user: User = Depends(current_user), s: Session = Depends(db)):
        check_local(s, user, body.local_id)
        return {"id": run(personal.clock, s, user, body.local_id, body.tipus).id}

    @app.get("/locals/{local_id}/hores")
    def hores(local_id: int, des: date, fins: date, user: User = Depends(current_user), s: Session = Depends(db)):
        need_manager(user)
        check_local(s, user, local_id)
        return personal.hours(s, local_id, des, fins)

    @app.post("/locals", status_code=201)
    def alta_local(body: LocalIn, user: User = Depends(current_user), s: Session = Depends(db)):
        need_admin(user)
        return {"id": run(service.create_local, s, user, body.nom).id}

    @app.post("/usuaris", status_code=201)
    def alta_usuari(body: UsuariIn, user: User = Depends(current_user), s: Session = Depends(db)):
        need_admin(user)
        u, secret = run(service.create_user, s, user, body.username, body.password, body.role, body.local_ids)
        return {"id": u.id, "totp_secret": secret}

    @app.get("/usuaris")
    def llista_usuaris(user: User = Depends(current_user), s: Session = Depends(db)):
        need_admin(user)
        return usuaris.list_users(s)

    class UsuariUpdateIn(BaseModel):
        active: bool | None = None
        role: str | None = None
        local_ids: list[int] | None = None

    def usuari_or_404(s: Session, user_id: int) -> User:
        u = s.get(User, user_id)
        if not u:
            raise HTTPException(404, "Usuari inexistent")
        return u

    @app.patch("/usuaris/{user_id}")
    def edita_usuari(user_id: int, body: UsuariUpdateIn, user: User = Depends(current_user), s: Session = Depends(db)):
        need_admin(user)
        run(usuaris.update_user, s, user, usuari_or_404(s, user_id), body.active, body.role, body.local_ids)
        return {"ok": True}

    @app.post("/usuaris/{user_id}/totp")
    def reinicia_totp(user_id: int, user: User = Depends(current_user), s: Session = Depends(db)):
        need_admin(user)
        return {"totp_secret": usuaris.reset_totp(s, user, usuari_or_404(s, user_id))}

    class ContrasenyaIn(BaseModel):
        password: str = Field(max_length=200)

    @app.post("/usuaris/{user_id}/contrasenya")
    def posa_contrasenya(user_id: int, body: ContrasenyaIn, user: User = Depends(current_user), s: Session = Depends(db)):
        need_admin(user)
        run(usuaris.set_password, s, user, usuari_or_404(s, user_id), body.password)
        return {"ok": True}

    class CanviContrasenyaIn(BaseModel):
        actual: str = Field(max_length=200)
        nova: str = Field(max_length=200)

    @app.post("/auth/canvi-contrasenya")
    def canvi_contrasenya(body: CanviContrasenyaIn, authorization: str = Header(default=""), user: User = Depends(current_user), s: Session = Depends(db)):
        _, _, token = authorization.partition(" ")
        try:
            usuaris.change_own_password(s, user, body.actual, body.nova, token)
        except service.LoginLocked:
            raise HTTPException(429, "Massa intents fallits: queda bloquejat uns minuts.")
        except PermissionError as e:
            raise HTTPException(403, str(e))
        except ValueError as e:
            raise HTTPException(422, str(e))
        return {"ok": True}

    @app.put("/locals/{local_id}/limits")
    def limits(local_id: int, body: LimitsIn, user: User = Depends(current_user), s: Session = Depends(db)):
        need_admin(user)
        loc = s.get(Local, local_id)
        if not loc:
            raise HTTPException(404, "Local inexistent")
        mg = lambda g: None if g is None else int(g * 1000)
        loc.limit_diari_mg, loc.limit_mensual_mg = mg(body.limit_diari_g), mg(body.limit_mensual_g)
        loc.tolerancia_bascula_mg = mg(body.tolerancia_bascula_g)
        service.audit_append(s, {"accio": "canvi_limits", "local": local_id, "per": user.id})
        s.commit()
        return {"ok": True}

    @app.get("/me")
    def me(user: User = Depends(current_user), s: Session = Depends(db)):
        if user.role == "admin":
            locs = s.scalars(select(Local).order_by(Local.id)).all()
        else:
            ids = [r.local_id for r in s.scalars(select(UserLocal).where(UserLocal.user_id == user.id))]
            locs = [s.get(Local, i) for i in ids]
        return {"id": user.id, "username": user.username, "role": user.role,
                "locals": [{"id": l.id, "nom": l.nom, "limit_diari_mg": l.limit_diari_mg,
                            "limit_mensual_mg": l.limit_mensual_mg,
                            "tolerancia_bascula_mg": l.tolerancia_bascula_mg, **ajustos.get(s, l.id)} for l in locs]}

    @app.post("/auth/logout")
    def logout(authorization: str = Header(default=""), s: Session = Depends(db)):
        import hashlib
        from .models import SessionToken
        _, _, token = authorization.partition(" ")
        row = s.get(SessionToken, hashlib.sha256(token.encode()).hexdigest()) if token else None
        if row:
            s.delete(row)
            s.commit()
        return {"ok": True}

    @app.get("/locals/{local_id}/caixa")
    def estat_caixa(local_id: int, user: User = Depends(current_user), s: Session = Depends(db)):
        check_local(s, user, local_id)
        cs = cash.current_session(s, local_id)
        if not cs:
            return {"oberta": False}
        out = {"oberta": True, "sessio": cs.id, "obertura_cent": cs.opening_cent}
        if user.role in CAN_CREATE_MEMBER:
            out["esperat_cent"] = cash.expected_cash(s, cs)
        return out

    front = Path(__file__).resolve().parents[2] / "frontend"
    if front.is_dir():
        app.mount("/", StaticFiles(directory=front, html=True), name="front")
    return app

from datetime import date
from decimal import Decimal
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import ajustos, cash, informes, personal, quotes, schema, service, socis, stock, usuaris
from .db import make_engine, make_session_factory
from .models import CashEntry, Local, Member, Product, StockMovement, User, UserLocal

CAN_CREATE_MEMBER = {"admin", "encarregat"}


def get_db_factory():
    engine = make_engine()
    falten = schema.missing_tables(engine)
    if falten:
        # Millor aturar-se aquí que donar errors 500 críptics a mig servei després d'actualitzar el programa.
        raise RuntimeError(f"Falten taules a la base de dades ({', '.join(falten)}). "
                           "Executa, amb l'usuari propietari: python -m app.cli actualitzar-bd")
    return make_session_factory(engine)


def create_app(session_factory=None) -> FastAPI:
    app = FastAPI(title="club-gestio")

    @app.middleware("http")
    async def security_headers(request, call_next):
        resp = await call_next(request)
        resp.headers["Content-Security-Policy"] = (
            "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; "
            "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        resp.headers["X-Frame-Options"] = "DENY"
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["Referrer-Policy"] = "no-referrer"
        if not request.url.path.startswith("/static-"):
            if request.url.path not in ("/", "/sw.js", "/util.js", "/bascula.js", "/app.js", "/views-dispensar.js", "/views-gestio.js",
                                        "/views-socis.js", "/views-informes.js", "/views-historial.js", "/views-admin.js", "/style.css", "/manifest.webmanifest", "/icon.svg"):
                resp.headers["Cache-Control"] = "no-store"
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
        username: str
        password: str
        totp: str

    class MemberIn(BaseModel):
        local_id: int
        nom: str = Field(min_length=2, max_length=120)
        document: str = Field(min_length=5, max_length=30)
        naixement: date
        telefon: str | None = None
        email: str | None = None

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

    class EntradaIn(BaseModel):
        product_id: int
        grams: Decimal = Field(gt=0, max_digits=9, decimal_places=3)
        nota: str | None = Field(default=None, max_length=300)

    class DispensacioIn(BaseModel):
        member_id: int
        product_id: int
        grams: Decimal = Field(gt=0, max_digits=9, decimal_places=3)
        pes_bascula_g: Decimal | None = Field(default=None, gt=0, max_digits=9, decimal_places=3)

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
        p = run(stock.add_product, s, user, body.local_id, body.nom, body.categoria, body.preu_cent_per_g)
        return {"id": p.id}

    class ProductUpdateIn(BaseModel):
        nom: str | None = Field(default=None, min_length=1, max_length=120)
        categoria: str | None = Field(default=None, max_length=60)
        preu_cent_per_g: int | None = Field(default=None, ge=0, le=10_000_000)
        actiu: bool | None = None

    @app.patch("/productes/{product_id}")
    def edita_producte(product_id: int, body: ProductUpdateIn, user: User = Depends(current_user), s: Session = Depends(db)):
        if user.role not in CAN_CREATE_MEMBER:
            raise HTTPException(403, "El teu rol no pot editar productes")
        product_or_404(s, user, product_id)
        run(stock.update_product, s, user, product_id, body.nom, body.categoria, body.preu_cent_per_g, body.actiu)
        return {"ok": True}

    @app.get("/locals/{local_id}/productes")
    def tots_els_productes(local_id: int, user: User = Depends(current_user), s: Session = Depends(db)):
        """Catàleg complet (també els inactius) per a la gestió; el dispensador només veu els actius a /estoc."""
        if user.role not in CAN_CREATE_MEMBER:
            raise HTTPException(403, "El teu rol no pot gestionar productes")
        check_local(s, user, local_id)
        prods = s.scalars(select(Product).where(Product.local_id == local_id).order_by(Product.actiu.desc(), Product.nom))
        return [{"id": p.id, "nom": p.nom, "categoria": p.categoria, "preu_cent_per_g": p.preu_cent_per_g, "actiu": p.actiu,
                 "estoc_g": str(Decimal(stock.stock_mg(s, p.id)) / 1000)} for p in prods]

    @app.get("/locals/{local_id}/estoc")
    def veure_estoc(local_id: int, user: User = Depends(current_user), s: Session = Depends(db)):
        check_local(s, user, local_id)
        prods = s.scalars(select(Product).where(Product.local_id == local_id, Product.actiu.is_(True)))
        return [{"id": p.id, "nom": p.nom, "categoria": p.categoria, "preu_cent_per_g": p.preu_cent_per_g,
                 "estoc_g": str(Decimal(stock.stock_mg(s, p.id)) / 1000)} for p in prods]

    @app.post("/moviments/entrada", status_code=201)
    def entrada(body: EntradaIn, user: User = Depends(current_user), s: Session = Depends(db)):
        if user.role not in CAN_CREATE_MEMBER:
            raise HTTPException(403, "El teu rol no pot registrar entrades")
        product_or_404(s, user, body.product_id)
        m = run(stock.receive, s, user, body.product_id, body.grams, body.nota)
        return {"id": m.id}

    @app.post("/dispensacions", status_code=201)
    def dispensacio(body: DispensacioIn, user: User = Depends(current_user), s: Session = Depends(db)):
        product_or_404(s, user, body.product_id)
        m = run(stock.dispense, s, user, body.member_id, body.product_id, body.grams, body.pes_bascula_g)
        return {"id": m.id, "import_cent": m.import_cent}

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
    def informe(local_id: int, des: date, fins: date, user: User = Depends(current_user), s: Session = Depends(db)):
        need_manager(user)
        check_local(s, user, local_id)
        if fins < des:
            raise HTTPException(422, "Rang de dates invàlid")
        return cash.report(s, local_id, des, fins)

    @app.get("/locals/{local_id}/apunts.csv")
    def apunts_csv(local_id: int, des: date, fins: date, user: User = Depends(current_user), s: Session = Depends(db)):
        need_manager(user)
        check_local(s, user, local_id)
        service.audit_append(s, {"accio": "exportar_csv", "informe": "apunts", "local": local_id, "per": user.id})
        s.commit()
        return Response(cash.entries_csv(s, local_id, des, fins), media_type="text/csv")

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
        def calcula(local_id: int, des: date | None, fins: date | None, user: User, s: Session):
            need_manager(user)
            check_local(s, user, local_id)
            if not amb_rang:
                return fn(s, local_id)
            if des is None or fins is None:
                raise HTTPException(422, "Cal indicar des de i fins a")
            if fins < des:
                raise HTTPException(422, "Rang de dates invàlid")
            return fn(s, local_id, des, fins)

        @app.get(f"/locals/{{local_id}}/informe/{nom}", name=f"informe_{nom}")
        def veure(local_id: int, des: date | None = None, fins: date | None = None,
                  user: User = Depends(current_user), s: Session = Depends(db)):
            return calcula(local_id, des, fins, user, s)

        @app.get(f"/locals/{{local_id}}/informe/{nom}.csv", name=f"informe_{nom}_csv")
        def exporta(local_id: int, des: date | None = None, fins: date | None = None,
                    user: User = Depends(current_user), s: Session = Depends(db)):
            r = calcula(local_id, des, fins, user, s)
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

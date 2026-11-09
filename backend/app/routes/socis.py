"""Rutes: socis (fitxa, cerques, foto, signatura, carnet) (extretes de main.py sense canviar-ne el comportament)."""
from datetime import date

from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .. import service, socis
from ..models import Member, User
from .comu import CAN_CREATE_MEMBER


def register(app, db, current_user, check_local, need_manager, run, member_or_404, member_payload):
    class MemberIn(BaseModel):
        local_id: int
        nom: str = Field(min_length=2, max_length=120)
        document: str = Field(min_length=5, max_length=30)
        naixement: date
        telefon: str | None = None
        email: str | None = None

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
        return member_payload(s, m, user)

    class EstatIn(BaseModel):
        estat: str

    class SignaturaIn(BaseModel):
        png_base64: str = Field(max_length=300_000)
        text_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")  # text informatiu que el soci accepta en signar

    @app.post("/socis/{member_id}/signatura", status_code=201)
    def signar(member_id: int, body: SignaturaIn, user: User = Depends(current_user), s: Session = Depends(db)):
        need_manager(user)
        sig = run(service.save_signature, s, user, member_or_404(s, user, member_id), body.png_base64, body.text_sha256)
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

    class CercaDocumentIn(BaseModel):
        document: str = Field(min_length=1, max_length=30)

    class CercaCarnetIn(BaseModel):
        codi: str = Field(min_length=1, max_length=100)

    # Cerques per POST amb cos: el document i el codi del carnet no queden a la URL (logs del proxy, historial, Referer).
    @app.post("/locals/{local_id}/socis/cerca")
    def cerca_soci(local_id: int, body: CercaDocumentIn, user: User = Depends(current_user), s: Session = Depends(db)):
        check_local(s, user, local_id)
        m = service.find_member_by_document(s, local_id, body.document)
        service.audit_append(s, {"accio": "cerca_soci", "local": local_id, "trobat": bool(m), "per": user.id})
        s.commit()
        if not m:
            raise HTTPException(404, "No existeix")
        return member_payload(s, m, user)

    @app.post("/locals/{local_id}/socis/carnet")
    def cerca_carnet(local_id: int, body: CercaCarnetIn, user: User = Depends(current_user), s: Session = Depends(db)):
        check_local(s, user, local_id)
        m = socis.find_by_card(s, local_id, body.codi)
        service.audit_append(s, {"accio": "cerca_carnet", "local": local_id, "trobat": bool(m), "per": user.id})
        s.commit()
        if not m:
            raise HTTPException(404, "No existeix")
        return member_payload(s, m, user)

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

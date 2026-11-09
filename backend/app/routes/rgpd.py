"""Rutes RGPD: text informatiu i consentiments, accés/portabilitat, supressió, retenció, consulta d'auditoria i ancoratges."""
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import auditoria_consulta, consentiments, controls, exportacio, retencio, service, supressio, textos
from ..models import AuditAnchor, Signature, User
from .comu import check_local, member_or_404, need_admin, need_manager, run

SIG_MAX_EDAT = timedelta(minutes=30)  # la signatura enllaçada amb sig_ultima ha de ser de la mateixa alta


class ConsentIn(BaseModel):
    versio: str = Field(max_length=20)
    text_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    finalitats: list[str] = Field(min_length=1, max_length=3)
    canal: str = Field(default="presencial", max_length=20)


class RetiradaIn(BaseModel):
    finalitat: str = Field(max_length=20)
    canal: str = Field(default="presencial", max_length=20)


class AltaRgpdIn(ConsentIn):
    """Tancament de l'alta: consentiments (el bàsic és obligatori), signatura lligada al hash del text, document exhibit i aval."""
    doc_verificat: bool = False
    avalador_id: int | None = None
    png_base64: str | None = Field(default=None, max_length=300_000)
    sig_ultima: bool = False  # la signatura ja s'ha desat (pantalla d'alta): s'hi enllaça el consentiment


class SupressioIn(BaseModel):
    motiu: str = Field(default="", max_length=100)
    confirmar: bool = False


class RetencioIn(BaseModel):
    confirmar: bool = False
    local_id: int | None = None


def router(db, current_user) -> APIRouter:
    r = APIRouter()

    @r.get("/textos/informatiu")
    def text_informatiu(versio: str = textos.VERSIO_ACTUAL, idioma: str = "ca", user: User = Depends(current_user)):
        try:
            return {"versio": versio, "idioma": idioma, "text": textos.text(versio, idioma), "sha256": textos.sha256(versio, idioma),
                    "hashes": textos.hashes(versio), "versions": textos.versions()}
        except ValueError as e:
            raise HTTPException(404, str(e))

    @r.post("/socis/{member_id}/alta-rgpd", status_code=201)
    def alta_rgpd(member_id: int, body: AltaRgpdIn, user: User = Depends(current_user), s: Session = Depends(db)):
        need_manager(user)
        m = member_or_404(s, user, member_id)
        if "basic" not in body.finalitats:
            raise HTTPException(422, "El consentiment del tractament bàsic és obligatori")
        if textos.idioma_del_hash(body.versio, body.text_sha256) is None:  # abans de desar res
            raise HTTPException(422, "El text informatiu acceptat no coincideix amb cap versió publicada")
        run(controls.complete_alta, s, user, m, body.doc_verificat, body.avalador_id)  # primer el que pot fallar per regles del local
        sig = run(service.save_signature, s, user, m, body.png_base64, body.text_sha256) if body.png_base64 else None
        if sig is None and body.sig_ultima:  # el consentiment queda lligat a (signatura, hash del text)
            sig = s.scalar(select(Signature).where(Signature.member_id == m.id).order_by(Signature.id.desc()).limit(1))
            if sig is None:
                raise HTTPException(422, "El soci encara no ha signat")
            if sig.text_sha256 != body.text_sha256:  # la signatura ha de ser del mateix text que s'accepta
                raise HTTPException(422, "La darrera signatura no correspon al text informatiu acceptat: cal tornar a signar")
            if datetime.now(timezone.utc) - supressio._aware(sig.ts) > SIG_MAX_EDAT:
                raise HTTPException(422, "La darrera signatura és massa antiga: cal tornar a signar")
        run(consentiments.grant, s, user, m, body.finalitats, body.versio, body.text_sha256, body.canal, sig.id if sig else None, False)
        s.commit()
        return {"consentiments": consentiments.status(s, m.id), "signatura": sig.id if sig else None}

    @r.get("/socis/{member_id}/consentiments")
    def veure_consentiments(member_id: int, user: User = Depends(current_user), s: Session = Depends(db)):
        need_manager(user)
        m = member_or_404(s, user, member_id)
        return {"vigents": consentiments.status(s, m.id), "historial": consentiments.history(s, m.id)}

    @r.post("/socis/{member_id}/consentiments", status_code=201)
    def dona_consentiment(member_id: int, body: ConsentIn, user: User = Depends(current_user), s: Session = Depends(db)):
        need_manager(user)
        m = member_or_404(s, user, member_id)
        run(consentiments.grant, s, user, m, body.finalitats, body.versio, body.text_sha256, body.canal)
        return {"vigents": consentiments.status(s, m.id)}

    @r.post("/socis/{member_id}/consentiments/retirada")
    def retira_consentiment(member_id: int, body: RetiradaIn, user: User = Depends(current_user), s: Session = Depends(db)):
        need_manager(user)
        m = member_or_404(s, user, member_id)
        run(consentiments.withdraw, s, user, m, body.finalitat, body.canal)
        return {"vigents": consentiments.status(s, m.id)}

    @r.get("/socis/{member_id}/exportacio")
    def exporta_soci(member_id: int, user: User = Depends(current_user), s: Session = Depends(db)):
        need_manager(user)
        return exportacio.export_member(s, user, member_or_404(s, user, member_id))

    @r.get("/socis/{member_id}/exportacio/consum.csv")
    def exporta_consum(member_id: int, user: User = Depends(current_user), s: Session = Depends(db)):
        need_manager(user)
        csv = exportacio.consumption_csv(s, user, member_or_404(s, user, member_id))
        return Response(csv, media_type="text/csv", headers={"Content-Disposition": f'attachment; filename="consum-soci-{member_id}.csv"'})

    @r.post("/socis/{member_id}/supressio")
    def suprimeix_soci(member_id: int, body: SupressioIn, user: User = Depends(current_user), s: Session = Depends(db)):
        need_admin(user)
        m = member_or_404(s, user, member_id)
        if not body.confirmar:
            return {"aplicat": False, "bloqueig": supressio.bloqueig(s, m), "min_dies": supressio.retencio_min_dies()}
        return {"aplicat": True, **run(supressio.pseudonymize, s, user.id, m, body.motiu)}

    @r.get("/locals/{local_id}/retencio")
    def retencio_simula(local_id: int, user: User = Depends(current_user), s: Session = Depends(db)):
        need_admin(user)
        check_local(s, user, local_id)
        return retencio.run(s, user.id, False, local_id)

    @r.post("/locals/{local_id}/retencio/aplicar")
    def retencio_aplica(local_id: int, body: RetencioIn, user: User = Depends(current_user), s: Session = Depends(db)):
        need_admin(user)
        check_local(s, user, local_id)
        if not body.confirmar:
            raise HTTPException(422, "Cal confirmar l'execució de la purga")
        return retencio.run(s, user.id, True, local_id)

    @r.get("/retencio")
    def retencio_global_simula(user: User = Depends(current_user), s: Session = Depends(db)):
        """Política de retenció GLOBAL (tots els locals, intents de login i sessions): només administrador."""
        need_admin(user)
        return retencio.run(s, user.id, False, None)

    @r.post("/retencio/aplicar")
    def retencio_global_aplica(body: RetencioIn, user: User = Depends(current_user), s: Session = Depends(db)):
        need_admin(user)
        if not body.confirmar:
            raise HTTPException(422, "Cal confirmar l'execució de la purga")
        return retencio.run(s, user.id, True, None)

    @r.get("/auditoria/consulta")
    def consulta_auditoria(soci: int | None = None, usuari: int | None = None, accio: str | None = Query(default=None, max_length=40),
                           des: date | None = None, fins: date | None = None, limit: int = Query(default=100, ge=1, le=500),
                           offset: int = Query(default=0, ge=0, le=1_000_000), user: User = Depends(current_user), s: Session = Depends(db)):
        need_admin(user)
        out = run(auditoria_consulta.query, s, soci, usuari, accio, des, fins, limit, offset)
        service.audit_append(s, {"accio": "consulta_auditoria", "filtre": {"f_soci": soci, "f_usuari": usuari, "f_accio": accio}, "per": user.id})
        s.commit()
        return out

    @r.get("/socis/{member_id}/accessos")
    def accessos(member_id: int, user: User = Depends(current_user), s: Session = Depends(db)):
        """Qui ha consultat o exportat les dades d'aquest soci."""
        need_admin(user)
        m = member_or_404(s, user, member_id)
        service.audit_append(s, {"accio": "consulta_accessos", "soci": m.id, "per": user.id})
        s.commit()
        return {"soci": m.id, "accessos": auditoria_consulta.accessos_al_soci(s, m.id)}

    @r.get("/socis/{member_id}/accessos.csv")
    def accessos_csv(member_id: int, user: User = Depends(current_user), s: Session = Depends(db)):
        need_admin(user)
        m = member_or_404(s, user, member_id)
        service.audit_append(s, {"accio": "exporta_accessos", "soci": m.id, "per": user.id})
        s.commit()
        return Response(auditoria_consulta.accessos_csv(auditoria_consulta.accessos_al_soci(s, m.id)), media_type="text/csv")

    @r.post("/auditoria/ancoratges", status_code=201)
    def desa_ancoratge(user: User = Depends(current_user), s: Session = Depends(db)):
        need_admin(user)
        a = service.audit_anchor_save(s, f"usuari:{user.id}")
        if not a:
            raise HTTPException(422, "L'auditoria és buida")
        s.commit()
        return {"seq": a.seq, "hash": a.hash, "ts": a.ts.isoformat()}

    @r.get("/auditoria/ancoratges")
    def llista_ancoratges(user: User = Depends(current_user), s: Session = Depends(db)):
        need_admin(user)
        return [{"id": a.id, "seq": a.seq, "hash": a.hash, "ts": a.ts.isoformat(), "origen": a.origen}
                for a in s.scalars(select(AuditAnchor).order_by(AuditAnchor.id.desc()).limit(200))]

    return r

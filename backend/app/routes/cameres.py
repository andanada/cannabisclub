"""Rutes: càmeres IP en directe (vegeu cameres.py)."""
from fastapi import Depends, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .. import cameres
from ..models import Camera, User
from .comu import need_permis


def register(app, db, current_user, check_local, need_admin, run):
    class CameraIn(BaseModel):
        nom: str = Field(min_length=1, max_length=60)
        url: str = Field(min_length=8, max_length=300)   # rtsp://usuari:contrasenya@192.168.x.x:554/camí

    class CameraUpdateIn(BaseModel):
        nom: str | None = Field(default=None, max_length=60)
        url: str | None = Field(default=None, max_length=300)
        actiu: bool | None = None
        ordre: int | None = Field(default=None, ge=0, le=999)

    def camera_or_404(s: Session, user: User, camera_id: int) -> Camera:
        c = s.get(Camera, camera_id)
        if not c:
            raise HTTPException(404, "Càmera inexistent")
        check_local(s, user, c.local_id)
        return c

    @app.get("/locals/{local_id}/cameres")
    def llista_cameres(local_id: int, user: User = Depends(current_user), s: Session = Depends(db)):
        need_permis(user, "cameres")
        check_local(s, user, local_id)
        return {"ffmpeg": cameres.ffmpeg_path() is not None, "cameres": cameres.llista(s, user, local_id)}

    @app.get("/cameres/{camera_id}/frame")
    def frame_camera(camera_id: int, user: User = Depends(current_user), s: Session = Depends(db)):
        """Últim fotograma JPEG de la càmera. S'actualitza ~2 cops per segon; la pantalla el demana amb la capçalera d'autenticació."""
        need_permis(user, "cameres")
        c = camera_or_404(s, user, camera_id)
        if not c.actiu:
            raise HTTPException(409, "Càmera desactivada")
        url = cameres.url_de(c)
        s.close()   # no es manté una connexió a la BD mentre esperem la càmera
        try:
            jpg = cameres.frame(c.id, url)
        except ValueError as e:
            raise HTTPException(503, str(e))
        return Response(jpg, media_type="image/jpeg", headers={"Cache-Control": "no-store"})

    @app.post("/locals/{local_id}/cameres", status_code=201)
    def alta_camera(local_id: int, body: CameraIn, user: User = Depends(current_user), s: Session = Depends(db)):
        need_admin(user)
        check_local(s, user, local_id)
        return {"id": run(cameres.crea, s, user, local_id, body.nom, body.url).id}

    @app.put("/cameres/{camera_id}")
    def edita_camera(camera_id: int, body: CameraUpdateIn, user: User = Depends(current_user), s: Session = Depends(db)):
        need_admin(user)
        run(cameres.edita, s, user, camera_or_404(s, user, camera_id), body.nom, body.url, body.actiu, body.ordre)
        return {"ok": True}

    @app.delete("/cameres/{camera_id}")
    def esborra_camera(camera_id: int, user: User = Depends(current_user), s: Session = Depends(db)):
        need_admin(user)
        run(cameres.esborra, s, user, camera_or_404(s, user, camera_id))
        return {"ok": True}

    @app.post("/cameres/{camera_id}/prova")
    def prova_camera(camera_id: int, user: User = Depends(current_user), s: Session = Depends(db)):
        """Comprova que arriba imatge (només administrador)."""
        need_admin(user)
        c = camera_or_404(s, user, camera_id)
        url = cameres.url_de(c)
        s.close()
        try:
            return {"ok": True, "bytes": len(cameres.frame(c.id, url))}
        except ValueError as e:
            return {"ok": False, "motiu": str(e)}

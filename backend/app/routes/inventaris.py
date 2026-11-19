"""Rutes: inventaris (control de l'estoc amb pesos reals)."""
from decimal import Decimal

from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .. import inventaris
from ..models import InventorySession, User
from .comu import need_dispensari, need_permis


def register(app, db, current_user, check_local, need_manager, run):
    class InventariIn(BaseModel):
        nom: str | None = Field(default=None, max_length=60)
        tipus: str = Field(default="dispensari", max_length=14)      # dispensari | magatzem | no_genetiques
        control: str = Field(default="complet", max_length=10)       # complet | producte
        product_id: int | None = None

    class RecompteIn(BaseModel):
        grams: Decimal = Field(ge=0, le=1_000_000, decimal_places=3)  # pes de la bàscula (al dispensari, amb la tara)
        nota: str | None = Field(default=None, max_length=300)

    def inventari_or_404(s: Session, user: User, inventari_id: int) -> InventorySession:
        need_dispensari(user)
        inv = s.get(InventorySession, inventari_id)
        if not inv:
            raise HTTPException(404, "Inventari inexistent")
        check_local(s, user, inv.local_id)
        return inv

    @app.get("/locals/{local_id}/inventaris")
    def llista_inventaris(local_id: int, user: User = Depends(current_user), s: Session = Depends(db)):
        need_dispensari(user)
        check_local(s, user, local_id)
        return inventaris.llista(s, local_id)

    @app.get("/locals/{local_id}/inventaris/resultats")
    def resultats_inventaris(local_id: int, user: User = Depends(current_user), s: Session = Depends(db)):
        need_permis(user, 'resultats_inventari')
        check_local(s, user, local_id)
        return inventaris.resultats(s, local_id)

    @app.post("/locals/{local_id}/inventaris", status_code=201)
    def obre_inventari(local_id: int, body: InventariIn, user: User = Depends(current_user), s: Session = Depends(db)):
        need_dispensari(user)
        check_local(s, user, local_id)
        return {"id": run(inventaris.obrir, s, user, local_id, body.nom, body.tipus, body.control, body.product_id).id}

    @app.get("/inventaris/{inventari_id}")
    def detall_inventari(inventari_id: int, user: User = Depends(current_user), s: Session = Depends(db)):
        from .. import permisos
        return inventaris.detall(s, inventari_or_404(s, user, inventari_id), permisos.te(user, 'resultats_inventari'))

    @app.put("/inventaris/{inventari_id}/linies/{product_id}")
    def compta_producte(inventari_id: int, product_id: int, body: RecompteIn, user: User = Depends(current_user), s: Session = Depends(db)):
        from .. import permisos
        return run(inventaris.comptar, s, user, inventari_or_404(s, user, inventari_id), product_id, body.grams, body.nota, permisos.te(user, 'resultats_inventari'))

    @app.post("/inventaris/{inventari_id}/guardar")
    def guarda_inventari(inventari_id: int, user: User = Depends(current_user), s: Session = Depends(db)):
        return run(inventaris.guardar, s, user, inventari_or_404(s, user, inventari_id))

    @app.post("/inventaris/{inventari_id}/ajustar")
    def ajusta_inventari(inventari_id: int, user: User = Depends(current_user), s: Session = Depends(db)):
        need_permis(user, 'resultats_inventari')
        return run(inventaris.ajustar, s, user, inventari_or_404(s, user, inventari_id))

    @app.post("/inventaris/{inventari_id}/cancelar")
    def cancella_inventari(inventari_id: int, user: User = Depends(current_user), s: Session = Depends(db)):
        run(inventaris.cancellar, s, user, inventari_or_404(s, user, inventari_id))
        return {"ok": True}

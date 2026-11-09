"""Rutes: inventaris (extretes de main.py sense canviar-ne el comportament)."""
from decimal import Decimal

from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .. import inventaris
from ..models import InventorySession, User


def register(app, db, current_user, check_local, need_manager, run):
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

"""Rutes: informes, apunts, moviments i personal (extretes de main.py sense canviar-ne el comportament)."""
from datetime import date

from fastapi import Depends, HTTPException, Query, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .. import cash, informes, informes_socis, personal, service, stock
from ..models import User


def register(app, db, current_user, check_local, need_manager, run, member_or_404, empleat_valid, personal_del_local, rang):
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

    @app.get("/locals/{local_id}/personal")
    def llista_personal(local_id: int, user: User = Depends(current_user), s: Session = Depends(db)):
        need_manager(user)
        check_local(s, user, local_id)
        return [{"id": u.id, "username": u.username, "role": u.role} for u in personal_del_local(s, local_id)]

    @app.get("/locals/{local_id}/apunts")
    def llista_apunts(local_id: int, des: date, fins: date, limit: int = Query(default=100, ge=1, le=500),
                      user: User = Depends(current_user), s: Session = Depends(db)):
        need_manager(user)
        check_local(s, user, local_id)
        rang(des, fins)
        return cash.entries_list(s, local_id, des, fins, limit)

    @app.get("/locals/{local_id}/moviments")
    def llista_moviments(local_id: int, des: date, fins: date, limit: int = Query(default=100, ge=1, le=500),
                         user: User = Depends(current_user), s: Session = Depends(db)):
        need_manager(user)
        check_local(s, user, local_id)
        rang(des, fins)
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
    registra_informe("visites", informes.visits, informes.visits_csv, True)
    registra_informe("evolucio", informes_socis.evolution, informes_socis.evolution_csv, True)
    registra_informe("demografia", informes_socis.demographics, informes_socis.demographics_csv, False)

    @app.get("/socis/{member_id}/consum")
    def consum_del_soci(member_id: int, des: date, fins: date, user: User = Depends(current_user), s: Session = Depends(db)):
        need_manager(user)
        rang(des, fins)
        return informes_socis.consumption(s, member_or_404(s, user, member_id), des, fins, actor=user)
    registra_informe("hores", informes.staff_hours, informes.hours_csv, True)

    class FitxatgeIn(BaseModel):
        local_id: int
        tipus: str

    @app.post("/fitxatge", status_code=201)
    def fitxar(body: FitxatgeIn, user: User = Depends(current_user), s: Session = Depends(db)):
        check_local(s, user, body.local_id)
        return {"id": run(personal.clock, s, user, body.local_id, body.tipus).id}

    @app.get("/locals/{local_id}/hores")
    def hores(local_id: int, des: date, fins: date, user: User = Depends(current_user), s: Session = Depends(db)):
        need_manager(user)
        check_local(s, user, local_id)
        return personal.hours(s, local_id, des, fins)

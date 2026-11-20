"""Rutes: informes, apunts, moviments i personal (extretes de main.py sense canviar-ne el comportament)."""
from datetime import date

from fastapi import Depends, HTTPException, Query, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .. import cash, estadistiques, estadistiques_dies, estadistiques_resum, informes, informes_socis, personal, service, stock
from ..models import User
from .comu import need_permis


def register(app, db, current_user, check_local, need_manager, run, member_or_404, empleat_valid, personal_del_local, rang):
    @app.get("/locals/{local_id}/informe")
    def informe(local_id: int, des: date, fins: date, usuari: int | None = None, user: User = Depends(current_user), s: Session = Depends(db)):
        need_permis(user, 'informes')
        check_local(s, user, local_id)
        if fins < des:
            raise HTTPException(422, "Rang de dates invàlid")
        empleat_valid(s, local_id, usuari)
        return cash.report(s, local_id, des, fins, usuari)

    @app.get("/locals/{local_id}/apunts.csv")
    def apunts_csv(local_id: int, des: date, fins: date, user: User = Depends(current_user), s: Session = Depends(db)):
        need_permis(user, 'informes')
        check_local(s, user, local_id)
        service.audit_append(s, {"accio": "exportar_csv", "informe": "apunts", "local": local_id, "per": user.id})
        s.commit()
        return Response(cash.entries_csv(s, local_id, des, fins), media_type="text/csv")

    @app.get("/locals/{local_id}/personal")
    def llista_personal(local_id: int, user: User = Depends(current_user), s: Session = Depends(db)):
        need_permis(user, 'informes')
        check_local(s, user, local_id)
        return [{"id": u.id, "username": u.username, "role": u.role} for u in personal_del_local(s, local_id)]

    @app.get("/locals/{local_id}/apunts")
    def llista_apunts(local_id: int, des: date, fins: date, limit: int = Query(default=100, ge=1, le=500),
                      user: User = Depends(current_user), s: Session = Depends(db)):
        from .comu import need_permis, need_recepcio
        need_recepcio(user)  # recepció (o gerència): és el llibre de la caixa
        check_local(s, user, local_id)
        rang(des, fins)
        return cash.entries_list(s, local_id, des, fins, limit)

    @app.get("/locals/{local_id}/moviments")
    def llista_moviments(local_id: int, des: date, fins: date, limit: int = Query(default=100, ge=1, le=500),
                         user: User = Depends(current_user), s: Session = Depends(db)):
        need_permis(user, 'historial')
        check_local(s, user, local_id)
        rang(des, fins)
        return stock.movements_list(s, local_id, des, fins, limit)

    # Informes de gestió (JSON i CSV). Només responsables; el CSV queda a l'auditoria.
    def registra_informe(nom: str, fn, csv_fn, amb_rang: bool):
        def calcula(local_id: int, des: date | None, fins: date | None, user: User, s: Session, usuari: int | None = None):
            need_permis(user, 'informes')
            check_local(s, user, local_id)
            if not amb_rang:
                return fn(s, local_id)
            empleat_valid(s, local_id, usuari)
            if des is None or fins is None:
                raise HTTPException(422, "Cal indicar des de i fins a")
            if fins < des:
                raise HTTPException(422, "Rang de dates invàlid")
            if nom == "visites":  # desxifra noms: rang limitat i consulta amb autor a l'auditoria
                if (fins - des).days > 366:
                    raise HTTPException(422, "El rang de visites no pot passar d'un any")
                return fn(s, local_id, des, fins, usuari, actor=user)
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
        if not user.pot_reemborsar:  # qui pot fer devolucions ha de poder veure què retorna
            need_permis(user, 'informes')
        rang(des, fins)
        return informes_socis.consumption(s, member_or_404(s, user, member_id), des, fins, actor=user)
    registra_informe("hores", informes.staff_hours, informes.hours_csv, True)

    @app.get("/locals/{local_id}/estadistiques/membres")
    def estadistica_membres(local_id: int, user: User = Depends(current_user), s: Session = Depends(db)):
        need_permis(user, 'informes')
        check_local(s, user, local_id)
        return estadistiques.membres(s, user, local_id)

    @app.get("/locals/{local_id}/estadistiques/dispensari")
    def estadistica_dispensari(local_id: int, des: date | None = None, fins: date | None = None,
                               user: User = Depends(current_user), s: Session = Depends(db)):
        need_permis(user, 'informes')
        check_local(s, user, local_id)
        if des and fins and fins < des:
            raise HTTPException(422, "Rang de dates invàlid")
        return estadistiques.dispensari(s, user, local_id, des, fins)

    def _rang(des: date, fins: date, max_dies: int = 3660):
        if fins < des or (fins - des).days > max_dies:
            raise HTTPException(422, "Rang de dates invàlid")

    @app.get("/locals/{local_id}/estadistiques/finances-dies")
    def estadistica_finances_dies(local_id: int, des: date, fins: date, user: User = Depends(current_user), s: Session = Depends(db)):
        need_permis(user, 'informes')
        check_local(s, user, local_id)
        _rang(des, fins, 365)
        return estadistiques_dies.finances_dies(s, user, local_id, des, fins)

    @app.get("/locals/{local_id}/estadistiques/rendibilitat")
    def estadistica_rendibilitat(local_id: int, des: date, fins: date, user: User = Depends(current_user), s: Session = Depends(db)):
        need_permis(user, 'informes')
        check_local(s, user, local_id)
        _rang(des, fins)
        return estadistiques_resum.rendibilitat(s, user, local_id, des, fins)

    @app.get("/locals/{local_id}/estadistiques/rendibilitat.csv")
    def estadistica_rendibilitat_csv(local_id: int, des: date, fins: date, user: User = Depends(current_user), s: Session = Depends(db)):
        r = estadistica_rendibilitat(local_id, des, fins, user, s)
        service.audit_append(s, {"accio": "exportar_csv", "informe": "rendibilitat", "local": local_id, "per": user.id})
        s.commit()
        return Response(estadistiques_resum.rendibilitat_csv(r), media_type="text/csv")

    @app.get("/locals/{local_id}/estadistiques/resum-mensual")
    def estadistica_resum(local_id: int, mes: str = Query(pattern=r"^\d{4}-(0[1-9]|1[0-2])$"), user: User = Depends(current_user), s: Session = Depends(db)):
        need_permis(user, 'informes')
        check_local(s, user, local_id)
        return estadistiques_resum.resum_mensual(s, user, local_id, mes)

    @app.get("/locals/{local_id}/estadistiques/resum-mensual.csv")
    def estadistica_resum_csv(local_id: int, mes: str = Query(pattern=r"^\d{4}-(0[1-9]|1[0-2])$"), user: User = Depends(current_user), s: Session = Depends(db)):
        r = estadistica_resum(local_id, mes, user, s)
        service.audit_append(s, {"accio": "exportar_csv", "informe": "resum_mensual", "local": local_id, "per": user.id})
        s.commit()
        return Response(estadistiques_resum.resum_csv(r), media_type="text/csv")

    @app.get("/locals/{local_id}/estadistiques/finances")
    def estadistica_finances(local_id: int, any: int | None = Query(default=None, ge=2000, le=2100),
                             user: User = Depends(current_user), s: Session = Depends(db)):
        need_permis(user, 'informes')
        check_local(s, user, local_id)
        return estadistiques.finances(s, user, local_id, any)

    class FitxatgeIn(BaseModel):
        local_id: int
        tipus: str

    @app.post("/fitxatge", status_code=201)
    def fitxar(body: FitxatgeIn, user: User = Depends(current_user), s: Session = Depends(db)):
        check_local(s, user, body.local_id)
        return {"id": run(personal.clock, s, user, body.local_id, body.tipus).id}

    @app.get("/locals/{local_id}/hores")
    def hores(local_id: int, des: date, fins: date, user: User = Depends(current_user), s: Session = Depends(db)):
        need_permis(user, 'informes')
        check_local(s, user, local_id)
        return personal.hours(s, local_id, des, fins)

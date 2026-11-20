"""Rutes: horaris (calendari, torns, sol·licituds amb aprovació, registre) i avançaments (només gerència)."""
from datetime import date

from fastapi import Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .. import horaris, horaris_canvis as canvis
from ..models import User

HORA = r"^([01]\d|2[0-3]):[0-5]\d$"


def register(app, db, current_user, check_local, need_manager, run, personal_del_local, rang):
    def mgr(local_id, user, s):
        need_manager(user)
        check_local(s, user, local_id)

    @app.get("/locals/{local_id}/horaris/config")
    def config_get(local_id: int, user: User = Depends(current_user), s: Session = Depends(db)):
        check_local(s, user, local_id)
        return horaris.get_config(s, local_id)

    class ConfigIn(BaseModel):
        torns: dict
        dies_unics: list[int] = []
        excepcions: list[dict] = []

    @app.put("/locals/{local_id}/horaris/config")
    def config_put(local_id: int, body: ConfigIn, user: User = Depends(current_user), s: Session = Depends(db)):
        mgr(local_id, user, s)
        return run(horaris.set_config, s, user, local_id, body.model_dump())

    @app.get("/locals/{local_id}/horaris/mes")
    def mes(local_id: int, any: int = 0, mes: int = 0, user: User = Depends(current_user), s: Session = Depends(db)):
        check_local(s, user, local_id)
        avui = date.today()
        any, mes = any or avui.year, mes or avui.month
        if not 2000 <= any <= 2100:
            any = avui.year
        out = run(horaris.mes, s, local_id, any, mes)
        out["treballadors"] = [{"id": u.id, "username": u.username} for u in personal_del_local(s, local_id)]
        out["pendents"] = len(canvis.llista_sollicituds(s, local_id, None if need_gerencia(user) else user, "pendent"))
        return out

    def need_gerencia(u):
        return u.role in ("admin", "encarregat")

    class SlotIn(BaseModel):
        data: date
        torn: str = Field(pattern="^(mati|tarda|unic)$")
        lloc: str = Field(pattern="^(dispensari|recepcio)$")
        user_id: int | None = None
        inici: str | None = Field(default=None, pattern=HORA)
        fi: str | None = Field(default=None, pattern=HORA)

    @app.put("/locals/{local_id}/horaris/slot")
    def slot(local_id: int, body: SlotIn, user: User = Depends(current_user), s: Session = Depends(db)):
        mgr(local_id, user, s)
        run(horaris.assigna, s, user, local_id, body.data, body.torn, body.lloc, body.user_id, body.inici, body.fi)
        return {"ok": True}

    class TornIn(BaseModel):
        data: date
        torn: str = Field(pattern="^(mati|tarda|unic)$")
        inici: str | None = Field(default=None, pattern=HORA)
        fi: str | None = Field(default=None, pattern=HORA)

    @app.put("/locals/{local_id}/horaris/torn")
    def torn(local_id: int, body: TornIn, user: User = Depends(current_user), s: Session = Depends(db)):
        mgr(local_id, user, s)
        run(horaris.horari_torn, s, user, local_id, body.data, body.torn, body.inici, body.fi)
        return {"ok": True}

    class SollicitudIn(BaseModel):
        tipus: str = Field(pattern="^(canvi|diferencia)$")
        data: date
        torn: str = Field(pattern="^(mati|tarda|unic)$")
        minuts: int = Field(default=0, ge=-720, le=720)
        substitut_id: int | None = None
        comentari: str | None = Field(default=None, max_length=300)

    @app.post("/locals/{local_id}/horaris/sollicituds", status_code=201)
    def sollicitud_alta(local_id: int, body: SollicitudIn, user: User = Depends(current_user), s: Session = Depends(db)):
        check_local(s, user, local_id)
        r = run(canvis.crea_sollicitud, s, user, local_id, body.tipus, body.data, body.torn, body.minuts, body.substitut_id, body.comentari)
        return {"id": r.id}

    @app.get("/locals/{local_id}/horaris/sollicituds")
    def sollicituds(local_id: int, estat: str | None = None, user: User = Depends(current_user), s: Session = Depends(db)):
        check_local(s, user, local_id)
        return canvis.llista_sollicituds(s, local_id, None if need_gerencia(user) else user, estat)

    class ResolIn(BaseModel):
        nota: str | None = Field(default=None, max_length=300)

    def _local_de(s, rid):
        from ..horaris_models import ShiftRequest
        from fastapi import HTTPException
        r = s.get(ShiftRequest, rid)
        if not r:
            raise HTTPException(404, "Sol·licitud inexistent")
        return r.local_id

    @app.post("/horaris/sollicituds/{rid}/aprova")
    def aprova(rid: int, body: ResolIn, user: User = Depends(current_user), s: Session = Depends(db)):
        need_manager(user)
        check_local(s, user, _local_de(s, rid))
        return {"id": run(canvis.aprova, s, user, rid, body.nota).id}

    @app.post("/horaris/sollicituds/{rid}/rebutja")
    def rebutja(rid: int, body: ResolIn, user: User = Depends(current_user), s: Session = Depends(db)):
        need_manager(user)
        check_local(s, user, _local_de(s, rid))
        return {"id": run(canvis.rebutja, s, user, rid, body.nota).id}

    @app.post("/horaris/sollicituds/{rid}/cancela")
    def cancela(rid: int, user: User = Depends(current_user), s: Session = Depends(db)):
        check_local(s, user, _local_de(s, rid))
        return {"id": run(canvis.cancela, s, user, rid).id}

    @app.get("/locals/{local_id}/horaris/registre")
    def registre(local_id: int, des: date, fins: date, user: User = Depends(current_user), s: Session = Depends(db)):
        mgr(local_id, user, s)
        rang(des, fins)
        return horaris.registre(s, local_id, des, fins)

    # ---- avançaments: només accés complet ----
    class AvancIn(BaseModel):
        data: date
        user_id: int
        import_cent: int = Field(gt=0, le=100_000_000)
        comentari: str | None = Field(default=None, max_length=300)
        de_caixa: bool = False
        metode: str = Field(default="efectiu", max_length=10)

    @app.post("/locals/{local_id}/horaris/avancos", status_code=201)
    def avanc_alta(local_id: int, body: AvancIn, user: User = Depends(current_user), s: Session = Depends(db)):
        mgr(local_id, user, s)
        a = run(canvis.registra_avanc, s, user, local_id, body.data, body.user_id, body.import_cent, body.comentari, body.de_caixa, body.metode)
        return {"id": a.id, "expense_id": a.expense_id}

    @app.get("/locals/{local_id}/horaris/avancos")
    def avancos(local_id: int, des: date, fins: date, user: User = Depends(current_user), s: Session = Depends(db)):
        mgr(local_id, user, s)
        rang(des, fins)
        return canvis.llista_avancos(s, local_id, des, fins)

    class AnulaIn(BaseModel):
        nota: str = Field(min_length=3, max_length=200)

    @app.post("/horaris/avancos/{aid}/anulacio", status_code=201)
    def avanc_anula(aid: int, body: AnulaIn, user: User = Depends(current_user), s: Session = Depends(db)):
        from fastapi import HTTPException
        from ..horaris_models import Advance
        a = s.get(Advance, aid)
        if not a:
            raise HTTPException(404, "Avançament inexistent")
        mgr(a.local_id, user, s)
        return {"id": run(canvis.anula_avanc, s, user, aid, body.nota).id}

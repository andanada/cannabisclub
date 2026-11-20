"""Rutes: despeses, categories, tipus de despesa, tipus de compte i comptes comptables (només responsables)."""
from datetime import date

from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .. import gastos, idempotencia
from ..models import Expense, User


def register(app, db, current_user, check_local, need_manager, run):
    class CatalogIn(BaseModel):
        nom: str = Field(min_length=1, max_length=60)
        descripcio: str | None = Field(default=None, max_length=200)

    class CatalogUpdateIn(BaseModel):
        nom: str | None = Field(default=None, max_length=60)
        descripcio: str | None = Field(default=None, max_length=200)
        actiu: bool | None = None

    for quin in gastos.CATALEGS:
        def _fes(quin):
            @app.get(f"/locals/{{local_id}}/gastos/{quin}", name=f"llista_{quin}")
            def llista(local_id: int, user: User = Depends(current_user), s: Session = Depends(db)):
                need_manager(user)
                check_local(s, user, local_id)
                return gastos.llista_catalog(s, local_id, quin)

            @app.post(f"/locals/{{local_id}}/gastos/{quin}", status_code=201, name=f"alta_{quin}")
            def alta(local_id: int, body: CatalogIn, user: User = Depends(current_user), s: Session = Depends(db)):
                need_manager(user)
                check_local(s, user, local_id)
                return {"id": run(gastos.crea_catalog, s, user, local_id, quin, body.nom, body.descripcio)}

            @app.put(f"/gastos/{quin}/{{rid}}", name=f"edita_{quin}")
            def edita(rid: int, body: CatalogUpdateIn, user: User = Depends(current_user), s: Session = Depends(db)):
                need_manager(user)
                M = gastos.CATALEGS[quin]
                r = s.get(M, rid)
                if not r:
                    raise HTTPException(404, "No existeix")
                check_local(s, user, r.local_id)
                run(gastos.edita_catalog, s, user, quin, rid, body.nom, body.descripcio, body.actiu)
                return {"ok": True}
        _fes(quin)

    class TipusCompteIn(BaseModel):
        nom: str = Field(min_length=1, max_length=60)
        descripcio: str | None = Field(default=None, max_length=200)
        operacio: str = Field(pattern="^(suma|resta)$")
        es_despesa: bool = False

    @app.get("/locals/{local_id}/gastos/tipus-compte")
    def llista_tipus_compte(local_id: int, user: User = Depends(current_user), s: Session = Depends(db)):
        need_manager(user)
        check_local(s, user, local_id)
        return gastos.llista_tipus_compte(s, local_id)

    @app.post("/locals/{local_id}/gastos/tipus-compte", status_code=201)
    def alta_tipus_compte(local_id: int, body: TipusCompteIn, user: User = Depends(current_user), s: Session = Depends(db)):
        need_manager(user)
        check_local(s, user, local_id)
        return {"id": run(gastos.crea_tipus_compte, s, user, local_id, body.nom, body.descripcio, body.operacio, body.es_despesa)}

    class CompteIn(BaseModel):
        numero: str = Field(min_length=1, max_length=20)
        descripcio: str | None = Field(default=None, max_length=200)
        tipus_id: int

    @app.get("/locals/{local_id}/gastos/comptes")
    def llista_comptes(local_id: int, user: User = Depends(current_user), s: Session = Depends(db)):
        need_manager(user)
        check_local(s, user, local_id)
        return gastos.llista_comptes(s, local_id)

    @app.post("/locals/{local_id}/gastos/comptes", status_code=201)
    def alta_compte(local_id: int, body: CompteIn, user: User = Depends(current_user), s: Session = Depends(db)):
        need_manager(user)
        check_local(s, user, local_id)
        return {"id": run(gastos.crea_compte, s, user, local_id, body.numero, body.descripcio, body.tipus_id)}

    class GastoIn(BaseModel):
        local_id: int
        data: date
        type_id: int
        category_id: int
        account_id: int | None = None
        import_cent: int = Field(gt=0, le=100_000_000)
        metode: str | None = Field(default=None, max_length=10)  # amb mètode surt de la caixa oberta
        comentaris: str | None = Field(default=None, max_length=300)
        client_ref: str | None = Field(default=None, pattern=idempotencia.REF_PATTERN)

    @app.post("/gastos", status_code=201)
    def alta_gasto(body: GastoIn, user: User = Depends(current_user), s: Session = Depends(db)):
        need_manager(user)
        check_local(s, user, body.local_id)

        def fes():
            e = run(gastos.registra, s, user, body.local_id, body.data, body.type_id, body.category_id, body.account_id,
                    body.import_cent, body.metode, body.comentaris)
            return {"id": e.id, "caixa": e.cash_entry_id is not None}
        return idempotencia.executa(s, user, "gastos", body.client_ref, body.model_dump(mode="json"), fes)

    class AnulacioIn(BaseModel):
        nota: str = Field(min_length=3, max_length=200)

    @app.post("/gastos/{expense_id}/anulacio", status_code=201)
    def anula_gasto(expense_id: int, body: AnulacioIn, user: User = Depends(current_user), s: Session = Depends(db)):
        need_manager(user)
        e = s.get(Expense, expense_id)
        if not e:
            raise HTTPException(404, "Despesa inexistent")
        check_local(s, user, e.local_id)
        return {"id": run(gastos.anula, s, user, expense_id, body.nota).id}

    @app.get("/locals/{local_id}/gastos/pendents")
    def pendents_gastos(local_id: int, user: User = Depends(current_user), s: Session = Depends(db)):
        """Despeses automàtiques d'entrades d'estoc pendents de revisió (doble control de la gerència)."""
        need_manager(user)
        check_local(s, user, local_id)
        return gastos.pendents(s, local_id)

    class RevisioIn(BaseModel):
        accio: str = Field(pattern="^(confirma|corregeix|comenta)$")
        comentari: str | None = Field(default=None, max_length=300)
        import_cent: int | None = Field(default=None, gt=0, le=100_000_000)

    @app.post("/gastos/{expense_id}/revisio", status_code=201)
    def revisa_gasto(expense_id: int, body: RevisioIn, user: User = Depends(current_user), s: Session = Depends(db)):
        need_manager(user)
        e = s.get(Expense, expense_id)
        if not e:
            raise HTTPException(404, "Despesa inexistent")
        check_local(s, user, e.local_id)
        return {"id": run(gastos.revisa, s, user, expense_id, body.accio, body.comentari, body.import_cent)}

    @app.get("/gastos/{expense_id}/revisions")
    def revisions_gasto(expense_id: int, user: User = Depends(current_user), s: Session = Depends(db)):
        need_manager(user)
        e = s.get(Expense, expense_id)
        if not e:
            raise HTTPException(404, "Despesa inexistent")
        check_local(s, user, e.local_id)
        return gastos.llista_revisions(s, expense_id)

    @app.get("/locals/{local_id}/gastos")
    def llista_gastos(local_id: int, des: date, fins: date, user: User = Depends(current_user), s: Session = Depends(db)):
        need_manager(user)
        check_local(s, user, local_id)
        if fins < des:
            raise HTTPException(422, "Rang de dates invàlid")
        return gastos.llista(s, local_id, des, fins)

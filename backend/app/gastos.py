"""Despeses i comptabilitat bàsica: categories i tipus de despesa, tipus de compte (suma/resta) i comptes comptables.

Una despesa pot sortir de la caixa (crea l'apunt de caixa en la mateixa transacció: o es fa tot o res) o no. Les despeses només
s'afegeixen; es corregeixen amb una anul·lació. L'import d'un compte és la suma de les seves despeses vigents amb el signe
que marca l'operació del seu tipus de compte (suma o resta)."""
from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from . import cash, service
from .models import Account, AccountType, Expense, ExpenseCategory, ExpenseReview, ExpenseType, User
from .stock import TZ

OPERACIONS = {"suma", "resta"}
CATEGORIA_COMPRES = "Proveïdors"   # categoria i tipus de les despeses que neixen d'una entrada d'estoc
TIPUS_COMPRES = "Compres"
CATEGORIA_CAIXA = "Caixa"          # tipus de les despeses apuntades a la pestanya Despesa de la Caixa
ACCIONS_REVISIO = {"confirma", "corregeix", "comenta"}
CATALEGS = {"categories": ExpenseCategory, "tipus": ExpenseType}


# ---------- catàlegs ----------

def llista_catalog(db: Session, local_id: int, quin: str) -> list[dict]:
    M = CATALEGS[quin]
    return [{"id": r.id, "nom": r.nom, "descripcio": r.descripcio or "", "actiu": r.actiu}
            for r in db.scalars(select(M).where(M.local_id == local_id).order_by(M.nom))]


def crea_catalog(db: Session, actor: User, local_id: int, quin: str, nom: str, descripcio: str | None, commit: bool = True) -> int:
    M = CATALEGS[quin]
    nom = (nom or "").strip()
    if not nom:
        raise ValueError("El nom no pot estar buit")
    if db.scalar(select(M.id).where(M.local_id == local_id, M.nom == nom)):
        raise ValueError("Ja existeix amb aquest nom")
    r = M(local_id=local_id, nom=nom, descripcio=(descripcio or "").strip() or None)
    db.add(r)
    db.flush()
    service.audit_append(db, {"accio": "alta_" + quin, "id": r.id, "local": local_id, "per": actor.id})
    if commit:
        db.commit()
    return r.id


def edita_catalog(db: Session, actor: User, quin: str, rid: int, nom: str | None, descripcio: str | None, actiu: bool | None,
                  commit: bool = True) -> None:
    M = CATALEGS[quin]
    r = db.get(M, rid)
    if not r:
        raise ValueError("No existeix")
    if nom is not None and nom.strip() != r.nom:
        if not nom.strip():
            raise ValueError("El nom no pot estar buit")
        if db.scalar(select(M.id).where(M.local_id == r.local_id, M.nom == nom.strip(), M.id != r.id)):
            raise ValueError("Ja existeix amb aquest nom")
        r.nom = nom.strip()
    if descripcio is not None:
        r.descripcio = descripcio.strip() or None
    if actiu is not None:
        r.actiu = actiu
    service.audit_append(db, {"accio": "edita_" + quin, "id": r.id, "per": actor.id})
    if commit:
        db.commit()


# ---------- tipus de compte i comptes ----------

def llista_tipus_compte(db: Session, local_id: int) -> list[dict]:
    return [{"id": t.id, "nom": t.nom, "descripcio": t.descripcio or "", "operacio": t.operacio, "es_despesa": t.es_despesa}
            for t in db.scalars(select(AccountType).where(AccountType.local_id == local_id).order_by(AccountType.nom))]


def crea_tipus_compte(db: Session, actor: User, local_id: int, nom: str, descripcio: str | None, operacio: str, es_despesa: bool) -> int:
    nom = (nom or "").strip()
    if not nom:
        raise ValueError("El nom no pot estar buit")
    if operacio not in OPERACIONS:
        raise ValueError("L'operació ha de ser suma o resta")
    if db.scalar(select(AccountType.id).where(AccountType.local_id == local_id, AccountType.nom == nom)):
        raise ValueError("Ja existeix un tipus de compte amb aquest nom")
    t = AccountType(local_id=local_id, nom=nom, descripcio=(descripcio or "").strip() or None, operacio=operacio, es_despesa=es_despesa)
    db.add(t)
    db.flush()
    service.audit_append(db, {"accio": "alta_tipus_compte", "id": t.id, "local": local_id, "per": actor.id})
    db.commit()
    return t.id


def _signe(tipus: AccountType) -> int:
    return 1 if tipus.operacio == "suma" else -1


def llista_comptes(db: Session, local_id: int) -> list[dict]:
    tipus = {t.id: t for t in db.scalars(select(AccountType).where(AccountType.local_id == local_id))}
    corregides = set(db.scalars(select(Expense.corregeix_id).where(Expense.local_id == local_id, Expense.corregeix_id.is_not(None))))
    saldos: dict[int, int] = {}
    for e in db.scalars(select(Expense).where(Expense.local_id == local_id, Expense.account_id.is_not(None), Expense.corregeix_id.is_(None))):
        if e.id not in corregides:
            saldos[e.account_id] = saldos.get(e.account_id, 0) + _signe(tipus[db.get(Account, e.account_id).tipus_id]) * e.import_cent
    return [{"id": c.id, "numero": c.numero, "descripcio": c.descripcio or "", "tipus_id": c.tipus_id,
             "tipus": tipus[c.tipus_id].nom if c.tipus_id in tipus else "", "import_cent": saldos.get(c.id, 0)}
            for c in db.scalars(select(Account).where(Account.local_id == local_id).order_by(Account.numero))]


def crea_compte(db: Session, actor: User, local_id: int, numero: str, descripcio: str | None, tipus_id: int) -> int:
    numero = (numero or "").strip()
    if not numero:
        raise ValueError("El número de compte no pot estar buit")
    t = db.get(AccountType, tipus_id)
    if not t or t.local_id != local_id:
        raise ValueError("Tipus de compte inexistent")
    if db.scalar(select(Account.id).where(Account.local_id == local_id, Account.numero == numero)):
        raise ValueError("Ja existeix un compte amb aquest número")
    c = Account(local_id=local_id, numero=numero, descripcio=(descripcio or "").strip() or None, tipus_id=tipus_id)
    db.add(c)
    db.flush()
    service.audit_append(db, {"accio": "alta_compte", "id": c.id, "local": local_id, "per": actor.id})
    db.commit()
    return c.id


# ---------- despeses ----------

def registra(db: Session, actor: User, local_id: int, data: date, type_id: int, category_id: int, account_id: int | None,
             cent: int, metode: str | None, comentaris: str | None, origen: str | None = None, movement_id: int | None = None,
             commit: bool = True) -> Expense:
    """Apunta una despesa. Amb `metode` surt de la caixa oberta (apunt de caixa en la mateixa transacció).
    `origen`/`movement_id` són opcionals (despeses automàtiques); amb `commit=False` la crida no tanca la transacció."""
    if cent <= 0:
        raise ValueError("L'import de la despesa ha de ser positiu")
    tp, cat = db.get(ExpenseType, type_id), db.get(ExpenseCategory, category_id)
    if not tp or tp.local_id != local_id or not tp.actiu:
        raise ValueError("Tipus de despesa inexistent o inactiu")
    if not cat or cat.local_id != local_id or not cat.actiu:
        raise ValueError("Categoria de despesa inexistent o inactiva")
    if account_id is not None:
        c = db.get(Account, account_id)
        if not c or c.local_id != local_id:
            raise ValueError("Compte inexistent")
    if data > datetime.now(TZ).date():
        raise ValueError("La data de la despesa no pot ser futura")
    entrada = None
    if metode is not None:
        entrada = cash.expense(db, actor, local_id, cent, metode, cat.nom, (comentaris or tp.nom)[:300], commit=False)
    e = Expense(local_id=local_id, data=data, user_id=actor.id, type_id=type_id, category_id=category_id, account_id=account_id,
                import_cent=cent, cash_entry_id=entrada.id if entrada else None, comentaris=(comentaris or "").strip() or None,
                origen=origen, movement_id=movement_id)
    db.add(e)
    db.flush()
    service.audit_append(db, {"accio": "gasto", "gasto": e.id, "cent": cent, "caixa": entrada is not None, "per": actor.id})
    if commit:
        db.commit()
    return e


def anula(db: Session, actor: User, expense_id: int, nota: str, commit: bool = True) -> Expense:
    orig = db.get(Expense, expense_id)
    if not orig or orig.corregeix_id is not None:
        raise ValueError("Despesa inexistent")
    if db.scalar(select(Expense.id).where(Expense.corregeix_id == orig.id)):
        raise ValueError("Aquesta despesa ja està anul·lada")
    if orig.cash_entry_id is not None:
        cash.correct_entry(db, actor, orig.cash_entry_id, "Anul·lació de despesa: " + nota, commit=False, des_de_gastos=True)
    a = Expense(local_id=orig.local_id, data=orig.data, user_id=actor.id, type_id=orig.type_id, category_id=orig.category_id,
                account_id=orig.account_id, import_cent=orig.import_cent, corregeix_id=orig.id, comentaris=nota)
    db.add(a)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise ValueError("Aquesta despesa ja està anul·lada")
    service.audit_append(db, {"accio": "anulacio_gasto", "gasto": a.id, "anula": orig.id, "per": actor.id})
    if commit:
        db.commit()
    return a


def _estats_revisio(db: Session, ids: list[int]) -> dict[int, str]:
    """confirmada | corregida per a les despeses ja revisades (una despesa d'estoc sense cap fila és pendent)."""
    if not ids:
        return {}
    out: dict[int, str] = {}
    q = select(ExpenseReview.expense_id, ExpenseReview.accio).where(ExpenseReview.expense_id.in_(ids), ExpenseReview.accio != "comenta").order_by(ExpenseReview.id)
    for eid, accio in db.execute(q):
        out[eid] = "confirmada" if accio == "confirma" else "corregida"
    return out


def llista(db: Session, local_id: int, des: date, fins: date, limit: int = 500) -> list[dict]:
    anulades = set(db.scalars(select(Expense.corregeix_id).where(Expense.local_id == local_id, Expense.corregeix_id.is_not(None))))
    noms = {i: n for i, n in db.execute(select(User.id, User.username))}
    tp = {t.id: t.nom for t in db.scalars(select(ExpenseType).where(ExpenseType.local_id == local_id))}
    ct = {c.id: c.nom for c in db.scalars(select(ExpenseCategory).where(ExpenseCategory.local_id == local_id))}
    cm = {c.id: c.numero for c in db.scalars(select(Account).where(Account.local_id == local_id))}
    q = (select(Expense).where(Expense.local_id == local_id, Expense.data >= des, Expense.data <= fins)
         .order_by(Expense.data.desc(), Expense.id.desc()).limit(limit))
    rows = list(db.scalars(q))
    estats = _estats_revisio(db, [e.id for e in rows if e.origen == "estoc"])
    return [{"id": e.id, "data": e.data.isoformat(), "empleat": noms.get(e.user_id), "tipus": tp.get(e.type_id, ""),
             "categoria": ct.get(e.category_id, ""), "compte": cm.get(e.account_id, ""), "import_cent": e.import_cent,
             "caixa": e.cash_entry_id is not None, "comentaris": e.comentaris or "", "anulacio": e.corregeix_id is not None,
             "anulada": e.id in anulades, "origen": e.origen or "manual", "movement_id": e.movement_id,
             "estat": "" if e.origen != "estoc" or e.corregeix_id is not None or e.id in anulades else estats.get(e.id, "pendent")} for e in rows]


# ---------- despeses automàtiques (estoc i caixa) i revisió ----------

def _cataleg_auto(db: Session, actor: User, local_id: int, quin: str, nom: str) -> int:
    """Troba (o crea, sense tancar la transacció) la categoria o el tipus de despesa amb aquest nom."""
    M = CATALEGS[quin]
    r = db.scalar(select(M).where(M.local_id == local_id, M.nom == nom))
    if r is None:
        try:
            with db.begin_nested():  # savepoint: si un altre procés la crea alhora, no es perd la transacció
                r = M(local_id=local_id, nom=nom)
                db.add(r)
                db.flush()
        except IntegrityError:
            r = db.scalar(select(M).where(M.local_id == local_id, M.nom == nom))
            if r is None:
                raise ValueError("No s'ha pogut crear la categoria o el tipus de despesa")
        else:
            service.audit_append(db, {"accio": "alta_" + quin, "id": r.id, "local": local_id, "auto": True, "per": actor.id})
    # Una categoria o un tipus desactivat NO es reactiva en silenci: la despesa automàtica l'usa igualment (es respecta la decisió de la gerència).
    return r.id


def registra_automatica(db: Session, actor: User, local_id: int, cent: int, comentaris: str | None, origen: str,
                        categoria: str = CATEGORIA_COMPRES, tipus: str = TIPUS_COMPRES, movement_id: int | None = None,
                        cash_entry_id: int | None = None, data: date | None = None) -> Expense:
    """Despesa creada pel sistema (no per un formulari): crea la categoria i el tipus si no existeixen. No tanca la transacció."""
    if cent <= 0:
        raise ValueError("L'import de la despesa ha de ser positiu")
    cat_id = _cataleg_auto(db, actor, local_id, "categories", categoria)
    tip_id = _cataleg_auto(db, actor, local_id, "tipus", tipus)
    e = Expense(local_id=local_id, data=data or datetime.now(TZ).date(), user_id=actor.id, type_id=tip_id, category_id=cat_id,
                import_cent=cent, cash_entry_id=cash_entry_id, comentaris=(comentaris or "").strip()[:300] or None, origen=origen, movement_id=movement_id)
    db.add(e)
    db.flush()
    service.audit_append(db, {"accio": "gasto", "gasto": e.id, "cent": cent, "caixa": cash_entry_id is not None, "origen": origen,
                              **({"moviment": movement_id} if movement_id else {}), "per": actor.id})
    return e


def registra_entrada_estoc(db: Session, actor: User, movement, producte_nom: str) -> Expense | None:
    """Cada entrada d'estoc amb preu de compra crea la seva despesa (Proveïdors · Compres), pendent de revisió. No fa commit."""
    if not movement.cost_cent or movement.cost_cent <= 0:
        return None
    from . import unitats
    return registra_automatica(db, actor, movement.local_id, movement.cost_cent,
                               f"Entrada d'estoc: {producte_nom} ({unitats.mg_to_g(movement.delta_mg)})", "estoc", movement_id=movement.id)


def anula_per_moviment(db: Session, actor: User, movement_id: int, nota: str) -> None:
    """Si es corregeix una entrada d'estoc, la seva despesa automàtica s'anul·la també (mateixa transacció, sense commit)."""
    files = db.scalars(select(Expense).where(Expense.movement_id == movement_id, Expense.origen == "estoc",
                                             Expense.corregeix_id.is_(None)).order_by(Expense.id)).all()
    for e in files:  # TOTES les vigents (entrada -> revisió que corregeix -> correcció de l'entrada: l'original ja és anul·lada)
        if not db.scalar(select(Expense.id).where(Expense.corregeix_id == e.id)):
            anula(db, actor, e.id, nota, commit=False)


def registra_de_caixa(db: Session, actor: User, local_id: int, cent: int, metode: str, categoria: str, concepte: str) -> tuple:
    """Despesa de la pestanya «Despesa» de la Caixa: apunt de caixa + despesa vinculada a Gastos, en una sola transacció."""
    cat = (categoria or "").strip()[:60] or CATEGORIA_CAIXA
    text = (concepte or "").strip()
    entrada = cash.expense(db, actor, local_id, cent, metode, cat, text[:300] or cat, commit=False)
    e = registra_automatica(db, actor, local_id, cent, text or cat, "caixa", categoria=cat, tipus=CATEGORIA_CAIXA, cash_entry_id=entrada.id)
    db.commit()
    return entrada, e


def _pendents_exp(db: Session, local_id: int) -> list[Expense]:
    anulades = set(db.scalars(select(Expense.corregeix_id).where(Expense.local_id == local_id, Expense.corregeix_id.is_not(None))))
    revisades = set(db.scalars(select(ExpenseReview.expense_id).where(ExpenseReview.accio != "comenta")))
    q = select(Expense).where(Expense.local_id == local_id, Expense.origen == "estoc", Expense.corregeix_id.is_(None)).order_by(Expense.id.desc())
    return [e for e in db.scalars(q) if e.id not in anulades and e.id not in revisades]


def pendents(db: Session, local_id: int) -> list[dict]:
    """Despeses automàtiques d'estoc encara per revisar, amb el producte i la quantitat de l'entrada."""
    from . import unitats
    from .models import Product, StockMovement
    noms = {i: n for i, n in db.execute(select(User.id, User.username))}
    out = []
    for e in _pendents_exp(db, local_id):
        m = db.get(StockMovement, e.movement_id) if e.movement_id else None
        p = db.get(Product, m.product_id) if m else None
        out.append({"id": e.id, "data": e.data.isoformat(), "empleat": noms.get(e.user_id), "import_cent": e.import_cent,
                    "producte": p.nom if p else "", "quantitat": unitats.mg_to_g(m.delta_mg) if m else None,
                    "unitat": p.unitat if p else "g", "comentaris": e.comentaris or "", "revisions": llista_revisions(db, e.id)})
    return out


def llista_revisions(db: Session, expense_id: int) -> list[dict]:
    noms = {i: n for i, n in db.execute(select(User.id, User.username))}
    return [{"id": r.id, "ts": r.ts.isoformat(), "usuari": noms.get(r.user_id), "accio": r.accio, "comentari": r.comentari or "",
             "nou_expense_id": r.nou_expense_id}
            for r in db.scalars(select(ExpenseReview).where(ExpenseReview.expense_id == expense_id).order_by(ExpenseReview.id))]


def revisa(db: Session, actor: User, expense_id: int, accio: str, comentari: str | None = None, import_cent: int | None = None) -> int:
    """Doble control: la gerència confirma, corregeix (nou import; l'original s'anul·la) o només comenta una despesa automàtica."""
    if accio not in ACCIONS_REVISIO:
        raise ValueError("Acció de revisió no vàlida")
    e = db.get(Expense, expense_id)
    if not e or e.corregeix_id is not None:
        raise ValueError("Despesa inexistent")
    comentari = (comentari or "").strip() or None
    if accio == "comenta":
        if not comentari:
            raise ValueError("Escriu el comentari")
    else:
        if e.origen != "estoc":
            raise ValueError("Aquesta despesa no és automàtica: no necessita revisió")
        if e.id not in {p.id for p in _pendents_exp(db, e.local_id)}:
            raise ValueError("Aquesta despesa ja està revisada o anul·lada")
    nou = None
    if accio == "corregeix":
        if not import_cent or import_cent <= 0:
            raise ValueError("Indica el nou import")
        if not comentari:
            raise ValueError("Explica el motiu de la correcció")
        anula(db, actor, e.id, "Correcció en la revisió: " + comentari, commit=False)
        nou = Expense(local_id=e.local_id, data=e.data, user_id=e.user_id, type_id=e.type_id, category_id=e.category_id, account_id=e.account_id,
                      import_cent=import_cent, comentaris=e.comentaris, origen="estoc", movement_id=e.movement_id)
        db.add(nou)
        db.flush()
        service.audit_append(db, {"accio": "gasto", "gasto": nou.id, "cent": import_cent, "caixa": False, "origen": "estoc", "per": actor.id})
    db.add(ExpenseReview(expense_id=e.id, user_id=actor.id, accio=accio, comentari=comentari, nou_expense_id=nou.id if nou else None))
    db.flush()
    service.audit_append(db, {"accio": "revisio_gasto", "gasto": e.id, "revisio": accio, **({"nou": nou.id} if nou else {}), "per": actor.id})
    if nou is not None:   # la despesa corregida ja és la bona: queda confirmada d'entrada
        db.add(ExpenseReview(expense_id=nou.id, user_id=actor.id, accio="confirma", comentari="Corregida per " + actor.username))
    db.commit()
    return nou.id if nou else e.id

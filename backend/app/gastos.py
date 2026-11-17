"""Despeses i comptabilitat bàsica: categories i tipus de despesa, tipus de compte (suma/resta) i comptes comptables.

Una despesa pot sortir de la caixa (crea l'apunt de caixa en la mateixa transacció: o es fa tot o res) o no. Les despeses només
s'afegeixen; es corregeixen amb una anul·lació. L'import d'un compte és la suma de les seves despeses vigents amb el signe
que marca l'operació del seu tipus de compte (suma o resta)."""
from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from . import cash, service
from .models import Account, AccountType, Expense, ExpenseCategory, ExpenseType, User
from .stock import TZ

OPERACIONS = {"suma", "resta"}
CATALEGS = {"categories": ExpenseCategory, "tipus": ExpenseType}


# ---------- catàlegs ----------

def llista_catalog(db: Session, local_id: int, quin: str) -> list[dict]:
    M = CATALEGS[quin]
    return [{"id": r.id, "nom": r.nom, "descripcio": r.descripcio or "", "actiu": r.actiu}
            for r in db.scalars(select(M).where(M.local_id == local_id).order_by(M.nom))]


def crea_catalog(db: Session, actor: User, local_id: int, quin: str, nom: str, descripcio: str | None) -> int:
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
    db.commit()
    return r.id


def edita_catalog(db: Session, actor: User, quin: str, rid: int, nom: str | None, descripcio: str | None, actiu: bool | None) -> None:
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
             cent: int, metode: str | None, comentaris: str | None) -> Expense:
    """Apunta una despesa. Amb `metode` surt de la caixa oberta (apunt de caixa en la mateixa transacció)."""
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
                import_cent=cent, cash_entry_id=entrada.id if entrada else None, comentaris=(comentaris or "").strip() or None)
    db.add(e)
    db.flush()
    service.audit_append(db, {"accio": "gasto", "gasto": e.id, "cent": cent, "caixa": entrada is not None, "per": actor.id})
    db.commit()
    return e


def anula(db: Session, actor: User, expense_id: int, nota: str) -> Expense:
    orig = db.get(Expense, expense_id)
    if not orig or orig.corregeix_id is not None:
        raise ValueError("Despesa inexistent")
    if db.scalar(select(Expense.id).where(Expense.corregeix_id == orig.id)):
        raise ValueError("Aquesta despesa ja està anul·lada")
    if orig.cash_entry_id is not None:
        cash.correct_entry(db, actor, orig.cash_entry_id, "Anul·lació de despesa: " + nota, commit=False)
    a = Expense(local_id=orig.local_id, data=orig.data, user_id=actor.id, type_id=orig.type_id, category_id=orig.category_id,
                account_id=orig.account_id, import_cent=orig.import_cent, corregeix_id=orig.id, comentaris=nota)
    db.add(a)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise ValueError("Aquesta despesa ja està anul·lada")
    service.audit_append(db, {"accio": "anulacio_gasto", "gasto": a.id, "anula": orig.id, "per": actor.id})
    db.commit()
    return a


def llista(db: Session, local_id: int, des: date, fins: date, limit: int = 500) -> list[dict]:
    anulades = set(db.scalars(select(Expense.corregeix_id).where(Expense.local_id == local_id, Expense.corregeix_id.is_not(None))))
    noms = {i: n for i, n in db.execute(select(User.id, User.username))}
    tp = {t.id: t.nom for t in db.scalars(select(ExpenseType).where(ExpenseType.local_id == local_id))}
    ct = {c.id: c.nom for c in db.scalars(select(ExpenseCategory).where(ExpenseCategory.local_id == local_id))}
    cm = {c.id: c.numero for c in db.scalars(select(Account).where(Account.local_id == local_id))}
    q = (select(Expense).where(Expense.local_id == local_id, Expense.data >= des, Expense.data <= fins)
         .order_by(Expense.data.desc(), Expense.id.desc()).limit(limit))
    return [{"id": e.id, "data": e.data.isoformat(), "empleat": noms.get(e.user_id), "tipus": tp.get(e.type_id, ""),
             "categoria": ct.get(e.category_id, ""), "compte": cm.get(e.account_id, ""), "import_cent": e.import_cent,
             "caixa": e.cash_entry_id is not None, "comentaris": e.comentaris or "", "anulacio": e.corregeix_id is not None,
             "anulada": e.id in anulades} for e in db.scalars(q)]

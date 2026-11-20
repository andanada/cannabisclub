from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import exists, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, aliased

from . import service
from .races import flush_or_error
from .csvutil import to_csv
from .models import CashEntry, CashRegister, CashSession, Product, StockMovement, User
from .stock import TZ

METODES = {"efectiu", "targeta", "bizum"}  # entra diner a la caixa
COBRAMENTS = METODES | {"monedero"}  # formes de pagar una dispensació
ELECTRONICS = {"targeta", "bizum"}  # van pel TPV: mai se sumen a l'efectiu del calaix


def comprova_metode_ingres(db: Session, local_id: int, metode: str) -> None:
    """Targeta i Bizum només es poden cobrar si el local els ha activat (ajust «targeta_activa»)."""
    if metode in ELECTRONICS:
        from . import ajustos
        if not ajustos.get(db, local_id)["targeta_activa"]:
            raise ValueError("Aquest local encara no accepta targeta ni Bizum: activa'ls a Configuració")


def comprova_metode_sortida(db: Session, local_id: int, metode: str) -> None:
    """Una despesa o un avançament que surt de caixa només pot ser en efectiu mentre el local no tingui la targeta activada."""
    if metode in ELECTRONICS:
        from . import ajustos
        if not ajustos.get(db, local_id)["targeta_activa"]:
            raise ValueError("Aquest local no té targeta ni Bizum activats: la despesa de caixa ha de ser en efectiu")


def open_session(db: Session, actor: User, local_id: int, opening_cent: int, register_id: int | None = None,
                 assigned_to: int | None = None) -> CashSession:
    """Obre una caixa. Sense `register_id` és la caixa implícita del local (una sola, com sempre); amb una caixa registradora, una
    sessió oberta per caixa. `assigned_to` és l'empleat que hi treballa (per defecte, qui l'obre); només en pot tenir una d'oberta."""
    if opening_cent < 0:
        raise ValueError("L'import d'obertura no pot ser negatiu")
    if register_id is not None:
        reg = db.get(CashRegister, register_id)
        if not reg or reg.local_id != local_id:
            raise ValueError("Caixa registradora inexistent")
        if not reg.actiu:
            raise ValueError("Aquesta caixa registradora està desactivada")
    if assigned_to is not None:
        from .models import UserLocal
        emp = db.get(User, assigned_to)
        if not emp or not emp.active or (emp.role != "admin" and not db.get(UserLocal, (assigned_to, local_id))):
            raise ValueError("L'empleat no existeix o no treballa en aquest local")
    ocupada = select(CashSession.id).where(CashSession.local_id == local_id, CashSession.closed_at.is_(None))
    ocupada = ocupada.where(CashSession.register_id.is_(None) if register_id is None else CashSession.register_id == register_id)
    if db.scalar(ocupada):
        raise ValueError("Aquesta caixa ja està oberta" if register_id is not None else "Ja hi ha una caixa oberta en aquest local")
    propietari = assigned_to if assigned_to is not None else actor.id
    # El propietari efectiu és l'assignat o, si no n'hi ha, qui l'ha obert: només una caixa oberta per propietari (si no, la segona
    # quedaria inabastable perquè resolve_session en tria una sola).
    if db.scalar(select(CashSession.id).where(CashSession.local_id == local_id, CashSession.closed_at.is_(None),
                                              func.coalesce(CashSession.assigned_to, CashSession.opened_by) == propietari)):
        raise ValueError("Aquest empleat ja té una caixa oberta")
    cs = CashSession(local_id=local_id, opened_by=actor.id, opening_cent=opening_cent, register_id=register_id,
                     caixa_clau=register_id or 0, assigned_to=assigned_to)
    db.add(cs)
    flush_or_error(db, "Ja hi ha una caixa oberta (o l'empleat ja en té una)")  # els índexs únics parcials atura l'obertura simultània
    service.audit_append(db, {"accio": "obrir_caixa", "sessio": cs.id, "local": local_id, "cent": opening_cent, "caixa": register_id,
                              "empleat": propietari, "per": actor.id})
    db.commit()
    return cs


def open_sessions(db: Session, local_id: int, lock: bool = False) -> list[CashSession]:
    q = select(CashSession).where(CashSession.local_id == local_id, CashSession.closed_at.is_(None)).order_by(CashSession.id)
    if lock:
        q = q.with_for_update().execution_options(populate_existing=True)
    return list(db.scalars(q))


def resolve_session(sessions: list[CashSession], actor: User | None) -> CashSession | None:
    """La caixa amb què treballa `actor`: la que té assignada (o ha obert, si no n'hi ha d'assignada); si no en té i n'hi ha
    una sola d'oberta al local, aquesta (així un local d'una sola caixa funciona com sempre). Amb diverses i cap de seva: error."""
    if not sessions:
        return None
    if actor is not None:
        meves = [c for c in sessions if (c.assigned_to if c.assigned_to is not None else c.opened_by) == actor.id]
        if len(meves) >= 1:
            return meves[0]
    if len(sessions) == 1:
        unica = sessions[0]
        if unica.assigned_to is None or actor is None or unica.assigned_to == actor.id:
            return unica  # local d'una sola caixa sense assignar: la fa servir qui hi treballa, com sempre
        raise ValueError("L'única caixa oberta està assignada a un altre empleat")
    raise ValueError("Hi ha diverses caixes obertes i cap és teva: demana a un responsable que te n'assigni una")


def current_session(db: Session, local_id: int, lock: bool = False, actor: User | None = None) -> CashSession | None:
    sessions = open_sessions(db, local_id, lock=False)
    cs = resolve_session(sessions, actor)
    if cs is not None and lock:  # es bloqueja NOMÉS la caixa triada
        cs = db.scalar(select(CashSession).where(CashSession.id == cs.id).with_for_update().execution_options(populate_existing=True))
    return cs


def _require_open(db: Session, local_id: int, actor: User | None = None) -> CashSession:
    """Sessió oberta de l'empleat, bloquejada fins al commit: tancar la caixa no pot creuar-se amb un cobrament o una despesa."""
    cs = current_session(db, local_id, lock=True, actor=actor)
    if not cs:
        raise ValueError("No hi ha cap caixa oberta en aquest local")
    return cs


def register_warehouse(db: Session, cs: CashSession | None) -> int | None:
    """Magatzem de la caixa registradora d'una sessió (None = principal)."""
    if cs is None or cs.register_id is None:
        return None
    reg = db.get(CashRegister, cs.register_id)
    return reg.warehouse_id if reg else None


def expected_cash(db: Session, cs: CashSession) -> int:
    return cs.opening_cent + db.scalar(select(func.coalesce(func.sum(CashEntry.import_cent), 0)).where(
        CashEntry.session_id == cs.id, CashEntry.metode == "efectiu"))


def unpaid_dispensations(db: Session, local_id: int, since: datetime | None = None, until: datetime | None = None,
                         limit: int = 500) -> list[dict]:
    """Dispensacions sense cobrar (ni cobrades i després corregides sense recobrar) i que no estan corregides, entre `since`
    (inclòs) i `until` (exclòs). Una sola consulta (abans, una per dispensació). Serveix d'avís en tancar la caixa i per
    mostrar els deutes de sessions anteriors."""
    correccio = aliased(StockMovement)
    cobrament, corregit = aliased(CashEntry), aliased(CashEntry)
    q = select(StockMovement).where(
        StockMovement.local_id == local_id, StockMovement.tipus == "dispensacio", StockMovement.import_cent > 0,
        ~exists().where(correccio.corregeix_id == StockMovement.id),
        # cobrament vigent = un cobrament que no té correcció
        ~exists().where(cobrament.movement_id == StockMovement.id, cobrament.tipus == "cobrament",
                        ~exists().where(corregit.corregeix_id == cobrament.id)))
    if since is not None:
        q = q.where(StockMovement.ts >= since)
    if until is not None:
        q = q.where(StockMovement.ts < until)
    return [{"moviment": m.id, "import_cent": m.import_cent, "soci_id": m.member_id, "producte_id": m.product_id}
            for m in db.scalars(q.order_by(StockMovement.id).limit(limit))]


def last_fons(db: Session, local_id: int, register_id: int | None = None) -> int | None:
    """Últim fons de caixa deixat en tancar (de la mateixa caixa): serveix d'import per defecte en tancar i en obrir."""
    return db.scalar(select(CashSession.fons_deixat_cent).where(
        CashSession.local_id == local_id, CashSession.caixa_clau == (register_id or 0), CashSession.closed_at.is_not(None),
        CashSession.fons_deixat_cent.is_not(None)).order_by(CashSession.id.desc()).limit(1))


def _valida_sortida(counted_cent: int, fons: int | None, billets: int | None, monedes: int | None) -> None:
    """Fons de caixa i desglossament del que SURT (comptat - fons) en billets i monedes: la suma ha de quadrar."""
    if fons is None and billets is None and monedes is None:
        return  # tancament sense desglossament (com abans)
    if fons is None or billets is None or monedes is None:
        raise ValueError("Cal indicar el fons de caixa, els billets i les monedes que surten")
    if min(fons, billets, monedes) < 0:
        raise ValueError("Els imports del fons, els billets i les monedes no poden ser negatius")
    if fons > counted_cent:
        raise ValueError("El fons de caixa no pot ser més gran que l'efectiu comptat")
    surt = counted_cent - fons
    if billets + monedes != surt:
        raise ValueError(f"Billets i monedes no quadren: surten {surt / 100:.2f} € de la caixa i has indicat {(billets + monedes) / 100:.2f} €")


def tpv_totals(db: Session, session_id: int) -> dict:
    """Totals de targeta i Bizum d'una sessió (netejats de correccions), per a la fulla del TPV. No compten per a l'efectiu."""
    out = {"targeta_cent": 0, "bizum_cent": 0, "targeta_n": 0, "bizum_n": 0}
    corr = aliased(CashEntry)
    q = select(CashEntry.metode, CashEntry.tipus, CashEntry.import_cent, exists().where(corr.corregeix_id == CashEntry.id)).where(
        CashEntry.session_id == session_id, CashEntry.metode.in_(sorted(ELECTRONICS)), CashEntry.categoria.is_(None))
    for metode, tipus, cent, es_corregit in db.execute(q):
        out[metode + "_cent"] += cent
        if tipus != "correccio" and not es_corregit:  # el recompte de cobraments descompta els anul·lats (la correcció no compta)
            out[metode + "_n"] += 1
    out["total_cent"] = out["targeta_cent"] + out["bizum_cent"]
    return out


def close_session(db: Session, actor: User, local_id: int, counted_cent: int, session_id: int | None = None,
                  fons_cent: int | None = None, billets_cent: int | None = None, monedes_cent: int | None = None) -> CashSession:
    """Tanca la caixa (la de l'actor, o la indicada amb `session_id`). El resultat porta `sense_cobrar` i `sense_cobrar_cent`.
    Amb `fons_cent` (el que es deixa a la caixa) cal repartir el que en surt (comptat - fons) en `billets_cent` i `monedes_cent`."""
    if session_id is not None:
        trobada = db.scalar(select(CashSession).where(CashSession.id == session_id, CashSession.local_id == local_id,
                                                       CashSession.closed_at.is_(None)).with_for_update().execution_options(populate_existing=True))
        if not trobada:
            raise ValueError("Aquesta caixa no existeix o ja està tancada")
        cs = trobada
    else:
        cs = _require_open(db, local_id, actor)
    if counted_cent < 0:
        raise ValueError("L'import comptat no pot ser negatiu")
    _valida_sortida(counted_cent, fons_cent, billets_cent, monedes_cent)
    cs.fons_deixat_cent, cs.sortida_billets_cent, cs.sortida_monedes_cent = fons_cent, billets_cent, monedes_cent
    cs.expected_cent = expected_cash(db, cs)
    cs.counted_cent = counted_cent
    cs.diff_cent = counted_cent - cs.expected_cent
    cs.closed_at = datetime.now(timezone.utc)
    cs.closed_by = actor.id
    pendents = unpaid_dispensations(db, local_id, cs.opened_at)
    service.audit_append(db, {"accio": "tancar_caixa", "sessio": cs.id, "esperat": cs.expected_cent,
                              "comptat": counted_cent, "diferencia": cs.diff_cent, "sense_cobrar": len(pendents), "per": actor.id,
                              "fons": fons_cent, "billets": billets_cent, "monedes": monedes_cent})
    db.commit()
    cs.sense_cobrar = pendents  # només per a la resposta (no és una columna)
    cs.sense_cobrar_cent = sum(p["import_cent"] for p in pendents)
    return cs


def _live_charge(db: Session, movement_id: int) -> CashEntry | None:
    """El cobrament vigent d'una dispensació: el més recent que no té correcció."""
    for e in db.scalars(select(CashEntry).where(CashEntry.movement_id == movement_id, CashEntry.tipus == "cobrament")
                        .order_by(CashEntry.id.desc())):
        if not db.scalar(select(CashEntry.id).where(CashEntry.corregeix_id == e.id)):
            return e
    return None


def charge_in_tx(db: Session, actor: User, mv: StockMovement, metode: str) -> CashEntry:
    """Cobra una dispensació SENSE fer commit (el cridador tanca la transacció)."""
    if metode not in COBRAMENTS:
        raise ValueError("Mètode de pagament no vàlid")
    if mv.tipus != "dispensacio":
        raise ValueError("Només es poden cobrar dispensacions")
    comprova_metode_ingres(db, mv.local_id, metode)
    from . import stock  # import local: stock importa cash
    stock._lock_member(db, mv.member_id)  # mateix ordre que stock.dispense/correct: soci -> producte -> sessió
    stock._lock_product_row(db, mv.product_id)
    cs = _require_open(db, mv.local_id, actor)
    if db.scalar(select(StockMovement.id).where(StockMovement.corregeix_id == mv.id)):
        raise ValueError("La dispensació està corregida")
    if _live_charge(db, mv.id):
        raise ValueError("Aquesta dispensació ja està cobrada")
    e = CashEntry(local_id=mv.local_id, session_id=cs.id, tipus="cobrament", metode=metode,
                  import_cent=mv.import_cent or 0, movement_id=mv.id, user_id=actor.id)
    db.add(e)
    db.flush()
    if metode == "monedero":
        from . import moneder
        moneder.pay(db, actor, mv.member_id, e)
    service.audit_append(db, {"accio": "cobrament", "apunt": e.id, "moviment": mv.id, "cent": e.import_cent, "metode": metode, "per": actor.id})
    return e


def charge(db: Session, actor: User, movement_id: int, metode: str) -> CashEntry:
    if metode not in COBRAMENTS:
        raise ValueError("Mètode de pagament no vàlid")
    mv = db.get(StockMovement, movement_id)
    if not mv or mv.tipus != "dispensacio":
        raise ValueError("Només es poden cobrar dispensacions")
    e = charge_in_tx(db, actor, mv, metode)
    db.commit()
    return e


def expense(db: Session, actor: User, local_id: int, cent: int, metode: str, categoria: str, concepte: str, commit: bool = True) -> CashEntry:
    if cent <= 0:
        raise ValueError("L'import de la despesa ha de ser positiu")
    if metode not in METODES:
        raise ValueError("Mètode de pagament no vàlid")
    comprova_metode_sortida(db, local_id, metode)
    cs = _require_open(db, local_id, actor)
    e = CashEntry(local_id=local_id, session_id=cs.id, tipus="despesa", metode=metode, import_cent=-cent,
                  categoria=categoria, concepte=concepte, user_id=actor.id)
    db.add(e)
    db.flush()
    service.audit_append(db, {"accio": "despesa", "apunt": e.id, "cent": cent, "categoria": categoria, "per": actor.id})
    if commit:
        db.commit()
    return e


def correct_entry(db: Session, actor: User, entry_id: int, concepte: str, commit: bool = True, des_de_gastos: bool = False) -> CashEntry:
    """Corregeix un apunt de caixa. Si és la sortida d'una despesa (Expense.cash_entry_id), l'anul·lació de la despesa es crea en la
    mateixa transacció (via gastos.anula): així Gastos i la caixa no es desquadren. `des_de_gastos` evita el bucle quan crida gastos."""
    orig = db.get(CashEntry, entry_id)
    if not orig:
        raise ValueError("Apunt inexistent")
    if orig.tipus == "correccio":
        raise ValueError("Una correcció no es pot corregir")
    if not des_de_gastos:
        from .models import Expense
        despesa = db.scalar(select(Expense).where(Expense.cash_entry_id == orig.id, Expense.corregeix_id.is_(None)))
        if despesa is not None and not db.scalar(select(Expense.id).where(Expense.corregeix_id == despesa.id)):
            from . import gastos
            gastos.anula(db, actor, despesa.id, concepte, commit=False)
            if commit:
                db.commit()
            return db.scalar(select(CashEntry).where(CashEntry.corregeix_id == orig.id))
    if db.scalar(select(CashEntry.id).where(CashEntry.corregeix_id == orig.id)):
        raise ValueError("Aquest apunt ja està corregit")
    from . import moneder, stock
    soci_moneder = moneder.member_of_entry(db, orig.id)
    if soci_moneder is not None:
        stock._lock_member(db, soci_moneder)  # ordre global: soci -> sessió de caixa -> auditoria
    cs = _require_open(db, orig.local_id, actor)  # sessió bloquejada
    if db.scalar(select(CashEntry.id).where(CashEntry.corregeix_id == orig.id)):
        raise ValueError("Aquest apunt ja està corregit")
    e = CashEntry(local_id=orig.local_id, session_id=cs.id, tipus="correccio", metode=orig.metode,
                  import_cent=-orig.import_cent, categoria=orig.categoria, concepte=concepte,
                  corregeix_id=orig.id, user_id=actor.id)
    db.add(e)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise ValueError("Aquest apunt ja està corregit")
    moneder.reverse_for_entry(db, actor, orig, e)
    service.audit_append(db, {"accio": "correccio_caixa", "apunt": e.id, "corregeix": orig.id, "per": actor.id})
    if commit:
        db.commit()
    return e


def _range(des: date, fins: date) -> tuple[datetime, datetime]:
    a = datetime.combine(des, time.min, tzinfo=TZ).astimezone(timezone.utc)
    b = datetime.combine(fins + timedelta(days=1), time.min, tzinfo=TZ).astimezone(timezone.utc)
    return a, b


def report(db: Session, local_id: int, des: date, fins: date, usuari: int | None = None) -> dict:
    a, b = _range(des, fins)
    q = select(CashEntry).where(CashEntry.local_id == local_id, CashEntry.ts >= a, CashEntry.ts < b)
    if usuari is not None:
        q = q.where(CashEntry.user_id == usuari)
    entries = db.scalars(q).all()
    per_dia = defaultdict(lambda: {"ingressos_cent": 0, "despeses_cent": 0, "efectiu_cent": 0, "targeta_cent": 0, "bizum_cent": 0})
    despeses = defaultdict(int)
    ingressos = despeses_total = 0
    per_metode = {"efectiu": 0, "targeta": 0, "bizum": 0}  # l'efectiu i el TPV van sempre separats
    for e in entries:
        dia = e.ts.replace(tzinfo=e.ts.tzinfo or timezone.utc).astimezone(TZ).date().isoformat()
        if e.metode == "monedero":  # gastar saldo no és un ingrés nou: ja es va comptar en recarregar el monedero
            continue
        if e.categoria is None:  # cobrament, o correcció d'un cobrament (import negatiu)
            per_dia[dia]["ingressos_cent"] += e.import_cent
            per_dia[dia][e.metode + "_cent"] += e.import_cent
            per_metode[e.metode] += e.import_cent
            ingressos += e.import_cent
        else:  # despesa, o correcció d'una despesa (import positiu, resta de la despesa)
            per_dia[dia]["despeses_cent"] += -e.import_cent
            despeses_total += -e.import_cent
            despeses[e.categoria] += -e.import_cent
    qm = select(func.coalesce(func.sum(-StockMovement.delta_mg), 0)).where(
        StockMovement.local_id == local_id, StockMovement.tipus.in_(["dispensacio", "correccio"]),
        StockMovement.member_id.is_not(None), StockMovement.ts >= a, StockMovement.ts < b)
    if usuari is not None:
        qm = qm.where(StockMovement.user_id == usuari)
    mg = db.scalar(qm)
    return {"des": des.isoformat(), "fins": fins.isoformat(), "ingressos_cent": ingressos,
            "ingressos_efectiu_cent": per_metode["efectiu"], "ingressos_targeta_cent": per_metode["targeta"],
            "ingressos_bizum_cent": per_metode["bizum"], "despeses_cent": despeses_total, "resultat_cent": ingressos - despeses_total,
            "despeses_per_categoria": dict(despeses), "dispensat_mg": mg,
            "per_dia": {k: per_dia[k] for k in sorted(per_dia)}}


def entries_list(db: Session, local_id: int, des: date, fins: date, limit: int = 100) -> list[dict]:
    """Apunts de caixa del rang, del més recent al més antic, amb qui els va fer i si han estat corregits."""
    a, b = _range(des, fins)
    corregits = set(db.scalars(select(CashEntry.corregeix_id).where(CashEntry.local_id == local_id, CashEntry.corregeix_id.is_not(None))))
    noms = {i: n for i, n in db.execute(select(User.id, User.username))}
    q = (select(CashEntry).where(CashEntry.local_id == local_id, CashEntry.ts >= a, CashEntry.ts < b)
         .order_by(CashEntry.id.desc()).limit(limit))
    return [{"id": e.id, "ts": e.ts.replace(tzinfo=e.ts.tzinfo or timezone.utc).isoformat(), "tipus": e.tipus, "metode": e.metode,
             "import_cent": e.import_cent, "categoria": e.categoria, "concepte": e.concepte, "usuari": noms.get(e.user_id),
             "corregeix_id": e.corregeix_id, "corregit": e.id in corregits} for e in db.scalars(q)]


def entries_csv(db: Session, local_id: int, des: date, fins: date) -> str:
    a, b = _range(des, fins)
    rows = [[e.id, e.ts.isoformat(), e.tipus, e.metode, e.import_cent, e.categoria or "", e.concepte or "",
             e.movement_id or "", e.corregeix_id or ""]
            for e in db.scalars(select(CashEntry).where(CashEntry.local_id == local_id, CashEntry.ts >= a, CashEntry.ts < b).order_by(CashEntry.id))]
    # to_csv neutralitza el text que un full de càlcul executaria com a fórmula (el concepte l'escriu l'usuari)
    return to_csv(["id", "data_hora_utc", "tipus", "metode", "import_cent", "categoria", "concepte", "moviment", "corregeix"], rows)


# ---------- caixes registradores i resum de sessions ----------

def registers_list(db: Session, local_id: int) -> dict:
    from .models import Warehouse
    obertes = {c.register_id: c for c in open_sessions(db, local_id)}
    noms = {i: n for i, n in db.execute(select(User.id, User.username))}
    mags = {w.id: w.nom for w in db.scalars(select(Warehouse).where(Warehouse.local_id == local_id))}
    out = [{"id": r.id, "nom": r.nom, "warehouse_id": r.warehouse_id, "magatzem": mags.get(r.warehouse_id), "actiu": r.actiu,
            "oberta": r.id in obertes, "sessio": obertes[r.id].id if r.id in obertes else None,
            "empleat": noms.get((obertes[r.id].assigned_to or obertes[r.id].opened_by)) if r.id in obertes else None}
           for r in db.scalars(select(CashRegister).where(CashRegister.local_id == local_id).order_by(CashRegister.nom))]
    implicita = obertes.get(None)
    return {"caixes": out, "implicita": {"oberta": implicita is not None, "sessio": implicita.id if implicita else None,
                                        "empleat": noms.get(implicita.assigned_to or implicita.opened_by) if implicita else None}}


def register_create(db: Session, actor: User, local_id: int, nom: str, warehouse_id: int | None) -> CashRegister:
    from .models import Warehouse
    nom = (nom or "").strip()
    if not nom:
        raise ValueError("El nom de la caixa no pot estar buit")
    if db.scalar(select(CashRegister.id).where(CashRegister.local_id == local_id, CashRegister.nom == nom)):
        raise ValueError("Ja existeix una caixa amb aquest nom")
    if warehouse_id is not None:
        w = db.get(Warehouse, warehouse_id)
        if not w or w.local_id != local_id:
            raise ValueError("Magatzem inexistent")
    r = CashRegister(local_id=local_id, nom=nom, warehouse_id=warehouse_id)
    db.add(r)
    db.flush()
    service.audit_append(db, {"accio": "alta_caixa_registradora", "caixa": r.id, "local": local_id, "magatzem": warehouse_id, "per": actor.id})
    db.commit()
    return r


def register_update(db: Session, actor: User, reg: CashRegister, nom: str | None, actiu: bool | None) -> None:
    if nom is not None and nom.strip() != reg.nom:
        if not nom.strip():
            raise ValueError("El nom de la caixa no pot estar buit")
        if db.scalar(select(CashRegister.id).where(CashRegister.local_id == reg.local_id, CashRegister.nom == nom.strip(), CashRegister.id != reg.id)):
            raise ValueError("Ja existeix una caixa amb aquest nom")
        reg.nom = nom.strip()
    if actiu is not None and actiu != reg.actiu:
        if not actiu and db.scalar(select(CashSession.id).where(CashSession.register_id == reg.id, CashSession.closed_at.is_(None))):
            raise ValueError("No es pot desactivar una caixa oberta: tanca-la primer")
        reg.actiu = actiu
    service.audit_append(db, {"accio": "edita_caixa_registradora", "caixa": reg.id, "per": actor.id})
    db.commit()


def sessions_summary(db: Session, local_id: int, des: date, fins: date) -> list[dict]:
    """Sessions de caixa (obertes o tancades) que s'han obert al rang, amb l'empleat, la caixa i els totals per mètode.
    Serveix de «resum d'empleats» (una targeta per torn) i de «moviments de caixa» (obertura i tancament amb import anterior i de control)."""
    a, b = _range(des, fins)
    sessions = list(db.scalars(select(CashSession).where(CashSession.local_id == local_id, CashSession.opened_at >= a, CashSession.opened_at < b)
                               .order_by(CashSession.id.desc())))
    ids = [c.id for c in sessions]
    totals: dict[int, dict] = defaultdict(lambda: defaultdict(int))
    if ids:
        for sid, metode, tipus, cat, cent in db.execute(select(CashEntry.session_id, CashEntry.metode, CashEntry.tipus, CashEntry.categoria, CashEntry.import_cent)
                                                        .where(CashEntry.session_id.in_(ids))):
            if cat is None:  # ingressos (cobraments, quotes, recàrregues i les seves correccions)
                totals[sid][metode] += cent
            else:
                totals[sid]["despeses"] += -cent
    noms = {i: n for i, n in db.execute(select(User.id, User.username))}
    regs = {r.id: r.nom for r in db.scalars(select(CashRegister).where(CashRegister.local_id == local_id))}
    out, anterior = [], {}
    for c in reversed(sessions):  # de més antiga a més nova per calcular l'import anterior de cada caixa
        t = totals[c.id]
        out.append({"id": c.id, "caixa": regs.get(c.register_id), "empleat": noms.get(c.assigned_to or c.opened_by), "obertura": c.opened_at.isoformat(),
                    "tancament": c.closed_at.isoformat() if c.closed_at else None, "obertura_cent": c.opening_cent,
                    "import_anterior_cent": anterior.get(c.register_id), "esperat_cent": c.expected_cent, "comptat_cent": c.counted_cent,
                    "diferencia_cent": c.diff_cent, "efectiu_cent": t.get("efectiu", 0), "targeta_cent": t.get("targeta", 0),
                    "bizum_cent": t.get("bizum", 0), "fons_deixat_cent": c.fons_deixat_cent, "sortida_billets_cent": c.sortida_billets_cent,
                    "sortida_monedes_cent": c.sortida_monedes_cent, "monedero_cent": t.get("monedero", 0), "despeses_cent": t.get("despeses", 0),
                    "total_cent": sum(t.get(k, 0) for k in ("efectiu", "targeta", "bizum"))})  # el monedero ja es va comptar en recarregar
        if c.counted_cent is not None:
            anterior[c.register_id] = c.counted_cent
    return out[::-1]

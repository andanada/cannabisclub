"""Traçabilitat per lot/partida. Una entrada pot dur un lot; una dispensació el tria (manual) o es reparteix per FIFO
(lot més antic amb existències). El lot d'un moviment viu a `movement_batches` (només d'afegir), amb els mg per lot: una
dispensació gran pot repartir-se entre diversos lots. Un producte sense lots funciona exactament com abans.

Límit conegut: els traspassos entre magatzems no porten lot, així que les existències per lot són orientatives si s'hi
fan traspassos; el balanç per producte continua sent el de `stock_movements`."""
import re
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import service
from .csvutil import to_csv
from .models import Batch, MovementBatch, Product, StockMovement, User

CODI_RE = re.compile(r"[A-Za-z0-9._/-]{1,40}")


def create(db: Session, actor: User, product: Product, codi: str, origen=None, proveidor=None, collita=None,
           data_entrada: date | None = None, analisi=None) -> Batch:
    codi = (codi or "").strip()
    if not CODI_RE.fullmatch(codi):
        raise ValueError("Codi de lot no vàlid (1 a 40 caràcters: lletres, xifres i . _ / -)")
    if db.scalar(select(Batch.id).where(Batch.product_id == product.id, Batch.codi == codi)):
        raise ValueError("Ja existeix un lot amb aquest codi per a aquest producte")
    b = Batch(local_id=product.local_id, product_id=product.id, codi=codi, origen=(origen or None), proveidor=(proveidor or None),
              collita=(collita or None), data_entrada=data_entrada or date.today(), analisi=(analisi or None), creat_per=actor.id)
    db.add(b)
    db.flush()
    service.audit_append(db, {"accio": "alta_lot", "lot": b.id, "producte": product.id, "codi": codi, "per": actor.id})
    db.commit()
    return b


def remaining_mg(db: Session, batch_id: int) -> int:
    return int(db.scalar(select(func.coalesce(func.sum(MovementBatch.mg), 0)).where(MovementBatch.batch_id == batch_id)))


def list_batches(db: Session, product_id: int) -> list[dict]:
    return [_view(db, b) for b in db.scalars(select(Batch).where(Batch.product_id == product_id).order_by(Batch.data_entrada, Batch.id))]


def list_dispensable(db: Session, product_id: int) -> list[dict]:
    """Lots que es poden triar en dispensar: actius i amb existències. Vista mínima (sense origen, proveïdor ni anàlisi),
    pensada per al dispensador, que no és encarregat."""
    vistes = ((b, remaining_mg(db, b.id)) for b in db.scalars(
        select(Batch).where(Batch.product_id == product_id, Batch.actiu.is_(True)).order_by(Batch.data_entrada, Batch.id)))
    return [{"id": b.id, "codi": b.codi, "data_entrada": b.data_entrada.isoformat(), "existencies_mg": mg} for b, mg in vistes if mg > 0]


def _view(db: Session, b: Batch) -> dict:
    return {"id": b.id, "product_id": b.product_id, "codi": b.codi, "origen": b.origen, "proveidor": b.proveidor, "collita": b.collita,
            "data_entrada": b.data_entrada.isoformat(), "analisi": b.analisi, "actiu": b.actiu, "existencies_mg": remaining_mg(db, b.id)}


# ---------- ganxos de stock.py ----------

def check_receive(db: Session, product: Product, batch_id: int | None) -> Batch | None:
    if batch_id is None:
        return None
    b = db.get(Batch, batch_id)
    if not b or b.product_id != product.id:
        raise ValueError("El lot no existeix o és d'un altre producte")
    if not b.actiu:
        raise ValueError("El lot està tancat")
    return b


def attach_entry(db: Session, movement: StockMovement, batch: Batch | None) -> None:
    if batch is not None:
        db.add(MovementBatch(movement_id=movement.id, batch_id=batch.id, mg=movement.delta_mg))


def plan_dispense(db: Session, product: Product, mg: int, batch_id: int | None) -> list[tuple[int, int]]:
    """Repartiment de la dispensació per lots: [(lot, mg)]. Manual: el lot ha de tenir existències suficients.
    Automàtic (FIFO): del lot més antic al més nou; el que no cobreixin els lots queda sense lot."""
    if batch_id is not None:
        b = check_receive(db, product, batch_id)
        if remaining_mg(db, b.id) < mg:
            raise ValueError("El lot triat no té prou existències")
        return [(b.id, mg)]
    pla, falta = [], mg
    for b in db.scalars(select(Batch).where(Batch.product_id == product.id, Batch.actiu.is_(True)).order_by(Batch.data_entrada, Batch.id)):
        if falta <= 0:
            break
        queda = remaining_mg(db, b.id)
        if queda > 0:
            agafa = min(queda, falta)
            pla.append((b.id, agafa))
            falta -= agafa
    return pla


def attach_dispense(db: Session, movement: StockMovement, pla: list[tuple[int, int]]) -> None:
    for bid, mg in pla:
        db.add(MovementBatch(movement_id=movement.id, batch_id=bid, mg=-mg))


def mirror_correction(db: Session, original: StockMovement, correction: StockMovement) -> None:
    """Una correcció retorna al(s) lot(s) el que l'original en va treure (o en treu el que hi va posar)."""
    for mb in db.scalars(select(MovementBatch).where(MovementBatch.movement_id == original.id)):
        db.add(MovementBatch(movement_id=correction.id, batch_id=mb.batch_id, mg=-mb.mg))


# ---------- informe de traçabilitat ----------

def trace(db: Session, batch: Batch) -> dict:
    """Entrades, sortides i destinataris (només id de soci, mai dades personals) d'un lot."""
    files = db.execute(select(MovementBatch, StockMovement).join(StockMovement, StockMovement.id == MovementBatch.movement_id)
                       .where(MovementBatch.batch_id == batch.id).order_by(StockMovement.id)).all()
    corregits = {m.corregeix_id for _, m in files if m.corregeix_id}
    moviments, entrat, sortit, socis = [], 0, 0, set()
    for mb, m in files:
        moviments.append({"moviment": m.id, "ts": m.ts.isoformat(), "tipus": m.tipus, "mg": mb.mg, "soci_id": m.member_id,
                          "corregeix_id": m.corregeix_id, "corregit": m.id in corregits})
        if m.tipus == "entrada":
            entrat += mb.mg
        elif m.tipus == "dispensacio" and m.id not in corregits:
            sortit += -mb.mg
            socis.add(m.member_id)
    return {"lot": _view(db, batch), "moviments": moviments, "entrat_mg": entrat, "dispensat_mg": sortit,
            "existencies_mg": remaining_mg(db, batch.id), "socis_afectats": sorted(s for s in socis if s is not None)}


def trace_csv(t: dict) -> str:
    return to_csv(["moviment", "data", "tipus", "mg", "soci_id", "corregeix_id", "corregit"],
                  [[m["moviment"], m["ts"], m["tipus"], m["mg"], m["soci_id"], m["corregeix_id"], m["corregit"]] for m in t["moviments"]])

"""Monedero del soci: saldo prepagat que es recarrega a la caixa i es gasta en dispensacions.

El saldo és la SUMA dels moviments (taula només d'afegir: mai es modifica un saldo). Una recàrrega entra a la caixa com a ingrés
(efectiu, targeta o Bizum); pagar amb el monedero no és un ingrés nou (ja es va comptar en recarregar) i per això els informes
de caixa no el sumen als ingressos. Corregir un pagament o una recàrrega en revoca el moviment del monedero."""
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import ajustos, cash, service
from .models import CashEntry, Member, User, WalletMovement

MAX_RECARREGA_CENT = 1_000_000


def actiu(db: Session, local_id: int) -> bool:
    """Cada soci té el seu compte: dispensar es paga del saldo (sense caixa al dispensari). Ja no es pot desactivar."""
    return True


def limit_negatiu_cent(db: Session, local_id: int) -> int:
    return int(ajustos.get(db, local_id)["moneder_limit_cent"] or 0)


def saldo(db: Session, member_id: int) -> int:
    return db.scalar(select(func.coalesce(func.sum(WalletMovement.import_cent), 0)).where(WalletMovement.member_id == member_id))


def _comprova_saldo(db: Session, local_id: int, member_id: int, canvi_cent: int, actor: User | None = None) -> None:
    """El saldo resultant no pot quedar per sota del límit negatiu: el de l'empleat si en té un de propi, si no el del local
    (0 = no es permet saldo negatiu)."""
    nou = saldo(db, member_id) + canvi_cent
    propi = actor.moneder_limit_cent if actor is not None else None
    if nou < -(propi if propi is not None else limit_negatiu_cent(db, local_id)):
        raise ValueError("Saldo del monedero insuficient")


def pay(db: Session, actor: User, member_id: int, entry: CashEntry) -> WalletMovement:
    """Descompta del monedero l'import d'un apunt de caixa de cobrament. SENSE commit; el soci ja ha d'estar bloquejat."""
    if not actiu(db, entry.local_id):
        raise ValueError("El monedero no està activat en aquest local")
    _comprova_saldo(db, entry.local_id, member_id, -entry.import_cent, actor)
    w = WalletMovement(local_id=entry.local_id, member_id=member_id, tipus="pagament", import_cent=-entry.import_cent,
                       cash_entry_id=entry.id, movement_id=entry.movement_id, user_id=actor.id)
    db.add(w)
    db.flush()
    service.audit_append(db, {"accio": "monedero_pagament", "soci": member_id, "cent": w.import_cent, "apunt": entry.id, "per": actor.id})
    return w


def recharge(db: Session, actor: User, member: Member, cent: int, metode: str) -> WalletMovement:
    if not actiu(db, member.local_id):
        raise ValueError("El monedero no està activat en aquest local")
    if member.estat == "baixa":
        raise ValueError("El soci està de baixa")
    if not 0 < cent <= MAX_RECARREGA_CENT:
        raise ValueError("L'import de la recàrrega ha d'estar entre 0,01 € i 10.000 €")
    if metode not in cash.METODES:
        raise ValueError("Mètode de pagament no vàlid")
    from . import stock
    stock._lock_member(db, member.id)  # ordre global: soci -> sessió de caixa -> auditoria
    cs = cash._require_open(db, member.local_id, actor)
    e = CashEntry(local_id=member.local_id, session_id=cs.id, tipus="recarrega", metode=metode, import_cent=cent,
                  concepte="Recàrrega del monedero", user_id=actor.id)
    db.add(e)
    db.flush()
    w = WalletMovement(local_id=member.local_id, member_id=member.id, tipus="recarrega", import_cent=cent,
                       cash_entry_id=e.id, user_id=actor.id)
    db.add(w)
    db.flush()
    service.audit_append(db, {"accio": "monedero_recarrega", "soci": member.id, "cent": cent, "metode": metode, "apunt": e.id, "per": actor.id})
    db.commit()
    return w


def reverse_for_entry(db: Session, actor: User, original: CashEntry, correction: CashEntry) -> None:
    """Si l'apunt corregit tocava el monedero, en desfà el moviment (SENSE commit). Una recàrrega només es pot anul·lar
    si el saldo resultant no passa del límit; la devolució d'un pagament sempre torna els diners al monedero."""
    w = db.scalar(select(WalletMovement).where(WalletMovement.cash_entry_id == original.id))
    if w is None:
        return
    if w.import_cent > 0:
        _comprova_saldo(db, w.local_id, w.member_id, -w.import_cent, actor)
    db.add(WalletMovement(local_id=w.local_id, member_id=w.member_id, tipus="correccio", import_cent=-w.import_cent,
                          cash_entry_id=correction.id, movement_id=w.movement_id, user_id=actor.id))
    db.flush()
    service.audit_append(db, {"accio": "monedero_correccio", "soci": w.member_id, "cent": -w.import_cent, "apunt": correction.id, "per": actor.id})


def member_of_entry(db: Session, entry_id: int) -> int | None:
    return db.scalar(select(WalletMovement.member_id).where(WalletMovement.cash_entry_id == entry_id))


def history(db: Session, member_id: int, limit: int = 200) -> list[dict]:
    return [{"id": w.id, "ts": w.ts.isoformat(), "tipus": w.tipus, "import_cent": w.import_cent, "moviment": w.movement_id}
            for w in db.scalars(select(WalletMovement).where(WalletMovement.member_id == member_id).order_by(WalletMovement.id.desc()).limit(limit))]

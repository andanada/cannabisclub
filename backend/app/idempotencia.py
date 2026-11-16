"""Protecció contra el doble enviament d'operacions amb diners o producte.

El client genera una referència (`client_ref`) per cada operació que l'usuari vol fer i l'envia amb la petició. Si la mateixa
referència torna a arribar (doble clic, Intro després del clic, reintent perquè la resposta es va perdre), l'operació NO es
repeteix: es retorna la resposta de la primera vegada.

La clau s'insereix a la mateixa transacció que l'operació: si l'operació falla, la clau desapareix amb ella i es pot tornar a
provar amb la mateixa referència. Dues peticions simultànies amb la mateixa clau: l'índex únic fa esperar la segona fins que
la primera acaba. Sense `client_ref` tot funciona com sempre.
"""
import hashlib
import json
from datetime import timedelta

from fastapi import HTTPException
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .models import IdempotencyKey, User, now

DIES = 7                       # les claus més velles s'esborren: un reintent no arriba mai tan tard
REF_PATTERN = r"^[A-Za-z0-9-]{16,64}$"

REPETIDA_DIFERENT = "Aquesta operació ja s'havia registrat amb altres dades. Revisa l'historial abans de repetir-la."
EN_CURS = "Aquesta operació ja s'està registrant. Espera un moment i revisa l'historial abans de repetir-la."


def _empremta(cos: dict) -> str:
    net = {k: v for k, v in cos.items() if k != "client_ref"}
    return hashlib.sha256(json.dumps(net, sort_keys=True, default=str, separators=(",", ":")).encode()).hexdigest()


def _resposta_desada(fila: IdempotencyKey, user: User, ruta: str, empremta: str) -> dict:
    if fila.user_id != user.id or fila.ruta != ruta or fila.cos_sha256 != empremta:
        raise HTTPException(409, REPETIDA_DIFERENT)
    if fila.resposta is None:
        raise HTTPException(409, EN_CURS)
    return json.loads(fila.resposta)


def executa(db: Session, user: User, ruta: str, client_ref: str | None, cos: dict, operacio) -> dict:
    """Executa `operacio()` (que fa el seu propi commit i retorna el diccionari de la resposta) una sola vegada per referència."""
    if not client_ref:
        return operacio()
    empremta = _empremta(cos)
    fila = db.scalar(select(IdempotencyKey).where(IdempotencyKey.clau == client_ref))
    if fila is not None:
        return _resposta_desada(fila, user, ruta, empremta)
    db.execute(delete(IdempotencyKey).where(IdempotencyKey.creat < now() - timedelta(days=DIES)))
    fila = IdempotencyKey(clau=client_ref, user_id=user.id, ruta=ruta, cos_sha256=empremta)
    db.add(fila)
    try:
        db.flush()
    except IntegrityError:   # una altra petició amb la mateixa referència ha acabat mentre aquesta esperava
        db.rollback()
        fila = db.scalar(select(IdempotencyKey).where(IdempotencyKey.clau == client_ref))
        if fila is None:
            raise HTTPException(409, EN_CURS)
        return _resposta_desada(fila, user, ruta, empremta)
    resposta = operacio()    # fa commit: la clau queda desada juntament amb l'operació (o cap de les dues)
    fila.resposta = json.dumps(resposta, default=str)
    db.commit()
    return resposta

"""Registre d'auditoria només d'afegir, amb hash encadenat (cada entrada inclou el hash de l'anterior)."""
import hashlib
import json
from dataclasses import dataclass

GENESIS = "0" * 64


def _digest(prev_hash: str, payload: dict) -> str:
    body = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256((prev_hash + body).encode()).hexdigest()


@dataclass(frozen=True)
class Entry:
    seq: int
    payload: dict
    prev_hash: str
    hash: str


def append(chain: list[Entry], payload: dict) -> Entry:
    prev = chain[-1].hash if chain else GENESIS
    entry = Entry(len(chain) + 1, payload, prev, _digest(prev, payload))
    chain.append(entry)
    return entry


def verify(chain: list[Entry]) -> tuple[bool, int | None]:
    """Torna (True, None) si la cadena és íntegra, o (False, seq) amb la primera entrada alterada."""
    prev = GENESIS
    for i, e in enumerate(chain, start=1):
        if e.seq != i or e.prev_hash != prev or e.hash != _digest(prev, e.payload):
            return False, e.seq
        prev = e.hash
    return True, None

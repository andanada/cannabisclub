"""Registre d'auditoria només d'afegir, amb hash encadenat (cada entrada inclou el hash de l'anterior).

Disseny de l'HMAC (sense canviar l'esquema)
-------------------------------------------
* Entrades ANTIGUES: hash = SHA-256(prev_hash + payload_canònic). Qui té accés d'escriptura a la BD pot refer-les
  senceres, perquè no hi ha cap secret.
* Entrades NOVES: el payload porta la marca ``"_alg": "h1"`` i hash = HMAC-SHA256(clau, prev_hash + payload_canònic).
  El hash segueix tenint 64 caràcters hexadecimals (la columna és String(64)), per això la marca d'algorisme viu dins del
  payload, que ja està cobert pel hash. La clau és CLUB_AUDIT_KEY o, si no hi és, es deriva de CLUB_INDEX_KEY amb una
  etiqueta de domini (HMAC(CLUB_INDEX_KEY, "club-gestio/audit-chain/v1")), de manera que no es reutilitza tal qual.
* Compatibilitat: la verificació tria l'algorisme per entrada (marca h1 -> HMAC; sense marca -> SHA-256).
* Degradació: com que la marca és dins del payload, qui refés la cadena amb SHA-256 podria treure-la. Es controla amb:
  (1) un cop vista una entrada h1, cap de posterior pot ser sense marca; (2) CLUB_AUDIT_HMAC_DES_DE=<seq>, punt de tall
  fixat fora de la BD (totes les entrades amb seq >= aquest valor han de ser h1); (3) l'ANCORATGE extern (últim seq + hash),
  que un atacant sense la clau no pot reproduir. Sense (2) ni (3), refer TOTA la cadena amb SHA-256 no es detecta:
  per això la verificació avisa «sense_ancoratge».
* Canviar CLUB_AUDIT_KEY (o CLUB_INDEX_KEY si no n'hi ha) invalida la verificació de les entrades h1 existents."""
import hashlib
import hmac
import json
import os
from dataclasses import dataclass

GENESIS = "0" * 64
ALG_KEY = "_alg"
ALG_HMAC = "h1"
_ETIQUETA = b"club-gestio/audit-chain/v1"


def audit_key() -> bytes:
    k = os.environ.get("CLUB_AUDIT_KEY")
    if k:
        return k.encode()
    base = os.environ.get("CLUB_INDEX_KEY")
    if not base:
        raise RuntimeError("Falta CLUB_AUDIT_KEY (o CLUB_INDEX_KEY) per signar l'auditoria")
    return hmac.new(base.encode(), _ETIQUETA, hashlib.sha256).digest()


def _body(payload: dict) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _digest(prev_hash: str, payload: dict) -> str:
    """SHA-256 pla (entrades antigues i cadenes en memòria de les proves)."""
    return hashlib.sha256((prev_hash + _body(payload)).encode()).hexdigest()


def digest_h1(prev_hash: str, payload: dict, key: bytes | None = None) -> str:
    return hmac.new(key or audit_key(), (prev_hash + _body(payload)).encode(), hashlib.sha256).hexdigest()


def is_h1(payload: dict) -> bool:
    return payload.get(ALG_KEY) == ALG_HMAC


def expected_hash(prev_hash: str, payload: dict, key: bytes) -> str:
    return digest_h1(prev_hash, payload, key) if is_h1(payload) else _digest(prev_hash, payload)


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

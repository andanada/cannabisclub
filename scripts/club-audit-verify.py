"""Verifica la cadena d'auditoria (hash encadenat) i surt amb codi 3 si està trencada.
Substitueix el botó «Verificar la integritat de l'auditoria» per a execució programada (timer setmanal).
Equivalent: `python -m app.cli verificar-auditoria [seq:hash]` (accepta un ancoratge).
Cal CLUB_DATABASE_URL (el rol de l'aplicació és suficient: només llegeix).
Ús: club-audit-verify.py   (des de qualsevol directori)"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app import service  # noqa: E402
from app.db import make_engine, make_session_factory  # noqa: E402


def main() -> int:
    with make_session_factory(make_engine())() as db:
        ok, bad = service.audit_verify(db)
    if ok:
        print("Auditoria íntegra.")
        return 0
    print(f"ALERTA: cadena d'auditoria trencada; primera fila alterada: seq={bad}", file=sys.stderr)
    return 3


if __name__ == "__main__":
    sys.exit(main())

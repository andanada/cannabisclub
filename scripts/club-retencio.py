"""Política de retenció de dades. Sense opcions només MOSTRA el que faria; no esborra res si no s'hi passa --aplicar.
  club-retencio.py [--local N] [--aplicar]
Variables: CLUB_RETENCIO_MIN_DIES (dies mínims des de la baixa, 365), CLUB_RETENCIO_FOTOS_DIES (365),
CLUB_RETENCIO_INTENTS_DIES (30). Cal CLUB_DATABASE_URL o CLUB_APP_DATABASE_URL, CLUB_FIELD_KEY i CLUB_INDEX_KEY."""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app import retencio  # noqa: E402
from app.db import make_engine, make_session_factory  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--aplicar", action="store_true", help="executa la purga (sense això, només simula)")
    ap.add_argument("--local", type=int, default=None)
    a = ap.parse_args(argv)
    with make_session_factory(make_engine())() as db:
        r = retencio.run(db, None, a.aplicar, a.local)
    print(json.dumps(r, indent=2, ensure_ascii=False))
    if not a.aplicar:
        print("\nSimulació: no s'ha canviat res. Torna a executar amb --aplicar per fer-ho.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())

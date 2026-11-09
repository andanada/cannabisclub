"""Ancoratge de l'auditoria des de la línia d'ordres (cal CLUB_DATABASE_URL i les claus a l'entorn):
  python -m app.audit_cli ancora              -> imprimeix «seq:hash» per guardar-ho FORA d'aquest equip
  python -m app.audit_cli verifica [seq:hash] -> verifica la cadena (i l'ancoratge, si es dona); codi de sortida 1 si falla"""
import sys

from . import service
from .db import make_engine, make_session_factory


def main(argv: list[str]) -> int:
    if not argv or argv[0] not in ("ancora", "verifica"):
        print(__doc__)
        return 2
    with make_session_factory(make_engine())() as db:
        if argv[0] == "ancora":
            a = service.audit_anchor(db)
            print(f"{a['seq']}:{a['hash']}" if a else "buida")
            return 0
        ancora = None
        if len(argv) > 1:
            seq, _, h = argv[1].partition(":")
            ancora = {"seq": int(seq), "hash": h}
        d = service.audit_verify_detail(db, ancora)
        print(("INTEGRA" if d["integra"] else f"ALTERADA a partir del seq {d['primera_alterada']}"),
              f"entrades={d['entrades']} ultim={d['ultim_seq']}:{d['ultim_hash']}", " ".join(d["avisos"]))
        return 0 if d["integra"] else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

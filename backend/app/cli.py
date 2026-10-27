"""Ordres d'administració. Ús: python -m app.cli crear-admin <usuari>  (la contrasenya es demana per terminal)."""
import getpass
import sys

import pyotp

from . import service
from . import schema
from .db import make_engine, make_session_factory


def main(argv: list[str]) -> int:
    if len(argv) != 2 or argv[0] != "crear-admin":
        print(__doc__)
        return 2
    engine = make_engine()
    schema.install(engine)
    password = getpass.getpass("Contrasenya (mínim 12 caràcters): ")
    if password != getpass.getpass("Repeteix-la: "):
        print("No coincideixen")
        return 1
    with make_session_factory(engine)() as db:
        u, secret = service.create_user(db, None, argv[1], password, "admin", [])
    print("Admin creat. Afegeix aquest secret a l'app d'autenticació (només es mostra ara):")
    print(secret)
    print(pyotp.TOTP(secret).provisioning_uri(name=argv[1], issuer_name="club-gestio"))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

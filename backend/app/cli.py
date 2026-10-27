"""Ordres d'administració.
  python -m app.cli crear-admin <usuari>      (la contrasenya es demana per terminal)
  python -m app.cli preparar-bd <fitxer .env>  (crea el rol de l'aplicació i en desa la contrasenya al fitxer, sense mostrar-la)
Cal CLUB_DATABASE_URL amb l'usuari PROPIETARI per a aquestes ordres; l'aplicació en funcionament fa servir el rol sense privilegis."""
import getpass
import sys

import pyotp

from . import service
from . import schema
from .db import make_engine, make_session_factory


def preparar_bd(env_file: str) -> int:
    import os
    import secrets
    from sqlalchemy.engine import make_url
    engine = make_engine()
    schema.install(engine)
    role = os.environ.get("CLUB_APP_ROLE", "club_app")
    password = secrets.token_urlsafe(24)
    schema.create_app_role(engine, role, password)
    schema.grant_app_role(engine, role)
    url = make_url(os.environ["CLUB_DATABASE_URL"]).set(username=role, password=password)
    fd = os.open(env_file, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    with os.fdopen(fd, "a") as f:
        f.write("CLUB_APP_DATABASE_URL=" + url.render_as_string(hide_password=False) + "\n")
    print(f"Rol «{role}» preparat. La URL de l'aplicació s'ha afegit a {env_file} (no s'ha mostrat la contrasenya).")
    return 0


def main(argv: list[str]) -> int:
    if len(argv) == 2 and argv[0] == "preparar-bd":
        return preparar_bd(argv[1])
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

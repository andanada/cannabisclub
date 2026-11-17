"""En la CI (CI=true) no es permet saltar proves: si falta PostgreSQL, les proves de concurrència, de rols i de buidatge es
saltarien en silenci i la CI quedaria en verd sense haver provat el que més importa. Fora de la CI, es salten com sempre."""
import os

import pytest


def _en_ci() -> bool:
    return os.environ.get("CI", "").lower() in ("1", "true", "yes")


def pytest_sessionstart(session):
    if _en_ci() and not os.environ.get("CLUB_TEST_PG_URL"):
        pytest.exit("CI: falta CLUB_TEST_PG_URL (PostgreSQL). Sense ell les proves essencials es saltarien i la CI no provaria res.", returncode=2)


def pytest_sessionfinish(session, exitstatus):
    if not _en_ci():
        return
    rep = session.config.pluginmanager.get_plugin("terminalreporter")
    saltades = rep.stats.get("skipped", []) if rep else []
    if saltades:
        rep.write_line(f"CI: {len(saltades)} proves saltades; a la CI no n'hi pot haver cap.", red=True)
        session.exitstatus = 1

"""Executa la suite completa contra un PostgreSQL real, amb una sola ordre:

    .venv/bin/python scripts/test-pg.py [arguments de pytest]

Tria, per ordre: CLUB_TEST_PG_URL ja definida; el paquet `pgserver` (PostgreSQL incrustat, sense Docker; es pot
instal·lar amb `pip install pgserver`); o Docker (contenidor postgres:17 temporal). Ho neteja tot en acabar.
"""
import os
import shutil
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def to_sqlalchemy(uri: str) -> str:
    return uri.replace("postgresql://", "postgresql+psycopg://", 1) if uri.startswith("postgresql://") else uri


@contextmanager
def embedded():
    import pgserver  # type: ignore
    data = tempfile.mkdtemp(prefix="club-pg-")
    server = pgserver.get_server(data, cleanup_mode="stop")
    try:
        yield to_sqlalchemy(server.get_uri())
    finally:
        server.cleanup()
        shutil.rmtree(data, ignore_errors=True)


@contextmanager
def docker():
    if not shutil.which("docker"):
        raise RuntimeError("no hi ha Docker")
    name = f"club-test-pg-{os.getpid()}"
    subprocess.run(["docker", "run", "-d", "--rm", "--name", name, "-e", "POSTGRES_USER=club", "-e", "POSTGRES_PASSWORD=club-test",
                    "-e", "POSTGRES_DB=club", "-p", "127.0.0.1::5432", "postgres:17"], check=True, stdout=subprocess.DEVNULL)
    try:
        for _ in range(60):
            if subprocess.run(["docker", "exec", name, "pg_isready", "-U", "club", "-d", "club"], capture_output=True).returncode == 0:
                break
            time.sleep(1)
        port = subprocess.run(["docker", "port", name, "5432/tcp"], capture_output=True, text=True, check=True).stdout.split()[0].rsplit(":", 1)[1]
        yield f"postgresql+psycopg://club:club-test@127.0.0.1:{port}/club"
    finally:
        subprocess.run(["docker", "rm", "-f", name], capture_output=True)


def main() -> int:
    args = sys.argv[1:] or ["-q", "-rs"]
    if os.environ.get("CLUB_TEST_PG_URL"):
        providers = [None]
    else:
        providers = []
        try:
            import pgserver  # noqa: F401
            providers.append(embedded)
        except ImportError:
            pass
        providers.append(docker)
    last_error = None
    for provider in providers:
        try:
            ctx = provider() if provider else contextmanager(lambda: (yield os.environ["CLUB_TEST_PG_URL"]))()
            with ctx as url:
                print(f"PostgreSQL de proves: {url.split('@')[-1]}")
                env = {**os.environ, "CLUB_TEST_PG_URL": url}
                return subprocess.run([sys.executable, "-m", "pytest", *args], cwd=ROOT / "backend", env=env).returncode
        except (RuntimeError, subprocess.CalledProcessError, OSError) as e:
            last_error = e
    print(f"No he pogut aconseguir un PostgreSQL ({last_error}).\nInstal·la pgserver (`pip install pgserver`) o Docker.", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())

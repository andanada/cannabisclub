#!/usr/bin/env bash
# Còpia xifrada de la base de dades del club.
#   club-backup.sh run                 fa la còpia (cal CLUB_BACKUP_GPG_RECIPIENT amb la clau PÚBLICA importada)
#   club-backup.sh restore-test <fitxer>   desxifra, restaura en un PostgreSQL temporal i verifica l'auditoria (cal la clau PRIVADA)
# La torre només necessita la clau pública: no pot desxifrar les còpies. La privada es guarda fora de la torre.
set -euo pipefail
umask 077

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${CLUB_ENV_FILE:-$REPO/.env}"
DEST="${CLUB_BACKUP_DIR:-/data/backups/club}"
KEEP="${CLUB_BACKUP_KEEP:-30}"
CONTAINER="${CLUB_DB_CONTAINER:-club-gestio-db-1}"
DBNAME="${CLUB_DB_NAME:-club}"
PY="${CLUB_PYTHON:-$REPO/.venv/bin/python}"

app_password() {  # extreu la contrasenya de CLUB_APP_DATABASE_URL sense mostrar-la
  "$PY" -I - "$ENV_FILE" <<'PYEOF'
import sys
from sqlalchemy.engine import make_url
for line in open(sys.argv[1]):
    if line.startswith("CLUB_APP_DATABASE_URL="):
        u = make_url(line.split("=", 1)[1].strip())
        print(u.password or ""); print(u.username or "")
        break
PYEOF
}

cmd_run() {
  : "${CLUB_BACKUP_GPG_RECIPIENT:?Falta CLUB_BACKUP_GPG_RECIPIENT (id de la clau pública amb què es xifra)}"
  gpg --batch --list-keys "$CLUB_BACKUP_GPG_RECIPIENT" >/dev/null 2>&1 || { echo "La clau pública '$CLUB_BACKUP_GPG_RECIPIENT' no és al clauer de GPG"; exit 1; }
  mkdir -p "$DEST"
  local work ts out creds user
  work="$(mktemp -d "$DEST/.work.XXXXXX")"; trap "rm -rf -- '$work'" EXIT
  creds="$(app_password)"; local pw; pw="$(sed -n 1p <<<"$creds")"; user="$(sed -n 2p <<<"$creds")"
  [ -n "$pw" ] || { echo "No trobo CLUB_APP_DATABASE_URL a $ENV_FILE"; exit 1; }
  # la contrasenya passa per l'entorn, no per la línia d'ordres (no surt a «ps»)
  PGPASSWORD="$pw" docker exec -e PGPASSWORD "$CONTAINER" pg_dump -U "$user" -d "$DBNAME" -Fc > "$work/club.dump"
  [ -s "$work/club.dump" ] || { echo "El volcat és buit"; exit 1; }
  # claus de xifrat de camps: sense elles, les dades dels socis de la còpia no es poden llegir
  grep -E '^(CLUB_FIELD_KEY|CLUB_INDEX_KEY)=' "$ENV_FILE" > "$work/keys.env" || : > "$work/keys.env"
  ts="$(date +%Y%m%d-%H%M%S)"; out="$DEST/club-$ts.tar.gpg"
  tar -C "$work" -cf - club.dump keys.env | gpg --batch --yes --trust-model always -r "$CLUB_BACKUP_GPG_RECIPIENT" -e -o "$out"
  gpg --batch --list-packets "$out" >/dev/null 2>&1 || { echo "La còpia xifrada no és vàlida"; rm -f "$out"; exit 1; }
  sha256sum "$out" > "$out.sha256"
  ls -1t "$DEST"/club-*.tar.gpg | tail -n +"$((KEEP + 1))" | while read -r old; do rm -f -- "$old" "$old.sha256"; done
  if [ -n "${CLUB_BACKUP_REMOTE:-}" ]; then
    rsync -a --chmod=F600 -e "ssh -o BatchMode=yes" "$out" "$out.sha256" "$CLUB_BACKUP_REMOTE/"
    echo "Copiat a $CLUB_BACKUP_REMOTE"
  else
    echo "AVÍS: CLUB_BACKUP_REMOTE no definit: la còpia només és a la torre."
  fi
  echo "OK $out ($(stat -c %s "$out") bytes)"
}

cmd_restore_test() {
  local file="${1:?Cal el fitxer .tar.gpg}" work name port pw
  [ -f "$file" ] || { echo "No existeix $file"; exit 1; }
  [ ! -f "$file.sha256" ] || (cd "$(dirname "$file")" && sha256sum -c "$(basename "$file").sha256" >/dev/null) || { echo "El hash no coincideix: còpia alterada o corrompuda"; exit 1; }
  work="$(mktemp -d)"; name="club-restore-test-$$"; pw="$(head -c 18 /dev/urandom | base64 | tr -d '/+=')"
  trap "docker rm -f '$name' >/dev/null 2>&1 || true; rm -rf -- '$work'" EXIT
  gpg --batch --decrypt "$file" 2>/dev/null | tar -C "$work" -xf -
  [ -s "$work/club.dump" ] || { echo "No s'ha pogut desxifrar (falta la clau privada?)"; exit 1; }
  docker run -d --rm --name "$name" -e POSTGRES_PASSWORD="$pw" -e POSTGRES_DB=restore -p 127.0.0.1::5432 postgres:17 >/dev/null
  for _ in $(seq 1 40); do docker exec "$name" pg_isready -U postgres -d restore >/dev/null 2>&1 && break; sleep 1; done
  docker exec -i "$name" pg_restore -U postgres -d restore --no-owner --no-privileges --exit-on-error < "$work/club.dump"
  port="$(docker port "$name" 5432/tcp | head -1 | sed 's/.*://')"
  "$PY" -I - "postgresql+psycopg://postgres:$pw@127.0.0.1:$port/restore" "$REPO/backend" <<'PYEOF'
import sys
sys.path.insert(0, sys.argv[2])
from sqlalchemy import create_engine, select, func, text
from sqlalchemy.orm import Session
from app import service
from app.models import AuditLog, Member, StockMovement, CashEntry
e = create_engine(sys.argv[1])
with Session(e) as s:
    ok, bad = service.audit_verify(s)
    print("Auditoria íntegra:", ok, "" if ok else f"(primera alterada: {bad})")
    for m in (AuditLog, Member, StockMovement, CashEntry):
        print(f"  {m.__tablename__}: {s.scalar(select(func.count()).select_from(m))} files")
    sys.exit(0 if ok else 3)
PYEOF
  echo "Restauració verificada."
}

case "${1:-}" in
  run) cmd_run ;;
  restore-test) shift; cmd_restore_test "$@" ;;
  *) sed -n '2,5p' "$0"; exit 2 ;;
esac

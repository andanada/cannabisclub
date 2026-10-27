#!/usr/bin/env bash
# Prova de punta a punta de club-backup.sh amb una clau GPG temporal i un PostgreSQL temporal.
# No toca la base de dades de desenvolupament ni cap clau real.
set -euo pipefail
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="$REPO/.venv/bin/python"
T="$(mktemp -d)"; chmod 700 "$T"
SRC="club-backup-src-$$"
cleanup() { docker rm -f "$SRC" >/dev/null 2>&1 || true; rm -rf -- "$T"; }
trap cleanup EXIT
fail() { echo "FALLA: $*"; exit 1; }

export GNUPGHOME="$T/gnupg"; mkdir -m 700 "$GNUPGHOME"
gpg --batch --passphrase '' --quick-generate-key prova@club.local rsa3072 encr never >/dev/null 2>&1

PW="$(head -c 18 /dev/urandom | base64 | tr -d '/+=')"
docker run -d --rm --name "$SRC" -e POSTGRES_USER=club -e POSTGRES_PASSWORD="$PW" -e POSTGRES_DB=club -p 127.0.0.1::5432 postgres:17 >/dev/null
for _ in $(seq 1 40); do docker exec "$SRC" pg_isready -U club -d club >/dev/null 2>&1 && break; sleep 1; done
PORT="$(docker port "$SRC" 5432/tcp | head -1 | sed 's/.*://')"
APPPW="$(head -c 18 /dev/urandom | base64 | tr -d '/+=')"
FKEY="$("$PY" -I -c 'from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())')"

CLUB_FIELD_KEY="$FKEY" CLUB_INDEX_KEY="clau-index-de-prova" "$PY" -I - "postgresql+psycopg://club:$PW@127.0.0.1:$PORT/club" "$APPPW" "$REPO/backend" <<'PYEOF'
import sys
from datetime import date
from decimal import Decimal
sys.path.insert(0, sys.argv[3])
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from app import cash, schema, service, stock
from app.models import Local
e = create_engine(sys.argv[1]); schema.install(e)
schema.create_app_role(e, "club_app", sys.argv[2]); schema.grant_app_role(e, "club_app")
with Session(e) as s:
    s.add(Local(id=1, nom="Local de prova")); s.commit()
    admin, _ = service.create_user(s, None, "admin", "contrasenya-de-prova-1", "admin", [])
    m = service.create_member(s, admin, 1, "Anna Prova", "12345678Z", date(1990, 5, 20), "600111222", "anna@example.com")
    p = stock.add_product(s, admin, 1, "Producte A", "", 800)
    stock.receive(s, admin, p.id, Decimal("10"), None)
    cash.open_session(s, admin, 1, 5000)
    d = stock.dispense(s, admin, m.id, p.id, Decimal("2"), None)
    cash.charge(s, admin, d.id, "efectiu")
print("dades de prova creades")
PYEOF

cat > "$T/env" <<ENVEOF
CLUB_APP_DATABASE_URL=postgresql+psycopg://club_app:$APPPW@127.0.0.1:$PORT/club
CLUB_FIELD_KEY=$FKEY
CLUB_INDEX_KEY=clau-index-de-prova
ENVEOF
export CLUB_ENV_FILE="$T/env" CLUB_DB_CONTAINER="$SRC" CLUB_BACKUP_DIR="$T/backups" CLUB_BACKUP_GPG_RECIPIENT="prova@club.local"

echo "== 1. còpia"
"$REPO/scripts/club-backup.sh" run 2>&1 | tail -3
FILE="$(ls "$T"/backups/club-*.tar.gpg | head -1)"
[ -s "$FILE" ] || fail "no s'ha creat la còpia"

echo "== 2. la còpia no conté dades en clar"
for needle in "Anna Prova" "12345678Z" "anna@example.com" "CLUB_FIELD_KEY" "$FKEY" "PGDMP"; do
  ! grep -aqF "$needle" "$FILE" || fail "el fitxer xifrat conté «$needle»"
done
echo "   cap rastre de dades ni de claus"

echo "== 3. restauració i verificació"
"$REPO/scripts/club-backup.sh" restore-test "$FILE"

echo "== 4. el volcat desxifrat tampoc té els camps personals en clar"
gpg --batch --decrypt "$FILE" 2>/dev/null | tar -xOf - club.dump > "$T/club.dump"
for needle in "Anna Prova" "12345678Z" "anna@example.com" "600111222"; do
  ! grep -aqF "$needle" "$T/club.dump" || fail "el volcat conté «$needle» en clar"
done
gpg --batch --decrypt "$FILE" 2>/dev/null | tar -xOf - keys.env | grep -q "^CLUB_FIELD_KEY=" || fail "la còpia no inclou la clau de camps"
echo "   camps xifrats; claus incloses dins de la còpia xifrada"

echo "== 5. còpia alterada: s'ha de detectar"
cp "$FILE" "$T/tamper.tar.gpg"; cp "$FILE.sha256" "$T/tamper.tar.gpg.sha256"
printf '\x00' | dd of="$T/tamper.tar.gpg" bs=1 seek=200 conv=notrunc 2>/dev/null
( cd "$T" && sed -i 's/club-[0-9-]*\.tar\.gpg/tamper.tar.gpg/' tamper.tar.gpg.sha256 )
if "$REPO/scripts/club-backup.sh" restore-test "$T/tamper.tar.gpg" >/dev/null 2>&1; then fail "una còpia alterada s'ha acceptat"; fi
echo "   alteració detectada"

echo "== 6. sense la clau privada no es pot desxifrar"
export GNUPGHOME="$T/altre"; mkdir -m 700 "$GNUPGHOME"
if "$REPO/scripts/club-backup.sh" restore-test "$FILE" >/dev/null 2>&1; then fail "s'ha desxifrat sense la clau privada"; fi
echo "   correcte: no es pot"

echo "== 7. rotació: només es conserven les N còpies més recents"
export GNUPGHOME="$T/gnupg"; export CLUB_BACKUP_KEEP=2
for _ in 1 2 3; do sleep 1; "$REPO/scripts/club-backup.sh" run >/dev/null 2>&1; done
N="$(ls "$T"/backups/club-*.tar.gpg | wc -l)"
[ "$N" -eq 2 ] || fail "esperava 2 còpies, n'hi ha $N"
echo "   queden $N còpies"
echo "TOT CORRECTE"

#!/usr/bin/env bash
# Prova de punta a punta de club-backup.sh amb una clau GPG temporal i un PostgreSQL temporal.
# No toca la base de dades de desenvolupament ni cap clau real.
# shellcheck disable=SC2012
set -euo pipefail
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="$REPO/.venv/bin/python"
T="$(mktemp -d)"; chmod 700 "$T"
SRC="club-backup-src-$$"
cleanup() { docker rm -f "$SRC" >/dev/null 2>&1 || true; rm -rf -- "$T"; }
trap cleanup EXIT
fail() { echo "FALLA: $*"; exit 1; }

export GNUPGHOME="$T/gnupg"; mkdir -m 700 "$GNUPGHOME"
# tres claus: destinatari del volcat, destinatari de les claus de camp i signatura de la torre
gpg --batch --passphrase '' --quick-generate-key volcat@club.local rsa3072 encr never >/dev/null 2>&1
gpg --batch --passphrase '' --quick-generate-key claus@club.local rsa3072 encr never >/dev/null 2>&1
gpg --batch --passphrase '' --quick-generate-key torre@club.local rsa3072 sign never >/dev/null 2>&1
SIGNER_FPR="$(gpg --batch --with-colons --fingerprint torre@club.local | awk -F: '/^fpr/{print $10; exit}')"
REMOTE="$T/remot"; mkdir -p "$REMOTE"

PW="$(head -c 18 /dev/urandom | base64 | tr -d '/+=')"
docker run -d --rm --name "$SRC" -e POSTGRES_USER=club -e POSTGRES_PASSWORD="$PW" -e POSTGRES_DB=club -p 127.0.0.1::5432 postgres:17 >/dev/null
# per TCP: pel socket ja respon el servidor temporal d'inicialització de la imatge, que després s'apaga
for _ in $(seq 1 60); do docker exec "$SRC" pg_isready -h 127.0.0.1 -U club -d club >/dev/null 2>&1 && break; sleep 1; done
docker exec "$SRC" pg_isready -h 127.0.0.1 -U club -d club >/dev/null 2>&1 || fail "el PostgreSQL de prova no arrenca"
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
export CLUB_ENV_FILE="$T/env" CLUB_DB_CONTAINER="$SRC" CLUB_BACKUP_DIR="$T/backups" CLUB_BACKUP_GPG_RECIPIENT="volcat@club.local"   CLUB_BACKUP_KEYS_RECIPIENT="claus@club.local" CLUB_BACKUP_SIGNER="torre@club.local" CLUB_BACKUP_SIGNER_FPR="$SIGNER_FPR"   CLUB_BACKUP_REMOTE="$REMOTE"

echo "== 0. sense remot la còpia ha de fallar sorollosament"
if CLUB_BACKUP_REMOTE="" "$REPO/scripts/club-backup.sh" run >/dev/null 2>&1; then fail "ha acceptat no tenir remot"; fi
echo "   correcte: es nega"

echo "== 1. còpia"
"$REPO/scripts/club-backup.sh" run 2>&1 | tail -3
FILE="$(ls "$T"/backups/club-*.dump.gpg | head -1)"
[ -s "$FILE" ] || fail "no s'ha creat la còpia"
[ -s "$REMOTE/$(basename "$FILE")" ] || fail "no s'ha copiat al remot"
KEYS="$(ls "$T"/backups/club-keys-*.keys.gpg | head -1)"
[ -s "$KEYS" ] || fail "no hi ha paquet de claus"
! compgen -G "$T/backups/*.part" >/dev/null || fail "hi ha fitxers intermedis"
[ -s "$FILE.anchor" ] || fail "no s'ha desat l'ancoratge d'auditoria al costat de la còpia"

echo "== 2. cap dada ni clau en clar, i claus separades del volcat"
for f in "$FILE" "$KEYS"; do
  for needle in "Anna Prova" "12345678Z" "anna@example.com" "CLUB_FIELD_KEY" "$FKEY" "PGDMP"; do
    ! grep -aqF "$needle" "$f" || fail "$f conté «$needle»"
  done
done
[ "$(gpg --batch --decrypt "$KEYS" 2>/dev/null | grep -c "^CLUB_FIELD_KEY=")" = 1 ] || fail "el paquet de claus no s'obre amb la seva clau"
[ "$( { gpg --batch --decrypt "$FILE" 2>/dev/null || true; } | head -c5)" = PGDMP ] || fail "el volcat no és un volcat"
echo "   correcte"

echo "== 3. restauració, signatura i verificació"
"$REPO/scripts/club-backup.sh" restore-test "$FILE"

echo "== 4. signatura d'una altra clau: s'ha de rebutjar"
if CLUB_BACKUP_SIGNER_FPR="0000000000000000000000000000000000000000" "$REPO/scripts/club-backup.sh" restore-test "$FILE" >/dev/null 2>&1; then fail "ha acceptat una empremta equivocada"; fi
echo "   correcte"

echo "== 5. sense sha256 o còpia alterada: s'ha de detectar"
cp "$FILE" "$T/tamper.dump.gpg"
if "$REPO/scripts/club-backup.sh" restore-test "$T/tamper.dump.gpg" >/dev/null 2>&1; then fail "ha acceptat una còpia sense sha256"; fi
cp "$FILE.sha256" "$T/tamper.dump.gpg.sha256"; sed -i 's/club-[0-9-]*\.dump\.gpg/tamper.dump.gpg/' "$T/tamper.dump.gpg.sha256"
ORIG="$(dd if="$T/tamper.dump.gpg" bs=1 skip=200 count=1 2>/dev/null | od -An -tu1 | tr -d " ")"
# shellcheck disable=SC2059  # intencionat: el format es construeix per escriure un byte arbitrari
printf "$(printf '\%03o' $(( (ORIG + 1) % 256 )))" | dd of="$T/tamper.dump.gpg" bs=1 seek=200 conv=notrunc 2>/dev/null
! cmp -s "$FILE" "$T/tamper.dump.gpg" || fail "la prova no ha alterat la copia"
if "$REPO/scripts/club-backup.sh" restore-test "$T/tamper.dump.gpg" >/dev/null 2>&1; then fail "una còpia alterada s'ha acceptat"; fi
echo "   correcte"

echo "== 6. sense la clau privada no es pot desxifrar"
export GNUPGHOME="$T/altre"; mkdir -m 700 "$GNUPGHOME"
if "$REPO/scripts/club-backup.sh" restore-test "$FILE" >/dev/null 2>&1; then fail "s'ha desxifrat sense la clau privada"; fi
echo "   correcte"

echo "== 7. retenció per capes (diàries 2 en aquesta prova), també al remot"
export GNUPGHOME="$T/gnupg" CLUB_BACKUP_KEEP_DAILY=2 CLUB_BACKUP_KEEP_WEEKLY=1 CLUB_BACKUP_KEEP_MONTHLY=1
for d in 20250101 20250102 20250103 20250104; do
  for dir in "$T/backups" "$REMOTE"; do : > "$dir/club-$d-030000.dump.gpg"; : > "$dir/club-$d-030000.dump.gpg.sha256"; done
done
"$REPO/scripts/club-backup.sh" prune
for dir in "$T/backups" "$REMOTE"; do
  N="$(ls "$dir"/club-2025*.dump.gpg 2>/dev/null | wc -l)"
  [ "$N" -le 2 ] || fail "retenció: a $dir queden $N còpies antigues"
done
echo "   correcte"
echo "TOT CORRECTE"

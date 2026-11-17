#!/usr/bin/env bash
# Desplegament repetible al servidor, des del teu ordinador:
#   scripts/deploy.sh --host usuari@servidor [--ref REF] [--deps] [--no-db-backup] [--dry-run]
#
# Què fa (i en aquest ordre):
#   1. Comprova que no hi ha canvis sense desar i que es desplega un commit concret (per defecte HEAD).
#   2. Puja aquell commit (git archive, sempre amb finals de línia LF) a una carpeta d'etapa del servidor.
#   3. Còpia de seguretat de la base de dades i del codi que hi ha ara (per poder tornar enrere).
#   4. Canvia backend/app, frontend, scripts i docs pels nous: el que ja no és al repositori DESAPAREIX del servidor.
#   5. Si requirements.lock ha canviat, instal·la amb hashes obligatoris (--deps el força la primera vegada).
#   6. actualitzar-bd, reinicia el servei i espera que /salut respongui amb LA VERSIÓ NOVA.
#   7. Si alguna cosa falla després del pas 4, TORNA ENRERE sola (codi anterior + reinici) i surt amb error.
# No toca .env, .venv ni les dades. La base de dades només rep canvis additius (actualitzar-bd), així que tornar enrere
# el codi és segur.
#
# Variables (o opcions): CLUB_DEPLOY_HOST (--host), CLUB_DEPLOY_DIR (/opt/club-gestio), CLUB_DEPLOY_SERVICE (club-gestio),
# CLUB_DEPLOY_DB_CONTAINER (club-gestio-db-1), CLUB_DEPLOY_PORT (8099, el del servei a 127.0.0.1 del servidor).
set -euo pipefail

HOST="${CLUB_DEPLOY_HOST:-}"
DIR="${CLUB_DEPLOY_DIR:-/opt/club-gestio}"
SERVICE="${CLUB_DEPLOY_SERVICE:-club-gestio}"
DBC="${CLUB_DEPLOY_DB_CONTAINER:-club-gestio-db-1}"
PORT="${CLUB_DEPLOY_PORT:-8099}"
REF="HEAD"; DEPS=0; DBBACKUP=1; DRY=0; FAILTEST=0; ALLOW_DIRTY=0

die() { echo "ERROR: $*" >&2; exit 1; }
while [ $# -gt 0 ]; do
  case "$1" in
    --host) HOST="${2:?falta el valor de --host}"; shift 2 ;;
    --ref) REF="${2:?falta el valor de --ref}"; shift 2 ;;
    --deps) DEPS=1; shift ;;
    --no-db-backup) DBBACKUP=0; shift ;;
    --dry-run) DRY=1; shift ;;
    --allow-dirty) ALLOW_DIRTY=1; shift ;;
    --prova-rollback) FAILTEST=1; shift ;;   # prova del camí de tornada enrere: força que la comprovació de salut falli
    -h|--help) sed -n '2,19p' "$0"; exit 0 ;;
    *) die "opció desconeguda: $1" ;;
  esac
done
[ -n "$HOST" ] || die "Falta el servidor: --host usuari@servidor (o CLUB_DEPLOY_HOST)"
case "$HOST$DIR$SERVICE$DBC$PORT" in *[\'\"\;\&\|\$\`\ ]*) die "valor no vàlid (espais o caràcters especials)";; esac

cd "$(git -C "$(dirname "${BASH_SOURCE[0]}")" rev-parse --show-toplevel)"
SHA="$(git rev-parse --short=10 "$REF")" || die "no existeix el commit $REF"
if [ "$ALLOW_DIRTY" = 0 ] && [ -n "$(git status --porcelain --untracked-files=no)" ]; then
  die "Hi ha canvis sense desar. Fes commit (es desplega un commit, no la carpeta de treball) o usa --allow-dirty sabent-ho."
fi
if git rev-parse --verify -q origin/main >/dev/null && [ "$REF" = HEAD ] \
   && [ -n "$(git log --oneline origin/main..HEAD 2>/dev/null)" ]; then
  echo "AVÍS: hi ha commits que encara no són a origin/main (git push)." >&2
fi
TS="$(date +%Y%m%d-%H%M%S)"
echo "Desplegant $SHA ($REF) a $HOST:$DIR"
[ "$DRY" = 0 ] || { echo "(--dry-run: no es fa res més)"; exit 0; }

SSH=(ssh -o BatchMode=yes -o ConnectTimeout=15 "$HOST")
STAGE="$DIR/.releases/$SHA-$TS"

echo "== 1. Pujant el codi a $STAGE"
# -c core.autocrlf=false: sense això, git archive exporta amb CRLF en un Windows amb autocrlf i el servidor rep fitxers amb \r
git -c core.autocrlf=false archive --format=tar "$REF" backend/app frontend scripts docs README.md REQUISITS.md docker-compose.yml \
    requirements.txt requirements-dev.txt requirements.lock 2>/dev/null \
  | "${SSH[@]}" "mkdir -p '$STAGE' && tar xf - -C '$STAGE'" \
  || die "no s'ha pogut pujar el codi"
printf '%s %s\n' "$SHA" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" | "${SSH[@]}" "cat > '$STAGE/VERSION'"

echo "== 2. Còpies (codi actual i base de dades)"
"${SSH[@]}" "set -e; mkdir -p ~/club-backups; tar czf ~/club-backups/codi-pre-$SHA-$TS.tgz -C '$DIR' backend/app frontend scripts docs && echo '   codi actual desat'"
if [ "$DBBACKUP" = 1 ]; then
  "${SSH[@]}" "set -e; u=\$(docker exec '$DBC' printenv POSTGRES_USER); docker exec '$DBC' pg_dump -U \"\$u\" -d club -Fc > ~/club-backups/pre-$SHA-$TS.dump; chmod 600 ~/club-backups/pre-$SHA-$TS.dump; [ -s ~/club-backups/pre-$SHA-$TS.dump ] && echo '   base de dades desada'" \
    || die "no s'ha pogut fer la còpia de la base de dades (res no s'ha tocat); --no-db-backup l'omet sabent-ho"
fi

# A partir d'aquí el servidor canvia: tot el que falla torna enrere.
echo "== 3. Canviant el codi, instal·lant i reiniciant (amb tornada enrere automàtica)"
rc=0
"${SSH[@]}" bash -s -- "$DIR" "$STAGE" "$SERVICE" "$PORT" "$SHA" "$DEPS" "$FAILTEST" <<'REMOTE' || rc=$?
set -uo pipefail
DIR="$1"; STAGE="$2"; SERVICE="$3"; PORT="$4"; SHA="$5"; DEPS="$6"; FAILTEST="$7"
PREV="$STAGE.prev"; mkdir -p "$PREV"
CANVIS="backend/app frontend scripts docs"
say() { echo "   $*"; }

restart() { sudo -n systemctl restart "$SERVICE"; }
salut() {   # espera /salut OK amb la versió que toca (30 s com a màxim)
  local esperada="$1" r i
  for i in $(seq 1 30); do
    r="$(curl -fsS "http://127.0.0.1:$PORT/salut" 2>/dev/null || true)"
    if [ -n "$r" ] && grep -q '"ok":true' <<<"$r" && { [ -z "$esperada" ] || grep -q "\"versio\":\"$esperada\"" <<<"$r"; }; then return 0; fi
    sleep 1
  done
  return 1
}
tornar_enrere() {
  say "TORNANT ENRERE: $1"
  for d in $CANVIS; do
    if [ -e "$PREV/$d" ]; then rm -rf "$DIR/$d"; mkdir -p "$(dirname "$DIR/$d")"; mv "$PREV/$d" "$DIR/$d"; fi
  done
  if [ -e "$PREV/VERSION" ]; then cp "$PREV/VERSION" "$DIR/VERSION"; else rm -f "$DIR/VERSION"; fi   # mai una versió que no és la que corre
  restart
  if salut ""; then say "tornat al codi anterior: el servei respon"; else say "ATENCIÓ: el servei NO respon ni amb el codi anterior (journalctl -u $SERVICE)"; fi
  exit 1
}

for d in $CANVIS; do   # el que hi ha ara es guarda a .prev, i el nou entra (desapareix el que ja no és al repositori)
  mkdir -p "$(dirname "$PREV/$d")"
  [ -e "$DIR/$d" ] && mv "$DIR/$d" "$PREV/$d"
  mkdir -p "$(dirname "$DIR/$d")"
  mv "$STAGE/$d" "$DIR/$d" || tornar_enrere "no s'ha pogut instal·lar $d"
done
if [ -f "$DIR/VERSION" ]; then cp "$DIR/VERSION" "$PREV/VERSION"; fi
cp "$STAGE/VERSION" "$DIR/VERSION"
for f in README.md REQUISITS.md docker-compose.yml requirements.txt requirements-dev.txt; do [ -f "$STAGE/$f" ] && cp "$STAGE/$f" "$DIR/$f"; done
say "codi nou instal·lat ($SHA); l'anterior és a $PREV"

# Dependències: només si requirements.lock ha canviat (o --deps). La primera vegada (sense referència) no s'instal·la per
# sorpresa: es demana --deps.
if [ -f "$STAGE/requirements.lock" ]; then
  nou="$(sha256sum "$STAGE/requirements.lock" | cut -d' ' -f1)"
  vell="$(cat "$DIR/.requirements.lock.sha256" 2>/dev/null || true)"
  if [ "$DEPS" = 1 ] || { [ -n "$vell" ] && [ "$vell" != "$nou" ]; }; then
    say "instal·lant dependències (requirements.lock amb hashes obligatoris)"
    "$DIR/.venv/bin/pip" install -q --require-hashes -r "$STAGE/requirements.lock" || tornar_enrere "ha fallat pip install"
    cp "$STAGE/requirements.lock" "$DIR/requirements.lock"; echo "$nou" > "$DIR/.requirements.lock.sha256"
  elif [ -z "$vell" ]; then
    say "AVÍS: no hi ha referència de requirements.lock (primer desplegament amb aquest script): no s'instal·la. Usa --deps per fer-ho."
    cp "$STAGE/requirements.lock" "$DIR/requirements.lock"; echo "$nou" > "$DIR/.requirements.lock.sha256.pendent"
  else
    say "dependències sense canvis"
  fi
fi

say "actualitzar-bd"
( cd "$DIR/backend" && set -a && . "$DIR/.env" && set +a && "$DIR/.venv/bin/python" -m app.cli actualitzar-bd ) || tornar_enrere "ha fallat actualitzar-bd"

say "reiniciant $SERVICE"
restart || tornar_enrere "no s'ha pogut reiniciar el servei"
if [ "$FAILTEST" = 1 ]; then salut "versio-que-no-existeix" || tornar_enrere "(prova) la comprovació de salut falla a propòsit"; fi
salut "$SHA" || tornar_enrere "/salut no respon amb la versió $SHA en 30 s"
say "el servei respon amb la versió $SHA"

# Neteja: es guarden només els 5 desplegaments més recents.
ls -1dt "$DIR"/.releases/*/ 2>/dev/null | tail -n +6 | while read -r v; do rm -rf "$v"; done
ls -1dt "$DIR"/.releases/*.prev 2>/dev/null | tail -n +6 | while read -r v; do rm -rf "$v"; done
exit 0
REMOTE
if [ "$rc" -ne 0 ]; then
  echo "DESPLEGAMENT FALLIT: el servidor ha tornat al codi anterior (vegeu els missatges de dalt)." >&2
  exit "$rc"
fi
echo "== OK: $SHA desplegat. Còpies a ~/club-backups (codi-pre-$SHA-$TS.tgz, pre-$SHA-$TS.dump)."

#!/usr/bin/env bash
# Còpia xifrada, signada i amb retenció per capes de la base de dades del club.
#   club-backup.sh run                    volcat -> gpg (xifra + signa) sense cap fitxer intermedi en clar; paquet de claus a part; còpia externa; retenció
#   club-backup.sh keys                   (re)genera només el paquet de claus de camp (xifrat a una ALTRA clau)
#   club-backup.sh restore-test <fitxer>  verifica sha256 i signatura (CLUB_BACKUP_SIGNER_FPR), restaura en un PostgreSQL temporal i verifica l'auditoria
#   club-backup.sh prune                  aplica la retenció (local i remot) sense fer cap còpia
# Variables: vegeu docs/COPIES.md. La torre només necessita claus PÚBLIQUES (destinataris) i la clau de signatura.
set -euo pipefail
umask 077

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${CLUB_ENV_FILE:-$REPO/.env}"
KEYS_FILE="${CLUB_KEYS_FILE:-$ENV_FILE}"        # ÚNICA font de CLUB_FIELD_KEY / CLUB_INDEX_KEY al servidor
DEST="${CLUB_BACKUP_DIR:-/data/backups/club}"
CONTAINER="${CLUB_DB_CONTAINER:-club-gestio-db-1}"
DBNAME="${CLUB_DB_NAME:-club}"
PY="${CLUB_PYTHON:-$REPO/.venv/bin/python}"
KEEP_DAILY="${CLUB_BACKUP_KEEP_DAILY:-14}"
KEEP_WEEKLY="${CLUB_BACKUP_KEEP_WEEKLY:-8}"
KEEP_MONTHLY="${CLUB_BACKUP_KEEP_MONTHLY:-12}"
RESTORE_IMAGE="${CLUB_RESTORE_IMAGE:-postgres:17}"
DUMP_RE='^club-[0-9]{8}-[0-9]{6}\.dump\.gpg$'

die() { echo "ERROR: $*" >&2; exit 1; }

app_credentials() {  # imprimeix contrasenya i usuari de CLUB_APP_DATABASE_URL (en línies separades), sense mostrar-los enlloc més
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

# ---------- remot (rsync/ssh «host:ruta», o una ruta local muntada) ----------
remote_is_ssh() { [[ "${CLUB_BACKUP_REMOTE}" == *:* ]]; }
remote_host() { echo "${CLUB_BACKUP_REMOTE%%:*}"; }
remote_path() { echo "${CLUB_BACKUP_REMOTE#*:}"; }
remote_ls() {
  if remote_is_ssh; then ssh -o BatchMode=yes "$(remote_host)" "ls -1 -- '$(remote_path)'" 2>/dev/null || true
  else ls -1 -- "$CLUB_BACKUP_REMOTE" 2>/dev/null || true; fi
}
remote_rm() {  # noms ja validats amb DUMP_RE: no hi ha caràcters especials
  local n
  for n in "$@"; do
    if remote_is_ssh; then ssh -o BatchMode=yes "$(remote_host)" "rm -f -- '$(remote_path)/$n' '$(remote_path)/$n.sha256' '$(remote_path)/$n.anchor'"
    else rm -f -- "$CLUB_BACKUP_REMOTE/$n" "$CLUB_BACKUP_REMOTE/$n.sha256" "$CLUB_BACKUP_REMOTE/$n.anchor"; fi
  done
}
remote_sha() {  # sha256 d'un fitxer remot
  if remote_is_ssh; then ssh -o BatchMode=yes "$(remote_host)" "sha256sum -- '$(remote_path)/$1'" | cut -d' ' -f1
  else sha256sum -- "$CLUB_BACKUP_REMOTE/$1" | cut -d' ' -f1; fi
}

# ---------- retenció per capes ----------
# stdin: noms club-AAAAMMDD-HHMMSS.dump.gpg. stdout: els que cal ESBORRAR.
# Es conserva la còpia més recent de cada un dels últims N dies, N setmanes ISO i N mesos (amb còpia).
retention_victims() {
  local names n d wk mo keep_this
  local -A seen_d=() seen_w=() seen_m=() keep=()
  mapfile -t names < <(grep -E "$DUMP_RE" | sort -r)
  for n in "${names[@]}"; do
    d="${n:5:8}"
    wk="$(date -d "$d" +%G-%V)"; mo="${d:0:6}"
    keep_this=0
    if [ -z "${seen_d[$d]:-}" ] && [ "${#seen_d[@]}" -lt "$KEEP_DAILY" ]; then seen_d[$d]=1; keep_this=1; fi
    if [ -z "${seen_w[$wk]:-}" ] && [ "${#seen_w[@]}" -lt "$KEEP_WEEKLY" ]; then seen_w[$wk]=1; keep_this=1; fi
    if [ -z "${seen_m[$mo]:-}" ] && [ "${#seen_m[@]}" -lt "$KEEP_MONTHLY" ]; then seen_m[$mo]=1; keep_this=1; fi
    [ "$keep_this" -eq 1 ] && keep[$n]=1
  done
  for n in "${names[@]}"; do [ -n "${keep[$n]:-}" ] || echo "$n"; done
}

# shellcheck disable=SC2012  # noms validats amb DUMP_RE
prune_local() {
  local v
  while read -r v; do [ -n "$v" ] && rm -f -- "$DEST/$v" "$DEST/$v.sha256" "$DEST/$v.anchor"; done < <(ls -1 "$DEST" | retention_victims)
}
prune_remote() {
  [ -n "${CLUB_BACKUP_REMOTE:-}" ] || return 0
  local victims
  mapfile -t victims < <(remote_ls | retention_victims)
  [ "${#victims[@]}" -gt 0 ] && remote_rm "${victims[@]}"
  return 0
}

# ---------- paquet de claus (a part del volcat, xifrat a una altra clau) ----------
make_keys_package() {
  : "${CLUB_BACKUP_KEYS_RECIPIENT:?Falta CLUB_BACKUP_KEYS_RECIPIENT (clau pública DIFERENT de la del volcat; vegeu docs/COPIES.md)}"
  [ "$CLUB_BACKUP_KEYS_RECIPIENT" != "${CLUB_BACKUP_GPG_RECIPIENT:-}" ] || die "CLUB_BACKUP_KEYS_RECIPIENT ha de ser diferent de CLUB_BACKUP_GPG_RECIPIENT: si no, una sola clau obre volcat i claus"
  gpg --batch --list-keys "$CLUB_BACKUP_KEYS_RECIPIENT" >/dev/null 2>&1 || die "la clau '$CLUB_BACKUP_KEYS_RECIPIENT' no és al clauer de GPG"
  [ -r "$KEYS_FILE" ] || die "no puc llegir $KEYS_FILE"
  local ts out
  ts="$(date +%Y%m%d-%H%M%S)"; out="$DEST/club-keys-$ts.keys.gpg"
  grep -E '^(CLUB_FIELD_KEY|CLUB_INDEX_KEY)=' "$KEYS_FILE" \
    | gpg --batch --yes --trust-model always -r "$CLUB_BACKUP_KEYS_RECIPIENT" ${CLUB_BACKUP_SIGNER:+-u "$CLUB_BACKUP_SIGNER" --sign} -e -o "$out.part"
  mv -- "$out.part" "$out"
  sha256sum "$out" | sed "s# .*/# #" > "$out.sha256"
  # el paquet de claus només es regenera si canvien: mantenim els 5 darrers
  # shellcheck disable=SC2012
  ls -1t "$DEST"/club-keys-*.keys.gpg | tail -n +6 | while read -r old; do rm -f -- "$old" "$old.sha256"; done
  if [ -n "${CLUB_BACKUP_KEYS_REMOTE:-${CLUB_BACKUP_REMOTE:-}}" ]; then
    rsync -a --chmod=F600 -e "ssh -o BatchMode=yes" "$out" "$out.sha256" "${CLUB_BACKUP_KEYS_REMOTE:-$CLUB_BACKUP_REMOTE}/"
  fi
  # L'empremta es desa NOMÉS aquí, quan el paquet ja és xifrat, mogut al seu lloc i (si cal) copiat: si make_keys_package
  # falla abans, la propera execució ho torna a intentar en lloc de creure que les claus ja estan guardades.
  keys_fingerprint > "$DEST/.keys.fingerprint"
  echo "Paquet de claus: $out"
}

keys_fingerprint() { grep -E '^(CLUB_FIELD_KEY|CLUB_INDEX_KEY)=' "$KEYS_FILE" | sha256sum | cut -d' ' -f1; }

keys_changed() {  # cert si les claus actuals no coincideixen amb l'última empremta registrada (no escriu res)
  local cur last="$DEST/.keys.fingerprint"
  cur="$(keys_fingerprint)"
  if [ -f "$last" ] && [ "$(cat "$last")" = "$cur" ] && ls "$DEST"/club-keys-*.keys.gpg >/dev/null 2>&1; then return 1; fi
  return 0
}

cmd_keys() { mkdir -p "$DEST"; make_keys_package; }

# Ancoratge de l'auditoria («seq:hash») desat al costat de la còpia i al remot: permet detectar que algú hagi retallat
# el final de la cadena. Si no es pot obtenir NO s'atura la còpia (ja és feta i verificada), però es avisa.
save_anchor() {
  local out="$1" anchor
  anchor="$(set -a; [ -r "$ENV_FILE" ] && . "$ENV_FILE"; set +a; cd "$REPO/backend" && "$PY" -m app.audit_cli ancora 2>/dev/null)" || anchor=""
  if ! [[ "$anchor" =~ ^[0-9]+:[0-9a-f]{64}$ ]]; then
    echo "AVÍS: no s'ha pogut obtenir l'ancoratge de l'auditoria (${anchor:-buit}); la còpia és vàlida igualment." >&2
    return 0
  fi
  echo "$anchor" > "$out.anchor"
  if [ -n "${CLUB_BACKUP_REMOTE:-}" ]; then
    rsync -a --chmod=F600 -e "ssh -o BatchMode=yes" "$out.anchor" "$CLUB_BACKUP_REMOTE/" || echo "AVÍS: l'ancoratge no s'ha pogut copiar al remot" >&2
  fi
  echo "Ancoratge d'auditoria: $anchor"
}

cmd_run() {
  : "${CLUB_BACKUP_GPG_RECIPIENT:?Falta CLUB_BACKUP_GPG_RECIPIENT (clau pública amb què es xifra el volcat)}"
  if [ -z "${CLUB_BACKUP_REMOTE:-}" ] && [ "${CLUB_BACKUP_ALLOW_LOCAL_ONLY:-0}" != "1" ]; then
    die "CLUB_BACKUP_REMOTE no definit. Una còpia només a la torre no serveix si la torre mor. Defineix-lo o, sabent-ho, CLUB_BACKUP_ALLOW_LOCAL_ONLY=1."
  fi
  gpg --batch --list-keys "$CLUB_BACKUP_GPG_RECIPIENT" >/dev/null 2>&1 || die "la clau pública '$CLUB_BACKUP_GPG_RECIPIENT' no és al clauer de GPG"
  if [ -n "${CLUB_BACKUP_SIGNER:-}" ]; then
    gpg --batch --list-secret-keys "$CLUB_BACKUP_SIGNER" >/dev/null 2>&1 || die "no trobo la clau de signatura '$CLUB_BACKUP_SIGNER' (clau secreta de la torre)"
  else
    [ "${CLUB_BACKUP_ALLOW_UNSIGNED:-0}" = "1" ] || die "Falta CLUB_BACKUP_SIGNER (clau de signatura de la torre). Sense signatura no es pot detectar una còpia substituïda."
  fi
  mkdir -p "$DEST"
  local creds pw user ts out
  creds="$(app_credentials)"; pw="$(sed -n 1p <<<"$creds")"; user="$(sed -n 2p <<<"$creds")"
  [ -n "$pw" ] || die "No trobo CLUB_APP_DATABASE_URL a $ENV_FILE"
  ts="$(date +%Y%m%d-%H%M%S)"; out="$DEST/club-$ts.dump.gpg"
  OUT_PART="$out.part"; trap 'rm -f -- "$OUT_PART"' EXIT
  # pg_dump -> gpg directament: el volcat mai toca el disc en clar. La contrasenya va per l'entorn (no surt a «ps»).
  PGPASSWORD="$pw" docker exec -e PGPASSWORD "$CONTAINER" pg_dump -U "$user" -d "$DBNAME" -Fc \
    | gpg --batch --yes --trust-model always -r "$CLUB_BACKUP_GPG_RECIPIENT" ${CLUB_BACKUP_SIGNER:+-u "$CLUB_BACKUP_SIGNER" --sign} -e -o "$out.part"
  [ "$(stat -c %s "$out.part")" -gt 1024 ] || die "El volcat xifrat és sospitosament petit"
  gpg --batch --list-packets "$out.part" >/dev/null 2>&1 || die "La còpia xifrada no és vàlida"
  mv -- "$out.part" "$out"
  ( cd "$DEST" && sha256sum "$(basename "$out")" > "$(basename "$out").sha256" )

  if keys_changed; then make_keys_package; fi
  prune_local

  if [ -n "${CLUB_BACKUP_REMOTE:-}" ]; then
    rsync -a --checksum --chmod=F600 -e "ssh -o BatchMode=yes" "$out" "$out.sha256" "$CLUB_BACKUP_REMOTE/"
    [ "$(remote_sha "$(basename "$out")")" = "$(cut -d' ' -f1 "$out.sha256")" ] || die "La còpia remota no coincideix amb la local"
    prune_remote
    echo "Copiat i verificat a $CLUB_BACKUP_REMOTE"
  else
    echo "AVÍS: només còpia local (CLUB_BACKUP_ALLOW_LOCAL_ONLY=1)." >&2
  fi
  save_anchor "$out"
  date +%s > "$DEST/.last-ok"
  echo "OK $out ($(stat -c %s "$out") bytes)"
}

cmd_restore_test() {
  local file="${1:?Cal el fitxer .dump.gpg}" work name port pw fpr_expected status
  [ -f "$file" ] || die "No existeix $file"
  [ -f "$file.sha256" ] || die "Falta $file.sha256 (obligatori)"
  fpr_expected="$(tr -d ' ' <<<"${CLUB_BACKUP_SIGNER_FPR:?Falta CLUB_BACKUP_SIGNER_FPR (empremta esperada de la clau de signatura de la torre)}" | tr a-f A-F)"
  ( cd "$(dirname "$file")" && sha256sum -c "$(basename "$file").sha256" >/dev/null ) || die "El hash no coincideix: còpia alterada o corrompuda"
  work="$(mktemp -d)"; status="$work/status"; name="club-restore-test-$$"; pw="$(head -c 18 /dev/urandom | base64 | tr -d '/+=')"
  trap 'docker rm -f "'"$name"'" >/dev/null 2>&1 || true; rm -rf -- "'"$work"'"' EXIT
  docker run -d --rm --name "$name" -e POSTGRES_PASSWORD="$pw" -e POSTGRES_DB=restore -p 127.0.0.1::5432 "$RESTORE_IMAGE" >/dev/null
  for _ in $(seq 1 40); do docker exec "$name" pg_isready -U postgres -d restore >/dev/null 2>&1 && break; sleep 1; done
  # 1) La signatura es comprova ABANS de passar res a pg_restore: una primera passada desxifra i descarta el contingut
  #    (cap fitxer en clar) només per obtenir l'estat de GPG; una còpia no signada per la clau esperada no arriba mai a la BD.
  gpg --batch --status-fd 3 --decrypt "$file" 3>"$status" >/dev/null 2>&1 \
    || die "No s'ha pogut desxifrar (falta la clau privada? signatura incorrecta?)"
  grep -q '^\[GNUPG:\] GOODSIG ' "$status" || die "La còpia no porta una signatura vàlida"
  # VALIDSIG: camp 3 = empremta del (sub)clau; camp 12 = empremta de la clau primària
  awk '$2=="VALIDSIG"{print toupper($3); print toupper($12)}' "$status" | grep -qx "$fpr_expected" \
    || die "La signatura NO és de la clau esperada ($fpr_expected): còpia substituïda o clau equivocada"
  echo "Signatura i hash verificats."
  # 2) Només ara es restaura: desxifrat -> pg_restore per tubería, cap fitxer en clar
  gpg --batch --decrypt "$file" 2>/dev/null \
    | docker exec -i "$name" pg_restore -U postgres -d restore --no-owner --no-privileges --exit-on-error \
    || die "No s'ha pogut restaurar la còpia"
  port="$(docker port "$name" 5432/tcp | head -1 | sed 's/.*://')"
  "$PY" -I - "postgresql+psycopg://postgres:$pw@127.0.0.1:$port/restore" "$REPO/backend" <<'PYEOF'
import sys
sys.path.insert(0, sys.argv[2])
from sqlalchemy import create_engine, select, func
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

cmd_prune() { prune_local; prune_remote; echo "Retenció aplicada."; }

case "${1:-}" in
  run) cmd_run ;;
  keys) cmd_keys ;;
  prune) cmd_prune ;;
  restore-test) shift; cmd_restore_test "$@" ;;
  *) sed -n '2,7p' "$0"; exit 2 ;;
esac

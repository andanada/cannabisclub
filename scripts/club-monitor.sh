#!/usr/bin/env bash
# Monitoratge del club. Pensat per a un temporitzador cada 15 minuts.
#   club-monitor.sh check            /salut, espai en disc, edat de l'última còpia i caducitat del certificat
#   club-monitor.sh alert <missatge> envia una alerta ara (l'usa OnFailure= de systemd)
#   club-monitor.sh test             envia una alerta de prova per comprovar CLUB_ALERT_CMD
# Notificació: CLUB_ALERT_CMD és una ordre de shell; rep el missatge a l'entrada estàndard i a $CLUB_ALERT_MESSAGE. Exemples:
#   CLUB_ALERT_CMD='mail -s "club: alerta" admin@exemple.cat'
#   CLUB_ALERT_CMD='curl -fsS --max-time 15 -d chat_id=XXXX --data-urlencode "text=$CLUB_ALERT_MESSAGE" https://api.telegram.org/botTOKEN/sendMessage'
#   (el token de Telegram va al fitxer d'entorn amb permisos 600, no a git)
# Només alerta en canviar d'estat i la repeteix cada CLUB_ALERT_REPEAT_MIN minuts (360) mentre duri el problema.
set -uo pipefail
umask 077

DEST="${CLUB_BACKUP_DIR:-/data/backups/club}"
HEALTH_URL="${CLUB_HEALTH_URL:-http://127.0.0.1:8099/salut}"
DISK_PATHS="${CLUB_DISK_PATHS:-/ $DEST}"
DISK_MAX_PCT="${CLUB_DISK_MAX_PCT:-85}"
BACKUP_MAX_AGE_H="${CLUB_BACKUP_MAX_AGE_H:-26}"
CERT_HOST="${CLUB_CERT_HOST:-}"        # host:port (p.ex. club.exemple.cat:443), o bé
CERT_FILE="${CLUB_CERT_FILE:-}"        # ruta al .pem
CERT_MIN_DAYS="${CLUB_CERT_MIN_DAYS:-14}"
REPEAT_MIN="${CLUB_ALERT_REPEAT_MIN:-360}"
STATE_DIR="${CLUB_MONITOR_STATE_DIR:-${XDG_STATE_HOME:-$HOME/.local/state}/club-monitor}"
mkdir -p "$STATE_DIR"

send() {  # send <missatge>
  local msg="$1"
  if [ -z "${CLUB_ALERT_CMD:-}" ]; then echo "ALERTA (sense CLUB_ALERT_CMD): $msg" >&2; return 1; fi
  CLUB_ALERT_MESSAGE="$msg" bash -c "$CLUB_ALERT_CMD" <<<"$msg" || { echo "ALERTA: ha fallat CLUB_ALERT_CMD" >&2; return 1; }
}

# report <clau> <ok|fail> <missatge>
report() {
  local key="$1" status="$2" msg="$3" f="$STATE_DIR/$1" now age
  now="$(date +%s)"
  if [ "$status" = fail ]; then
    echo "FALLA [$key]: $msg"
    if [ ! -f "$f" ]; then send "[club ${HOSTNAME:-host}] $msg" && echo "$now" > "$f"
    else
      age=$(( (now - $(cat "$f")) / 60 ))
      if [ "$age" -ge "$REPEAT_MIN" ]; then send "[club ${HOSTNAME:-host}] (continua) $msg" && echo "$now" > "$f"; fi
    fi
    FAILED=1
  elif [ -f "$f" ]; then
    rm -f -- "$f"; send "[club ${HOSTNAME:-host}] recuperat: $key"
  fi
}

check_health() {
  if curl -fsS --max-time 10 -o /dev/null "$HEALTH_URL" 2>/dev/null; then report salut ok ""
  else report salut fail "El servei no respon a $HEALTH_URL (o la base de dades està caiguda)"; fi
}

check_disk() {
  local p pct bad=""
  for p in $DISK_PATHS; do
    [ -d "$p" ] || continue
    pct="$(df --output=pcent "$p" | tail -1 | tr -dc '0-9')"
    [ -n "$pct" ] && [ "$pct" -ge "$DISK_MAX_PCT" ] && bad="$bad $p=${pct}%"
  done
  if [ -z "$bad" ]; then report disc ok ""; else report disc fail "Disc ple (límit ${DISK_MAX_PCT}%):$bad"; fi
}

check_backup_age() {
  local f="$DEST/.last-ok" now age_h
  now="$(date +%s)"
  if [ ! -f "$f" ]; then report copia fail "No hi ha constància de cap còpia correcta a $DEST"; return; fi
  age_h=$(( (now - $(cat "$f")) / 3600 ))
  if [ "$age_h" -gt "$BACKUP_MAX_AGE_H" ]; then report copia fail "L'última còpia correcta fa ${age_h} h (límit ${BACKUP_MAX_AGE_H} h)"
  else report copia ok ""; fi
}

check_cert() {
  local end="" end_ts days
  [ -n "$CERT_HOST" ] || [ -n "$CERT_FILE" ] || return 0
  if [ -n "$CERT_FILE" ]; then end="$(openssl x509 -enddate -noout -in "$CERT_FILE" 2>/dev/null | cut -d= -f2)"
  else end="$(echo | openssl s_client -servername "${CERT_HOST%%:*}" -connect "$CERT_HOST" 2>/dev/null | openssl x509 -noout -enddate 2>/dev/null | cut -d= -f2)"; fi
  end_ts="$(date -d "$end" +%s 2>/dev/null || true)"
  if [ -z "$end_ts" ]; then report certificat fail "No puc llegir la caducitat del certificat (${CERT_FILE:-$CERT_HOST})"; return; fi
  days=$(( (end_ts - $(date +%s)) / 86400 ))
  if [ "$days" -lt "$CERT_MIN_DAYS" ]; then report certificat fail "El certificat caduca en $days dies"; else report certificat ok ""; fi
}

FAILED=0
case "${1:-}" in
  check) check_health; check_disk; check_backup_age; check_cert; exit "$FAILED" ;;
  alert) shift; send "[club ${HOSTNAME:-host}] ${*:-alerta sense text}" ;;
  test) send "[club ${HOSTNAME:-host}] prova d'alerta correcta" && echo "Enviada." ;;
  *) sed -n '2,5p' "$0"; exit 2 ;;
esac

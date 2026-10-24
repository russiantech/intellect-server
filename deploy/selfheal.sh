#!/usr/bin/env bash
# deploy/selfheal.sh - external watchdog for Intellect API (cPanel / Passenger or Supervisor)
# Run every minute from cron. Safe to run concurrently (flock), never loops forever,
# backs off after repeated failures, rotates its own log.
set -u

APP_DIR="${APP_DIR:-$HOME/intellect-api.salesnet.ng}"
HEALTH_URL="${HEALTH_URL:-https://intellect-api.salesnet.ng/health}"
MODE="${MODE:-auto}"                      # auto | passenger | supervisor
SUP_PROGRAM="${SUP_PROGRAM:-intellect-api}"
SUP_CTL="${SUP_CTL:-$HOME/virtualenv/intellect-api.salesnet.ng/3.13/bin/supervisorctl}"
SUP_CONF="${SUP_CONF:-$HOME/supervisor/supervisord.conf}"
SUP_D="${SUP_D:-$HOME/virtualenv/intellect-api.salesnet.ng/3.13/bin/supervisord}"
STATE_DIR="$APP_DIR/logs/selfheal"
LOG="$STATE_DIR/selfheal.log"
FAILS_FILE="$STATE_DIR/fails"
LAST_RESTART="$STATE_DIR/last_restart"
FAIL_THRESHOLD=2            # consecutive failed checks before acting
COOLDOWN=60                 # min seconds between restarts
MAX_LOG_BYTES=5242880

mkdir -p "$STATE_DIR" "$APP_DIR/tmp"
exec 9>"$STATE_DIR/lock"; flock -n 9 || exit 0

ts()  { date '+%Y-%m-%d %H:%M:%S'; }
log() { echo "$(ts) | $*" >> "$LOG"; }
[ -f "$LOG" ] && [ "$(stat -c%s "$LOG" 2>/dev/null || echo 0)" -gt "$MAX_LOG_BYTES" ] && mv -f "$LOG" "$LOG.1"

healthy() {
  local code
  code=$(curl -s -o /dev/null -m 15 -w '%{http_code}' "$HEALTH_URL" 2>/dev/null || echo 000)
  [ "$code" = "200" ]
}

detect_mode() {
  if [ "$MODE" != "auto" ]; then echo "$MODE"; return; fi
  if [ -x "$SUP_CTL" ] && [ -S "$HOME/supervisor/supervisor.sock" ]; then echo supervisor; else echo passenger; fi
}

restart_app() {
  local now last; now=$(date +%s); last=$(cat "$LAST_RESTART" 2>/dev/null || echo 0)
  if [ $((now-last)) -lt $COOLDOWN ]; then log "cooldown active, skip restart"; return; fi
  echo "$now" > "$LAST_RESTART"
  case "$(detect_mode)" in
    supervisor)
      if ! "$SUP_CTL" -c "$SUP_CONF" status >/dev/null 2>&1; then
        log "supervisord down -> starting it"; "$SUP_D" -c "$SUP_CONF" >> "$LOG" 2>&1
        sleep 3
      fi
      "$SUP_CTL" -c "$SUP_CONF" restart "$SUP_PROGRAM" >> "$LOG" 2>&1 \
        || "$SUP_CTL" -c "$SUP_CONF" start "$SUP_PROGRAM" >> "$LOG" 2>&1
      log "supervisor restart issued";;
    passenger)
      touch "$APP_DIR/tmp/restart.txt"
      log "passenger restart issued (tmp/restart.txt touched)";;
  esac
}

if healthy; then
  [ "$(cat "$FAILS_FILE" 2>/dev/null || echo 0)" != "0" ] && log "recovered"
  echo 0 > "$FAILS_FILE"; exit 0
fi

fails=$(( $(cat "$FAILS_FILE" 2>/dev/null || echo 0) + 1 )); echo "$fails" > "$FAILS_FILE"
log "health check failed ($fails/$FAIL_THRESHOLD)"
if [ "$fails" -ge "$FAIL_THRESHOLD" ]; then
  restart_app
  sleep 20
  if healthy; then log "healthy after restart"; echo 0 > "$FAILS_FILE"
  else log "STILL DOWN after restart (will retry next cycle)"; fi
fi

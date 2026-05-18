#!/usr/bin/env bash
# deploy/monitor.sh — Belt-and-suspenders health monitor.
# Cron: */5 * * * * bash /home/USER/DOMAIN/deploy/monitor.sh
set -euo pipefail

source "$(dirname "$0")/_lib.sh"

MONITOR_LOG="${SUPERVISOR_DIR}/logs/monitor.log"
HEALTH_URL="http://localhost:${PORT}${HEALTH_PATH}"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" >> "$MONITOR_LOG"; }

# ─────────────────────────────────────────────────────────────────
# Rotate monitor log if > 1000 lines
rotate_log() {
    if [[ -f "$MONITOR_LOG" ]]; then
        local lines
        lines=$(wc -l < "$MONITOR_LOG")
        if (( lines > 1000 )); then
            tail -n 500 "$MONITOR_LOG" > "${MONITOR_LOG}.tmp"
            mv "${MONITOR_LOG}.tmp" "$MONITOR_LOG"
        fi
    fi
}

# ─────────────────────────────────────────────────────────────────
main() {
    rotate_log

    # 1. Ensure supervisor daemon is alive
    if ! supervisor_running; then
        log "ERROR: supervisord not running — starting…"
        bash "${DEPLOY_DIR}/control.sh" start >> "$MONITOR_LOG" 2>&1
        sleep 3
    fi

    # 2. Check app process state via supervisor
    local status
    status=$($SUPERVISORCTL status "${APP_NAME}" 2>&1 || true)
    if ! echo "$status" | grep -q "RUNNING"; then
        log "ERROR: ${APP_NAME} not RUNNING ($status) — restarting…"
        bash "${DEPLOY_DIR}/control.sh" restart >> "$MONITOR_LOG" 2>&1
        return 0
    fi

    # 3. HTTP health check
    if ! health_ok; then
        log "ERROR: HTTP health check failed (${HEALTH_URL}) — restarting…"
        bash "${DEPLOY_DIR}/control.sh" restart >> "$MONITOR_LOG" 2>&1
        return 0
    fi

    # All good — silent success
}

main

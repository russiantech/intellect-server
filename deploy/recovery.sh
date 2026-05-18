#!/usr/bin/env bash
# deploy/recovery.sh — Emergency recovery (can run standalone).
set -euo pipefail

source "$(dirname "$0")/_lib.sh" 2>/dev/null || {
    echo "WARNING: _lib.sh not found — using hardcoded fallback" >&2
    APP_DIR="/home/salesne2/intellect-api.salesnet.ng"
    DEPLOY_DIR="${APP_DIR}/deploy"
    CONTROL="${DEPLOY_DIR}/control.sh"
    LOG_FILE="${DEPLOY_DIR}/recovery.log"
    PORT=8001
    HEALTH_PATH="/health"
}

LOG_FILE="${DEPLOY_DIR}/recovery.log"
mkdir -p "$(dirname "$LOG_FILE")"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" >> "$LOG_FILE"; }

# ─────────────────────────────────────────────────────────────────
main() {
    if ! curl -sf --max-time 5 "http://localhost:${PORT}${HEALTH_PATH}" >/dev/null 2>&1; then
        log "App not responding — attempting recovery…"

        # Graceful restart
        bash "${DEPLOY_DIR}/control.sh" restart >> "$LOG_FILE" 2>&1
        sleep 5

        # If still dead, nuke from orbit
        if ! curl -sf --max-time 5 "http://localhost:${PORT}${HEALTH_PATH}" >/dev/null 2>&1; then
            log "Graceful restart failed — hard reset…"
            bash "${DEPLOY_DIR}/control.sh" kill   >> "$LOG_FILE" 2>&1
            sleep 2
            bash "${DEPLOY_DIR}/control.sh" start  >> "$LOG_FILE" 2>&1
        fi

        log "Recovery attempt complete"
    fi
}

main

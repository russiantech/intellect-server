#!/usr/bin/env bash
# deploy/control.sh — SINGLE SOURCE OF TRUTH for process management.
# Usage: bash deploy/control.sh <command>
set -euo pipefail

source "$(dirname "$0")/_lib.sh"

# ─────────────────────────────────────────────────────────────────
usage() {
    echo -e "${W}Usage:${N} bash deploy/control.sh <command>"
    echo ""
    echo -e "${C}App Lifecycle${N}"
    echo "  start        Start app (and supervisord if needed)"
    echo "  stop         Stop app gracefully"
    echo "  restart      FULL cold restart — kills master, loads new code from disk"
    echo "  graceful     Zero-downtime — same code, new workers only (SIGHUP)"
    echo "  status       Show supervisor + process + port status"
    echo ""
    echo -e "${C}Observability${N}"
    echo "  logs         Tail app stdout log"
    echo "  logs-err     Tail app stderr log"
    echo "  logs-sup     Tail supervisord log"
    echo "  health       Full health check (process + HTTP + cron)"
    echo ""
    echo -e "${C}Supervisor${N}"
    echo "  reload       Reread + update supervisor config"
    echo "  kill         Shutdown supervisord and all managed processes"
    echo ""
    echo -e "${C}Dev${N}"
    echo "  shell        Drop into venv shell in app dir"
    echo "  workers      Show live worker processes + memory"
}

# ── LIFECYCLE ────────────────────────────────────────────────────

cmd_start() {
    ensure_supervisor
    info "Starting ${APP_NAME}…"
    $SUPERVISORCTL start "${APP_NAME}"
    sleep 1
    $SUPERVISORCTL status "${APP_NAME}"
}

cmd_stop() {
    info "Stopping ${APP_NAME}…"
    $SUPERVISORCTL stop "${APP_NAME}"
    success "Stopped"
}

# COLD RESTART: kills gunicorn master + workers, starts fresh from disk.
# This is the ONLY restart path that guarantees new code is loaded.
# Use after: git pull, code edits, dependency changes, new endpoints.
cmd_restart() {
    section "Restarting ${APP_NAME} — COLD restart (new master, new code from disk)"

    # 1. Stop via supervisor (clean signal to workers)
    info "Stopping supervisor-managed app…"
    $SUPERVISORCTL stop "${APP_NAME}" 2>/dev/null || true
    sleep 1

    # 2. Hard-kill any lingering gunicorn/uvicorn processes
    #    (prevents stale preload_app master from surviving)
    info "Killing lingering processes…"
    pkill -9 -f "gunicorn.*${APP_NAME}" 2>/dev/null || true
    pkill -9 -f "uvicorn.*${APP_NAME}" 2>/dev/null || true
    sleep 2

    # 3. Ensure supervisor is alive
    ensure_supervisor

    # 4. Start fresh — loads current code from disk
    info "Starting fresh app…"
    $SUPERVISORCTL start "${APP_NAME}"
    sleep 3

    # 5. Verify
    $SUPERVISORCTL status "${APP_NAME}"

    if health_ok; then
        success "App healthy on port ${PORT}"
    else
        warn "App started but health check failed — check logs"
    fi
}

# GRACEFUL: SIGHUP reload. Same master, same code, new workers.
# Use ONLY for: memory cleanup, worker refresh. NEVER for code deploys.
cmd_graceful() {
    section "Graceful reload ${APP_NAME} — same code, new workers"
    ensure_supervisor
    local gpid
    gpid=$($SUPERVISORCTL pid "${APP_NAME}" 2>/dev/null || echo "")
    if [[ -n "$gpid" && "$gpid" =~ ^[0-9]+$ ]]; then
        kill -HUP "$gpid" 2>/dev/null && success "Graceful reload triggered" && return 0
    fi
    warn "No gunicorn master PID — falling back to cold restart…"
    cmd_restart
}

cmd_status() {
    section "Supervisor status"
    $SUPERVISORCTL status "${APP_NAME}"

    echo ""
    section "Port ${PORT}"
    ss -tlnp "sport = :${PORT}" 2>/dev/null \
        || netstat -tlnp 2>/dev/null | grep ":${PORT}" \
        || warn "Nothing on port ${PORT}"

    echo ""
    section "Gunicorn master"
    local mpid
    mpid=$($SUPERVISORCTL pid "${APP_NAME}" 2>/dev/null || echo "")
    if [[ -n "$mpid" && "$mpid" =~ ^[0-9]+$ ]]; then
        ps -o pid,ppid,rss,vsz,pcpu,pmem,stat,args --pid "$mpid" 2>/dev/null \
            | awk 'NR==1{print} NR>1{printf "  %-8s %-8s %5s MB  %5s%%  %s\n", $1,$2,$3/1024,$6,$8}'
    else
        warn "No master PID from supervisor"
    fi
}

# ── OBSERVABILITY ────────────────────────────────────────────────

cmd_logs()     { tail -f "${LOG_DIR}/app.log"; }
cmd_logs_err() { tail -f "${LOG_DIR}/app.error.log"; }
cmd_logs_sup() { tail -f "${SUPERVISOR_DIR}/logs/supervisord.log"; }

cmd_health() {
    section "Health check — ${APP_NAME}"

    if app_running; then
        success "Supervisor: RUNNING"
        $SUPERVISORCTL status "${APP_NAME}"
    else
        error "Supervisor: NOT RUNNING"
    fi

    echo ""
    if health_ok; then
        success "HTTP ${HEALTH_PATH}: OK  (http://localhost:${PORT}${HEALTH_PATH})"
    else
        error "HTTP ${HEALTH_PATH}: UNREACHABLE"
    fi

    echo ""
    if crontab -l 2>/dev/null | grep -q "supervisord -c ${SUPERVISOR_DIR}"; then
        success "Cron: reboot auto-start configured"
    else
        warn "Cron: no reboot auto-start found"
    fi

    echo ""
    section "Last 5 errors"
    grep -iE "error|critical|exception" "${LOG_DIR}/app.log" 2>/dev/null \
        | tail -5 || echo "  (none)"
}

# ── SUPERVISOR CONFIG ────────────────────────────────────────────

cmd_reload() {
    section "Reloading supervisor config"
    $SUPERVISORCTL reread
    $SUPERVISORCTL update
    success "Config reloaded — run 'restart' to apply worker changes"
}

cmd_kill() {
    warn "Shutting down supervisord and all managed processes…"
    $SUPERVISORCTL shutdown || true
    success "Supervisord stopped"
}

# ── DEV ──────────────────────────────────────────────────────────

cmd_shell() {
    info "Opening venv shell in ${APP_DIR}"
    cd "${APP_DIR}"
    exec bash --rcfile <(echo "source ${VENV_PATH}/bin/activate; PS1='(${APP_NAME}) \\u@\\h:\\w\\$ '")
}

cmd_workers() {
    section "Gunicorn workers"
    local master_pid
    master_pid=$($SUPERVISORCTL pid "${APP_NAME}" 2>/dev/null || echo "")

    if [[ -z "$master_pid" || ! "$master_pid" =~ ^[0-9]+$ ]]; then
        warn "No master process found via supervisor"
        return 1
    fi

    local pids
    pids=$(ps -o pid --ppid="$master_pid" --no-headers 2>/dev/null | tr '\n' ',' | sed 's/,$//')
    
    if [[ -z "$pids" ]]; then
        warn "No worker processes found"
        return 1
    fi

    ps -o pid,ppid,rss,vsz,pcpu,pmem,stat,args \
        --pid "$master_pid" --pid "$pids" \
        2>/dev/null \
        | awk 'NR==1{print} NR>1{$7=""; printf "  %-8s %-8s %5s MB  %5s%%  %s\n", $1,$2,$3/1024,$6,$8}' \
        || warn "Could not read worker info"
}

# ── ROUTER ───────────────────────────────────────────────────────
case "${1:-}" in
    start)     cmd_start ;;
    stop)      cmd_stop ;;
    restart)   cmd_restart ;;      # COLD restart — loads new code from disk
    graceful)  cmd_graceful ;;    # SIGHUP — same code, new workers only
    status)    cmd_status ;;
    logs)      cmd_logs ;;
    logs-err)  cmd_logs_err ;;
    logs-sup)  cmd_logs_sup ;;
    health)    cmd_health ;;
    reload)    cmd_reload ;;
    kill)      cmd_kill ;;
    shell)     cmd_shell ;;
    workers)   cmd_workers ;;
    *)         usage; exit 1 ;;
esac


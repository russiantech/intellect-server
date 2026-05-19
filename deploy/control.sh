#!/usr/bin/env bash
# deploy/control.sh — App management interface.
# Usage: bash deploy/control.sh <command>
set -euo pipefail

source "$(dirname "$0")/_lib.sh"

# ─────────────────────────────────────────────────────────────────
usage() {
    echo -e "${W}Usage:${N} bash deploy/control.sh <command>"
    echo ""
    echo -e "${C}App${N}"
    echo "  start        Start app (and supervisord if needed)"
    echo "  stop         Stop app gracefully"
    echo "  restart      Zero-downtime restart"
    echo "  status       Show supervisor + process status"
    echo ""
    echo -e "${C}Observability${N}"
    echo "  logs         Tail app stdout log"
    echo "  logs-err     Tail app stderr log"
    echo "  logs-sup     Tail supervisord log"
    echo "  health       Full health check (process + HTTP)"
    echo ""
    echo -e "${C}Supervisor${N}"
    echo "  reload       Reread + update supervisor config"
    echo "  kill         Shutdown supervisord (and app)"
    echo ""
    echo -e "${C}Dev${N}"
    echo "  shell        Drop into venv shell in app dir"
    echo "  workers      Show live worker processes + memory"
}

# ─────────────────────────────────────────────────────────────────
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

cmd_restart() {
    # Gunicorn SIGHUP = reload workers without dropping connections
    section "Restarting ${APP_NAME}"
    ensure_supervisor

    local pid_file="${SUPERVISOR_DIR}/supervisord.pid"
    if supervisor_running && app_running; then
        info "Sending HUP to gunicorn master (graceful reload)…"
        local gpid
        gpid=$($SUPERVISORCTL pid "${APP_NAME}" 2>/dev/null || echo "")
        if [[ -n "$gpid" && "$gpid" =~ ^[0-9]+$ ]]; then
            kill -HUP "$gpid" 2>/dev/null && success "Graceful reload triggered" && return 0
        fi
    fi

    # Fallback: supervisor restart
    info "Falling back to supervisor restart…"
    $SUPERVISORCTL restart "${APP_NAME}"
    sleep 2
    $SUPERVISORCTL status "${APP_NAME}"
}

cmd_status() {
    section "Supervisor status"
    $SUPERVISORCTL status "${APP_NAME}"

    echo ""
    section "Process tree"
    pgrep -a -f "gunicorn.*${APP_NAME}" 2>/dev/null \
        | awk '{printf "  PID %-7s  %s\n", $1, substr($0, index($0,$2))}' \
        || warn "No gunicorn processes found"

    echo ""
    section "Port ${PORT}"
    ss -tlnp "sport = :${PORT}" 2>/dev/null || netstat -tlnp 2>/dev/null | grep ":${PORT}" || warn "Nothing on port ${PORT}"
}

cmd_logs()     { tail -f "${LOG_DIR}/app.log"; }
cmd_logs_err() { tail -f "${LOG_DIR}/app.error.log"; }
cmd_logs_sup() { tail -f "${SUPERVISOR_DIR}/logs/supervisord.log"; }

cmd_health() {
    section "Health check — ${APP_NAME}"

    # Supervisor
    if app_running; then
        success "Supervisor: RUNNING"
        $SUPERVISORCTL status "${APP_NAME}"
    else
        error "Supervisor: NOT RUNNING"
    fi

    # HTTP health endpoint
    echo ""
    if health_ok; then
        success "HTTP ${HEALTH_PATH}: OK  (http://localhost:${PORT}${HEALTH_PATH})"
    else
        error "HTTP ${HEALTH_PATH}: UNREACHABLE"
    fi

    # Cron
    echo ""
    if crontab -l 2>/dev/null | grep -q "supervisord -c ${SUPERVISOR_DIR}"; then
        success "Cron: reboot auto-start configured"
    else
        warn "Cron: no reboot auto-start found"
    fi

    # Recent errors
    echo ""
    section "Last 5 errors"
    grep -iE "error|critical|exception" "${LOG_DIR}/app.log" 2>/dev/null \
        | tail -5 || echo "  (none)"
}

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

cmd_shell() {
    info "Opening venv shell in ${APP_DIR}"
    cd "${APP_DIR}"
    exec bash --rcfile <(echo "source ${VENV_PATH}/bin/activate; PS1='(${APP_NAME}) \u@\h:\w\$ '")
}

# cmd_workers() {
#     section "Gunicorn workers"
#     ps -o pid,ppid,rss,vsz,pcpu,pmem,stat,args \
#         --pid "$(pgrep -d',' -f "gunicorn.*${APP_NAME}" 2>/dev/null || echo 0)" \
#         2>/dev/null \
#         | awk 'NR==1{print} NR>1{$7=""; printf "  %-8s %-8s %5s MB  %5s%%  %s\n", $1,$2,$3/1024,$6,$8}' \
#         || warn "No workers found"
# }

# 2
cmd_workers() {
    section "Gunicorn workers"

    ps -eo pid,ppid,rss,pcpu,stat,args \
        | grep -E "gunicorn|uvicorn" \
        | grep -v grep \
        | awk '{
            printf "  PID %-7s PPID %-7s RSS %-8s KB CPU %-5s%% %s\n",
            $1, $2, $3, $4, substr($0, index($0,$6))
        }'

    if ! ps -eo args | grep -q "gunicorn\|uvicorn"; then
        warn "No workers found"
    fi
}

# ─────────────────────────────────────────────────────────────────
case "${1:-}" in
    start)     cmd_start ;;
    stop)      cmd_stop ;;
    restart)   cmd_restart ;;
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

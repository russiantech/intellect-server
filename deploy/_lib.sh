#!/usr/bin/env bash
# deploy/_lib.sh — Shared helpers. Source this; never run it directly.
# Usage: source "$(dirname "${BASH_SOURCE[0]}")/_lib.sh"

# v1
[[ "${BASH_SOURCE[0]}" == "${0}" ]] && echo "Source this file, don't execute it." && exit 1

DEPLOY_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# APP_ROOT="$(dirname "$DEPLOY_DIR")"
APP_ROOT="$(cd "$DEPLOY_DIR/.." && pwd)"

source "${DEPLOY_DIR}/config.env"

# ── Derived Paths ─────────────────────────────────────────────────
APP_DIR="/home/${CPANEL_USER}/${DOMAIN}"
VENV_PATH="/home/${CPANEL_USER}/virtualenv/${DOMAIN}/${PYTHON_VERSION}"
VENV_BIN="${VENV_PATH}/bin"
SUPERVISOR_DIR="${HOME}/supervisor"
LOG_DIR="${APP_DIR}/logs"
GUNICORN_CONF="${DEPLOY_DIR}/gunicorn.conf.py"

# Supervisor program name — dots not allowed
APP_NAME="${DOMAIN//./-}"

SUPERVISORCTL="${VENV_BIN}/supervisorctl -c ${SUPERVISOR_DIR}/supervisord.conf"
SUPERVISORD="${VENV_BIN}/supervisord -c ${SUPERVISOR_DIR}/supervisord.conf"
GUNICORN="${VENV_BIN}/gunicorn"

# ── Resolve Worker Count ──────────────────────────────────────────
if [[ "${WORKERS}" == "auto" ]]; then
    _cpu=$(nproc 2>/dev/null || sysctl -n hw.ncpu 2>/dev/null || echo 1)
    RESOLVED_WORKERS=$(( _cpu * 2 + 1 ))
    (( RESOLVED_WORKERS > 4 )) && RESOLVED_WORKERS=4
else
    RESOLVED_WORKERS="${WORKERS}"
fi

# ── Terminal Colors ───────────────────────────────────────────────
R='\033[0;31m' G='\033[0;32m' Y='\033[1;33m'
B='\033[0;34m' C='\033[0;36m' W='\033[1m'   N='\033[0m'

info()    { echo -e "${B}  →${N}  $*"; }
success() { echo -e "${G}  ✓${N}  $*"; }
warn()    { echo -e "${Y}  !${N}  $*"; }
error()   { echo -e "${R}  ✗${N}  $*" >&2; }
section() { echo -e "\n${W}${C}▸ $*${N}"; }
hr()      { echo -e "${C}$(printf '─%.0s' {1..58})${N}"; }
die()     { error "$*"; exit 1; }

# ── Supervisor Helpers ────────────────────────────────────────────
supervisor_running() {
    local pid="${SUPERVISOR_DIR}/supervisord.pid"
    [[ -f "$pid" ]] && kill -0 "$(cat "$pid")" 2>/dev/null
}

ensure_supervisor() {
    supervisor_running && return 0

    local pid_file="${SUPERVISOR_DIR}/supervisord.pid"
    local sock_file="${SUPERVISOR_DIR}/supervisor.sock"

    [[ -f "$pid_file" ]] && rm -f "$pid_file" && warn "Removed stale PID file"
    [[ -S "$sock_file" ]] && rm -f "$sock_file" && warn "Removed stale socket"

    info "Starting supervisord..."
    $SUPERVISORD || die "supervisord failed — check ${SUPERVISOR_DIR}/logs/supervisord.log"

    for i in {1..10}; do
        $SUPERVISORCTL status &>/dev/null && success "Supervisord ready" && return 0
        sleep 1
    done

    die "Supervisord did not become ready within 10s"
}

app_running() {
    $SUPERVISORCTL status "${APP_NAME}" 2>/dev/null | grep -q "RUNNING"
}

health_ok() {
    curl -sf --max-time 5 "http://localhost:${PORT}${HEALTH_PATH}" >/dev/null 2>&1
}

require_cmd() {
    command -v "$1" &>/dev/null || die "Required command not found: $1"
}

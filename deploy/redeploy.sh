#!/usr/bin/env bash
# deploy/redeploy.sh — Emergency hard redeploy.
# Use when control.sh restart isn't enough or for manual recovery.
set -euo pipefail

source "$(dirname "$0")/_lib.sh"

cd "${APP_DIR}"

section "Emergency redeploy — ${DOMAIN}"

# 1. Inspect current state
info "Current status:"
bash "${DEPLOY_DIR}/control.sh" status || true
echo ""
ps aux | grep -E "gunicorn|uvicorn" | grep -v grep || true
echo ""

# 2. Nuke everything — supervisor, gunicorn master, uvicorn, anything lingering
warn "Killing all app processes…"
bash "${DEPLOY_DIR}/control.sh" kill 2>/dev/null || true
pkill -9 -f "gunicorn.*${APP_NAME}" 2>/dev/null || true
pkill -9 -f "uvicorn.*${APP_NAME}" 2>/dev/null || true
sleep 2

# 3. Clean up stale PID/socket files
[[ -f "${SUPERVISOR_DIR}/supervisord.pid" ]] && rm -f "${SUPERVISOR_DIR}/supervisord.pid"
[[ -S "${SUPERVISOR_DIR}/supervisor.sock" ]] && rm -f "${SUPERVISOR_DIR}/supervisor.sock"

# 4. Start fresh — loads current code from disk
info "Starting fresh…"
bash "${DEPLOY_DIR}/control.sh" start

sleep 3

# 5. Verify
section "Verification"
bash "${DEPLOY_DIR}/control.sh" status
bash "${DEPLOY_DIR}/control.sh" workers

# 6. HTTP smoke tests
info "Smoke tests:"
curl -sf --max-time 5 "http://localhost:${PORT}${HEALTH_PATH}" && success "Health OK" || warn "Health failed"
curl -sf --max-time 5 "http://localhost:${PORT}/docs" >/dev/null && success "Docs OK" || warn "Docs failed"
curl -sf --max-time 5 "http://localhost:${PORT}/api/v1/courses" >/dev/null && success "Courses OK" || warn "Courses failed"

success "Redeploy complete"


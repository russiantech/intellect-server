#!/usr/bin/env bash
# deploy/ci.sh — CI/CD release pipeline.
# Usage: bash deploy/ci.sh
set -euo pipefail

source "$(dirname "$0")/_lib.sh"

DEPLOY_LOG="${DEPLOY_DIR}/deploy.log"
GIT_REMOTE="origin"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$DEPLOY_LOG"; }

# ─────────────────────────────────────────────────────────────────
check_git() {
    if [[ ! -d "${APP_DIR}/.git" ]]; then
        die "${APP_DIR} is not a git repository."
    fi
}

pull_code() {
    section "Pulling latest code"
    cd "${APP_DIR}"
    git fetch "$GIT_REMOTE" "$GIT_BRANCH"
    local old_hash new_hash
    old_hash=$(git rev-parse HEAD)
    git reset --hard "${GIT_REMOTE}/${GIT_BRANCH}"
    new_hash=$(git rev-parse HEAD)
    if [[ "$old_hash" == "$new_hash" ]]; then
        warn "Already up-to-date ($GIT_BRANCH)"
        return 1
    fi
    success "Updated: ${old_hash:0:7} → ${new_hash:0:7}"
    return 0
}

install_deps() {
    section "Installing dependencies"
    source "${VENV_PATH}/bin/activate"
    if [[ -f "${APP_DIR}/requirements.txt" ]]; then
        pip install --quiet -r "${APP_DIR}/requirements.txt"
        success "Requirements installed"
    else
        warn "No requirements.txt found"
    fi
}

run_tests() {
    [[ "${RUN_TESTS}" == "true" ]] || return 0
    section "Running tests"
    source "${VENV_PATH}/bin/activate"
    cd "${APP_DIR}"
    pytest || die "Tests failed — aborting deploy"
    success "Tests passed"
}

run_migrations() {
    [[ "${RUN_MIGRATIONS}" == "true" ]] || return 0
    section "Running migrations"
    source "${VENV_PATH}/bin/activate"
    cd "${APP_DIR}"
    alembic upgrade head || die "Migration failed — aborting deploy"
    success "Migrations complete"
}

regenerate_configs() {
    section "Regenerating configs"
    # If config.env changed, rewrite gunicorn.conf.py
    if git diff --name-only HEAD~1 HEAD 2>/dev/null | grep -q "config.env"; then
        bash "${DEPLOY_DIR}/deploy.sh" --skip-preflight 2>/dev/null || true
        info "config.env changed — configs regenerated"
    fi
}

full_restart() {
    section "Full restart (picks up code changes)"
    bash "${DEPLOY_DIR}/redeploy.sh"
    bash "${DEPLOY_DIR}/control.sh" restart
}

# ─────────────────────────────────────────────────────────────────
main() {
    hr
    log "CI/CD start — ${DOMAIN}"
    hr

    check_git
    pull_code || { log "No changes"; exit 0; }
    install_deps
    run_tests
    run_migrations
    regenerate_configs
    full_restart

    hr
    log "CI/CD complete — ${DOMAIN}"
    hr
}

main

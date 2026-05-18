#!/usr/bin/env bash
# deploy/release.sh — Manual release trigger.
# Usage: bash deploy/release.sh
set -euo pipefail

source "$(dirname "$0")/_lib.sh"

section "Manual Release — ${DOMAIN}"
info "Branch: ${GIT_BRANCH}"
info "Tests:  ${RUN_TESTS}"
info "Migrations: ${RUN_MIGRATIONS}"
echo ""

read -rp "Proceed? [Y/n]: " ans
[[ "$ans" =~ ^[Nn]$ ]] && die "Aborted"

bash "${DEPLOY_DIR}/ci.sh"

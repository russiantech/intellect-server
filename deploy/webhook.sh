#!/usr/bin/env bash
# deploy/webhook.sh — Git push webhook handler.
# Call this from your repo's webhook URL (POST to your server).
# Or run manually: bash deploy/webhook.sh
set -euo pipefail

source "$(dirname "$0")/_lib.sh"

WEBHOOK_LOG="${DEPLOY_DIR}/webhook.log"
SECRET_FILE="${DEPLOY_DIR}/.webhook_secret"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$WEBHOOK_LOG"; }

# ── Validate push event (optional signature check) ──────────────
validate_signature() {
    [[ -f "$SECRET_FILE" ]] || return 0  # No secret = skip check

    local sig="${HTTP_X_HUB_SIGNATURE_256:-${HTTP_X_GITLAB_TOKEN:-}}"
    [[ -n "$sig" ]] || die "No signature header"

    local secret
    secret=$(cat "$SECRET_FILE")
    # Simple check: compare token directly (GitLab style)
    if [[ "$sig" == "$secret" ]]; then
        return 0
    fi

    # GitHub HMAC-SHA256 check
    local body
    body=$(cat)
    local computed
    computed=$(echo -n "$body" | openssl dgst -sha256 -hmac "$secret" | sed 's/^.* //')
    if [[ "sha256=$computed" == "$sig" ]]; then
        return 0
    fi

    die "Invalid webhook signature"
}

# ── Main webhook handler ────────────────────────────────────────
main() {
    # If called via HTTP (CGI/PHP passes headers as env vars)
    # Otherwise manual run skips validation
    if [[ -n "${HTTP_X_GITHUB_EVENT:-}" || -n "${HTTP_X_GITLAB_EVENT:-}" ]]; then
        validate_signature
        log "Webhook received: push to ${GIT_BRANCH}"
    else
        log "Manual webhook trigger"
    fi

    # Run CI/CD
    bash "${DEPLOY_DIR}/ci.sh" >> "$WEBHOOK_LOG" 2>&1
    local exit_code=$?

    if [[ $exit_code -eq 0 ]]; then
        log "Webhook deploy succeeded"
        echo "Status: 200 OK"
        echo "Content-Type: application/json"
        echo ""
        echo '{"status":"ok","message":"Deployed"}'
    else
        log "Webhook deploy FAILED (exit $exit_code)"
        echo "Status: 500 Internal Server Error"
        echo "Content-Type: application/json"
        echo ""
        echo '{"status":"error","message":"Deploy failed"}'
    fi
}

main

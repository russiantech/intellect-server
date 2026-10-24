#!/usr/bin/env bash
# Installs the watchdog into the user's crontab idempotently.
set -euo pipefail
APP_DIR="${APP_DIR:-$HOME/intellect-api.salesnet.ng}"
chmod 755 "$APP_DIR/deploy/selfheal.sh"
TMP=$(mktemp)
crontab -l 2>/dev/null | grep -v 'intellect-selfheal' > "$TMP" || true
cat >> "$TMP" <<CRON
* * * * * /bin/bash $APP_DIR/deploy/selfheal.sh >/dev/null 2>&1 # intellect-selfheal
@reboot sleep 30 && /bin/bash $APP_DIR/deploy/selfheal.sh >/dev/null 2>&1 # intellect-selfheal
CRON
crontab "$TMP"; rm -f "$TMP"
echo "Installed. Current crontab:"; crontab -l | grep intellect-selfheal

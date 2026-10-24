#!/usr/bin/env bash
# deploy/install_selfheal.sh - idempotent installer for the watchdog cron + sanity audit.
#   bash deploy/install_selfheal.sh
set -u
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
HOME_DIR="${HOME:-/home/$(id -un)}"
SUP_DIR="${SUP_DIR:-$HOME_DIR/supervisor}"
SUP_CONF="${SUP_CONF:-$SUP_DIR/supervisord.conf}"
VENV_BIN="${VENV_BIN:-$(ls -d "$HOME_DIR"/virtualenv/"$(basename "$APP_DIR")"/*/bin 2>/dev/null | head -1)}"
G='\033[0;32m'; R='\033[0;31m'; Y='\033[1;33m'; N='\033[0m'
ok(){ echo -e "${G}✓${N} $*"; }; warn(){ echo -e "${Y}!${N} $*"; }; bad(){ echo -e "${R}✗${N} $*"; BAD=1; }; BAD=0

echo "== 1. Environment =="
[ -x "$VENV_BIN/supervisord" ] && [ -x "$VENV_BIN/supervisorctl" ] && ok "supervisor binaries: $VENV_BIN" || bad "supervisord/supervisorctl not found in '$VENV_BIN' (pip install supervisor in the venv, or set VENV_BIN)"
[ -f "$SUP_CONF" ] && ok "supervisor conf: $SUP_CONF" || bad "missing $SUP_CONF"
command -v flock >/dev/null && command -v curl >/dev/null && ok "flock + curl present" || bad "flock and curl are required"
chmod 755 "$SCRIPT_DIR/selfheal.sh" "$SCRIPT_DIR/test_recovery.sh" 2>/dev/null

echo; echo "== 2. Supervisor program audit =="
CONFS="$SUP_DIR/conf.d/*.conf"
PROGS=$(grep -h '^\[program:' $CONFS 2>/dev/null | tr -d '[]' | sed 's/program://')
echo "programs defined: ${PROGS:-<none>}"
[ "$(echo "$PROGS" | grep -c .)" -gt 1 ] && warn "more than one program is defined - make sure only ONE serves this app (two copies fight over the port)"
for key in autorestart startretries startsecs stopasgroup killasgroup; do
  grep -qh "^$key *=" $CONFS 2>/dev/null && ok "$key set" || warn "$key not set in conf.d (recommended: autorestart=true startretries=999999 startsecs=10 stopasgroup=true killasgroup=true)"
done
grep -qh '^autorestart *= *true' $CONFS 2>/dev/null || { grep -qh '^autorestart' $CONFS 2>/dev/null && bad "autorestart is not 'true'"; }
grep -qh '^exitcodes' $CONFS 2>/dev/null && warn "exitcodes is set; make sure it does not make exit code 0 count as 'expected' only if you rely on autorestart=unexpected"

echo; echo "== 3. selfheal.env =="
if [ ! -f "$SCRIPT_DIR/selfheal.env" ]; then
  cp "$SCRIPT_DIR/selfheal.env.example" "$SCRIPT_DIR/selfheal.env" 2>/dev/null && ok "created deploy/selfheal.env (edit HEALTH_URL / PROGRAM if auto-detect is wrong)"
else ok "deploy/selfheal.env exists"; fi

echo; echo "== 4. Cron =="
TMP=$(mktemp); crontab -l 2>/dev/null | grep -v 'intellect-selfheal' > "$TMP" || true
cat >> "$TMP" <<CRON
* * * * * /bin/bash $SCRIPT_DIR/selfheal.sh >/dev/null 2>&1 # intellect-selfheal
@reboot sleep 30 && /bin/bash $SCRIPT_DIR/selfheal.sh >/dev/null 2>&1 # intellect-selfheal
CRON
crontab "$TMP" && ok "cron installed" || bad "could not install cron"; rm -f "$TMP"
crontab -l | grep intellect-selfheal
crontab -l | grep -v intellect-selfheal | grep -qi 'supervisord' && warn "you also have a separate @reboot supervisord line - harmless, but the watchdog now covers it"

echo; echo "== 5. First run =="
VERBOSE=1 LOOPS=1 bash "$SCRIPT_DIR/selfheal.sh"; sleep 2
tail -5 "$APP_DIR/logs/selfheal/selfheal.log" 2>/dev/null
[ "$BAD" -eq 0 ] && echo -e "\n${G}Installed.${N} Now run:  bash deploy/test_recovery.sh" || echo -e "\n${R}Fix the ✗ items above, then re-run this installer.${N}"

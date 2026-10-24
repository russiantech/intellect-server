#!/usr/bin/env bash
# =============================================================================
# deploy/selfheal.sh  (v2)  -  watchdog for a Supervisor-managed FastAPI app
#
# Run from cron every minute. Each run keeps checking for ~55s (every 20s), so
# the worst-case detection time is ~20s, and runs never overlap (flock).
#
# Recovery ladder (cheapest first):
#   L1  supervisord dead / hung / stale pid+sock   -> clear orphans, start supervisord
#   L2  program not RUNNING (STOPPED/FATAL/BACKOFF/missing) -> supervisorctl start
#   L3  program RUNNING but health check fails 2x  -> supervisorctl restart
#   L4  restarts do not help 3x in a row           -> HARD reset (shutdown, kill
#                                                      orphans, fresh supervisord)
# Planned downtime: `touch $APP_DIR/logs/selfheal/PAUSE`  (remove to resume)
#
# Everything is overridable by env vars or by deploy/selfheal.env
# =============================================================================
set -u
export PATH="/usr/local/bin:/usr/bin:/bin:${PATH:-}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="${APP_DIR:-$(cd "$SCRIPT_DIR/.." && pwd)}"
[ -f "$SCRIPT_DIR/selfheal.env" ] && . "$SCRIPT_DIR/selfheal.env"
APP_REAL="$(cd "$APP_DIR" 2>/dev/null && pwd -P || echo "$APP_DIR")"   # /proc/<pid>/cwd is symlink-resolved (e.g. /home -> /home2)

HOME_DIR="${HOME:-/home/$(id -un)}"
SUP_DIR="${SUP_DIR:-$HOME_DIR/supervisor}"
SUP_CONF="${SUP_CONF:-$SUP_DIR/supervisord.conf}"
SUP_PID="${SUP_PID:-$SUP_DIR/supervisord.pid}"
SUP_SOCK="${SUP_SOCK:-$SUP_DIR/supervisor.sock}"
VENV_BIN="${VENV_BIN:-$(ls -d "$HOME_DIR"/virtualenv/"$(basename "$APP_DIR")"/*/bin 2>/dev/null | head -1)}"
SUPERVISORCTL="${SUPERVISORCTL:-$VENV_BIN/supervisorctl}"
SUPERVISORD="${SUPERVISORD:-$VENV_BIN/supervisord}"
PYTHON="${PYTHON:-$( [ -x "$VENV_BIN/python" ] && echo "$VENV_BIN/python" || command -v python3)}"

PROGRAM="${PROGRAM:-}"                         # auto-detected if empty
HEALTH_URL="${HEALTH_URL:-https://$(basename "$APP_DIR")/health}"
LOCAL_URL="${LOCAL_URL:-}"                     # auto-detected from the app's listening port if empty
USER_LOCAL_URL="$LOCAL_URL"
CURL_TIMEOUT="${CURL_TIMEOUT:-10}"

FAIL_THRESHOLD="${FAIL_THRESHOLD:-2}"          # consecutive failed checks before restart
STARTUP_GRACE="${STARTUP_GRACE:-45}"           # seconds after (re)start before health is judged
RESTART_COOLDOWN="${RESTART_COOLDOWN:-45}"
HARD_RESET_AFTER="${HARD_RESET_AFTER:-3}"      # failed restarts in a row -> hard reset
LOOPS="${LOOPS:-3}"                            # checks per cron run
LOOP_SLEEP="${LOOP_SLEEP:-20}"
HEALTH_WAIT="${HEALTH_WAIT:-40}"                # seconds to wait for health after a restart
MAX_LOG_BYTES="${MAX_LOG_BYTES:-5242880}"
PAUSE_MAX_HOURS="${PAUSE_MAX_HOURS:-6}"

STATE_DIR="${STATE_DIR:-$APP_DIR/logs/selfheal}"
LOG="$STATE_DIR/selfheal.log"
mkdir -p "$STATE_DIR" 2>/dev/null || { echo "cannot create $STATE_DIR" >&2; exit 1; }

# ---------- single instance ----------
exec 9>"$STATE_DIR/lock"
flock -n 9 || exit 0

ts()  { date '+%Y-%m-%d %H:%M:%S'; }
log() { echo "$(ts) | $*" >> "$LOG"; [ -n "${VERBOSE:-}" ] && echo "$(ts) | $*"; return 0; }
if [ -f "$LOG" ] && [ "$(stat -c%s "$LOG" 2>/dev/null || echo 0)" -gt "$MAX_LOG_BYTES" ]; then mv -f "$LOG" "$LOG.1"; fi

ctl() { timeout 20 "$SUPERVISORCTL" -c "$SUP_CONF" "$@" 2>&1; }

[ -x "$SUPERVISORCTL" ] && [ -x "$SUPERVISORD" ] || { log "FATAL config: supervisorctl/supervisord not found (VENV_BIN='$VENV_BIN'). Set VENV_BIN in deploy/selfheal.env"; exit 1; }
[ -f "$SUP_CONF" ] || { log "FATAL config: $SUP_CONF not found. Set SUP_CONF in deploy/selfheal.env"; exit 1; }

get_int() { [ -f "$STATE_DIR/$1" ] && cat "$STATE_DIR/$1" 2>/dev/null || echo "${2:-0}"; }
set_int() { echo "$2" > "$STATE_DIR/$1"; }

# ---------- L1: supervisord ----------
supervisord_ok() {
  # alive = pid file points at a live process AND the control socket answers
  local pid; pid=$(cat "$SUP_PID" 2>/dev/null || true)
  [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null || return 1
  ctl pid >/dev/null 2>&1
}

# Kill leftovers of the app (orphans keep the port bound, so a fresh instance would crash-loop).
# Matches python/gunicorn/uvicorn processes of THIS user whose cwd is the app dir. Never touches supervisord.
_orphan_pids() {
  local me pid d; me=$(id -u)
  for d in /proc/[0-9]*; do
    pid=${d#/proc/}; [ "$pid" = "$$" ] && continue
    [ "$(stat -c%u "$d" 2>/dev/null)" = "$me" ] || continue
    [ "$(readlink "$d/cwd" 2>/dev/null)" = "$APP_REAL" ] || continue
    case "$(cat "$d/comm" 2>/dev/null)" in python*|gunicorn*|uvicorn*) echo "$pid";; esac
  done
}
kill_orphans() {
  local pids; pids=$(_orphan_pids); [ -z "$pids" ] && return 0
  log "killing orphan app process(es): $(echo $pids | tr '\n' ' ')"
  kill -CONT $pids 2>/dev/null; kill -TERM $pids 2>/dev/null; sleep 3
  pids=$(_orphan_pids); [ -n "$pids" ] && { kill -KILL $pids 2>/dev/null; sleep 1; }
  return 0
}

start_supervisord() {
  log "L1: supervisord not healthy -> recovering"
  # a hung supervisord (pid alive, socket dead) must go first
  local old; old=$(cat "$SUP_PID" 2>/dev/null || true)
  [ -n "$old" ] && kill -0 "$old" 2>/dev/null && { kill -TERM "$old" 2>/dev/null; sleep 3; kill -KILL "$old" 2>/dev/null; }
  kill_orphans
  rm -f "$SUP_PID" "$SUP_SOCK"
  # 9>&- : do NOT let supervisord (a long-lived daemon) inherit our flock fd, or it would hold the lock forever
  timeout 30 "$SUPERVISORD" -c "$SUP_CONF" >> "$LOG" 2>&1 9>&-
  local i; for i in $(seq 1 20); do supervisord_ok && { log "L1: supervisord is up"; return 0; }; sleep 1; done
  log "L1: FAILED to start supervisord (see $SUP_DIR/logs/supervisord.log)"; return 1
}

# ---------- program discovery / state ----------
detect_program() {
  [ -n "$PROGRAM" ] && return 0
  local names; names=$(ctl status | awk 'NF && $1!~/^(error|unix:)/ {print $1}')
  PROGRAM=$(echo "$names" | grep -i "$(basename "$APP_DIR" | sed 's/[._]/-/g')" | head -1)
  [ -z "$PROGRAM" ] && PROGRAM=$(echo "$names" | grep -i intellect | head -1)
  [ -z "$PROGRAM" ] && PROGRAM=$(echo "$names" | head -1)
  [ -n "$PROGRAM" ]
}
prog_line()  { ctl status "$PROGRAM" | head -1; }
prog_state() { prog_line | awk '{print $2}'; }
prog_pid()   { prog_line | sed -n 's/.*pid \([0-9]*\),.*/\1/p'; }
uptime_secs() { # seconds of uptime from "uptime H:MM:SS"; 999999 if >= 1 day
  local l; l=$(prog_line); echo "$l" | grep -q 'day' && { echo 999999; return; }
  echo "$l" | sed -n 's/.*uptime \([0-9]*\):\([0-9]*\):\([0-9]*\).*/\1 \2 \3/p' | awk '{print $1*3600+$2*60+$3}'
}

# ---------- health ----------
http_code() { local c; c=$(curl -s -o /dev/null -m "$CURL_TIMEOUT" -w '%{http_code}' "$1" 2>/dev/null); echo "${c:-000}"; }
ok_code()   { case "$1" in 2??|3??) return 0;; *) return 1;; esac; }

detect_local_url() { # find a TCP port the app (or its children) is LISTENing on, no ss/lsof needed
  [ -n "$LOCAL_URL" ] && return 0
  local pid port; pid=$(prog_pid); [ -n "$pid" ] || return 1
  port=$("$PYTHON" - "$pid" <<'PY' 2>/dev/null
import os, sys
root = int(sys.argv[1]); pids = {root}
for p in filter(str.isdigit, os.listdir('/proc')):          # root + descendants
    try:
        stat = open(f'/proc/{p}/stat').read().rsplit(')', 1)[1].split()
        if int(stat[1]) in pids: pids.add(int(p))
    except Exception: pass
for _ in range(3):
    for p in filter(str.isdigit, os.listdir('/proc')):
        try:
            if int(open(f'/proc/{p}/stat').read().rsplit(')',1)[1].split()[1]) in pids: pids.add(int(p))
        except Exception: pass
inodes = set()
for p in pids:
    try:
        for fd in os.listdir(f'/proc/{p}/fd'):
            l = os.readlink(f'/proc/{p}/fd/{fd}')
            if l.startswith('socket:['): inodes.add(l[8:-1])
    except Exception: pass
for f in ('/proc/net/tcp', '/proc/net/tcp6'):
    try:
        for line in open(f).read().splitlines()[1:]:
            c = line.split()
            if c[3] == '0A' and c[9] in inodes:
                print(int(c[1].split(':')[1], 16)); sys.exit(0)
    except Exception: pass
PY
  )
  [ -n "$port" ] && LOCAL_URL="http://127.0.0.1:$port/health"
  [ -n "$LOCAL_URL" ]
}

app_healthy() { # 0 healthy, 1 app unhealthy; sets HEALTH_NOTE
  HEALTH_NOTE=""
  detect_local_url || true
  local lc="" pc
  if [ -n "$LOCAL_URL" ]; then
    lc=$(http_code "$LOCAL_URL")
    if ! ok_code "$lc"; then HEALTH_NOTE="local $LOCAL_URL=$lc"; LOCAL_URL="$USER_LOCAL_URL"; return 1; fi
  fi
  pc=$(http_code "$HEALTH_URL")
  if ok_code "$pc"; then return 0; fi
  if [ -n "$lc" ]; then HEALTH_NOTE="app OK locally ($lc) but public $HEALTH_URL=$pc (proxy/LiteSpeed issue, restart would not help)"; PUBLIC_ONLY_FAIL=1; return 0; fi
  HEALTH_NOTE="public $HEALTH_URL=$pc"; return 1
}

wait_healthy() { local i; for i in $(seq 1 "${1:-40}"); do app_healthy && return 0; sleep 1; done; return 1; }

hard_reset() {
  log "L4: HARD RESET (shutdown supervisord, kill orphans, fresh start)"
  ctl shutdown >/dev/null 2>&1; sleep 3
  local old; old=$(cat "$SUP_PID" 2>/dev/null || true); [ -n "$old" ] && kill -KILL "$old" 2>/dev/null
  kill_orphans; rm -f "$SUP_PID" "$SUP_SOCK"
  start_supervisord && { ctl start "$PROGRAM" >/dev/null 2>&1; sleep 2; }
}

# ---------- one check cycle ----------
check_once() {
  PUBLIC_ONLY_FAIL=""
  if [ -f "$STATE_DIR/PAUSE" ]; then                                           # planned maintenance
    if [ -n "$(find "$STATE_DIR/PAUSE" -mmin +"$((PAUSE_MAX_HOURS*60))" 2>/dev/null)" ]; then
      log "PAUSE flag older than ${PAUSE_MAX_HOURS}h -> ignoring and removing it"; rm -f "$STATE_DIR/PAUSE"
    else return 0; fi
  fi

  supervisord_ok || { start_supervisord || return 1; set_int last_restart "$(date +%s)"; }

  detect_program || { log "L2: no program found in supervisor (conf.d missing?) -> reread/update"; ctl reread >/dev/null; ctl update >/dev/null; detect_program || { log "L2: still no program; check $SUP_DIR/conf.d"; return 1; }; }

  local st; st=$(prog_state)
  case "$st" in
    RUNNING) ;;
    STARTING) return 0;;
    STOPPING) return 0;;
    "")      log "L2: program '$PROGRAM' unknown to supervisor -> reread/update/start"; ctl reread >/dev/null; ctl update >/dev/null; ctl start "$PROGRAM" >/dev/null; sleep 3; return 0;;
    STOPPED) log "L2: program '$PROGRAM' is STOPPED -> starting"; ctl start "$PROGRAM" >/dev/null; sleep 3
             [ "$(prog_state)" = "RUNNING" ] || { kill_orphans; ctl restart "$PROGRAM" >/dev/null; }
             set_int last_restart "$(date +%s)"; set_int fails 0; return 0;;
    *)       log "L2: program '$PROGRAM' is $st -> clearing orphans and starting"; kill_orphans; ctl start "$PROGRAM" >/dev/null; sleep 3
             [ "$(prog_state)" = "RUNNING" ] || { ctl restart "$PROGRAM" >/dev/null; }
             set_int last_restart "$(date +%s)"; set_int fails 0; return 0;;
  esac

  local up; up=$(uptime_secs); [ -z "$up" ] && up=999999
  [ "$up" -lt "$STARTUP_GRACE" ] && return 0                                  # still warming up

  if app_healthy; then
    [ "$(get_int fails)" != "0" ] && log "recovered (health OK)"
    [ -n "$PUBLIC_ONLY_FAIL" ] && [ "$(get_int pubfail 0)" = "0" ] && log "WARN: $HEALTH_NOTE"
    [ -n "$PUBLIC_ONLY_FAIL" ] && set_int pubfail 1 || set_int pubfail 0
    set_int fails 0; set_int bad_restarts 0; date +%s > "$STATE_DIR/last_ok"
    return 0
  fi

  local f=$(( $(get_int fails) + 1 )); set_int fails "$f"
  log "health check failed ($f/$FAIL_THRESHOLD): $HEALTH_NOTE"
  [ "$f" -lt "$FAIL_THRESHOLD" ] && return 0

  local now last cd bad0; now=$(date +%s); last=$(get_int last_restart); bad0=$(get_int bad_restarts)
  cd=$(( RESTART_COOLDOWN * (1 + bad0*2) )); [ "$cd" -gt 300 ] && cd=300      # back off while restarts keep failing
  [ $((now-last)) -lt "$cd" ] && return 0
  set_int last_restart "$now"

  local bad; bad=$(get_int bad_restarts)
  if [ "$bad" -ge $((HARD_RESET_AFTER-1)) ]; then
    hard_reset; set_int bad_restarts 0
  else
    log "L3: restarting $PROGRAM"; ctl restart "$PROGRAM" >/dev/null
  fi
  if wait_healthy "$HEALTH_WAIT"; then log "healthy after recovery"; set_int fails 0; set_int bad_restarts 0
  else set_int bad_restarts $((bad+1)); log "STILL UNHEALTHY after recovery attempt ($((bad+1))/$HARD_RESET_AFTER): $HEALTH_NOTE"; fi
}

for i in $(seq 1 "$LOOPS"); do
  check_once || true
  [ "$i" -lt "$LOOPS" ] && sleep "$LOOP_SLEEP"
done
exit 0

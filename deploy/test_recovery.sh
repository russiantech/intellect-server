#!/usr/bin/env bash
# =============================================================================
# deploy/test_recovery.sh - proves the self-recovery works by BREAKING the app on purpose.
#
#   bash deploy/test_recovery.sh            # run all scenarios (≈3-5 min, brief downtime each)
#   bash deploy/test_recovery.sh T2 T4      # run selected scenarios
#
# WARNING: this kills your app / supervisord on purpose. Run it when a few seconds of
# downtime is acceptable. Each scenario passes only if the app is serving /health again
# within MAX_WAIT seconds WITHOUT any manual action.
#
# Scenarios
#  T1 app process SIGKILLed                (supervisord should revive it by itself)
#  T2 supervisord SIGKILLed, app orphaned  (stale pid+sock; watchdog must revive supervisord)
#  T3 supervisord AND app both SIGKILLed   (whole stack dead)
#  T4 app hung (SIGSTOP; port open, no answers)       -> health check restart
#  T5 supervisord hung (SIGSTOP)                       -> watchdog replaces it
#  T6 program stopped; PAUSE flag must be honoured, then released -> restarted
#
# By default the watchdog is invoked directly (like cron would). Use  USE_CRON=1  to
# instead wait for the real cron entry to do the job (needs ~1 min per scenario).
# =============================================================================
set -u
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="${APP_DIR:-$(cd "$SCRIPT_DIR/.." && pwd)}"
[ -f "$SCRIPT_DIR/selfheal.env" ] && . "$SCRIPT_DIR/selfheal.env"
HOME_DIR="${HOME:-/home/$(id -un)}"
SUP_DIR="${SUP_DIR:-$HOME_DIR/supervisor}"
SUP_CONF="${SUP_CONF:-$SUP_DIR/supervisord.conf}"
SUP_PID="${SUP_PID:-$SUP_DIR/supervisord.pid}"
VENV_BIN="${VENV_BIN:-$(ls -d "$HOME_DIR"/virtualenv/"$(basename "$APP_DIR")"/*/bin 2>/dev/null | head -1)}"
SUPERVISORCTL="${SUPERVISORCTL:-$VENV_BIN/supervisorctl}"
HEALTH_URL="${HEALTH_URL:-https://$(basename "$APP_DIR")/health}"
MAX_WAIT="${MAX_WAIT:-150}"
STATE_DIR="${STATE_DIR:-$APP_DIR/logs/selfheal}"
USE_CRON="${USE_CRON:-0}"
ctl() { timeout 20 "$SUPERVISORCTL" -c "$SUP_CONF" "$@" 2>&1; }

# if supervisord is down, let the watchdog bring it up so the program can be discovered
ctl pid >/dev/null 2>&1 || { echo "supervisord not running -> asking watchdog to start it"; LOOPS=1 STARTUP_GRACE=3 bash "$SCRIPT_DIR/selfheal.sh"; sleep 2; }
PROGRAM="${PROGRAM:-$(ctl status | awk 'NF && $1!~/^(error|unix:)/ {print $1}' | grep -i "$(basename "$APP_DIR" | sed 's/[._]/-/g')" | head -1)}"
[ -z "$PROGRAM" ] && PROGRAM="$(ctl status | awk 'NF && $1!~/^(error|unix:)/ {print $1}' | head -1)"
[ -n "$PROGRAM" ] || { echo "Cannot find supervised program. Start supervisord first:  bash deploy/control.sh start"; exit 2; }

G='\033[0;32m'; R='\033[0;31m'; Y='\033[1;33m'; N='\033[0m'
code() { local c; c=$(curl -s -o /dev/null -m 8 -w '%{http_code}' "$HEALTH_URL" 2>/dev/null); echo "${c:-000}"; }
up()   { [ "$(code)" = "200" ] && ctl status "$PROGRAM" | grep -q RUNNING; }
prog_pid() { ctl status "$PROGRAM" | sed -n 's/.*pid \([0-9]*\),.*/\1/p'; }
sup_pid()  { cat "$SUP_PID" 2>/dev/null; }
tree() { local p="$1" c; echo "$p"; for c in $(pgrep -P "$p" 2>/dev/null); do tree "$c"; done; }

ensure_up_first() {
  up && return 0
  echo -e "${Y}App is not healthy before the test; letting the watchdog fix it first...${N}"
  local i; for i in $(seq 1 12); do LOOPS=1 STARTUP_GRACE=${STARTUP_GRACE:-45} bash "$SCRIPT_DIR/selfheal.sh"; up && return 0; sleep 10; done
  up
}

# heal: let recovery run; returns seconds taken or fails
heal_wait() {
  local t0 t; t0=$(date +%s)
  while :; do
    t=$(( $(date +%s) - t0 ))
    up && { echo "$t"; return 0; }
    [ "$t" -ge "$MAX_WAIT" ] && { echo "$t"; return 1; }
    if [ "$USE_CRON" != "1" ]; then LOOPS=1 bash "$SCRIPT_DIR/selfheal.sh" >/dev/null 2>&1; fi
    sleep 4
  done
}

PASS=0; FAIL=0; RESULTS=()
verdict() { # name, rc, seconds, [stable-check]
  if [ "$2" -eq 0 ]; then
    sleep 5; if up; then echo -e "${G}PASS${N} $1 - recovered in ${3}s and stayed healthy"; RESULTS+=("PASS $1 ${3}s"); PASS=$((PASS+1)); return; fi
  fi
  echo -e "${R}FAIL${N} $1 - not healthy after ${3}s"; RESULTS+=("FAIL $1"); FAIL=$((FAIL+1))
}
WANT=("$@")
want() { [ ${#WANT[@]} -eq 0 ] && return 0; local w; for w in "${WANT[@]}"; do [ "$w" = "$1" ] && return 0; done; return 1; }

echo "Program: $PROGRAM | health: $HEALTH_URL | supervisor conf: $SUP_CONF | mode: $([ "$USE_CRON" = 1 ] && echo real-cron || echo direct)"
ensure_up_first || { echo -e "${R}Baseline app is not healthy and could not be fixed - aborting${N}"; exit 1; }
echo -e "${G}baseline healthy${N}"; rm -f "$STATE_DIR/PAUSE"; trap 'rm -f "$STATE_DIR/PAUSE"' EXIT
need_pid() { [ -n "$1" ] || { echo -e "${R}FAIL${N} $2 - test harness could not find the app pid"; RESULTS+=("FAIL $2 (no pid)"); FAIL=$((FAIL+1)); return 1; }; }

if want T1; then echo; echo "== T1: kill -9 the app process =="
  p=$(prog_pid); need_pid "$p" T1 && kill -9 $(tree "$p") 2>/dev/null && {
  # supervisor alone should handle this; give it time WITHOUT the watchdog
  t0=$(date +%s); while ! up && [ $(( $(date +%s)-t0 )) -lt 40 ]; do sleep 1; done
  if up; then verdict T1 0 $(( $(date +%s)-t0 )); else echo -e "${Y}supervisord did not revive it alone; watchdog takes over${N}"; s=$(heal_wait); verdict T1 $? "$s"; fi; }
fi

if want T2; then echo; echo "== T2: kill -9 supervisord only (app orphaned, stale pid/sock) =="
  sp=$(sup_pid); need_pid "$sp" T2 || sp=""; [ -n "$sp" ] && kill -9 "$sp" 2>/dev/null; sleep 2
  echo "supervisord dead: $(kill -0 "$sp" 2>/dev/null && echo NO || echo yes) | ctl: $(ctl status 2>&1 | head -1)"
  [ -n "$sp" ] && { s=$(heal_wait); verdict T2 $? "$s"; }
fi

if want T3; then echo; echo "== T3: kill -9 supervisord AND all app processes =="
  p=$(prog_pid); sp=$(sup_pid); kids=$(tree "$p" 2>/dev/null)
  kill -9 "$sp" $kids 2>/dev/null; sleep 2
  s=$(heal_wait); verdict T3 $? "$s"
fi

if want T4; then echo; echo "== T4: app hung (SIGSTOP) =="
  p=$(prog_pid); if need_pid "$p" T4; then kill -STOP $(tree "$p") 2>/dev/null; sleep 1
  c=$(code); echo "app answers? $c (expected 000 = hung)"
  if [ "$c" = "200" ]; then echo -e "${R}FAIL${N} T4 - could not hang the app (test invalid)"; FAIL=$((FAIL+1)); RESULTS+=("FAIL T4 invalid")
  else s=$(heal_wait); verdict T4 $? "$s"; fi; fi
fi

if want T5; then echo; echo "== T5: supervisord hung (SIGSTOP) =="
  sp=$(sup_pid); kill -STOP "$sp" 2>/dev/null
  # app keeps serving, but supervisord can no longer manage it: the watchdog must replace it
  s=0; for i in 1 2 3 4; do LOOPS=1 bash "$SCRIPT_DIR/selfheal.sh" >/dev/null 2>&1; ctl pid >/dev/null 2>&1 && break; sleep 3; done
  if ctl pid >/dev/null 2>&1 && kill -0 "$(sup_pid)" 2>/dev/null; then verdict T5 0 "$s"; else
    for i in 1 2 3; do LOOPS=1 bash "$SCRIPT_DIR/selfheal.sh" >/dev/null 2>&1; ctl pid >/dev/null 2>&1 && break; sleep 3; done
    ctl pid >/dev/null 2>&1; verdict T5 $? "$s"; fi
fi

if want T6; then echo; echo "== T6: program stopped + PAUSE flag =="
  touch "$STATE_DIR/PAUSE"; ctl stop "$PROGRAM" >/dev/null; sleep 2
  for i in 1 2; do LOOPS=1 bash "$SCRIPT_DIR/selfheal.sh" >/dev/null 2>&1; sleep 2; done
  if up; then echo -e "${R}FAIL${N} T6 - watchdog ignored PAUSE flag"; FAIL=$((FAIL+1)); RESULTS+=("FAIL T6 pause")
  else echo -e "${G}PASS${N} T6a - PAUSE flag honoured (app stays down during maintenance)"; PASS=$((PASS+1)); RESULTS+=("PASS T6a pause")
    rm -f "$STATE_DIR/PAUSE"; s=$(heal_wait); verdict T6b $? "$s"; fi
fi

echo; echo "================ SUMMARY ================"; printf '%s\n' "${RESULTS[@]}"
echo "passed=$PASS failed=$FAIL"; [ "$FAIL" -eq 0 ]

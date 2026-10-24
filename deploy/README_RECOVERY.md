# Intellect API – self-recovery (Supervisor + cron watchdog)

## Which approach is best?
**Supervisor + a cron watchdog**, exactly the ScoreApp pattern, with one important upgrade.

| Layer | Job | Speed |
|---|---|---|
| Supervisor (`autorestart`, `startretries=999999`) | revives the *app* when it exits | ~1-3 s |
| Cron watchdog `selfheal.sh` (every minute, checks every 20 s) | revives *supervisord itself*, kills orphans, restarts a *hung* app, hard-resets | ≤ ~20-60 s |

Why not the others: **Passenger** can't be supervised from outside (you only get LiteSpeed's 503 page);
**systemd** needs root (not on shared cPanel); **cron alone** is slow and can't tell a hung app from a healthy one.
Supervisor alone is not enough: nothing restarts supervisord when it dies, and that is what happened to you.

## What actually went wrong (from your last logs)
1. `control.sh restart` printed `unix:///home/salesne2/supervisor/supervisor.sock no such file` → **supervisord was dead**.
   Your app was down and nothing could bring it back. (ScoreApp has the same single point of failure; the watchdog protects both patterns.)
2. My first watchdog assumed Passenger when it saw no socket, so it only did `touch tmp/restart.txt` (a no-op for Supervisor) for ~6 minutes until you ran `control.sh restart` yourself. That logic is **replaced**.

## What the new `deploy/selfheal.sh` does (all tested, see below)
- L1 supervisord dead / hung / stale `pid` + `sock` → kill leftovers, clear files, start supervisord
- L2 program STOPPED / FATAL / BACKOFF / missing → clear orphans (a leftover process holding the port makes new ones crash-loop), start it
- L3 program RUNNING but `/health` fails twice → `supervisorctl restart`
- L4 restarts keep failing → hard reset, with growing back-off (no thrash on a genuinely broken deploy)
- never overlaps (flock), ignores the 45 s after a restart, rotates its log, doesn't restart when only the public proxy fails
- **Planned downtime:** `touch logs/selfheal/PAUSE` (auto-expires after 6 h, so it can't be forgotten forever); `rm` it to resume.

## Step-by-step on the server
```bash
cd ~/intellect-api.salesnet.ng
source ~/virtualenv/intellect-api.salesnet.ng/3.13/bin/activate

# 1. Look at what exists (send me the output if anything looks odd)
~/virtualenv/intellect-api.salesnet.ng/3.13/bin/supervisorctl -c ~/supervisor/supervisord.conf status
ls ~/supervisor/conf.d/
tail -30 ~/supervisor/logs/supervisord.log        # why did supervisord die? look for "received SIGTERM/SIGKILL", memory, or errors

# 2. Only ONE program may serve this app. If both `intellect-api` (from my first zip, port 8002)
#    and `intellect-api-salesnet-ng` exist, delete the extra .conf you don't use, then:
#    supervisorctl -c ~/supervisor/supervisord.conf reread && ... update

# 3. Install the new files (replace the old ones; same names)
#    copy deploy/selfheal.sh, deploy/test_recovery.sh, deploy/install_selfheal.sh, deploy/selfheal.env.example
#    (or git add/commit/push from your machine and `git pull` here)
chmod +x deploy/*.sh

# 4. Install the cron + audit your supervisor conf (idempotent, replaces the old cron lines)
bash deploy/install_selfheal.sh
#    It prints ✓/! for: autorestart, startretries, startsecs, stopasgroup, killasgroup.
#    Add any missing key to your [program:...] block, then `bash deploy/control.sh reload`.
#    Required for the program block (ScoreApp has the same):
#      autorestart=true  startretries=999999  startsecs=10  stopasgroup=true  killasgroup=true

# 5. PROVE it works (breaks the app on purpose; ~5 min, a few seconds of downtime per test)
bash deploy/test_recovery.sh
#    Expect:  passed=7 failed=0
#    Optional real-cron proof (waits for cron instead of calling the script):  USE_CRON=1 bash deploy/test_recovery.sh T2

# 6. Watch it
tail -f logs/selfheal/selfheal.log
```
Quick manual drill (30 seconds): `kill -9 $(cat ~/supervisor/supervisord.pid)` → within ~1 min `curl https://intellect-api.salesnet.ng/health` is 200 again and the log shows `L1: supervisord is up`.

## What I tested (simulated server: real supervisord + uvicorn app, cold start)
| # | Failure | Result |
|---|---|---|
| T1 | app `kill -9` | PASS (supervisor revives in ~4 s) |
| T2 | supervisord `kill -9`, app orphaned, stale pid/sock | PASS (8 s, orphan killed) |
| T3 | supervisord + app both `kill -9` | PASS (5 s) |
| T4 | app hung (SIGSTOP, alive but silent) | PASS (restart after 2 failed checks) |
| T5 | supervisord hung (SIGSTOP) | PASS (replaced) |
| T6 | program stopped: PAUSE honoured, then released | PASS |
| E1 | 3 watchdog runs at once | PASS (flock, no stacking) |
| E2 | bad deploy (syntax error) then fixed | PASS (recovers with no manual step) |
| E3 | app always returns 500 | escalates L3→L4 with back-off, recovers after the fix |
Bugs found *by* these tests and fixed: supervisord inheriting the lock fd (would have disabled the watchdog after the first recovery); `/proc` cwd vs symlinked home (`/home` → `/home2`); a forgotten PAUSE file.

**Not testable here:** the real cron daemon, LiteSpeed, and your exact `control.sh`/`gunicorn.conf.py`. Step 5 on your server covers that.
If your `deploy/control.sh`, `_lib.sh`, `gunicorn.conf.py` or `~/supervisor/conf.d/*.conf` do any broad `pkill`, send them to me and I'll make them watchdog-safe.

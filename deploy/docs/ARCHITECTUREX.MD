GitHub push / Manual / Cron
        │
        ▼
   ┌─────────┐
   │webhook.sh│ ──► validates signature, logs
   └────┬────┘
        │
   ┌────▼────┐
   │release.sh│ ──► confirms with user
   └────┬────┘
        │
   ┌────▼────┐
   │  ci.sh   │ ──► git pull, pip install, pytest, alembic
   └────┬────┘      (NO process logic)
        │
        ▼
   ┌──────────┐
   │control.sh │ ◄── SINGLE SOURCE OF TRUTH
   │  restart │     (supervisorctl restart = new master, new code)
   └────┬─────┘
        │
   ┌────▼────┐
   │monitor.sh│ ──► health check, delegates to control.sh
   │recovery.sh│
   └──────────┘
   
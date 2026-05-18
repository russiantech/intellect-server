# System Architecture

## Boot Sequence

```
Server Reboot
    │
    ▼
@reboot Cron (sleep 30)
    │
    ▼
supervisord (daemon)
    │
    ▼
Gunicorn master + N Uvicorn workers
    │
    ▼
FastAPI app (main:app)
```

## Request Flow

```
Internet
    │
    ▼
Apache/Nginx (cPanel reverse proxy)
    │
    ▼
localhost:8001  ← Gunicorn (bind)
    │
    ▼
UvicornWorker (async ASGI)
    │
    ▼
FastAPI router → your business logic
```

## Process Model

```
supervisord
    └── gunicorn: master [intellect-api-salesnet-ng]
            ├── uvicorn: worker 1  (pid 1234)
            ├── uvicorn: worker 2  (pid 1235)
            └── uvicorn: worker 3  (pid 1236)
```

*Workers auto-recycle after `max_requests` to prevent memory leaks.*

## Crash Recovery Matrix

| Event | Detection | Action | Downtime |
|-------|-----------|--------|----------|
| App exception | Supervisor exit code | Restart 1s later | ~2s |
| Memory kill (OOM) | Supervisor signal | Restart immediately | ~2s |
| Gunicorn worker hung | `timeout` expiry | Worker killed + replaced | 0s (others serve) |
| Server reboot | Cron @reboot | Full stack restart | ~30s |
| Manual kill | Supervisor signal | Restart immediately | ~2s |
| Health check fail | `monitor.sh` HTTP | `control.sh restart` | ~5s |

## Directory Layout

```
/home/salesne2/
│
├── supervisor/
│   ├── supervisord.conf
│   ├── conf.d/
│   │   └── intellect-api-salesnet-ng.conf
│   └── logs/
│       ├── supervisord.log
│       └── monitor.log
│
├── virtualenv/intellect-api.salesnet.ng/3.13/
│   └── bin/gunicorn, uvicorn, supervisorctl, …
│
└── intellect-api.salesnet.ng/
    ├── main.py
    ├── deploy/
    │   ├── config.env
    │   ├── _lib.sh
    │   ├── deploy.sh
    │   ├── control.sh
    │   ├── ci.sh
    │   ├── monitor.sh
    │   ├── recovery.sh
    │   └── gunicorn.conf.py
    └── logs/
        ├── app.log
        ├── app.error.log
        ├── access.log
        └── error.log
```

## Scaling Behavior

```
CPU cores = 1  →  workers = 3  (capped)
CPU cores = 2  →  workers = 4  (capped)
CPU cores = 4  →  workers = 4  (capped at 4 for shared hosting)
```

Override in `config.env`:
```bash
WORKERS=2
```

## CI/CD Pipeline

```
git push origin main
        │
        ▼
   [webhook]
        │
        ▼
    ci.sh
   ┌─────────────┐
   │ git fetch   │
   │ git reset   │
   └─────────────┘
        │
        ▼
   ┌─────────────┐
   │ pip install │
   │ requirements│
   └─────────────┘
        │
        ▼
   ┌─────────────┐      ┌─────────────┐
   │ pytest      │──NO──→│ abort       │
   └─────────────┘      └─────────────┘
        │ YES
        ▼
   ┌─────────────┐      ┌─────────────┐
   │ alembic     │──NO──→│ abort       │
   │ upgrade head│      └─────────────┘
   └─────────────┘
        │ YES
        ▼
   ┌─────────────┐
   │ gunicorn    │
   │ HUP reload  │
   └─────────────┘
        │
        ▼
    LIVE
```

## Security Model

- Everything runs as `salesne2` (never root)
- App binds `0.0.0.0:8001` but only accessible via cPanel reverse proxy
- `.env` is `chmod 600`
- Supervisor socket is `chmod 0700`
- Secrets never appear in process list (`ps aux`)

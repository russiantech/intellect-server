# Intellect API: crash fix + self-recovery

## What went wrong (from your logs)
1. **Root cause** – `handlers.py:263` returns `exc.errors()` in the 422 response. With Pydantic v2, any
   `field_validator` that raises `ValueError` puts the *exception object* in `errors()[i]["ctx"]["error"]`.
   `json.dumps` can't encode it -> `TypeError` **inside the error handler**.
2. That second exception escaped through `BaseHTTPMiddleware` (`main.py:62`) as an `ExceptionGroup`,
   up to `passenger_wsgi.py:109`, so `start_response()` was never called ->
   `wsgiAppHandler pApp->start_response() return NULL` -> worker dies.
3. **Why it didn't recover** – Passenger only respawns a worker on the *next* request, and the log shows
   workers killed by `signal 15` and repeated "Starting Intellect API..." with no external watchdog. Your ScoreApp
   recovers because Supervisor + cron `@reboot` watch it from outside; Intellect had nothing equivalent.

## What's fixed (3 layers)
| Layer | File | Guarantee |
|---|---|---|
| Error serialization | `app/core/exceptions/safe_json.py` | Building an error response can never raise (sanitizes ValueError, bytes, sets, nested objects; strips `input` so passwords are never echoed) |
| Handlers + middleware | `resilient_handlers.py`, `asgi_middleware.py` | Catch-all 500 JSON; pure-ASGI middleware replaces `BaseHTTPMiddleware`; every response has `x-request-id` |
| Server boundary | `passenger_wsgi.py` | a2wsgi bridge; boot failure or WSGI error still returns a valid response, never `start_response NULL` |
| External recovery | `deploy/selfheal.sh` | Cron every minute: health check -> restart (Passenger `restart.txt` or Supervisor), cooldown, lock, log rotation, `@reboot` |

Tested locally: old handler reproduces your exact `TypeError`; new stack returns 422/500 JSON, bad-body requests,
404s and the WSGI bridge all respond cleanly.

## Install (SSH, in `~/intellect-api.salesnet.ng`)
```bash
source ~/virtualenv/intellect-api.salesnet.ng/3.13/bin/activate
pip install a2wsgi
cp passenger_wsgi.py passenger_wsgi.py.bak-$(date +%F)       # keep a backup
# copy the new files in (paths as in this zip), then:
```
Edit `main.py`:
```python
from app.core.exceptions.asgi_middleware import SafeRequestMiddleware
from app.core.exceptions.resilient_handlers import register_resilient_handlers

# remove the old  @app.middleware("http") / BaseHTTPMiddleware dispatch (line ~62), then:
app.add_middleware(SafeRequestMiddleware)
register_resilient_handlers(app)        # call AFTER your existing handler registration

@app.get("/health", include_in_schema=False)
async def health():
    return {"status": "ok"}
```
Also make your existing `handlers.py::_error_response` use `safe_json_response(...)` and
`sanitize_validation_errors(exc.errors())` so there is only one code path.
Then:
```bash
bash deploy/install_selfheal.sh       # installs cron watchdog (idempotent)
touch tmp/restart.txt                  # reload Passenger
curl -i https://intellect-api.salesnet.ng/health
tail -f logs/selfheal/selfheal.log
```
**Chaos test:** `pkill -f intellect-api` or `touch` a syntax error in a module then revert; the watchdog logs the
failure and restarts within ~1-2 minutes.

## Option B: exactly like ScoreApp (Supervisor + uvicorn)
Passenger can't restart itself instantly. For ~1-second recovery, run uvicorn under Supervisor (config in
`deploy/intellect-api.conf`, port 8002; check yours isn't in use) and point cPanel/.htaccess at
`127.0.0.1:8002`. `selfheal.sh` auto-detects Supervisor and manages it. Tell me your `.htaccess` and
`ScoreApp` conf and I'll adapt precisely.

## Other things the logs showed
- "Starting Intellect API..." x3-4 in the same second -> multiple workers each running startup/`create_all`.
  Move table creation to Alembic (you have `migrations/`) or guard it with a lock, to avoid races.
- The `signal 15` kills at 19:03/19:10 are Passenger/cPanel recycling (or your deploy scripts); not app bugs.

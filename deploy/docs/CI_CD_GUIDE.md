# CI/CD Setup Guide 🚀

Three ways to deploy automatically. Pick one.

---

## Option 1: Manual Release (Simplest)

```bash
cd ~/intellect-api.salesnet.ng
bash deploy/release.sh
```

What happens:
1. `git fetch origin main`
2. `git reset --hard origin/main`
3. `pip install -r requirements.txt`
4. `pytest` (if `RUN_TESTS=true` in config.env)
5. `alembic upgrade head` (if `RUN_MIGRATIONS=true`)
6. `control.sh restart` (full restart, picks up code)

---

## Option 2: Git Push Webhook (Automatic)

### A. On Your Server — Create Webhook Secret

```bash
cd ~/intellect-api.salesnet.ng/deploy
# Generate a random secret
python -c "import secrets; print(secrets.token_urlsafe(32))" > .webhook_secret
chmod 600 .webhook_secret
cat .webhook_secret
# Copy this value for GitHub/GitLab
```

### B. Create a Webhook Endpoint

Since cPanel doesn't expose raw ports for webhooks, use a **PHP bridge** or a **dedicated route** in your FastAPI app.

#### Method A: PHP Webhook Bridge (Recommended for cPanel)

Create `~/intellect-api.salesnet.ng/webhook.php`:

```php
<?php
// webhook.php — Git push webhook receiver
// Place this in your public_html or app root

$deploy_dir = '/home/salesne2/intellect-api.salesnet.ng/deploy';
$secret_file = "$deploy_dir/.webhook_secret";
$log_file = "$deploy_dir/webhook.log";

// Read raw body
$body = file_get_contents('php://input');

// Validate signature (GitHub style)
$sig = $_SERVER['HTTP_X_HUB_SIGNATURE_256'] ?? '';
if (file_exists($secret_file)) {
    $secret = trim(file_get_contents($secret_file));
    $computed = 'sha256=' . hash_hmac('sha256', $body, $secret);
    if (!hash_equals($computed, $sig)) {
        http_response_code(403);
        die(json_encode(['status' => 'error', 'message' => 'Invalid signature']));
    }
}

// Validate branch (optional)
$payload = json_decode($body, true);
$ref = $payload['ref'] ?? '';
if ($ref !== 'refs/heads/main') {
    http_response_code(200);
    die(json_encode(['status' => 'ignored', 'message' => "Not main branch: $ref"]));
}

// Trigger deploy (non-blocking)
$cmd = "bash $deploy_dir/webhook.sh > /dev/null 2>&1 &";
exec($cmd);

http_response_code(200);
echo json_encode(['status' => 'ok', 'message' => 'Deploy triggered']);
```

Then in cPanel, point a subdomain or path to this file:
- `https://intellect-api.salesnet.ng/webhook.php` (if in app root)
- Or `https://deploy.intellect-api.salesnet.ng/webhook.php` (subdomain)

#### Method B: FastAPI Webhook Route (If You Control Routing)

Add to your FastAPI app:

```python
import subprocess
from fastapi import APIRouter, Header, Request, HTTPException
import hmac
import hashlib
import os

webhook_router = APIRouter()

WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET")

def verify_signature(body: bytes, signature: str) -> bool:
    if not WEBHOOK_SECRET:
        return True
    computed = "sha256=" + hmac.new(
        WEBHOOK_SECRET.encode(), body, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(computed, signature)

@webhook_router.post("/deploy-webhook")
async def deploy_webhook(
    request: Request,
    x_hub_signature_256: str = Header(None)
):
    body = await request.body()
    if not verify_signature(body, x_hub_signature_256 or ""):
        raise HTTPException(403, "Invalid signature")

    payload = await request.json()
    if payload.get("ref") != "refs/heads/main":
        return {"status": "ignored", "ref": payload.get("ref")}

    # Trigger deploy in background
    subprocess.Popen(
        ["bash", "/home/salesne2/intellect-api.salesnet.ng/deploy/webhook.sh"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return {"status": "ok", "message": "Deploy triggered"}
```

### C. Configure GitHub/GitLab

**GitHub:**
1. Repo → Settings → Webhooks → Add webhook
2. Payload URL: `https://intellect-api.salesnet.ng/webhook.php`
3. Content type: `application/json`
4. Secret: paste from `.webhook_secret`
5. Events: Just the **push** event
6. Active: ✅

**GitLab:**
1. Project → Settings → Webhooks
2. URL: `https://intellect-api.salesnet.ng/webhook.php`
3. Secret token: paste from `.webhook_secret`
4. Trigger: **Push events**
5. Add webhook

---

## Option 3: Cron-Based Polling (No Webhook Needed)

If your host blocks webhooks or you want simplicity:

```bash
crontab -e
# Add (checks every 2 minutes):
*/2 * * * * cd /home/salesne2/intellect-api.salesnet.ng && bash deploy/ci.sh > /dev/null 2>&1
```

This polls git every 2 minutes. If `origin/main` moved, it deploys.

**Pros:** No webhook setup, works behind firewalls  
**Cons:** 2-minute delay, unnecessary git fetches

---

## Pipeline Flow

```
Git push → origin/main
    │
    ├───► Webhook ──► webhook.php ──► webhook.sh ──► ci.sh
    │
    └───► Cron poll ───────────────► ci.sh
                                        │
                                        ▼
                                    ┌───────────┐
                                    │ git fetch │
                                    │ git reset │
                                    └───────────┘
                                        │
                                        ▼
                                    ┌───────────┐
                                    │ pip install
                                    │ requirements
                                    └───────────┘
                                        │
                                        ▼
                                    ┌───────────┐      ┌───────────┐
                                    │ pytest    │──NO──► ABORT     │
                                    │ (optional)│      └───────────┘
                                    └───────────┘
                                        │ YES
                                        ▼
                                    ┌───────────┐      ┌───────────┐
                                    │ alembic   │──NO──► ABORT     │
                                    │ upgrade   │      └───────────┘
                                    │ (optional)│
                                    └───────────┘
                                        │ YES
                                        ▼
                                    ┌───────────┐
                                    │ control.sh│
                                    │ restart   │  ← Full restart, new code
                                    └───────────┘
                                        │
                                        ▼
                                    LIVE
```

---

## Configuring config.env

```bash
# deploy/config.env
GIT_BRANCH="main"        # Branch to deploy
RUN_TESTS=false          # Set true when you have tests
RUN_MIGRATIONS=false     # Set true when you have alembic
```

---

## Logs

| Log | Path |
|-----|------|
| Deploy log | `~/intellect-api.salesnet.ng/deploy/deploy.log` |
| Webhook log | `~/intellect-api.salesnet.ng/deploy/webhook.log` |
| App log | `~/intellect-api.salesnet.ng/logs/app.log` |

---

## Rollback on Failed Deploy

If `ci.sh` fails (tests or migrations), it **aborts before restart**. Your running app stays untouched.

To manually rollback:
```bash
cd ~/intellect-api.salesnet.ng
git log --oneline -5          # find last good commit
git reset --hard <commit>     # go back
bash deploy/control.sh restart
```

---

## Security Checklist

- [ ] `.webhook_secret` is `chmod 600`
- [ ] Webhook URL uses HTTPS
- [ ] Secret token is random (32+ chars)
- [ ] Webhook only triggers on `refs/heads/main`
- [ ] `RUN_TESTS=true` before enabling auto-deploy

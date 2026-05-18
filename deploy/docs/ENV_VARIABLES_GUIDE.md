# Environment Variables & Secrets 🔐

## Rule #1: Never commit secrets to git.

## Method: `.env` File (Recommended)

### 1. Install python-dotenv

```bash
source ~/virtualenv/intellect-api.salesnet.ng/3.13/bin/activate
pip install python-dotenv
```

### 2. Create `.env` in app root

```bash
cd ~/intellect-api.salesnet.ng
nano .env
```

Example:

```bash
# Database
DATABASE_URL=postgresql://user:pass@localhost/dbname

# App
SECRET_KEY=$(python -c "import secrets; print(secrets.token_urlsafe(32))")
DEBUG=False

# APIs
STRIPE_SECRET_KEY=sk_live_xxx
```

### 3. Lock it down

```bash
chmod 600 .env
echo ".env" >> .gitignore
```

### 4. Load in FastAPI

```python
from dotenv import load_dotenv
import os

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
SECRET_KEY   = os.getenv("SECRET_KEY")
```

## Supervisor Environment (Optional)

If you prefer env vars in supervisor config, edit:
`~/supervisor/conf.d/intellect-api-salesnet-ng.conf`

```ini
environment=
    PATH="/home/salesne2/virtualenv/.../bin:%(ENV_PATH)s",
    PYTHONUNBUFFERED="1",
    DATABASE_URL="postgresql://..."
```

Then:
```bash
bash deploy/control.sh reload
bash deploy/control.sh restart
```

## Hybrid Mode (Best for Production)

**Supervisor config:**
```ini
environment=
    PATH="...",
    PYTHONUNBUFFERED="1",
    ENV_FILE="/home/salesne2/intellect-api.salesnet.ng/.env"
```

**App:**
```python
from dotenv import load_dotenv
import os

env_file = os.environ.get("ENV_FILE", ".env")
load_dotenv(env_file)
```

## Multiple Environments

```
.env.development
.env.staging
.env.production
```

```python
import os
from dotenv import load_dotenv

ENV = os.getenv("ENVIRONMENT", "development")
load_dotenv(f".env.{ENV}")
```

## Quick Reference

```bash
# Generate secret
python -c "import secrets; print(secrets.token_urlsafe(32))"

# Secure file
chmod 600 .env

# Restart after env change
bash deploy/control.sh restart
```

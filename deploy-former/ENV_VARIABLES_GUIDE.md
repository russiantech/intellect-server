# Environment Variables & Secrets Management 🔐

## Quick Setup for Production Secrets

### Method 1: Using .env File (Recommended)

**Step 1:** Install python-dotenv in your virtualenv

```bash
source ~/virtualenv/api-studentscores.simplylovely.ng/3.13/bin/activate
pip install python-dotenv
```

**Step 2:** Create a `.env` file in your app directory

```bash
cd ~/api-studentscores.simplylovely.ng
nano .env
```

Add your secrets:

```bash
# Database
DATABASE_URL=postgresql://user:pass@localhost/dbname
DB_PASSWORD=your_super_secret_password

# API Keys
STRIPE_SECRET_KEY=sk_live_xxxxxxxxxxxxx
SENDGRID_API_KEY=SG.xxxxxxxxxxxxx

# App Config
SECRET_KEY=your_random_secret_key_here
DEBUG=False
ALLOWED_HOSTS=yourdomain.com,www.yourdomain.com

# External Services
AWS_ACCESS_KEY_ID=AKIAXXXXXXXXXXXXX
AWS_SECRET_ACCESS_KEY=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

**Step 3:** Secure the .env file

```bash
chmod 600 .env  # Only you can read/write
```

**Step 4:** Load in your FastAPI app (main.py)

```python
from dotenv import load_dotenv
import os

# Load environment variables
load_dotenv()

# Access them
DATABASE_URL = os.getenv("DATABASE_URL")
SECRET_KEY = os.getenv("SECRET_KEY")
STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY")

# Or with defaults
DEBUG = os.getenv("DEBUG", "False") == "True"
```

**Step 5:** Add .env to .gitignore

```bash
echo ".env" >> .gitignore
```

**Never commit secrets to git!**

---

### Method 2: Direct Environment Variables in Supervisor

Edit `~/supervisor/conf.d/fastapi-studentscores.conf`:

```ini
[program:fastapi-studentscores]
command=...
directory=...
environment=
    PATH="/home/simpdinr/virtualenv/.../bin:%(ENV_PATH)s",
    PYTHONUNBUFFERED="1",
    DATABASE_URL="postgresql://user:pass@localhost/db",
    SECRET_KEY="your_secret_here",
    STRIPE_SECRET_KEY="sk_live_xxxxx"
```

Then reload:

```bash
bash control.sh reload
bash control.sh restart
```

**Access in Python:**

```python
import os

DATABASE_URL = os.environ.get("DATABASE_URL")
SECRET_KEY = os.environ.get("SECRET_KEY")
```

---

### Method 3: Hybrid (Best for Production)

Combine both methods - use .env for secrets, supervisor for system config:

**Supervisor config:**
```ini
environment=
    PATH="/home/simpdinr/virtualenv/.../bin",
    PYTHONUNBUFFERED="1",
    ENV_FILE="/home/simpdinr/api-studentscores.simplylovely.ng/.env"
```

**In your app:**
```python
from dotenv import load_dotenv
import os

# Load from custom path
env_file = os.environ.get("ENV_FILE", ".env")
load_dotenv(env_file)
```

---

## 🔒 Security Best Practices

### 1. File Permissions

```bash
# .env file - only owner can read
chmod 600 .env

# Config files - only owner can read/write
chmod 600 ~/supervisor/conf.d/*.conf

# Database credentials - only owner
chmod 600 ~/my_app/database.ini
```

### 2. Never Commit Secrets

`.gitignore` should include:
```
.env
.env.*
*.pem
*.key
secrets/
config/secrets.py
database.ini
```

### 3. Rotate Secrets Regularly

```bash
# Generate new secret key
python -c "import secrets; print(secrets.token_urlsafe(32))"

# Update .env file
nano .env

# Restart app
bash control.sh restart
```

### 4. Use Strong Secrets

```python
# Generate strong secret key
import secrets

SECRET_KEY = secrets.token_urlsafe(32)
API_KEY = secrets.token_hex(32)
```

---

## 📦 Database Connection Example

### PostgreSQL with .env

**.env:**
```bash
DB_HOST=localhost
DB_PORT=5432
DB_NAME=myapp
DB_USER=myuser
DB_PASSWORD=super_secret_password
```

**main.py:**
```python
from dotenv import load_dotenv
import os
from sqlalchemy import create_engine

load_dotenv()

DATABASE_URL = (
    f"postgresql://{os.getenv('DB_USER')}:"
    f"{os.getenv('DB_PASSWORD')}@"
    f"{os.getenv('DB_HOST')}:"
    f"{os.getenv('DB_PORT')}/"
    f"{os.getenv('DB_NAME')}"
)

engine = create_engine(DATABASE_URL)
```

---

## 🌐 Multiple Environments

For dev/staging/production:

**Structure:**
```
.env.development
.env.staging
.env.production
```

**Load based on environment:**
```python
import os
from dotenv import load_dotenv

ENV = os.getenv("ENVIRONMENT", "development")
load_dotenv(f".env.{ENV}")
```

**In supervisor config:**
```ini
environment=ENVIRONMENT="production"
```

---

## 🔑 API Keys & External Services

### Example with Multiple Services

**.env:**
```bash
# Stripe
STRIPE_PUBLIC_KEY=pk_live_xxxxx
STRIPE_SECRET_KEY=sk_live_xxxxx
STRIPE_WEBHOOK_SECRET=whsec_xxxxx

# SendGrid
SENDGRID_API_KEY=SG.xxxxx
FROM_EMAIL=noreply@yourdomain.com

# AWS S3
AWS_ACCESS_KEY_ID=AKIAXXXXX
AWS_SECRET_ACCESS_KEY=xxxxx
AWS_BUCKET_NAME=my-app-uploads
AWS_REGION=us-east-1

# OAuth
GOOGLE_CLIENT_ID=xxxxx.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=xxxxx
FACEBOOK_APP_ID=xxxxx
FACEBOOK_APP_SECRET=xxxxx
```

**main.py:**
```python
from dotenv import load_dotenv
import os

load_dotenv()

class Config:
    # Stripe
    STRIPE_PUBLIC_KEY = os.getenv("STRIPE_PUBLIC_KEY")
    STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY")
    
    # SendGrid
    SENDGRID_API_KEY = os.getenv("SENDGRID_API_KEY")
    FROM_EMAIL = os.getenv("FROM_EMAIL")
    
    # AWS
    AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID")
    AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY")
    AWS_BUCKET_NAME = os.getenv("AWS_BUCKET_NAME")
    AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
```

---

## ⚠️ Common Mistakes to Avoid

### ❌ Don't Do This:

```python
# Hardcoded secrets
SECRET_KEY = "my_secret_key_123"  # BAD!
DATABASE_URL = "postgresql://user:password@localhost/db"  # BAD!
```

```bash
# Committing .env to git
git add .env  # NEVER!
```

```bash
# World-readable secrets
chmod 644 .env  # BAD! Others can read it
```

### ✅ Do This Instead:

```python
# Load from environment
SECRET_KEY = os.getenv("SECRET_KEY")
if not SECRET_KEY:
    raise ValueError("SECRET_KEY not set!")
```

```bash
# Secure permissions
chmod 600 .env

# Add to .gitignore
echo ".env" >> .gitignore
```

---

## 🔄 Updating Secrets

When you need to change secrets:

```bash
# 1. Edit .env file
nano ~/api-studentscores.simplylovely.ng/.env

# 2. Restart app (will reload .env)
bash ~/api-studentscores.simplylovely.ng/control.sh restart

# 3. Verify (check logs for any errors)
bash ~/api-studentscores.simplylovely.ng/control.sh logs
```

---

## 📋 Template .env File

Create this as `.env.template` (commit this one to git):

```bash
# Database Configuration
DATABASE_URL=postgresql://user:password@localhost/dbname
DB_PASSWORD=

# Application Secrets
SECRET_KEY=
JWT_SECRET_KEY=
ENCRYPTION_KEY=

# API Keys
STRIPE_SECRET_KEY=
SENDGRID_API_KEY=
AWS_ACCESS_KEY_ID=
AWS_SECRET_ACCESS_KEY=

# Application Settings
DEBUG=False
ALLOWED_HOSTS=yourdomain.com
CORS_ORIGINS=https://yourdomain.com

# External Services
REDIS_URL=redis://localhost:6379
CELERY_BROKER_URL=redis://localhost:6379
```

Users copy this to `.env` and fill in their values:

```bash
cp .env.template .env
nano .env  # Fill in actual values
```

---

## 🎯 Quick Reference

```bash
# Install dotenv
pip install python-dotenv

# Create .env
nano .env

# Secure it
chmod 600 .env

# Add to gitignore
echo ".env" >> .gitignore

# Generate secret key
python -c "import secrets; print(secrets.token_urlsafe(32))"

# Restart after changes
bash control.sh restart
```

---

**Remember:** Secrets in .env, never in git! 🔐

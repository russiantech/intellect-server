# Pre-Flight Checklist ✈️

Before running the deployment script, verify these items:

## ✅ Required Information

- [ ] **Virtualenv path** - Get it from cPanel's Python app settings or run:
  ```bash
  find ~/ -name "activate" -path "*/virtualenv/*" 2>/dev/null
  ```
  Should look like: `/home/simpdinr/virtualenv/DOMAIN/3.X/bin/activate`

- [ ] **App directory** - Where your `main.py` lives:
  ```bash
  find ~/ -name "main.py" -type f 2>/dev/null
  ```
  Should look like: `/home/simpdinr/DOMAIN/main.py`

- [ ] **Port number** - Must be unique, typically 8001-8999
  Check if port is free:
  ```bash
  netstat -tlnp | grep 8001
  ```
  (No output = port is free)

## ✅ App Requirements

- [ ] **main.py exists** in your app directory
- [ ] **FastAPI installed** in virtualenv:
  ```bash
  source /path/to/venv/bin/activate
  python -c "import fastapi; print('FastAPI installed')"
  ```

- [ ] **uvicorn installed**:
  ```bash
  python -c "import uvicorn; print('Uvicorn installed')"
  ```

- [ ] **App runs manually** (test first!):
  ```bash
  cd /path/to/app
  source /path/to/venv/bin/activate
  uvicorn main:app --host 0.0.0.0 --port 8001
  ```
  Press Ctrl+C to stop after confirming it works.

## ✅ Edit the Deployment Script

Before running, open `deploy-fastapi.sh` and update these lines:

```bash
VENV_PATH="/home/simpdinr/virtualenv/api-studentscores.simplylovely.ng/3.13"
                    ^^^^^^^^^^^^^^^^ YOUR virtualenv path

APP_DIR="/home/simpdinr/api-studentscores.simplylovely.ng"
                    ^^^^^^^^^^^^^^^^ YOUR app directory

APP_NAME="fastapi-studentscores"
         ^^^^^^^^^^^^^^^^^^ A name for your app (no spaces)

UVICORN_PORT="8001"
              ^^^^ Your chosen port
```

## ✅ File Permissions

- [ ] Upload `deploy-fastapi.sh` to your home directory
- [ ] Make it executable:
  ```bash
  chmod +x deploy-fastapi.sh
  ```

## 🚀 Ready to Deploy?

If all checkboxes are marked:

```bash
bash deploy-fastapi.sh
```

This will take 30-60 seconds and will:
1. ✅ Install Supervisor
2. ✅ Create configuration files
3. ✅ Set up auto-start on reboot
4. ✅ Start your app
5. ✅ Create control script
6. ✅ Generate documentation

## 🆘 If Something Goes Wrong

1. **Check the error message** - The script shows clear errors
2. **Verify paths** - Most errors are from wrong paths
3. **Test manually first** - Make sure app runs with uvicorn directly
4. **Check logs** - After deployment: `bash control.sh logs`

## 📋 After Deployment

Test your deployed app:

```bash
# Check status
bash ~/YOUR_APP_DIR/control.sh status

# View logs
bash ~/YOUR_APP_DIR/control.sh logs

# Test the endpoint
curl http://localhost:YOUR_PORT/
```

## 🎯 Quick Path Finder Commands

Copy/paste these to find your paths:

```bash
# Find virtualenv
echo "=== Virtualenv paths ==="
find ~/ -name "activate" -path "*/virtualenv/*" 2>/dev/null

# Find main.py
echo "=== App directories (contains main.py) ==="
find ~/ -name "main.py" -type f 2>/dev/null | xargs dirname

# Find free ports
echo "=== Ports in use ==="
netstat -tlnp 2>/dev/null | grep -E "800[0-9]|80[1-9][0-9]"

# Your username
echo "=== Username ==="
whoami
```

---

Good luck! 🚀

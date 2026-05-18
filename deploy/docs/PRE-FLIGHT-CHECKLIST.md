# Pre-Flight Checklist ✈️

Before running `deploy.sh`, verify:

## Required Info

- [ ] **cPanel username** — `whoami`
- [ ] **Domain** — exactly as in cPanel Python Apps (`intellect-api.salesnet.ng`)
- [ ] **Python version** — must match cPanel assignment (`3.13`)
- [ ] **Port** — unique, 8001–8999, not in use by other apps

## Verify Paths

```bash
# Virtualenv
ls ~/virtualenv/intellect-api.salesnet.ng/3.13/bin/activate

# App directory
ls ~/intellect-api.salesnet.ng/main.py

# Port free
netstat -tlnp | grep 8001   # should be empty
```

## Edit config.env

```bash
cd ~/intellect-api.salesnet.ng/deploy
nano config.env
```

Ensure these match your cPanel setup:
```bash
CPANEL_USER="salesne2"
DOMAIN="intellect-api.salesnet.ng"
PYTHON_VERSION="3.13"
PORT=8001
```

## Manual Test

```bash
cd ~/intellect-api.salesnet.ng
source ~/virtualenv/intellect-api.salesnet.ng/3.13/bin/activate
uvicorn main:app --host 0.0.0.0 --port 8001
# Ctrl+C when confirmed working
```

## Ready?

```bash
bash deploy/deploy.sh
```

Takes ~60 seconds. Then:

```bash
bash deploy/control.sh status
bash deploy/control.sh health
```

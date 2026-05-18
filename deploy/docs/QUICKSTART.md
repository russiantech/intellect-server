# Quick Start Guide

## One-Time Setup

```bash
# 1. Upload your app to cPanel Python Apps
# 2. Ensure main.py exists
# 3. Edit deploy/config.env

bash deploy/deploy.sh
```

Done. Your app is live.

## Daily Commands

```bash
# Status
bash deploy/control.sh status

# Logs (live)
bash deploy/control.sh logs
bash deploy/control.sh logs-err

# Restart after code change
bash deploy/control.sh restart

# Full health check
bash deploy/control.sh health

# Worker memory usage
bash deploy/control.sh workers

# Virtualenv shell
bash deploy/control.sh shell
```

## Deploy Code Updates

```bash
cd ~/intellect-api.salesnet.ng
git pull origin main
bash deploy/control.sh restart
```

Or use the CI/CD pipeline:

```bash
bash deploy/release.sh
```

## Install Dependencies

```bash
bash deploy/control.sh shell
pip install -r requirements.txt
exit
bash deploy/control.sh restart
```

## Troubleshooting

### App won't start
```bash
bash deploy/control.sh logs-err
```

### Port in use
```bash
bash deploy/control.sh restart   # kills old, starts new
```

### After reboot
```bash
# Wait 30s for cron, then:
bash deploy/control.sh status
```

### Supervisor stuck
```bash
bash deploy/control.sh kill
sleep 2
bash deploy/control.sh start
```

## Cron Setup

```bash
# Auto-recovery every 5 minutes
crontab -e
# Add:
*/5 * * * * bash /home/salesne2/intellect-api.salesnet.ng/deploy/monitor.sh
```

## File Locations

| File | Path |
|------|------|
| Config | `~/intellect-api.salesnet.ng/deploy/config.env` |
| App logs | `~/intellect-api.salesnet.ng/logs/app.log` |
| Access logs | `~/intellect-api.salesnet.ng/logs/access.log` |
| Supervisor logs | `~/supervisor/logs/supervisord.log` |
| Monitor logs | `~/supervisor/logs/monitor.log` |

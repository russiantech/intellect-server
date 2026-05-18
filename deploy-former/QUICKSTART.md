# FastAPI Production Deployment on cPanel - Complete Guide

## 📦 What You're Getting

This deployment package gives you **production-grade FastAPI hosting** on cPanel with:

✅ **Automatic crash recovery** - App restarts if it crashes  
✅ **Memory kill protection** - Restarts if killed by cPanel  
✅ **Boot persistence** - Auto-starts after server reboots  
✅ **Process monitoring** - Supervisor keeps everything running  
✅ **Log management** - Automatic log rotation  
✅ **Easy control** - Simple commands to manage everything  

---

## 🚀 Installation (One-Time Setup)

### Step 1: Upload the deployment script

Upload `deploy-fastapi.sh` to your server and edit the configuration section:

```bash
# Edit these lines at the top of deploy-fastapi.sh:
VENV_PATH="/home/simpdinr/virtualenv/api-studentscores.simplylovely.ng/3.13"
APP_DIR="/home/simpdinr/api-studentscores.simplylovely.ng"
APP_NAME="fastapi-studentscores"
UVICORN_HOST="0.0.0.0"
UVICORN_PORT="8001"
```

### Step 2: Make it executable and run

```bash
chmod +x deploy-fastapi.sh
bash deploy-fastapi.sh
```

That's it! The script will:
- Install Supervisor in your virtualenv
- Create all configuration files
- Set up auto-start on reboot
- Start your FastAPI app
- Create a control script for easy management

### Step 3: Verify it's running

```bash
bash ~/api-studentscores.simplylovely.ng/control.sh status
```

You should see:
```
fastapi-studentscores         RUNNING   pid 12345, uptime 0:00:05
```

---

## 🎮 Daily Usage - Control Commands

All commands use the control script created in your app directory:

```bash
cd ~/api-studentscores.simplylovely.ng

# Start the app
bash control.sh start

# Stop the app  
bash control.sh stop

# Restart the app (after code changes)
bash control.sh restart

# Check if running
bash control.sh status

# View live logs
bash control.sh logs

# View error logs
bash control.sh logs-err

# Get a shell with virtualenv activated
bash control.sh shell
```

---

## 🔄 Common Workflows

### Deploying Code Updates

```bash
cd ~/api-studentscores.simplylovely.ng

# Pull your latest code
git pull
# OR upload new files via FTP/cPanel

# Restart to apply changes
bash control.sh restart

# Check it started successfully
bash control.sh status
```

### Installing New Python Packages

```bash
cd ~/api-studentscores.simplylovely.ng

# Activate virtualenv
source ~/virtualenv/api-studentscores.simplylovely.ng/3.13/bin/activate

# Install packages
pip install new-package

# Restart app
bash control.sh restart
```

### Viewing Logs

```bash
# Watch live application logs
bash control.sh logs

# Exit with Ctrl+C

# View supervisor daemon logs
bash control.sh logs-err

# Or manually check files:
tail -f ~/api-studentscores.simplylovely.ng/logs/app.log
tail -f ~/supervisor/logs/supervisord.log
```

### Changing Port or Configuration

```bash
# Edit the supervisor config
nano ~/supervisor/conf.d/fastapi-studentscores.conf

# Find the line:
# command=/home/simpdinr/.../uvicorn main:app --host 0.0.0.0 --port 8001

# Change port or add options like --workers 2

# Reload configuration
bash control.sh reload

# Restart app
bash control.sh restart
```

---

## 🛡️ What Happens When...

| Scenario | What Happens | Action Required |
|----------|-------------|-----------------|
| **App crashes** | ✅ Auto-restarts in ~1 second | None |
| **Out of memory** | ✅ Auto-restarts when killed | None |
| **You disconnect SSH** | ✅ Keeps running | None |
| **Server reboots** | ✅ Auto-starts in ~30 seconds | None |
| **Manual kill** | ✅ Auto-restarts immediately | None |
| **Code update** | 🔄 Needs restart | `bash control.sh restart` |
| **Config change** | 🔄 Needs reload+restart | `bash control.sh reload && bash control.sh restart` |

---

## 🔧 Advanced Features

### Multiple Workers (for better performance)

Edit `~/supervisor/conf.d/fastapi-studentscores.conf`:

```bash
# Change this line:
command=.../uvicorn main:app --host 0.0.0.0 --port 8001 --workers 4

# Reload and restart:
bash control.sh reload
bash control.sh restart
```

**Recommended workers:** Number of CPU cores (usually 1-4 on shared hosting)

### Adding a Health Check Endpoint (Recommended)

Add to your `main.py`:

```python
@app.get("/health")
async def health_check():
    return {"status": "ok", "timestamp": datetime.now().isoformat()}
```

This allows monitoring scripts to verify your app is responding.

### Extra Monitoring Layer (Optional)

For maximum reliability, add the monitoring script to cron:

```bash
# Make monitor script executable
chmod +x ~/api-studentscores.simplylovely.ng/monitor.sh

# Add to crontab (checks every 5 minutes)
crontab -e

# Add this line:
*/5 * * * * /home/simpdinr/api-studentscores.simplylovely.ng/monitor.sh
```

This adds HTTP health checks on top of Supervisor's process monitoring.

---

## 🆘 Troubleshooting

### App Won't Start

**Check the logs:**
```bash
bash control.sh logs
```

**Common issues:**
- Port already in use → Change port in config
- Import errors → Check virtualenv has all dependencies
- Syntax errors → Fix in main.py

**Try manual start to see full error:**
```bash
cd ~/api-studentscores.simplylovely.ng
source ~/virtualenv/api-studentscores.simplylovely.ng/3.13/bin/activate
uvicorn main:app --host 0.0.0.0 --port 8001
# (Press Ctrl+C when done troubleshooting)
```

### Port Already in Use

```bash
# Find what's using the port
lsof -i :8001

# Kill it
kill -9 <PID>

# Or just restart everything
bash control.sh kill
sleep 2
bash control.sh start
```

### Supervisor Not Responding

```bash
# Complete restart
bash control.sh kill
sleep 2
bash control.sh start

# Or manually:
pkill -f supervisord
sleep 2
~/virtualenv/api-studentscores.simplylovely.ng/3.13/bin/supervisord -c ~/supervisor/supervisord.conf
```

### Check What's Actually Running

```bash
# Process list
ps aux | grep uvicorn
ps aux | grep supervisord

# Network connections
netstat -tlnp | grep 8001

# Supervisor status
bash control.sh status
```

### After Server Reboot

The cron job should auto-start everything in ~30 seconds. If not:

```bash
# Check cron job exists
crontab -l | grep supervisor

# Manually start
bash control.sh start

# Check logs for boot issues
cat ~/supervisor/logs/supervisord.log
```

---

## 📁 File Locations

| What | Where |
|------|-------|
| **Control Script** | `~/api-studentscores.simplylovely.ng/control.sh` |
| **App Logs** | `~/api-studentscores.simplylovely.ng/logs/app.log` |
| **Supervisor Config** | `~/supervisor/supervisord.conf` |
| **App Config** | `~/supervisor/conf.d/fastapi-studentscores.conf` |
| **Supervisor Logs** | `~/supervisor/logs/supervisord.log` |
| **Monitor Script** | `~/api-studentscores.simplylovely.ng/monitor.sh` |

---

## 🗑️ Uninstallation

To completely remove the deployment (keeps your app code):

```bash
bash uninstall.sh
```

This removes:
- Supervisor daemon and configs
- Log files  
- Control scripts
- Cron jobs

Your app code and virtualenv are preserved.

---

## 💡 Pro Tips

1. **Check logs regularly** - `bash control.sh logs` helps catch issues early

2. **Set up log rotation** - Included automatically, but keep an eye on disk space

3. **Use a reverse proxy** - Apache/nginx → your app for production (usually cPanel handles this)

4. **Monitor resource usage** - cPanel's metrics panel shows CPU/RAM usage

5. **Test before deploying** - Always test code changes locally first

6. **Keep backups** - Regularly backup your app code and database

7. **Version control** - Use git for code management

8. **Environment variables** - Use `.env` file for secrets (never commit it!)

---

## 📊 Comparison vs Other Methods

| Method | Crash Recovery | Memory Kill | Reboot | Complexity |
|--------|---------------|-------------|---------|------------|
| **nohup only** | ❌ | ❌ | ❌ | Low |
| **Cron polling** | ✅ | ✅ | ✅ | Medium |
| **Supervisor (this)** | ✅ | ✅ | ✅ | Medium |
| **systemd** | ✅ | ✅ | ✅ | High (needs root) |
| **Docker** | ✅ | ✅ | ✅ | High (often blocked) |

**Winner:** Supervisor gives you systemd-like reliability without needing root access!

---

## 🤝 Support

If you run into issues:

1. Check the logs: `bash control.sh logs`
2. Review this guide's troubleshooting section
3. Verify configuration in `~/supervisor/conf.d/`
4. Check cPanel resource limits
5. Test manual start to isolate the issue

---

## 📝 Quick Reference Card

Print or save this for quick access:

```bash
# === MOST USED COMMANDS ===

# Start/Stop/Restart
bash control.sh start
bash control.sh stop  
bash control.sh restart

# Check Status
bash control.sh status

# View Logs
bash control.sh logs

# After Code Update
bash control.sh restart

# === LOCATIONS ===
# Control script: ~/api-studentscores.simplylovely.ng/control.sh
# App logs: ~/api-studentscores.simplylovely.ng/logs/app.log
# Config: ~/supervisor/conf.d/fastapi-studentscores.conf
```

---

**Deployment Date:** (filled in by script)  
**Version:** 1.0  
**Last Updated:** February 2026

Happy deploying! 🚀

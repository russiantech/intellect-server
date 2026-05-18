# FastAPI Production Deployment Package for cPanel 🚀

## 📦 What's Included

This complete deployment package gives you production-ready FastAPI hosting on cPanel with enterprise-grade reliability:

- ✅ **Automatic crash recovery**
- ✅ **Memory kill protection** 
- ✅ **Server reboot persistence**
- ✅ **Process monitoring with Supervisor**
- ✅ **Automatic log rotation**
- ✅ **Simple management commands**
- ✅ **Environment variables & secrets management**

## 📁 Files in This Package

| File | Purpose |
|------|---------|
| `deploy-fastapi.sh` | 🎯 **Main deployment script** - Run this once to set everything up |
| `QUICKSTART.md` | 📖 Complete usage guide with examples |
| `PRE-FLIGHT-CHECKLIST.md` | ✈️ Verify requirements before deploying |
| `ENV_VARIABLES_GUIDE.md` | 🔐 Secrets & environment variables setup |
| `monitor.sh` | 🔍 Optional health monitoring script |
| `uninstall.sh` | 🗑️ Clean removal script |

## 🚀 Quick Start (5 Minutes)

### Step 1: Pre-Flight Check ✈️

Open `PRE-FLIGHT-CHECKLIST.md` and verify:
- ✅ You have your virtualenv path
- ✅ You know your app directory
- ✅ Your app runs manually with uvicorn
- ✅ You have a free port (8001-8999)

### Step 2: Configure Deployment 🔧

Edit `deploy-fastapi.sh` and update these lines (around line 17):

```bash
VENV_PATH="/home/YOUR_USER/virtualenv/YOUR_DOMAIN/3.13"
APP_DIR="/home/YOUR_USER/YOUR_DOMAIN"
APP_NAME="your-app-name"
UVICORN_PORT="8001"
```

### Step 3: Upload & Deploy 📤

Upload all files to your server, then:

```bash
# Make executable
chmod +x deploy-fastapi.sh

# Run deployment
bash deploy-fastapi.sh
```

The script will install everything and start your app in ~60 seconds.

### Step 4: Verify ✓

```bash
# Check status
bash ~/YOUR_APP_DIR/control.sh status

# Should show: RUNNING
```

## 🎮 Daily Usage

After deployment, use the `control.sh` script created in your app directory:

```bash
cd ~/YOUR_APP_DIR

# Start/stop/restart
bash control.sh start
bash control.sh stop
bash control.sh restart

# Check status & logs
bash control.sh status
bash control.sh logs

# After code updates
git pull  # or upload new files
bash control.sh restart
```

**Full documentation:** See `QUICKSTART.md` for detailed examples and workflows.

## 🏗️ Architecture

```
Your Setup After Deployment:
├── ~/supervisor/
│   ├── supervisord.conf          # Main supervisor config
│   ├── conf.d/
│   │   └── your-app.conf         # Your app configuration
│   └── logs/
│       └── supervisord.log       # Supervisor logs
│
├── ~/YOUR_APP_DIR/
│   ├── main.py                   # Your FastAPI app
│   ├── control.sh               # ⭐ Management script
│   ├── monitor.sh               # Optional monitoring
│   ├── .env                     # Secrets (you create)
│   └── logs/
│       └── app.log              # Application logs
│
└── crontab
    └── @reboot → start supervisor  # Auto-start after reboot
```

## 🛡️ What Gets Protected

| Scenario | Without Deployment | With This Deployment |
|----------|-------------------|---------------------|
| App crashes | ❌ Process dies | ✅ Auto-restarts in 1s |
| Out of memory | ❌ Killed | ✅ Auto-restarts |
| Server reboot | ❌ Gone forever | ✅ Auto-starts in 30s |
| SSH disconnect | ✅ Keeps running | ✅ Keeps running |
| Manual kill | ❌ Stays dead | ✅ Auto-restarts |
| cPanel limits | ❌ Dies | ✅ Restarts when possible |

## 📚 Documentation Guide

### For First-Time Setup:
1. Read `PRE-FLIGHT-CHECKLIST.md` ← Start here!
2. Edit `deploy-fastapi.sh` configuration
3. Run deployment
4. Read `QUICKSTART.md` for daily usage

### For Production Secrets:
- Read `ENV_VARIABLES_GUIDE.md`
- Create `.env` file
- Never commit secrets to git

### For Ongoing Management:
- Keep `QUICKSTART.md` handy
- Reference the troubleshooting section
- Use `control.sh` for everything

## 🔧 Common Tasks

### Deploying Code Updates
```bash
cd ~/YOUR_APP_DIR
git pull
bash control.sh restart
```

### Installing Dependencies
```bash
source ~/virtualenv/YOUR_DOMAIN/3.X/bin/activate
pip install new-package
bash control.sh restart
```

### Viewing Logs
```bash
bash control.sh logs  # Live tail
# Press Ctrl+C to exit
```

### Changing Port
```bash
nano ~/supervisor/conf.d/your-app.conf
# Edit port number
bash control.sh reload
bash control.sh restart
```

## 🆘 Troubleshooting

### App won't start?
```bash
bash control.sh logs  # Check for errors
```

### Port already in use?
```bash
bash control.sh restart  # Will kill old process
```

### After server reboot?
```bash
# Wait 30 seconds, then check:
bash control.sh status
```

**Full troubleshooting guide:** See `QUICKSTART.md` → Troubleshooting section

## 🔒 Security Features

- ✅ Secrets stored in `.env` file (not in code)
- ✅ Proper file permissions (600 for sensitive files)
- ✅ Process runs as your user (not root)
- ✅ Logs rotated automatically
- ✅ No ports exposed publicly without your setup

## ⚙️ Advanced Features

### Multiple Workers (Better Performance)
Edit `~/supervisor/conf.d/your-app.conf`:
```ini
command=.../uvicorn main:app --host 0.0.0.0 --port 8001 --workers 4
```

### Health Monitoring (Extra Reliability)
```bash
chmod +x monitor.sh
crontab -e
# Add: */5 * * * * /home/USER/APP_DIR/monitor.sh
```

### Environment Variables
See `ENV_VARIABLES_GUIDE.md` for complete setup

## 📊 Comparison to Other Methods

| Method | Pros | Cons | Best For |
|--------|------|------|----------|
| **nohup only** | Simple | No recovery | Quick tests |
| **Cron polling** | Works anywhere | Resource waste | Fallback option |
| **This (Supervisor)** | ✅ Best reliability<br>✅ Easy management<br>✅ Production-ready | Requires setup | **Production apps** ← You! |
| systemd | Perfect control | Needs root | VPS/dedicated |
| Docker | Containerized | Often blocked | Cloud hosting |

## 🗑️ Uninstallation

To completely remove (keeps your app code):

```bash
bash uninstall.sh
```

## 💡 Pro Tips

1. **Always test manually first** - Make sure uvicorn works before deploying
2. **Use version control** - Git for your app code
3. **Keep .env secure** - chmod 600, never commit
4. **Monitor logs regularly** - `bash control.sh logs`
5. **Set up backups** - Your app code and database
6. **Read QUICKSTART.md** - It has everything you need

## 📞 Getting Help

**Before asking for help, check:**
1. `bash control.sh logs` - What's the actual error?
2. `bash control.sh status` - Is it running?
3. QUICKSTART.md troubleshooting section
4. Did you edit the configuration correctly?

**Common mistakes:**
- ❌ Wrong virtualenv path
- ❌ Wrong app directory
- ❌ Port already in use
- ❌ Missing dependencies in virtualenv

## ✨ What Makes This Special

Unlike basic `nohup` or cron solutions:

- **True process supervision** - Not just checking if running
- **Instant restarts** - No polling delay
- **Resource efficient** - Supervisor uses ~2MB RAM
- **Battle-tested** - Used by thousands of production systems
- **Professional tools** - Same tech used by big companies
- **No root needed** - Works in shared hosting

## 🎯 Next Steps

After deployment:

1. ✅ Verify it's running: `bash control.sh status`
2. ✅ Test your endpoints: `curl http://localhost:PORT/`
3. ✅ Set up .env for secrets (see ENV_VARIABLES_GUIDE.md)
4. ✅ Configure your reverse proxy (usually via cPanel)
5. ✅ Set up backups for your code and database
6. ✅ Add health monitoring endpoint to your app
7. ✅ Bookmark QUICKSTART.md for reference

## 📝 Quick Commands Cheat Sheet

```bash
# Most used commands
bash control.sh start    # Start app
bash control.sh stop     # Stop app
bash control.sh restart  # Restart (after code changes)
bash control.sh status   # Check if running
bash control.sh logs     # View live logs

# Less common
bash control.sh reload   # Reload config (after editing .conf)
bash control.sh shell    # Get virtualenv shell
bash control.sh kill     # Stop supervisor completely
```

## 🚀 You're Ready!

Everything is prepared for a professional FastAPI deployment. Follow the steps above and you'll have a production-ready setup in minutes.

**Start with:** `PRE-FLIGHT-CHECKLIST.md`  
**Deploy with:** `bash deploy-fastapi.sh`  
**Manage with:** `bash control.sh`  
**Learn more:** `QUICKSTART.md`

Good luck! 🎉

---

**Package Version:** 1.0  
**Created:** February 2026  
**Compatible with:** cPanel, shared hosting, VPS (without root)  
**Tested on:** Ubuntu, CentOS, CloudLinux

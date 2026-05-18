#!/bin/bash

###############################################################################
# FastAPI Deployment Script for cPanel with Supervisor
# This script sets up a production-ready FastAPI deployment with:
# - Supervisor for process management
# - Automatic crash recovery
# - Boot persistence via cron
# - Log rotation
# - Easy management commands
###############################################################################

set -e  # Exit on error

# ========== CONFIGURATION ==========
# EDIT THESE VALUES FOR YOUR SETUP

VENV_PATH="/home/simpdinr/virtualenv/api-studentscores.simplylovely.ng/3.13"
APP_DIR="/home/simpdinr/api-studentscores.simplylovely.ng"
APP_NAME="fastapi-studentscores"
UVICORN_HOST="0.0.0.0"
UVICORN_PORT="8001"
SUPERVISOR_DIR="$HOME/supervisor"

# Advanced settings (usually don't need to change)
UVICORN_WORKERS=1  # Set to number of CPU cores if you want multiple workers
UVICORN_EXTRA_ARGS=""  # e.g., "--reload" for development

# ========== COLORS FOR OUTPUT ==========
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# ========== HELPER FUNCTIONS ==========

print_step() {
    echo -e "${BLUE}==>${NC} ${GREEN}$1${NC}"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

check_requirements() {
    print_step "Checking requirements..."
    
    if [ ! -f "$VENV_PATH/bin/activate" ]; then
        print_error "Virtualenv not found at: $VENV_PATH"
        exit 1
    fi
    
    if [ ! -d "$APP_DIR" ]; then
        print_error "App directory not found at: $APP_DIR"
        exit 1
    fi
    
    if [ ! -f "$APP_DIR/main.py" ]; then
        print_error "main.py not found in: $APP_DIR"
        exit 1
    fi
    
    print_success "All requirements met"
}

install_supervisor() {
    print_step "Installing Supervisor..."
    
    source "$VENV_PATH/bin/activate"
    pip install supervisor --quiet
    
    print_success "Supervisor installed"
}

create_directories() {
    print_step "Creating directory structure..."
    
    mkdir -p "$SUPERVISOR_DIR/conf.d"
    mkdir -p "$SUPERVISOR_DIR/logs"
    mkdir -p "$APP_DIR/logs"
    
    print_success "Directories created"
}

create_supervisord_config() {
    print_step "Creating supervisord.conf..."
    
    cat > "$SUPERVISOR_DIR/supervisord.conf" << EOF
[unix_http_server]
file=$SUPERVISOR_DIR/supervisor.sock
chmod=0700

[supervisord]
logfile=$SUPERVISOR_DIR/logs/supervisord.log
logfile_maxbytes=50MB
logfile_backups=10
loglevel=info
pidfile=$SUPERVISOR_DIR/supervisord.pid
nodaemon=false
minfds=1024
minprocs=200

[rpcinterface:supervisor]
supervisor.rpcinterface_factory = supervisor.rpcinterface:make_main_rpcinterface

[supervisorctl]
serverurl=unix://$SUPERVISOR_DIR/supervisor.sock

[include]
files = $SUPERVISOR_DIR/conf.d/*.conf
EOF
    
    print_success "supervisord.conf created"
}

create_app_config() {
    print_step "Creating FastAPI app configuration..."
    
    cat > "$SUPERVISOR_DIR/conf.d/$APP_NAME.conf" << EOF
[program:$APP_NAME]
command=$VENV_PATH/bin/uvicorn main:app --host $UVICORN_HOST --port $UVICORN_PORT --workers $UVICORN_WORKERS $UVICORN_EXTRA_ARGS
directory=$APP_DIR
user=$(whoami)
autostart=true
autorestart=true
startretries=999999
stopwaitsecs=10
redirect_stderr=true
stdout_logfile=$APP_DIR/logs/app.log
stdout_logfile_maxbytes=50MB
stdout_logfile_backups=10
environment=PATH="$VENV_PATH/bin:%(ENV_PATH)s",PYTHONUNBUFFERED="1"

; Resource limits (adjust if needed)
; priority=999
; stopasgroup=true
; killasgroup=true
EOF
    
    print_success "App configuration created"
}

create_control_script() {
    print_step "Creating control script..."
    
    cat > "$APP_DIR/control.sh" << 'SCRIPT_EOF'
#!/bin/bash

# ========== CONFIGURATION ==========
SUPERVISOR_DIR="$HOME/supervisor"
VENV_PATH="/home/simpdinr/virtualenv/api-studentscores.simplylovely.ng/3.13"
APP_NAME="fastapi-studentscores"
APP_DIR="/home/simpdinr/api-studentscores.simplylovely.ng"

SUPERVISORCTL="$VENV_PATH/bin/supervisorctl -c $SUPERVISOR_DIR/supervisord.conf"
SUPERVISORD="$VENV_PATH/bin/supervisord -c $SUPERVISOR_DIR/supervisord.conf"

# ========== COLORS ==========
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# ========== FUNCTIONS ==========

print_usage() {
    echo "FastAPI Control Script"
    echo ""
    echo "Usage: $0 [command]"
    echo ""
    echo "Commands:"
    echo "  start       Start the FastAPI app and Supervisor"
    echo "  stop        Stop the FastAPI app"
    echo "  restart     Restart the FastAPI app"
    echo "  status      Show app status"
    echo "  logs        Show app logs (tail -f)"
    echo "  logs-err    Show error logs"
    echo "  supervisor  Start Supervisor daemon"
    echo "  kill        Stop Supervisor completely"
    echo "  reload      Reload Supervisor configuration"
    echo "  shell       Activate virtualenv and cd to app"
    echo ""
}

start_supervisor() {
    if [ -f "$SUPERVISOR_DIR/supervisord.pid" ] && kill -0 $(cat "$SUPERVISOR_DIR/supervisord.pid") 2>/dev/null; then
        echo -e "${YELLOW}Supervisor is already running${NC}"
    else
        echo -e "${BLUE}Starting Supervisor...${NC}"
        $SUPERVISORD
        sleep 2
        echo -e "${GREEN}Supervisor started${NC}"
    fi
}

cmd_start() {
    start_supervisor
    echo -e "${BLUE}Starting $APP_NAME...${NC}"
    $SUPERVISORCTL start $APP_NAME
    sleep 1
    $SUPERVISORCTL status $APP_NAME
}

cmd_stop() {
    echo -e "${BLUE}Stopping $APP_NAME...${NC}"
    $SUPERVISORCTL stop $APP_NAME
}

cmd_restart() {
    echo -e "${BLUE}Restarting $APP_NAME...${NC}"
    $SUPERVISORCTL restart $APP_NAME
    sleep 1
    $SUPERVISORCTL status $APP_NAME
}

cmd_status() {
    $SUPERVISORCTL status $APP_NAME
}

cmd_logs() {
    tail -f "$APP_DIR/logs/app.log"
}

cmd_logs_err() {
    tail -f "$SUPERVISOR_DIR/logs/supervisord.log"
}

cmd_supervisor() {
    start_supervisor
    $SUPERVISORCTL status
}

cmd_kill() {
    echo -e "${YELLOW}Stopping all Supervisor processes...${NC}"
    $SUPERVISORCTL shutdown
    echo -e "${GREEN}Supervisor stopped${NC}"
}

cmd_reload() {
    echo -e "${BLUE}Reloading Supervisor configuration...${NC}"
    $SUPERVISORCTL reread
    $SUPERVISORCTL update
    echo -e "${GREEN}Configuration reloaded${NC}"
}

cmd_shell() {
    echo -e "${GREEN}Activating virtualenv and changing to app directory...${NC}"
    echo -e "${YELLOW}Run: source $VENV_PATH/bin/activate && cd $APP_DIR${NC}"
    cd "$APP_DIR"
    bash --rcfile <(echo "source $VENV_PATH/bin/activate; PS1='(venv) \u@\h:\w\$ '")
}

# ========== MAIN ==========

case "$1" in
    start)
        cmd_start
        ;;
    stop)
        cmd_stop
        ;;
    restart)
        cmd_restart
        ;;
    status)
        cmd_status
        ;;
    logs)
        cmd_logs
        ;;
    logs-err)
        cmd_logs_err
        ;;
    supervisor)
        cmd_supervisor
        ;;
    kill)
        cmd_kill
        ;;
    reload)
        cmd_reload
        ;;
    shell)
        cmd_shell
        ;;
    *)
        print_usage
        exit 1
        ;;
esac
SCRIPT_EOF
    
    chmod +x "$APP_DIR/control.sh"
    
    print_success "Control script created at: $APP_DIR/control.sh"
}

add_health_check_endpoint() {
    print_step "Checking for health endpoint..."
    
    if grep -q "@app.get.*health" "$APP_DIR/main.py"; then
        print_success "Health endpoint already exists"
    else
        print_warning "No health endpoint found in main.py"
        echo ""
        echo "Consider adding this to your FastAPI app for monitoring:"
        echo ""
        echo -e "${YELLOW}@app.get(\"/health\")
async def health_check():
    return {\"status\": \"ok\"}${NC}"
        echo ""
    fi
}

setup_cron() {
    print_step "Setting up cron job for auto-start on reboot..."
    
    CRON_CMD="@reboot sleep 30 && $VENV_PATH/bin/supervisord -c $SUPERVISOR_DIR/supervisord.conf"
    
    # Check if cron job already exists
    if crontab -l 2>/dev/null | grep -q "supervisord -c $SUPERVISOR_DIR"; then
        print_warning "Cron job already exists"
    else
        # Add cron job
        (crontab -l 2>/dev/null; echo "$CRON_CMD") | crontab -
        print_success "Cron job added for auto-start on reboot"
    fi
    
    echo ""
    echo "Current crontab:"
    crontab -l | grep supervisor || echo "(no supervisor cron jobs)"
}

create_readme() {
    print_step "Creating README..."
    
    cat > "$APP_DIR/DEPLOYMENT_README.md" << EOF
# FastAPI Deployment on cPanel - Quick Reference

## 🚀 Quick Start

### Start the app:
\`\`\`bash
bash $APP_DIR/control.sh start
\`\`\`

### Check status:
\`\`\`bash
bash $APP_DIR/control.sh status
\`\`\`

### View logs:
\`\`\`bash
bash $APP_DIR/control.sh logs
\`\`\`

## 📋 All Commands

| Command | Description |
|---------|-------------|
| \`start\` | Start the FastAPI app and Supervisor |
| \`stop\` | Stop the FastAPI app |
| \`restart\` | Restart the FastAPI app |
| \`status\` | Show current status |
| \`logs\` | View application logs (live) |
| \`logs-err\` | View Supervisor error logs |
| \`supervisor\` | Start Supervisor daemon |
| \`kill\` | Stop Supervisor completely |
| \`reload\` | Reload configuration |
| \`shell\` | Activate virtualenv shell |

## 🔧 Configuration Files

- **Supervisor Config**: \`$SUPERVISOR_DIR/supervisord.conf\`
- **App Config**: \`$SUPERVISOR_DIR/conf.d/$APP_NAME.conf\`
- **Control Script**: \`$APP_DIR/control.sh\`
- **App Logs**: \`$APP_DIR/logs/app.log\`
- **Supervisor Logs**: \`$SUPERVISOR_DIR/logs/supervisord.log\`

## 🛡️ What's Protected

| Scenario | Result |
|----------|--------|
| App crash (exception) | ✅ Auto-restart |
| Memory kill by cPanel | ✅ Auto-restart |
| Server reboot | ✅ Auto-start (via cron) |
| SSH disconnect | ✅ Keeps running |
| Process manually killed | ✅ Auto-restart |

## 🔄 Common Tasks

### Update your app code:
\`\`\`bash
cd $APP_DIR
git pull  # or however you update
bash control.sh restart
\`\`\`

### Install new dependencies:
\`\`\`bash
source $VENV_PATH/bin/activate
pip install -r requirements.txt
bash $APP_DIR/control.sh restart
\`\`\`

### Change port or workers:
1. Edit: \`$SUPERVISOR_DIR/conf.d/$APP_NAME.conf\`
2. Run: \`bash $APP_DIR/control.sh reload\`
3. Run: \`bash $APP_DIR/control.sh restart\`

### Debug issues:
\`\`\`bash
# Check supervisor status
bash $APP_DIR/control.sh status

# View live logs
bash $APP_DIR/control.sh logs

# Check if process is listening
netstat -tlnp | grep $UVICORN_PORT

# Test health endpoint
curl http://localhost:$UVICORN_PORT/health
\`\`\`

## 🆘 Troubleshooting

### App won't start?
\`\`\`bash
# Check logs for errors
bash $APP_DIR/control.sh logs

# Try starting manually to see error
cd $APP_DIR
source $VENV_PATH/bin/activate
uvicorn main:app --host $UVICORN_HOST --port $UVICORN_PORT
\`\`\`

### Port already in use?
\`\`\`bash
# Find what's using the port
lsof -i :$UVICORN_PORT

# Kill the process
kill -9 <PID>

# Or use control script
bash $APP_DIR/control.sh restart
\`\`\`

### Supervisor not responding?
\`\`\`bash
# Kill and restart
bash $APP_DIR/control.sh kill
sleep 2
bash $APP_DIR/control.sh supervisor
bash $APP_DIR/control.sh start
\`\`\`

## 📞 Support

For issues, check:
1. Application logs: \`$APP_DIR/logs/app.log\`
2. Supervisor logs: \`$SUPERVISOR_DIR/logs/supervisord.log\`
3. System logs: \`/var/log/messages\` or \`dmesg\`

---

**Deployment Date**: $(date)
**App Location**: $APP_DIR
**Virtualenv**: $VENV_PATH
**Port**: $UVICORN_PORT
EOF
    
    print_success "README created at: $APP_DIR/DEPLOYMENT_README.md"
}

start_services() {
    print_step "Starting services..."
    
    # Start supervisord
    source "$VENV_PATH/bin/activate"
    $VENV_PATH/bin/supervisord -c "$SUPERVISOR_DIR/supervisord.conf"
    
    sleep 2
    
    # Check status
    $VENV_PATH/bin/supervisorctl -c "$SUPERVISOR_DIR/supervisord.conf" status
    
    print_success "Services started"
}

# ========== MAIN DEPLOYMENT PROCESS ==========

main() {
    echo ""
    echo "═══════════════════════════════════════════════════════"
    echo "  FastAPI Deployment Script for cPanel"
    echo "═══════════════════════════════════════════════════════"
    echo ""
    
    check_requirements
    install_supervisor
    create_directories
    create_supervisord_config
    create_app_config
    create_control_script
    add_health_check_endpoint
    setup_cron
    create_readme
    start_services
    
    echo ""
    echo "═══════════════════════════════════════════════════════"
    print_success "DEPLOYMENT COMPLETE!"
    echo "═══════════════════════════════════════════════════════"
    echo ""
    echo -e "${GREEN}Your FastAPI app is now running in production mode!${NC}"
    echo ""
    echo "📍 Quick commands:"
    echo "   • Check status:  ${BLUE}bash $APP_DIR/control.sh status${NC}"
    echo "   • View logs:     ${BLUE}bash $APP_DIR/control.sh logs${NC}"
    echo "   • Restart:       ${BLUE}bash $APP_DIR/control.sh restart${NC}"
    echo ""
    echo "📖 Full documentation: ${BLUE}$APP_DIR/DEPLOYMENT_README.md${NC}"
    echo ""
    echo -e "${YELLOW}⚠️  After server reboot, Supervisor will auto-start via cron${NC}"
    echo ""
    
    # Show current status
    echo "Current Status:"
    $VENV_PATH/bin/supervisorctl -c "$SUPERVISOR_DIR/supervisord.conf" status
    echo ""
}

# Run main deployment
main

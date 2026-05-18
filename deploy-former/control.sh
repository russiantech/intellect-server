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

# print_usage() {
#     echo "FastAPI Control Script"
#     echo ""
#     echo "Usage: $0 [command]"
#     echo ""
#     echo "Commands:"
#     echo "  start       Start the FastAPI app and Supervisor"
#     echo "  stop        Stop the FastAPI app"
#     echo "  restart     Restart the FastAPI app"
#     echo "  status      Show app status"
#     echo "  logs        Show app logs (tail -f)"
#     echo "  logs-err    Show error logs"
#     echo "  supervisor  Start Supervisor daemon"
#     echo "  kill        Stop Supervisor completely"
#     echo "  reload      Reload Supervisor configuration"
#     echo "  shell       Activate virtualenv and cd to app"
#     echo ""
# }

# v2
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
    echo "  health      Run comprehensive health check"
    echo "  shell       Activate virtualenv and cd to app"
    echo ""
}

# start_supervisor() {
#     if [ -f "$SUPERVISOR_DIR/supervisord.pid" ] && kill -0 $(cat "$SUPERVISOR_DIR/supervisord.pid") 2>/dev/null; then
#         echo -e "${YELLOW}Supervisor is already running${NC}"
#     else
#         echo -e "${BLUE}Starting Supervisor...${NC}"
#         $SUPERVISORD
#         sleep 2
#         echo -e "${GREEN}Supervisor started${NC}"
#     fi
# }

start_supervisor() {
    SOCKET_FILE="$SUPERVISOR_DIR/supervisor.sock"
    PID_FILE="$SUPERVISOR_DIR/supervisord.pid"
    
    # Check if supervisor is actually running
    if [ -f "$PID_FILE" ] && kill -0 $(cat "$PID_FILE") 2>/dev/null; then
        echo -e "${YELLOW}Supervisor is already running${NC}"
        return 0
    fi
    
    # Remove stale PID file if exists
    if [ -f "$PID_FILE" ]; then
        echo -e "${YELLOW}Removing stale PID file${NC}"
        rm -f "$PID_FILE"
    fi
    
    # Remove stale socket if exists and supervisor is not running
    if [ -S "$SOCKET_FILE" ] && ! $SUPERVISORCTL status &>/dev/null; then
        echo -e "${YELLOW}Unlinking stale socket $SOCKET_FILE${NC}"
        rm -f "$SOCKET_FILE"
    fi
    
    # Start supervisord
    echo -e "${BLUE}Starting Supervisor...${NC}"
    $SUPERVISORD
    
    # Wait up to 10 seconds for it to start
    for i in {1..10}; do
        if $SUPERVISORCTL status &>/dev/null; then
            echo -e "${GREEN}Supervisor started${NC}"
            return 0
        fi
        sleep 1
    done
    
    echo -e "${RED}ERROR: Supervisor failed to start${NC}"
    echo -e "${YELLOW}Check logs: tail $SUPERVISOR_DIR/logs/supervisord.log${NC}"
    return 1
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

cmd_health() {
    echo -e "${BLUE}=== Health Check ===${NC}"
    
    # Check Supervisor
    if $SUPERVISORCTL status $APP_NAME &>/dev/null; then
        STATUS=$($SUPERVISORCTL status $APP_NAME)
        if echo "$STATUS" | grep -q "RUNNING"; then
            echo -e "${GREEN}✓ Supervisor: Running${NC}"
            echo -e "  $STATUS"
        else
            echo -e "${RED}✗ Supervisor: Not Running${NC}"
            echo -e "  $STATUS"
        fi
    else
        echo -e "${RED}✗ Supervisor: Not Responding${NC}"
    fi
    
    # Check App
    echo ""
    if curl -s http://localhost:8001/ > /dev/null 2>&1; then
        echo -e "${GREEN}✓ App: Responding on port 8001${NC}"
    else
        echo -e "${RED}✗ App: Not responding on port 8001${NC}"
    fi
    
    # Check Cron
    echo ""
    if crontab -l | grep -q "@reboot.*supervisord"; then
        echo -e "${GREEN}✓ Cron: Auto-start configured${NC}"
        crontab -l | grep "@reboot"
    else
        echo -e "${YELLOW}⚠ Cron: Auto-start not found${NC}"
    fi
    
    # Check Logs
    echo ""
    echo -e "${BLUE}Recent errors (last 5):${NC}"
    grep -i "error\|warning\|critical" "$APP_DIR/logs/app.log" 2>/dev/null | tail -5 || echo "No recent errors"
}

# ========== MAIN ==========

# case "$1" in
#     start)
#         cmd_start
#         ;;
#     stop)
#         cmd_stop
#         ;;
#     restart)
#         cmd_restart
#         ;;
#     status)
#         cmd_status
#         ;;
#     logs)
#         cmd_logs
#         ;;
#     logs-err)
#         cmd_logs_err
#         ;;
#     supervisor)
#         cmd_supervisor
#         ;;
#     kill)
#         cmd_kill
#         ;;
#     reload)
#         cmd_reload
#         ;;
#     shell)
#         cmd_shell
#         ;;
#     *)
#         print_usage
#         exit 1
#         ;;
# esac

# v2
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
    health)
        cmd_health
        ;;
    *)
        print_usage
        exit 1
        ;;
esac

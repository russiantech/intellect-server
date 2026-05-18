#!/bin/bash

###############################################################################
# FastAPI Health Monitor (Optional)
# This provides an extra layer of monitoring beyond Supervisor
# Add to cron if you want belt-and-suspenders reliability:
#   */5 * * * * /home/simpdinr/api-studentscores.simplylovely.ng/monitor.sh
###############################################################################

# ========== CONFIGURATION ==========
VENV_PATH="/home/simpdinr/virtualenv/api-studentscores.simplylovely.ng/3.13"
SUPERVISOR_DIR="$HOME/supervisor"
APP_NAME="fastapi-studentscores"
HEALTH_URL="http://localhost:8001/health"
LOG_FILE="$HOME/supervisor/logs/monitor.log"

SUPERVISORCTL="$VENV_PATH/bin/supervisorctl -c $SUPERVISOR_DIR/supervisord.conf"
SUPERVISORD="$VENV_PATH/bin/supervisord -c $SUPERVISOR_DIR/supervisord.conf"

# ========== MONITORING LOGIC ==========

log_message() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" >> "$LOG_FILE"
}

# Check if supervisor daemon is running
if ! pgrep -f "supervisord -c $SUPERVISOR_DIR/supervisord.conf" > /dev/null; then
    log_message "ERROR: Supervisor daemon not running. Starting..."
    $SUPERVISORD
    sleep 3
fi

# Check if app process is running via supervisor
APP_STATUS=$($SUPERVISORCTL status $APP_NAME 2>&1)

if echo "$APP_STATUS" | grep -q "RUNNING"; then
    # Process is running according to supervisor
    
    # Additional health check via HTTP (if health endpoint exists)
    if command -v curl &> /dev/null; then
        if ! curl -sf --max-time 5 "$HEALTH_URL" > /dev/null 2>&1; then
            log_message "WARNING: App running but health check failed. Restarting..."
            $SUPERVISORCTL restart $APP_NAME
        fi
    fi
else
    # Process not running - restart it
    log_message "ERROR: App not running. Status: $APP_STATUS. Restarting..."
    $SUPERVISORCTL start $APP_NAME
fi

# Rotate log if it gets too big (keep last 1000 lines)
if [ -f "$LOG_FILE" ]; then
    LINE_COUNT=$(wc -l < "$LOG_FILE")
    if [ "$LINE_COUNT" -gt 1000 ]; then
        tail -n 1000 "$LOG_FILE" > "${LOG_FILE}.tmp"
        mv "${LOG_FILE}.tmp" "$LOG_FILE"
    fi
fi

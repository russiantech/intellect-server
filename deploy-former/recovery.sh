#!/bin/bash

APP_DIR="/home/simpdinr/api-studentscores.simplylovely.ng"
CONTROL="$APP_DIR/deploy/control.sh"
LOG_FILE="$APP_DIR/deploy/recovery.log"

# Create deploy directory if it doesn't exist
mkdir -p "$APP_DIR/deploy"

# Check if app is responding
if ! curl -sf http://localhost:8001/ > /dev/null 2>&1; then
    echo "[$(date)] App not responding, restarting..." >> "$LOG_FILE"
    
    # Try graceful restart first
    $CONTROL restart
    sleep 5
    
    # If still not responding, force restart
    if ! curl -sf http://localhost:8001/ > /dev/null 2>&1; then
        echo "[$(date)] Graceful restart failed, forcing..." >> "$LOG_FILE"
        $CONTROL kill
        sleep 2
        $CONTROL supervisor
        sleep 3
        $CONTROL start
    fi
    
    echo "[$(date)] Recovery attempt complete" >> "$LOG_FILE"
fi

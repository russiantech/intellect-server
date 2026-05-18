#!/bin/bash

###############################################################################
# Uninstall Script for FastAPI Supervisor Deployment
# This removes all deployment components while preserving your app code
###############################################################################

# ========== CONFIGURATION ==========
VENV_PATH="/home/simpdinr/virtualenv/api-studentscores.simplylovely.ng/3.13"
SUPERVISOR_DIR="$HOME/supervisor"
APP_DIR="/home/simpdinr/api-studentscores.simplylovely.ng"

# ========== COLORS ==========
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo ""
echo -e "${YELLOW}═══════════════════════════════════════════════════════${NC}"
echo -e "${YELLOW}  FastAPI Deployment Uninstaller${NC}"
echo -e "${YELLOW}═══════════════════════════════════════════════════════${NC}"
echo ""
echo -e "${RED}WARNING: This will remove:${NC}"
echo "  • Supervisor daemon and configuration"
echo "  • All log files"
echo "  • Control scripts"
echo "  • Cron jobs"
echo ""
echo -e "${GREEN}This will KEEP:${NC}"
echo "  • Your FastAPI app code"
echo "  • Your virtualenv"
echo "  • Your application data"
echo ""
read -p "Continue? (y/N): " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Aborted."
    exit 0
fi

echo ""
echo -e "${YELLOW}Stopping services...${NC}"

# Stop supervisor
if [ -f "$VENV_PATH/bin/supervisorctl" ]; then
    $VENV_PATH/bin/supervisorctl -c "$SUPERVISOR_DIR/supervisord.conf" shutdown 2>/dev/null || true
fi

# Kill any remaining processes
pkill -f "supervisord -c $SUPERVISOR_DIR" 2>/dev/null || true

echo -e "${GREEN}✓${NC} Services stopped"

# Remove cron jobs
echo -e "${YELLOW}Removing cron jobs...${NC}"
crontab -l 2>/dev/null | grep -v "supervisord" | crontab - 2>/dev/null || true
echo -e "${GREEN}✓${NC} Cron jobs removed"

# Remove supervisor directory
echo -e "${YELLOW}Removing Supervisor files...${NC}"
if [ -d "$SUPERVISOR_DIR" ]; then
    rm -rf "$SUPERVISOR_DIR"
    echo -e "${GREEN}✓${NC} Supervisor directory removed"
fi

# Remove control script
echo -e "${YELLOW}Removing control scripts...${NC}"
if [ -f "$APP_DIR/control.sh" ]; then
    rm -f "$APP_DIR/control.sh"
    echo -e "${GREEN}✓${NC} Control script removed"
fi

if [ -f "$APP_DIR/monitor.sh" ]; then
    rm -f "$APP_DIR/monitor.sh"
    echo -e "${GREEN}✓${NC} Monitor script removed"
fi

if [ -f "$APP_DIR/DEPLOYMENT_README.md" ]; then
    rm -f "$APP_DIR/DEPLOYMENT_README.md"
    echo -e "${GREEN}✓${NC} Deployment README removed"
fi

# Remove supervisor package from virtualenv (optional)
read -p "Also uninstall supervisor from virtualenv? (y/N): " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    source "$VENV_PATH/bin/activate"
    pip uninstall supervisor -y
    echo -e "${GREEN}✓${NC} Supervisor package uninstalled"
fi

echo ""
echo -e "${GREEN}═══════════════════════════════════════════════════════${NC}"
echo -e "${GREEN}Uninstallation Complete!${NC}"
echo -e "${GREEN}═══════════════════════════════════════════════════════${NC}"
echo ""
echo "Your app code at $APP_DIR is preserved."
echo ""
echo "To run your app manually:"
echo "  cd $APP_DIR"
echo "  source $VENV_PATH/bin/activate"
echo "  uvicorn main:app --host 0.0.0.0 --port 8001"
echo ""

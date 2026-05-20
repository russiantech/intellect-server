cd ~/intellect-api.salesnet.ng

# 1. See what's actually on port 8001 (likely an old process)
# ss -tlnp | grep 8001
bash deploy/control.sh status

ps aux | grep -E "gunicorn|uvicorn"

# 2. Nuke everything — old gunicorn master, old uvicorn, anything lingering
bash deploy/control.sh kill          # stops supervisor + its children
pkill -9 -f gunicorn                 # insurance
pkill -9 -f uvicorn                  # insurance
sleep 2

# 3. Start fresh (this loads CURRENT code from disk)
bash deploy/control.sh start

# 4. Verify
bash deploy/control.sh status
bash deploy/control.sh workers       # should now show master + 3 workers
curl http://localhost:8001/health
curl http://localhost:8001/docs
curl http://localhost:8001/deploy-webhook
curl http://localhost:8001/api/v1/courses

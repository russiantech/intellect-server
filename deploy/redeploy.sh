cd ~/intellect-api.salesnet.ng

# 1. See what's actually on port 8001 (likely an old process)
ss -tlnp | grep 8001
ps aux | grep -E "gunicorn|uvicorn"

# 2. Nuke everything — old gunicorn master, old uvicorn, anything lingering
bash control.sh kill          # stops supervisor + its children
pkill -9 -f gunicorn                 # insurance
pkill -9 -f uvicorn                  # insurance
sleep 2

# 3. Start fresh (this loads CURRENT code from disk)
bash control.sh start

# 4. Verify
bash control.sh status
bash control.sh workers       # should now show master + 3 workers
curl http://localhost:8001/health
curl http://localhost:8001/docs
curl http://localhost:8001/deploy-webhook
curl http://localhost:8001/api/v1/courses

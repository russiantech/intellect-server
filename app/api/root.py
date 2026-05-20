# app/api/root.py

import hashlib
import hmac
import os
import shutil
import subprocess
import time
from datetime import datetime

from fastapi import APIRouter, Header, HTTPException, Request
from sqlalchemy import text

from app.core.config import get_app_config
from app.db.database import get_engine
from app.utils.responses import api_response

# ── Config ────────────────────────────────────────────────────────
cfg = get_app_config()
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET")

# ── Routers ───────────────────────────────────────────────────────
root_router = APIRouter(tags=["Root"], prefix="")
health_router = APIRouter(tags=["Health"], prefix="/health")


# ── Helpers ───────────────────────────────────────────────────────

def verify_signature(body: bytes, signature: str) -> bool:
    """
    Verify GitHub webhook HMAC-SHA256 signature.
    Skips verification if WEBHOOK_SECRET is not configured.
    """
    if not WEBHOOK_SECRET:
        return True

    computed = "sha256=" + hmac.new(
        WEBHOOK_SECRET.encode(),
        body,
        hashlib.sha256,
    ).hexdigest()

    return hmac.compare_digest(computed, signature)


def _db_ping() -> str:
    """Run a lightweight DB connectivity check. Returns 'ok' or an error string."""
    try:
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
        return "ok"
    except Exception as exc:
        return f"error: {exc}"


def _disk_status(path: str = "/tmp") -> str:
    """Return free-disk status string for the given path."""
    try:
        usage = shutil.disk_usage(path)
        free_gb = usage.free / (1024 ** 3)
        label = "ok" if free_gb > 1 else "low"
        return f"{label} ({free_gb:.1f} GB free)"
    except Exception as exc:
        return f"error: {exc}"


# ── Root ──────────────────────────────────────────────────────────

@root_router.get("/")
async def root():
    return api_response(
        success=True,
        message=f"Welcome to {cfg.general_config.site_name} API",
        data={
            "title": cfg.general_config.site_name,
            "mode": "development" if cfg.general_config.development_mode else "production",
            "description": cfg.general_config.site_description,
            "status": "ok",
            "version": "0.2.0",
            "docs": "/docs",
            "redocs": "/redocs",
            "developer": "Chris James",
        },
    )


# ── Deploy Webhook ────────────────────────────────────────────────

@root_router.post("/deploy-webhook")
async def deploy_webhook(
    request: Request,
    x_hub_signature_256: str = Header(default=""),
):
    """
    GitHub webhook endpoint for automated deployments.
    Only triggers on pushes to the main branch.
    """
    body = await request.body()

    if not verify_signature(body, x_hub_signature_256):
        raise HTTPException(status_code=403, detail="Invalid webhook signature")

    payload = await request.json()

    if payload.get("ref") != "refs/heads/main":
        return api_response(
            success=True,
            message="Webhook ignored",
            data={"status": "ignored", "ref": payload.get("ref")},
        )

    deploy_script = "/home/salesne2/intellect-api.salesnet.ng/deploy/webhook.sh"

    if not os.path.exists(deploy_script):
        raise HTTPException(status_code=500, detail="Deploy script not found")

    try:
        subprocess.Popen(
            ["bash", deploy_script],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return api_response(
            success=True,
            message="Deployment triggered successfully",
            data={"status": "ok", "branch": "main"},
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to trigger deployment: {exc}")


# ── Health: Liveness ──────────────────────────────────────────────

@health_router.get("")
async def health_liveness():
    """
    Liveness probe.
    Returns 200 as long as the process is running — no dependency checks.
    """
    return api_response(
        success=True,
        message="App running",
        data={
            "status": "healthy",
            "timestamp": datetime.utcnow().isoformat() + "Z",
        },
    )


# ── Health: Deep ──────────────────────────────────────────────────

@health_router.get("/deep")
def health_deep():
    """
    Deep health check.
    Verifies database connectivity and available disk space.
    Returns 503 if any critical dependency is degraded.
    """
    start = time.perf_counter()
    checks: dict = {}

    checks["database"] = _db_ping()
    checks["disk"] = _disk_status()
    checks["response_time_ms"] = round((time.perf_counter() - start) * 1000, 2)

    critical_failed = [k for k in ("database",) if not checks[k].startswith("ok")]

    if critical_failed:
        raise HTTPException(
            status_code=503,
            detail={
                "status": "degraded",
                "checks": checks,
                "failed": critical_failed,
            },
        )

    return api_response(
        success=True,
        message="All systems operational",
        data={
            "status": "ok",
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "checks": checks,
        },
    )


# ── Health: Readiness ─────────────────────────────────────────────

@health_router.get("/ready")
def health_ready():
    """
    Readiness probe.
    Returns 200 only when the app is ready to serve traffic.
    Use this for load-balancer / cPanel health checks.
    """
    db_status = _db_ping()

    if not db_status.startswith("ok"):
        raise HTTPException(
            status_code=503,
            detail={
                "ready": False,
                "checks": {"database": db_status},
            },
        )

    return api_response(
        success=True,
        message="Ready to serve traffic",
        data={
            "ready": True,
            "checks": {"database": db_status},
        },
    )


# ── Health: Metrics ───────────────────────────────────────────────

@health_router.get("/metrics")
def health_metrics():
    """
    Process and system resource metrics.
    Requires psutil (`pip install psutil`).
    """
    try:
        import psutil
    except ImportError:
        raise HTTPException(
            status_code=501,
            detail="psutil is not installed. Run: pip install psutil",
        )

    memory = psutil.virtual_memory()
    disk = psutil.disk_usage("/")

    return api_response(
        success=True,
        message="System metrics",
        data={
            "memory": {
                "total_mb": memory.total // (1024 ** 2),
                "used_mb": memory.used // (1024 ** 2),
                "percent": memory.percent,
            },
            "disk": {
                "total_gb": disk.total // (1024 ** 3),
                "used_gb": disk.used // (1024 ** 3),
                "percent": round(disk.used / disk.total * 100, 1),
            },
            "cpu_percent": psutil.cpu_percent(interval=0.1),
            "timestamp": datetime.utcnow().isoformat() + "Z",
        },
    )


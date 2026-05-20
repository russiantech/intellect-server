"""
app/api/health.py — Production health check endpoints.
Add these to your FastAPI router for monitoring and load balancers.
"""

import time
import asyncio
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.core.performance.cache_config import cache
from app.db.database import get_engine

router = APIRouter(prefix="/health", tags=["Health"])

class HealthResponse(BaseModel):
    status: str
    timestamp: str
    version: str = "2.0"
    checks: dict

class ReadinessResponse(BaseModel):
    ready: bool
    checks: dict

# ── Basic Liveness ─────────────────────────────────────────────
@router.get("", response_model=HealthResponse)
async def health_check():
    """Liveness probe — returns 200 if process is running."""
    return HealthResponse(
        status="ok",
        timestamp=datetime.utcnow().isoformat(),
        checks={"process": "up"},
    )

# ── Deep Health (dependencies) ─────────────────────────────────
@router.get("/deep", response_model=HealthResponse)
async def deep_health():
    """Deep health check — verifies database, cache, disk."""
    checks = {}
    start = time.time()

    # Database check
    try:
        engine = get_engine()
        async with engine.connect() as conn:
            result = await conn.execute("SELECT 1")
            checks["database"] = "ok" if result.scalar() == 1 else "fail"
    except Exception as e:
        checks["database"] = f"error: {str(e)}"

    # Cache check
    try:
        await cache.init()
        test_key = f"health:{time.time()}"
        await cache.set(test_key, "ping", ttl=5)
        result = await cache.get(test_key)
        checks["cache"] = "ok" if result == "ping" else "fail"
    except Exception as e:
        checks["cache"] = f"error: {str(e)}"

    # Disk check
    try:
        import shutil
        usage = shutil.disk_usage("/tmp")
        free_gb = usage.free / (1024**3)
        checks["disk"] = f"ok ({free_gb:.1f}GB free)" if free_gb > 1 else f"low ({free_gb:.1f}GB free)"
    except Exception as e:
        checks["disk"] = f"error: {str(e)}"

    duration = (time.time() - start) * 1000
    checks["response_time_ms"] = round(duration, 2)

    # Fail if any critical check fails
    critical = ["database", "cache"]
    failed = [c for c in critical if not checks[c].startswith("ok")]

    if failed:
        raise HTTPException(
            status_code=503,
            detail={"status": "degraded", "checks": checks, "failed": failed},
        )

    return HealthResponse(
        status="ok",
        timestamp=datetime.utcnow().isoformat(),
        checks=checks,
    )

# ── Readiness Probe (for Kubernetes/cPanel load balancers) ─────
@router.get("/ready", response_model=ReadinessResponse)
async def readiness_check():
    """Readiness probe — returns 200 only when ready to serve traffic."""
    checks = {}

    try:
        engine = get_engine()
        async with engine.connect() as conn:
            await conn.execute("SELECT 1")
        checks["database"] = "ok"
    except Exception as e:
        checks["database"] = f"error: {str(e)}"
        return ReadinessResponse(ready=False, checks=checks)

    try:
        await cache.init()
        checks["cache"] = "ok"
    except Exception as e:
        checks["cache"] = f"error: {str(e)}"
        return ReadinessResponse(ready=False, checks=checks)

    return ReadinessResponse(ready=True, checks=checks)

# ── Metrics Endpoint (for Prometheus-style monitoring) ─────────
@router.get("/metrics")
async def metrics():
    """Simple metrics for monitoring dashboards."""
    import psutil

    memory = psutil.virtual_memory()
    disk = psutil.disk_usage("/")

    return {
        "memory": {
            "total_mb": memory.total // (1024**2),
            "used_mb": memory.used // (1024**2),
            "percent": memory.percent,
        },
        "disk": {
            "total_gb": disk.total // (1024**3),
            "used_gb": disk.used // (1024**3),
            "percent": round(disk.used / disk.total * 100, 1),
        },
        "cpu_percent": psutil.cpu_percent(interval=0.1),
        "timestamp": datetime.utcnow().isoformat(),
    }

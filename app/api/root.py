# app/api/root.py

import hashlib
import hmac
import os
import subprocess
from datetime import datetime

from fastapi import APIRouter, Header, HTTPException, Request

from app.core.config import get_app_config
from app.utils.responses import api_response

root_router = APIRouter(tags=["Root"], prefix="")

cfg = get_app_config()

WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET")


def verify_signature(body: bytes, signature: str) -> bool:
    """
    Verify GitHub webhook signature.
    If WEBHOOK_SECRET is not configured, signature verification is skipped.
    """
    if not WEBHOOK_SECRET:
        return True

    computed = "sha256=" + hmac.new(
        WEBHOOK_SECRET.encode(),
        body,
        hashlib.sha256,
    ).hexdigest()

    return hmac.compare_digest(computed, signature)


@root_router.get("/")
async def root():
    return api_response(
        success=True,
        message=f"Welcome to {cfg.general_config.site_name} API",
        data={
            "title": cfg.general_config.site_name,
            "mode": (
                "development"
                if cfg.general_config.development_mode
                else "production"
            ),
            "description": cfg.general_config.site_description,
            "status": "ok",
            "version": "0.2.0",
            "docs": "/docs",
            "redocs": "/redocs",
            "developer": "Chris James",
        },
    )


@root_router.get("/health")
async def health():
    return api_response(
        success=True,
        message="App Running",
        data={
            "status": "healthy",
            "timestamp": datetime.utcnow().isoformat() + "Z",
        },
    )


@root_router.post("/deploy-webhook")
async def deploy_webhook(
    request: Request,
    x_hub_signature_256: str = Header(default=""),
):
    """
    GitHub webhook endpoint for automated deployments.
    Only triggers deployment for pushes to the main branch.
    """

    body = await request.body()

    # Verify webhook signature
    if not verify_signature(body, x_hub_signature_256):
        raise HTTPException(
            status_code=403,
            detail="Invalid webhook signature",
        )

    payload = await request.json()

    # Only deploy from main branch
    if payload.get("ref") != "refs/heads/main":
        return api_response(
            success=True,
            message="Webhook ignored",
            data={
                "status": "ignored",
                "ref": payload.get("ref"),
            },
        )

    deploy_script = (
        "/home/salesne2/intellect-api.salesnet.ng/deploy/webhook.sh"
    )

    # Ensure deploy script exists
    if not os.path.exists(deploy_script):
        raise HTTPException(
            status_code=500,
            detail="Deploy script not found",
        )

    try:
        # Trigger deployment asynchronously
        subprocess.Popen(
            ["bash", deploy_script],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        return api_response(
            success=True,
            message="Deployment triggered successfully",
            data={
                "status": "ok",
                "branch": "main",
            },
        )

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to trigger deployment: {str(exc)}",
        )





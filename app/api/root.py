# app/api/root.py

from fastapi import APIRouter
from app.utils.responses import api_response
from datetime import datetime

from app.core.config import get_app_config

root_router = APIRouter(tags=["Root"], prefix="")

cfg = get_app_config()

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
            }
    )

@root_router.get("/health")
async def health():
    return api_response(
        success=True,
        message="App Running",
        data={"status": "healthy", "timestamp": datetime.now().isoformat() + "Z"}
    )

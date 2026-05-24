"""
Authentication endpoints — Intellect LMS
Signup: two-step (initiate → verify via 6-digit code, Redis-backed)
Password reset: code-based (no URL tokens)
OAuth 2.0: Google, GitHub, Facebook, LinkedIn
Multi-identifier signin: email | username | phone
"""

import base64
import json
import logging
import secrets
import urllib.parse
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.models import User, Role, OAuthAccount
from app.schemas import (
    SignupRequest, SigninRequest, ForgotPasswordRequest,
    ChangePasswordRequest, SuccessResponse,
)
from app.core.security.security import (
    create_access_token, hash_password, verify_password,
    decode_token,
)
from app.services.email_service import (
    send_verification_email, send_welcome_email,
    send_password_reset_email,
)
from app.api.deps.auth import ImpersonationError, can_impersonate, get_current_user, bearer_scheme, require_admin
from app.api.deps.storage import get_redis_service
from app.services.redis_service import RedisService
from app.core.config import get_app_config
from app.utils.helpers import generate_secure_code
from app.utils.responses import api_response
from app.core.config.loader import OAUTH_REGISTRY

# HELPERS
from app.utils.auth import (
    _create_or_link_oauth_user, _fetch_oauth_userinfo, 
    _issue_tokens, _oauth_error_html, 
    _resolve_user_by_identifier,
    _user_to_public
)

router = APIRouter(prefix="/auth", tags=["Authentication"])
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Signup — Step 1 & 2, Resend (unchanged from your working code)
# ---------------------------------------------------------------------------

@router.post("/signup", status_code=status.HTTP_202_ACCEPTED)
async def signup(
    payload: SignupRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    redis: Optional[RedisService] = Depends(get_redis_service),
):
    if not redis:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Service temporarily unavailable. Please try again.",
        )

    if db.query(User).filter(User.email == payload.email.lower()).first():
        raise HTTPException(status_code=400, detail="Email already registered.")
    if db.query(User).filter(User.username == payload.username.lower()).first():
        raise HTTPException(status_code=400, detail="Username already taken.")

    email_code = generate_secure_code(6)
    signup_token = secrets.token_urlsafe(32)

    signup_data = {
        "name": payload.name,
        "username": payload.username.lower(),
        "email": payload.email.lower(),
        "phone": payload.phone or "",
        "password": hash_password(payload.password),
        "email_code": email_code,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    redis_key = f"intellect:signup_pending:{signup_token}"
    if not redis.set(redis_key, signup_data, expiry=600):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Could not initiate signup. Please try again.",
        )

    background_tasks.add_task(
        send_verification_email,
        payload.email.lower(),
        payload.name or payload.username,
        email_code,
    )

    logger.info(f"Signup initiated for {payload.email}")

    return api_response(
        success=True,
        message="Verification code sent! Please check your email.",
        data={
            "token": signup_token,
            "email": payload.email.lower(),
            "expires_in_seconds": 600,
        }
    )


@router.post("/signup/verify-signup", status_code=status.HTTP_201_CREATED)
async def verify_signup(
    payload: dict,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    redis: Optional[RedisService] = Depends(get_redis_service),
):
    if not redis:
        raise HTTPException(status_code=503, detail="Service temporarily unavailable.")

    token: str = payload.get("token", "")
    email_code: str = payload.get("email_code", "")

    if not token or not email_code:
        raise HTTPException(status_code=400, detail="Token and code are required.")

    redis_key = f"intellect:signup_pending:{token}"
    signup_data = redis.get(redis_key, as_json=True)

    if not signup_data:
        raise HTTPException(status_code=400, detail="Session expired or invalid. Please sign up again.")
    if signup_data.get("email_code") != email_code.strip():
        raise HTTPException(status_code=400, detail="Invalid verification code.")

    if db.query(User).filter(User.email == signup_data["email"]).first():
        redis.delete(redis_key)
        raise HTTPException(status_code=400, detail="Email already registered.")
    if db.query(User).filter(User.username == signup_data["username"]).first():
        redis.delete(redis_key)
        raise HTTPException(status_code=400, detail="Username already taken.")

    student_role = db.query(Role).filter(Role.name == "student").first()
    if not student_role:
        student_role = Role(name="student", description="Learner / Student")
        db.add(student_role)
        db.flush()

    user = User(
        name=signup_data["name"],
        username=signup_data["username"],
        email=signup_data["email"],
        phone=signup_data["phone"] or None,
        password_hash=signup_data["password"],
        email_verified=True,
    )
    user.roles.append(student_role)

    try:
        db.add(user)
        db.commit()
        db.refresh(user)
    except Exception as exc:
        db.rollback()
        logger.error(f"User creation failed: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to create account. Please try again.")

    redis.delete(redis_key)

    cfg = get_app_config()
    background_tasks.add_task(
        send_welcome_email,
        user.email, user.name or user.username,
        cfg.general_config.whatsapp_community_link,
    )

    logger.info(f"User {user.username} created successfully.")

    return {
        "success": True,
        "message": "Account created! You can now sign in.",
        "data": {"username": user.username, "email": user.email},
    }


@router.post("/signup/resend", response_model=SuccessResponse)
async def resend_signup_code(
    payload: dict,
    background_tasks: BackgroundTasks,
    redis: Optional[RedisService] = Depends(get_redis_service),
):
    if not redis:
        raise HTTPException(status_code=503, detail="Service temporarily unavailable.")

    token = payload.get("token", "")
    redis_key = f"intellect:signup_pending:{token}"
    signup_data = redis.get(redis_key, as_json=True)

    if not signup_data:
        raise HTTPException(status_code=400, detail="Session expired. Please sign up again.")

    new_code = generate_secure_code(6)
    signup_data["email_code"] = new_code
    redis.set(redis_key, signup_data, expiry=600)

    background_tasks.add_task(
        send_verification_email,
        signup_data["email"],
        signup_data["name"] or signup_data["username"],
        new_code,
    )

    return SuccessResponse(message="New verification code sent.")


# ---------------------------------------------------------------------------
# Sign In — Multi-identifier
# ---------------------------------------------------------------------------

@router.post("/signin")
async def signin(payload: SigninRequest, db: Session = Depends(get_db)):
    
    user = _resolve_user_by_identifier(db, payload.identifier)

    if not user or not verify_password(payload.password, user.password_hash):
        # detail=f"Invalid sign-in details. Make sure any of email, username, phone [{payload.identifier}] or password [{payload.password}] used is actually correct."
        detail=f"Ensure any of email, username, phone [{payload.identifier}] or password [{payload.password}] used is actually correct."

        raise HTTPException(status_code=401, detail=detail)

    if not user.email_verified:
        raise HTTPException(status_code=403, detail="Please verify your email before signing in.")

    user.is_online = True
    user.last_seen = datetime.now(timezone.utc)
    db.commit()

    return _issue_tokens(user)


# ---------------------------------------------------------------------------
# Refresh / Signout / Me
# ---------------------------------------------------------------------------

@router.post("/refresh")
async def refresh_token(
    credentials=Depends(bearer_scheme),
    db: Session = Depends(get_db),
):
    if not credentials:
        raise HTTPException(status_code=401, detail="Refresh token required.")
    payload = decode_token(credentials.credentials)
    if not payload or payload.get("type") != "refresh":
        raise HTTPException(status_code=401, detail="Invalid refresh token.")

    user = db.query(User).filter(User.id == int(payload["sub"]), User.is_active == True).first()
    if not user:
        raise HTTPException(status_code=401, detail="User not found.")

    return _issue_tokens(user)


@router.post("/signout", response_model=SuccessResponse)
async def signout(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    user.is_online = False
    user.last_seen = datetime.now(timezone.utc)
    db.commit()
    return SuccessResponse(message="Signed out successfully.")


@router.get("/me")
async def get_me(user: User = Depends(get_current_user)):
    return _user_to_public(user)


# ---------------------------------------------------------------------------
# Forgot / Reset / Change Password
# ---------------------------------------------------------------------------

@router.post("/forgot-password")
async def forgot_password(
    payload: ForgotPasswordRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    redis: Optional[RedisService] = Depends(get_redis_service),
):
    if not redis:
        raise HTTPException(status_code=503, detail="Service temporarily unavailable.")

    user = db.query(User).filter(
        User.email == payload.email.lower(),
        User.is_active == True,
    ).first()

    reset_token = secrets.token_urlsafe(32)
    reset_code = generate_secure_code(6)

    if user:
        redis_key = f"intellect:pwd_reset:{reset_token}"
        redis.set(
            redis_key,
            {
                "user_id": str(user.id),
                "email": user.email,
                "reset_code": reset_code,
            },
            expiry=900,
        )
        background_tasks.add_task(
            send_password_reset_email,
            user.email,
            user.name or user.username,
            reset_code,
        )
        logger.info(f"Password reset initiated for {user.email}")

    return api_response(
        success=True,
        message="If that email is registered, a reset code has been sent.",
        data={
            "token": reset_token,
            "email": payload.email.lower(),
            "expires_in_seconds": 900,
        },
    )


@router.post("/reset-password")
async def reset_password(
    payload: dict,
    db: Session = Depends(get_db),
    redis: Optional[RedisService] = Depends(get_redis_service),
):
    if not redis:
        raise HTTPException(status_code=503, detail="Service temporarily unavailable.")

    token: str = payload.get("token", "")
    email_code: str = payload.get("email_code", "")
    new_password: str = payload.get("new_password", "")

    if not token or not email_code or not new_password:
        raise HTTPException(status_code=400, detail="Token, code and new password are required.")
    if len(new_password) < 4:
        raise HTTPException(status_code=400, detail="Password must be at least 4 characters.")

    redis_key = f"intellect:pwd_reset:{token}"
    reset_data = redis.get(redis_key, as_json=True)

    if not reset_data or reset_data.get("reset_code") != email_code.strip().upper():
        raise HTTPException(status_code=400, detail="Invalid or expired reset code.")

    user = db.query(User).filter(User.id == int(reset_data["user_id"])).first()
    if not user or not user.is_active:
        redis.delete(redis_key)
        raise HTTPException(status_code=400, detail="Account unavailable.")

    user.password_hash = hash_password(new_password)
    db.commit()
    redis.delete(redis_key)

    return api_response(
        success=True,
        message="Password reset successfully. You can now sign in.",
        data={"email": user.email},
    )


@router.post("/forgot-password/resend")
async def resend_reset_code(
    payload: dict,
    background_tasks: BackgroundTasks,
    redis: Optional[RedisService] = Depends(get_redis_service),
):
    if not redis:
        raise HTTPException(status_code=503, detail="Service temporarily unavailable.")

    token = payload.get("token", "")
    redis_key = f"intellect:pwd_reset:{token}"
    reset_data = redis.get(redis_key, as_json=True)

    if not reset_data:
        raise HTTPException(status_code=400, detail="Session expired. Please start again.")

    new_code = generate_secure_code(6)
    reset_data["reset_code"] = new_code
    redis.set(redis_key, reset_data, expiry=900)

    background_tasks.add_task(
        send_password_reset_email,
        reset_data["email"],
        reset_data.get("name") or reset_data["email"],
        new_code,
    )

    return SuccessResponse(message="New reset code sent.")


@router.post("/change-password", response_model=SuccessResponse)
async def change_password(
    payload: ChangePasswordRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not verify_password(payload.current_password, user.password_hash):
        raise HTTPException(status_code=400, detail="Current password is incorrect.")
    user.password_hash = hash_password(payload.new_password)
    db.commit()
    return SuccessResponse(message="Password changed successfully.")


# ---------------------------------------------------------------------------
# OAuth — Discovery endpoint (so frontend knows which buttons to render)
# ---------------------------------------------------------------------------

# @router.get("/oauth/providers")
# async def list_oauth_providers():
#     cfg = get_app_config()
#     return api_response(
#         success=True,
#         message="Available OAuth providers retrieved successfully.",
#         data=[
#             {"provider": name, "name": name.title()}
#             for name in cfg.oauth_provider_config.keys()
#         ],
#     )

# v2

@router.get("/oauth/providers")
async def list_oauth_providers():
    cfg = get_app_config()
    data = [
        {
            "provider": key,
            "name": key.title(),
            "enabled": key in cfg.oauth_provider_config,
        }
        for key in OAUTH_REGISTRY
    ]
    return api_response(
        success=True,
        message="OAuth providers retrieved.",
        data=data,
    )


# ---------------------------------------------------------------------------
# OAuth — Authorize & Callback
# ---------------------------------------------------------------------------
@router.get("/oauth/{provider}")
async def oauth_authorize(
    provider: str,
    request: Request,
    redis: Optional[RedisService] = Depends(get_redis_service),
):
    if not redis:
        raise HTTPException(status_code=503, detail="Service temporarily unavailable.")

    app_cfg = get_app_config()
    cfg = app_cfg.oauth_provider_config.get(provider)
    if not cfg:
        raise HTTPException(status_code=400, detail="Unsupported or disabled OAuth provider.")

    # Per-provider override from env, or auto-build from api_url + prefix
    if cfg.redirect_uri:
        redirect_uri = cfg.redirect_uri
    else:
        api_prefix = app_cfg.general_config.api_prefix.rstrip('/')
        redirect_uri = f"{app_cfg.hosting_config.api_url.rstrip('/')}{api_prefix}/auth/oauth/{provider}/callback"

    state = secrets.token_urlsafe(32)

    redis_key = f"intellect:oauth_state:{state}"
    redis.set(redis_key, {"provider": provider, "redirect_uri": redirect_uri}, expiry=600)

    qs = {
        "client_id": cfg.client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(cfg.scopes),
        "state": state,
    }
    if provider == "google":
        qs["access_type"] = "offline"
        qs["prompt"] = "consent"

    auth_url = cfg.authorize_url + "?" + urllib.parse.urlencode(qs)

    return api_response(
        success=True,
        message=f"{provider.title()} authorization URL generated successfully.",
        data={
            "authorization_url": auth_url,
            "state": state,
            "provider": provider,
        }
    )


# ---------------------------------------------------------------------------
# OAuth — Callback: popup lands here after provider consent
# Returns HTML that postMessages tokens to window.opener and closes itself
# ---------------------------------------------------------------------------

@router.get("/oauth/{provider}/callback")
async def oauth_callback(
    provider: str,
    code: str,
    state: str,
    request: Request,
    db: Session = Depends(get_db),
    redis: Optional[RedisService] = Depends(get_redis_service),
):
    if not redis:
        raise HTTPException(status_code=503, detail="Service temporarily unavailable.")

    state_key = f"intellect:oauth_state:{state}"
    state_data = redis.get(state_key, as_json=True)
    if not state_data or state_data.get("provider") != provider:
        return _oauth_error_html("Invalid or expired OAuth state.")
    redis.delete(state_key)

    app_cfg = get_app_config()
    cfg = app_cfg.oauth_provider_config.get(provider)
    if not cfg:
        return _oauth_error_html("Unsupported OAuth provider.")

    redirect_uri = state_data["redirect_uri"]

    # Exchange code
    token_payload = {
        "client_id": cfg.client_id,
        "client_secret": cfg.client_secret,
        "code": code,
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code",
    }
    async with httpx.AsyncClient() as client:
        token_resp = await client.post(cfg.token_url, data=token_payload)
    if token_resp.status_code != 200:
        logger.error(f"OAuth token exchange failed: {token_resp.text}")
        return _oauth_error_html("Failed to exchange OAuth code.")

    token_json = token_resp.json()
    access_token = token_json.get("access_token")
    if not access_token:
        return _oauth_error_html("OAuth provider did not return an access token.")

    # Fetch user info
    try:
        userinfo = await _fetch_oauth_userinfo(provider, access_token, cfg)
    except Exception as exc:
        logger.error(f"OAuth userinfo failed: {exc}", exc_info=True)
        return _oauth_error_html("Failed to fetch user info from provider.")

    # Create / link / sign in — pass provider tokens for storage
    account_id = userinfo["id"]
    user = _create_or_link_oauth_user(
        db, provider, account_id, userinfo,
        provider_tokens={
            "access_token": token_json.get("access_token"),
            "refresh_token": token_json.get("refresh_token"),
            "expires_at": token_json.get("expires_in"),
        }
    )

    user.is_online = True
    user.last_seen = datetime.now(timezone.utc)
    db.commit()

    tokens = _issue_tokens(user)
    payload = {
        "access_token": tokens["access_token"],
        "refresh_token": tokens["refresh_token"],
        "token_type": "bearer",
        "user": _user_to_public(user),
    }
    payload_b64 = base64.b64encode(json.dumps(payload, default=str).encode()).decode()

    frontend_fallback = f"{app_cfg.hosting_config.frontend_url.rstrip('/')}/auth/oauth-callback"

    html = f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><title>Intellect — OAuth</title>
<style>
body{{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
display:flex;align-items:center;justify-content:center;min-height:100vh;
margin:0;background:#f8f9fa;color:#6c757d}}
.box{{text-align:center}}
.spinner{{width:24px;height:24px;border:2px solid #dee2e6;
border-top-color:#0d6efd;border-radius:50%;
animation:spin 1s linear infinite;margin:0 auto 12px}}
@keyframes spin{{to{{transform:rotate(360deg)}}}}
p{{margin:0;font-size:0.875rem}} small{{font-size:0.75rem;opacity:0.7}}
</style></head>
<body>
<div class="box"><div class="spinner"></div><p>Completing sign in…</p>
<<small>You can close this window if it doesn't close automatically.</small></div>
<script>
(function(){{
  const payload=JSON.parse(atob('{payload_b64}'));
  if(window.opener&&window.opener!==window){{
    window.opener.postMessage({{type:'INTELLECT_OAUTH_SUCCESS',payload:payload}},'*');
    window.close();
  }}else{{
    const q=new URLSearchParams({{access_token:payload.access_token,refresh_token:payload.refresh_token}});
    window.location.href='{frontend_fallback}?' + q.toString();
  }}
}})();
</script>
</body></html>"""

    return HTMLResponse(content=html)


# ---------------------------------------------------------------------------
# OAuth — Link / Unlink (authenticated)
# ---------------------------------------------------------------------------

@router.post("/oauth/unlink", response_model=SuccessResponse)
async def unlink_oauth(
    payload: dict,  # { provider: str }
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    provider: str = payload.get("provider", "")
    if not provider:
        raise HTTPException(status_code=400, detail="Provider is required.")

    account = db.query(OAuthAccount).filter(
        OAuthAccount.user_id == user.id,
        OAuthAccount.provider == provider,
    ).first()

    if not account:
        raise HTTPException(status_code=404, detail="Account not linked.")

    # Count OTHER linked providers (excluding the one we're removing)
    other_oauth_count = db.query(OAuthAccount).filter(
        OAuthAccount.user_id == user.id,
        OAuthAccount.provider != provider,
    ).count()

    has_local_password = bool(user.password_hash)

    if other_oauth_count == 0 and not has_local_password:
        raise HTTPException(
            status_code=400,
            detail="Add a password before unlinking your only sign-in method.",
        )

    db.delete(account)
    db.commit()
    return SuccessResponse(message=f"{provider.title()} account unlinked.")


# 

# app/api/v1/auth_impersonation.py
# Admin impersonation endpoints — secure, audited, restricted

# from datetime import datetime, timedelta, timezone
# from typing import Optional
# from fastapi import APIRouter, Depends, HTTPException
# from sqlalchemy.orm import Session

# from app.db.database import get_db
# from app.models import User
# from app.api.deps.auth import get_current_user, require_admin
# from app.core.config import get_app_config
# from app.core.security import create_access_token
# import logging

# router = APIRouter(prefix="/auth", tags=["Auth"])
# logger = logging.getLogger(__name__)

# Hard-coded super-admin email as requested
# SUPER_ADMIN_EMAIL = "chrisjsmez@gmail.com"




# def _can_impersonate(admin_user: User) -> bool:
#     """Only the specific super-admin email can impersonate."""
#     return admin_user.is_admin() and admin_user.email.lower() == SUPER_ADMIN_EMAIL.lower()


# from app.utils.auth import ImpersonationError, _c

@router.post("/impersonate/{user_id}")
async def impersonate_user(
    user_id: int,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """
    Admin impersonation: generate a temporary access token for the target user.
    Only available to the designated super-admin email.

    Returns a token that the frontend can use to switch sessions.
    The original admin token must be preserved client-side for reversion.
    """
    if not can_impersonate(admin):
        raise ImpersonationError(
            "Impersonation is restricted to the primary system administrator."
        )

    target = db.query(User).filter(User.id == user_id, User.is_active == True).first()
    if not target:
        raise HTTPException(status_code=404, detail="Target user not found or inactive")

    # Prevent impersonating another admin (security boundary)
    if target.is_admin() and target.id != admin.id:
        raise ImpersonationError("Cannot impersonate another administrator.")

    # Audit log
    logger.warning(
        "IMPERSONATION: Admin %s (%s) is impersonating user %s (%s)",
        admin.id, admin.email, target.id, target.email
    )

    # Generate a short-lived impersonation token (15 min)
    impersonation_token = create_access_token(
        data={
            "sub": str(target.id),
            "impersonated_by": str(admin.id),
            "impersonated_by_email": admin.email,
            "type": "impersonation",
        },
        expires_delta=timedelta(minutes=15),
    )

    return {
        "token": impersonation_token,
        "target_user": {
            "id": target.id,
            "name": target.name,
            "email": target.email,
            "username": target.username,
            "roles": [r.name for r in target.roles],
            "primary_role": target.primary_role(),
        },
        "impersonated_by": {
            "id": admin.id,
            "name": admin.name,
            "email": admin.email,
        },
        "expires_in": 900,  # 15 minutes in seconds
    }


@router.post("/impersonate/revert")
async def revert_impersonation(
    user: User = Depends(get_current_user),
):
    """
    Revert impersonation: returns confirmation.
    The frontend swaps back to the stored original admin token.
    """
    # Audit log
    if getattr(user, '_is_impersonating', False):
        logger.info(
            "IMPERSONATION REVERT: User %s reverting from impersonation by admin %s",
            user.id, getattr(user, '_impersonated_by_id', 'unknown')
        )

    return {
        "message": "Impersonation session ended. Restore your original admin token.",
        "reverted": True,
    }
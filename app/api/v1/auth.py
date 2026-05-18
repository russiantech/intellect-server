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
import re
import secrets
import urllib.parse
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any

import httpx
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.models import User, Role, OAuthAccount
from app.schemas import (
    SignupRequest, SigninRequest, ForgotPasswordRequest,
    ChangePasswordRequest, SuccessResponse,
)
from app.core.security.security import (
    hash_password, verify_password,
    create_access_token, create_refresh_token, decode_token,
)
from app.services.email_service import (
    send_verification_email, send_welcome_email,
    send_password_reset_email,
)
from app.api.deps.auth import get_current_user, bearer_scheme
from app.api.deps.storage import get_redis_service
from app.services.redis_service import RedisService
from app.core.config import get_app_config
from app.utils.helpers import generate_secure_code
from app.utils.responses import api_response

router = APIRouter(prefix="/auth", tags=["Authentication"])
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# DRY Helpers
# ---------------------------------------------------------------------------

# def _user_to_public(user: User) -> dict:
#     return {
#         "id": user.id,
#         "name": user.name,
#         "username": user.username,
#         "email": user.email,
#         "phone": user.phone,
#         "image": user.image,
#         "title": user.title,
#         "gender": user.gender,
#         "city": user.city,
#         "country": user.country,
#         "lang": user.lang,
#         "about": user.about,
#         "socials": user.socials,
#         "education": user.education,
#         "expertise": user.expertise,
#         "is_creator": user.is_creator,
#         "creator_bio": user.creator_bio,
#         "creator_approved": user.creator_approved,
#         "email_verified": user.email_verified,
#         "is_online": user.is_online,
#         "last_seen": user.last_seen,
#         "roles": [r.name for r in user.roles],
#         "primary_role": user.primary_role(),
#         "created_at": user.created_at,
#         "oauth_providers": [oa.provider for oa in user.oauth_accounts],
#     }


from datetime import datetime, timezone  # ensure this import exists

def _user_to_public(user: User) -> dict:
    
    def _dt(v):
        return v.isoformat() if isinstance(v, datetime) else v

    return {
        "id": user.id,
        "name": user.name,
        "username": user.username,
        "email": user.email,
        "phone": user.phone,
        "image": user.image,
        "title": user.title,
        "gender": user.gender,
        "city": user.city,
        "country": user.country,
        "lang": user.lang,
        "about": user.about,
        "socials": user.socials,
        "education": user.education,
        "expertise": user.expertise,
        "is_creator": user.is_creator,
        "creator_bio": user.creator_bio,
        "creator_approved": user.creator_approved,
        "email_verified": user.email_verified,
        "is_online": user.is_online,
        "last_seen": _dt(user.last_seen),
        "roles": [r.name for r in user.roles],
        "primary_role": user.primary_role(),
        "created_at": _dt(user.created_at),
        "oauth_providers": [oa.provider for oa in user.oauth_accounts],
    }


def _issue_tokens(user: User) -> dict:
    data = {"sub": str(user.id)}
    return {
        "access_token": create_access_token(data),
        "refresh_token": create_refresh_token(data),
        "token_type": "bearer",
        "user": _user_to_public(user),
    }


def _normalize_phone(phone: Optional[str]) -> str:
    if not phone:
        return ""
    return re.sub(r'[\s\-\(\)\+]', '', phone.strip().lower())


def _resolve_user_by_identifier(db: Session, identifier: str) -> Optional[User]:
    clean = identifier.strip().lower()
    user = db.query(User).filter(
        User.is_active == True,
        (User.email == clean) | (User.username == clean)
    ).first()
    if user:
        return user

    phone_clean = _normalize_phone(clean)
    if phone_clean and len(phone_clean) >= 7:
        candidates = db.query(User).filter(
            User.is_active == True,
            User.phone.isnot(None)
        ).limit(100).all()
        for u in candidates:
            if _normalize_phone(u.phone) == phone_clean:
                return u
    return None


def _generate_username(db: Session, base: str) -> str:
    base = re.sub(r'[^a-z0-9]', '', base.lower())[:20]
    if not db.query(User).filter(User.username == base).first():
        return base
    for i in range(1, 1000):
        candidate = f"{base}{i}"
        if not db.query(User).filter(User.username == candidate).first():
            return candidate
    return f"{base}{secrets.token_hex(4)}"


async def _fetch_oauth_userinfo(provider: str, access_token: str, cfg: Any) -> Dict[str, Any]:
    headers = {"Authorization": f"Bearer {access_token}"}
    async with httpx.AsyncClient() as client:
        if provider == "github":
            r = await client.get(cfg.userinfo_url, headers=headers)
            r.raise_for_status()
            data = r.json()
            email = data.get("email")
            if not email and cfg.emails_url:
                er = await client.get(cfg.emails_url, headers=headers)
                emails = er.json()
                primary = next((e for e in emails if e.get("primary")), None)
                email = primary["email"] if primary else (emails[0]["email"] if emails else None)
            return {
                "id": str(data["id"]),
                "email": email,
                "name": data.get("name") or data.get("login"),
                "picture": data.get("avatar_url"),
            }

        if provider == "google":
            r = await client.get(cfg.userinfo_url, headers=headers)
            r.raise_for_status()
            data = r.json()
            return {
                "id": data["sub"],
                "email": data.get("email"),
                "name": data.get("name"),
                "picture": data.get("picture"),
                "verified": data.get("email_verified", False),
                "phone": None,  # ← explicitly None, not available
            }

        if provider == "facebook":
            r = await client.get(
                cfg.userinfo_url,
                params={"fields": "id,name,email,picture", "access_token": access_token}
            )
            r.raise_for_status()
            data = r.json()
            return {
                "id": data["id"],
                "email": data.get("email"),
                "name": data.get("name"),
                "picture": data.get("picture", {}).get("data", {}).get("url"),
            }

        if provider == "linkedin":
            r = await client.get(cfg.userinfo_url, headers=headers)
            r.raise_for_status()
            data = r.json()
            email_r = await client.get(
                "https://api.linkedin.com/v2/emailAddress?q=members&projection=(elements*(handle~))",
                headers=headers,
            )
            email_data = email_r.json()
            elements = email_data.get("elements", [])
            email = elements[0].get("handle~", {}).get("emailAddress") if elements else None
            first = data.get("localizedFirstName", "")
            last = data.get("localizedLastName", "")
            return {
                "id": data.get("id"),
                "email": email,
                "name": f"{first} {last}".strip(),
                "picture": None,
            }

        raise HTTPException(status_code=400, detail=f"Unsupported OAuth provider: {provider}")


def _create_or_link_oauth_user(
    db: Session,
    provider: str,
    account_id: str,
    userinfo: Dict[str, Any],
    provider_tokens: Dict[str, Any],
) -> User:
    email = (userinfo.get("email") or "").lower().strip()
    name = userinfo.get("name") or email.split("@")[0]

    existing_link = db.query(OAuthAccount).filter(
        OAuthAccount.provider == provider,
        OAuthAccount.provider_account_id == account_id,
    ).first()
    if existing_link:
        return existing_link.user

    if email:
        user = db.query(User).filter(User.email == email).first()
        if user:
            oauth = OAuthAccount(
                user_id=user.id,
                provider=provider,
                provider_account_id=account_id,
            )
            db.add(oauth)
            db.commit()
            return user

    username = _generate_username(db, name or email or provider)
    random_pw = secrets.token_urlsafe(32)
    user = User(
        name=name,
        username=username,
        email=email or f"{username}@{provider}.oauth",
        password_hash=hash_password(random_pw),
        email_verified=userinfo.get("verified", True),
    )
    student_role = db.query(Role).filter(Role.name == "student").first()
    if not student_role:
        student_role = Role(name="student", description="Learner / Student")
        db.add(student_role)
        db.flush()
    user.roles.append(student_role)

    db.add(user)
    db.flush()

    # oauth = OAuthAccount(
    #     user_id=user.id,
    #     provider=provider,
    #     provider_account_id=account_id,
    # )
    oauth = OAuthAccount(
        user_id=user.id,
        provider=provider,
        provider_account_id=account_id,
        access_token=provider_tokens.get("access_token"),
        refresh_token=provider_tokens.get("refresh_token"),
        expires_at=provider_tokens.get("expires_at"),  # if provider returns it
    )
    db.add(oauth)
    db.commit()
    db.refresh(user)
    return user


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
        raise HTTPException(status_code=401, detail="Invalid email, username, phone or password.")

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

@router.get("/oauth/providers")
async def list_oauth_providers():
    cfg = get_app_config()
    return api_response(
        success=True,
        message="Available OAuth providers retrieved successfully.",
        data=[
            {"provider": name, "name": name.title()}
            for name in cfg.oauth_provider_config.keys()
        ],
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

# @router.get("/oauth/{provider}/callback")
# async def oauth_callback(
#     provider: str,
#     code: str,
#     state: str,
#     request: Request,
#     db: Session = Depends(get_db),
#     redis: Optional[RedisService] = Depends(get_redis_service),
# ):
#     if not redis:
#         raise HTTPException(status_code=503, detail="Service temporarily unavailable.")

#     # 1. Validate state
#     state_key = f"intellect:oauth_state:{state}"
#     state_data = redis.get(state_key, as_json=True)
#     if not state_data or state_data.get("provider") != provider:
#         return _oauth_error_html("Invalid or expired OAuth state.")
#     redis.delete(state_key)

#     app_cfg = get_app_config()
#     cfg = app_cfg.oauth_provider_config.get(provider)
#     if not cfg:
#         return _oauth_error_html("Unsupported OAuth provider.")

#     redirect_uri = state_data["redirect_uri"]

#     # 2. Exchange code for access token
#     token_payload = {
#         "client_id": cfg.client_id,
#         "client_secret": cfg.client_secret,
#         "code": code,
#         "redirect_uri": redirect_uri,
#         "grant_type": "authorization_code",
#     }
#     async with httpx.AsyncClient() as client:
#         token_resp = await client.post(cfg.token_url, data=token_payload)
#     if token_resp.status_code != 200:
#         logger.error(f"OAuth token exchange failed: {token_resp.text}")
#         return _oauth_error_html("Failed to exchange OAuth code.")

#     token_json = token_resp.json()
#     access_token = token_json.get("access_token")
#     if not access_token:
#         return _oauth_error_html("OAuth provider did not return an access token.")

#     # 3. Fetch user info
#     try:
#         userinfo = await _fetch_oauth_userinfo(provider, access_token, cfg)
#     except Exception as exc:
#         logger.error(f"OAuth userinfo failed: {exc}", exc_info=True)
#         return _oauth_error_html("Failed to fetch user info from provider.")

#     # 4. Create / link / sign in
#     account_id = userinfo["id"]
#     # user = _create_or_link_oauth_user(db, provider, account_id, userinfo)
#     user = _create_or_link_oauth_user(
#     db, provider, account_id, userinfo,
#     provider_tokens={
#         "access_token": token_json.get("access_token"),
#         "refresh_token": token_json.get("refresh_token"),
#         "expires_at": token_json.get("expires_in"),  # or calculate from now + expires_in
#     }
#     )
#     user.is_online = True
#     user.last_seen = datetime.now(timezone.utc)
#     db.commit()

#     # 5. Issue tokens
#     tokens = _issue_tokens(user)
#     payload = {
#         "access_token": tokens["access_token"],
#         "refresh_token": tokens["refresh_token"],
#         "token_type": "bearer",
#         "user": _user_to_public(user),
#     }
#     payload_b64 = base64.b64encode(json.dumps(payload).encode()).decode()

#     # Frontend fallback route (used if popup opener is missing)
#     frontend_fallback = f"{app_cfg.hosting_config.frontend_url.rstrip('/')}/auth/oauth-callback"

#     frontend_origin = app_cfg.hosting_config.frontend_url.rstrip('/')

#     # In the success HTML, replace the wildcard:
#     # FROM: window.opener.postMessage({...}, '*');
#     # TO:   window.opener.postMessage({...}, '{frontend_origin}');

#     html = f"""<!DOCTYPE html>
#     <html lang="en">
#     <head><meta charset="UTF-8"><title>Intellect — OAuth</title>
#     <style>
#     body{{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
#     display:flex;align-items:center;justify-content:center;min-height:100vh;
#     margin:0;background:#f8f9fa;color:#6c757d}}
#     .box{{text-align:center}}
#     .spinner{{width:24px;height:24px;border:2px solid #dee2e6;
#     border-top-color:#0d6efd;border-radius:50%;
#     animation:spin 1s linear infinite;margin:0 auto 12px}}
#     @keyframes spin{{to{{transform:rotate(360deg)}}}}
#     p{{margin:0;font-size:0.875rem}} small{{font-size:0.75rem;opacity:0.7}}
#     </style></head>
#     <body>
#     <div class="box"><div class="spinner"></div><p>Completing sign in…</p>
#     <<small>You can close this window if it doesn't close automatically.</small></div>
#     <script>
#     (function(){{
#     const payload=JSON.parse(atob('{payload_b64}'));
#     if(window.opener&&window.opener!==window){{
#         window.opener.postMessage({{type:'INTELLECT_OAUTH_SUCCESS',payload:payload}},'{frontend_origin}');
#         window.close();
#     }}else{{
#         const q=new URLSearchParams({{access_token:payload.access_token,refresh_token:payload.refresh_token}});
#         window.location.href='{frontend_fallback}?' + q.toString();
#     }}
#     }})();
#     </script>
#     </body></html>"""

#     return HTMLResponse(content=html)

# v2
# ---------------------------------------------------------------------------
# OAuth — Callback
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


def _create_or_link_oauth_user(
    db: Session,
    provider: str,
    account_id: str,
    userinfo: Dict[str, Any],
    provider_tokens: Dict[str, Any],
) -> User:
    """Find existing OAuth link, auto-link by email, or create a new account."""
    email = (userinfo.get("email") or "").lower().strip()
    name = userinfo.get("name") or email.split("@")[0]

    # 1. Already linked?
    existing_link = db.query(OAuthAccount).filter(
        OAuthAccount.provider == provider,
        OAuthAccount.provider_account_id == account_id,
    ).first()
    if existing_link:
        # Update tokens
        existing_link.access_token = provider_tokens.get("access_token")
        existing_link.refresh_token = provider_tokens.get("refresh_token")
        if provider_tokens.get("expires_at"):
            existing_link.expires_at = datetime.now(timezone.utc) + timedelta(seconds=provider_tokens["expires_at"])
        db.commit()
        return existing_link.user

    # 2. Auto-link by email if user exists
    if email:
        user = db.query(User).filter(User.email == email).first()
        if user:
            oauth = OAuthAccount(
                user_id=user.id,
                provider=provider,
                provider_account_id=account_id,
                access_token=provider_tokens.get("access_token"),
                refresh_token=provider_tokens.get("refresh_token"),
            )
            if provider_tokens.get("expires_at"):
                oauth.expires_at = datetime.now(timezone.utc) + timedelta(seconds=provider_tokens["expires_at"])
            db.add(oauth)
            db.commit()
            return user

    # 3. Create new user
    username = _generate_username(db, name or email or provider)
    random_pw = secrets.token_urlsafe(32)
    user = User(
        name=name,
        username=username,
        email=email or f"{username}@{provider}.oauth",
        phone=userinfo.get("phone"),  # ← will be None for Google
        password_hash=hash_password(random_pw),
        email_verified=userinfo.get("verified", True),
    )
    student_role = db.query(Role).filter(Role.name == "student").first()
    if not student_role:
        student_role = Role(name="student", description="Learner / Student")
        db.add(student_role)
        db.flush()
    user.roles.append(student_role)

    db.add(user)
    db.flush()

    oauth = OAuthAccount(
        user_id=user.id,
        provider=provider,
        provider_account_id=account_id,
        access_token=provider_tokens.get("access_token"),
        refresh_token=provider_tokens.get("refresh_token"),
    )
    if provider_tokens.get("expires_at"):
        oauth.expires_at = datetime.now(timezone.utc) + timedelta(seconds=provider_tokens["expires_at"])
    db.add(oauth)
    db.commit()
    db.refresh(user)
    return user


def _oauth_error_html(message: str) -> HTMLResponse:
    """Return HTML that signals error to opener or redirects to fallback."""
    app_cfg = get_app_config()
    frontend_fallback = f"{app_cfg.hosting_config.frontend_url.rstrip('/')}/auth/oauth-callback"
    frontend_origin = app_cfg.hosting_config.frontend_url.rstrip('/')
    msg_b64 = base64.b64encode(message.encode()).decode()
    html = f"""<!DOCTYPE html>
    <html><head><title>Sign In Error</title></head>
    <body style="font-family:sans-serif;text-align:center;margin-top:40px;color:#666;">
    <p>Authentication failed.</p>
    <script>
    const msg=atob('{msg_b64}');
    if(window.opener&&window.opener!==window){{
    window.opener.postMessage({{type:'INTELLECT_OAUTH_ERROR',payload:{{message:msg}}}},'{frontend_origin}');
    window.close();
    }}else{{
    window.location.href='{frontend_fallback}?error='+encodeURIComponent(msg);
    }}
    </script></body></html>"""
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


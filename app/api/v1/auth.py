"""
Authentication endpoints — Intellect LMS
Signup: two-step (initiate → verify via 6-digit code, Redis-backed)
Password reset: code-based (no URL tokens)
"""

import logging
import secrets
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.models import User, Role
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
from app.api.deps.storage import get_redis_service          # add this dep (see note below)
from app.services.redis_service import RedisService       # reuse or mirror Score App's
from app.core.config import get_app_config
from app.utils.helpers import generate_secure_code
from app.utils.responses import api_response        # 6-digit generator

router = APIRouter(prefix="/auth", tags=["Authentication"])
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _user_to_public(user: User) -> dict:
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
        "last_seen": user.last_seen,
        "roles": [r.name for r in user.roles],
        "primary_role": user.primary_role(),
        "created_at": user.created_at,
    }


def _issue_tokens(user: User) -> dict:
    data = {"sub": str(user.id)}
    return {
        "access_token": create_access_token(data),
        "refresh_token": create_refresh_token(data),
        "token_type": "bearer",
        "user": _user_to_public(user),
    }


# ---------------------------------------------------------------------------
# Signup — Step 1: Initiate
# ---------------------------------------------------------------------------

@router.post("/signup", status_code=status.HTTP_202_ACCEPTED)
async def signup(
    payload: SignupRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    redis: Optional[RedisService] = Depends(get_redis_service),
):
    """
    Validate credentials, generate a 6-digit email code and store
    signup data in Redis (10 min). Returns a signup_token the client
    must present at /signup/verify-signup.
    """
    if not redis:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Service temporarily unavailable. Please try again.",
        )

    # Uniqueness checks
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
        "password": hash_password(payload.password),   # store hashed — never raw
        "email_code": email_code,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    
    print(signup_data)

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
        email_code,  # pass code, not URL
    )

    logger.info(f"Signup initiated for {payload.email}")

    # return {
    #     "success": True,
    #     "message": "Verification code sent! Check your email.",
    #     "data": {
    #         "token": signup_token,
    #         "email": payload.email.lower(),
    #         "expires_in_seconds": 600,
    #     },
    # }
    
    return api_response(
            success=True,
            message="Verification codes sent! Please check your email and phone.",
            data={
                "token": signup_token,
                "email": payload.email.lower(),
                # "phone": data.phone,
                # "email_sent": email_sent,
                # "sms_sent": sms_sent,
                "expires_in_seconds": 600
            }
        )


# ---------------------------------------------------------------------------
# Signup — Step 2: Verify
# ---------------------------------------------------------------------------

@router.post("/signup/verify-signup", status_code=status.HTTP_201_CREATED)
async def verify_signup(
    payload: dict,              # { token: str, email_code: str }
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    redis: Optional[RedisService] = Depends(get_redis_service),
):
    print(payload)
    """Confirm the 6-digit code and create the user account."""
    if not redis:
        raise HTTPException(status_code=503, detail="Service temporarily unavailable.")

    token: str = payload.get("token", "")
    email_code: str = payload.get("email_code", "")

    if not token or not email_code:
        raise HTTPException(status_code=400, detail="Token and code are required.")

    redis_key = f"intellect:signup_pending:{token}"
    signup_data = redis.get(redis_key, as_json=True)

    if not signup_data:
        raise HTTPException(
            status_code=400,
            detail="Session expired or invalid. Please sign up again.",
        )

    if signup_data.get("email_code") != email_code.strip():
        raise HTTPException(status_code=400, detail="Invalid verification code.")

    # Race-condition guard
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
        password_hash=signup_data["password"],   # already hashed
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


# ---------------------------------------------------------------------------
# Signup — Resend code
# ---------------------------------------------------------------------------

@router.post("/signup/resend", response_model=SuccessResponse)
async def resend_signup_code(
    payload: dict,      # { token: str }
    background_tasks: BackgroundTasks,
    redis: Optional[RedisService] = Depends(get_redis_service),
):
    print(payload)
    if not redis:
        raise HTTPException(status_code=503, detail="Service temporarily unavailable.")

    token = payload.get("token", "")
    redis_key = f"intellect:signup_pending:{token}"
    signup_data = redis.get(redis_key, as_json=True)

    if not signup_data:
        raise HTTPException(status_code=400, detail="Session expired. Please sign up again.")

    new_code = generate_secure_code(6)
    signup_data["email_code"] = new_code
    redis.set(redis_key, signup_data, expiry=600)  # reset TTL

    background_tasks.add_task(
        send_verification_email,
        signup_data["email"],
        signup_data["name"] or signup_data["username"],
        new_code,
    )

    return SuccessResponse(message="New verification code sent.")


# ---------------------------------------------------------------------------
# Sign In
# ---------------------------------------------------------------------------

@router.post("/signin")
async def signin(payload: SigninRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(
        User.email == payload.email.lower(),
        User.is_active == True,
    ).first()

    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password.")

    if not user.email_verified:
        raise HTTPException(status_code=403, detail="Please verify your email before signing in.")

    user.is_online = True
    user.last_seen = datetime.now(timezone.utc)
    db.commit()

    return _issue_tokens(user)


# ---------------------------------------------------------------------------
# Refresh token
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


# ---------------------------------------------------------------------------
# Sign Out
# ---------------------------------------------------------------------------

@router.post("/signout", response_model=SuccessResponse)
async def signout(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    user.is_online = False
    user.last_seen = datetime.now(timezone.utc)
    db.commit()
    return SuccessResponse(message="Signed out successfully.")


# ---------------------------------------------------------------------------
# Forgot Password — sends 6-digit code
# ---------------------------------------------------------------------------

# @router.post("/forgot-password", response_model=SuccessResponse)
# async def forgot_password(
#     payload: ForgotPasswordRequest,
#     background_tasks: BackgroundTasks,
#     db: Session = Depends(get_db),
#     redis: Optional[RedisService] = Depends(get_redis_service),
# ):
#     if not redis:
#         raise HTTPException(status_code=503, detail="Service temporarily unavailable.")

#     user = db.query(User).filter(User.email == payload.email.lower()).first()

#     # Always return the same message (security best-practice: don't reveal existence)
#     generic_msg = "If that email is registered, a reset code has been sent."
#     if not user or not user.is_active:
#         return SuccessResponse(message=generic_msg)

#     reset_code = generate_secure_code(6)
#     redis_key = f"intellect:pwd_reset:{reset_code}"
#     redis.set(
#         redis_key,
#         {"user_id": str(user.id), "email": user.email},
#         expiry=900,  # 15 minutes
#     )

#     background_tasks.add_task(
#         send_password_reset_email,
#         user.email, user.name or user.username, reset_code,
#     )

#     logger.info(f"Password reset code issued for {user.email}")
#     return SuccessResponse(message=generic_msg)


# # ---------------------------------------------------------------------------
# # Reset Password — consumes 6-digit code
# # ---------------------------------------------------------------------------

# @router.post("/reset-password", response_model=SuccessResponse)
# async def reset_password(
#     payload: dict,    # { reset_code: str, new_password: str }
#     db: Session = Depends(get_db),
#     redis: Optional[RedisService] = Depends(get_redis_service),
# ):
#     if not redis:
#         raise HTTPException(status_code=503, detail="Service temporarily unavailable.")

#     reset_code: str = (payload.get("reset_code") or "").strip().upper()
#     new_password: str = payload.get("new_password") or ""

#     if not reset_code or not new_password:
#         raise HTTPException(status_code=400, detail="Reset code and new password are required.")

#     redis_key = f"intellect:pwd_reset:{reset_code}"
#     reset_data = redis.get(redis_key, as_json=True)

#     if not reset_data:
#         raise HTTPException(status_code=400, detail="Invalid or expired reset code.")

#     user = db.query(User).filter(User.id == int(reset_data["user_id"])).first()
#     if not user or not user.is_active:
#         redis.delete(redis_key)
#         raise HTTPException(status_code=400, detail="Account unavailable.")

#     user.password_hash = hash_password(new_password)
#     db.commit()
#     redis.delete(redis_key)

#     return SuccessResponse(message="Password reset successfully. You can now sign in.")

# v2
# ---------------------------------------------------------------------------
# Forgot Password — Step 1: Initiate (returns token, code sent via email)
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
    reset_code  = generate_secure_code(6)

    # Always return identical shape so we don't leak email existence.
    # Only store & send if the user actually exists.
    if user:
        redis_key = f"intellect:pwd_reset:{reset_token}"
        redis.set(
            redis_key,
            {
                "user_id": str(user.id),
                "email": user.email,
                "reset_code": reset_code,
            },
            expiry=900,  # 15 minutes
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


# ---------------------------------------------------------------------------
# Forgot Password — Step 2: Verify code + set new password
# ---------------------------------------------------------------------------

@router.post("/reset-password")
async def reset_password(
    payload: dict,   # { token: str, email_code: str, new_password: str }
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


# ---------------------------------------------------------------------------
# Forgot Password — Resend code
# ---------------------------------------------------------------------------

@router.post("/forgot-password/resend")
async def resend_reset_code(
    payload: dict,   # { token: str }
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


# ---------------------------------------------------------------------------
# Change Password (authenticated)
# ---------------------------------------------------------------------------

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
# Get current user
# ---------------------------------------------------------------------------

@router.get("/me")
async def get_me(user: User = Depends(get_current_user)):
    return _user_to_public(user)


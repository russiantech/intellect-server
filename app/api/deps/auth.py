from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.core.security.security import decode_token
from app.models import User

bearer_scheme = HTTPBearer(auto_error=False)


def _get_token_payload(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
) -> dict:
    if not credentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    payload = decode_token(credentials.credentials)
    if not payload or payload.get("type") != "access":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")
    return payload


# def get_current_user(
#     payload: dict = Depends(_get_token_payload),
#     db: Session = Depends(get_db),
# ) -> User:
#     user_id = payload.get("sub")
#     if not user_id:
#         raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token payload")
#     user = db.query(User).filter(User.id == int(user_id), User.is_active == True).first()
#     if not user:
#         raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found or inactive")
#     return user


# v2
# app/api/deps/auth.py — Additions for impersonation token handling
# Add this to your existing auth deps file

from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from jose import JWTError, jwt

from app.db.database import get_db
from app.models import User
from app.core.config import get_app_config

security = HTTPBearer(auto_error=False)

async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db),
) -> User:
    """
    Resolve current user from JWT token.
    Handles both normal tokens and impersonation tokens.
    """
    if not credentials:
        raise HTTPException(status_code=401, detail="Not authenticated")

    cfg = get_app_config()
    try:
        payload = jwt.decode(
            credentials.credentials,
            cfg.security_config.auth_jwt_secret_key or cfg.security_config.jwt_secret_key,
            algorithms=[cfg.security_config.jwt_algorithm],
        )
        user_id: str = payload.get("sub")
        if user_id is None:
            raise HTTPException(status_code=401, detail="Invalid token")

        # Check if this is an impersonation token
        impersonated_by = payload.get("impersonated_by")
        token_type = payload.get("type")

    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")

    user = db.query(User).filter(User.id == int(user_id)).first()
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="User not found or inactive")

    # Attach impersonation metadata to the user object for downstream use
    if impersonated_by and token_type == "impersonation":
        user._is_impersonating = True
        user._impersonated_by_id = int(impersonated_by)
        user._impersonated_by_email = payload.get("impersonated_by_email")
    else:
        user._is_impersonating = False
        user._impersonated_by_id = None
        user._impersonated_by_email = None

    return user


# def require_admin(user: User = Depends(get_current_user)) -> User:
#     if not user.is_admin():
#         raise HTTPException(status_code=403, detail="Admin access required")
#     return user


async def optional_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db),
) -> User | None:
    """Optional authentication — returns None if no valid token."""
    if not credentials:
        return None
    try:
        return await get_current_user(credentials, db)
    except HTTPException:
        return None

# 

def get_current_verified_user(user: User = Depends(get_current_user)) -> User:
    if not user.email_verified:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Email not verified. Please verify your email first.",
        )
    return user


def require_admin(user: User = Depends(get_current_user)) -> User:
    if not user.is_admin():
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")
    return user


# def require_super_admin(user: User = Depends(get_current_user)) -> User:
#     if not user.has_role("super_admin"):
#         raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Super admin access required")
#     return user

def require_super_admin(user: User = Depends(get_current_user)) -> User:
    """
    Super-admin: role='super_admin' OR email in APP_SUPER_ADMIN_EMAILS env list.
    Configurable — never a single hardcoded address.
    """
    cfg = get_app_config().security_config
    is_role_sa = user.has_role("super_admin")
    is_email_sa = user.email.lower() in [e.lower() for e in (cfg.super_admin_emails or [])]
    if not (is_role_sa or is_email_sa):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Super admin access required")
    return user

def require_creator_or_admin(user: User = Depends(get_current_verified_user)) -> User:
    if not (user.is_creator or user.is_admin()):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Creator or Admin access required")
    return user


def require_tutor_or_admin(user: User = Depends(get_current_user)) -> User:
    if not (user.has_role("tutor") or user.is_admin()):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Tutor or Admin access required")
    return user


class ImpersonationError(HTTPException):
    def __init__(self, detail: str):
        super().__init__(status_code=403, detail=detail)

def can_impersonate(user: User) -> bool:
    """
    True if user may impersonate others.
    Checks super_admin ROLE or presence in APP_SUPER_ADMIN_EMAILS list.
    Multiple emails supported — comma-separated in .env.
    """
    cfg = get_app_config().security_config
    has_role = user.has_role("super_admin")
    in_list = user.email.lower() in [e.lower() for e in (cfg.super_admin_emails or [])]
    return has_role or in_list

def require_impersonation_rights(user: User = Depends(get_current_user)) -> User:
    if not can_impersonate(user):
        raise ImpersonationError("You do not have impersonation privileges")
    return user

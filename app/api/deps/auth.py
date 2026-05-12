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


def get_current_user(
    payload: dict = Depends(_get_token_payload),
    db: Session = Depends(get_db),
) -> User:
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token payload")
    user = db.query(User).filter(User.id == int(user_id), User.is_active == True).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found or inactive")
    return user


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


def require_super_admin(user: User = Depends(get_current_user)) -> User:
    if not user.has_role("super_admin"):
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


def optional_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User | None:
    if not credentials:
        return None
    payload = decode_token(credentials.credentials)
    if not payload or payload.get("type") != "access":
        return None
    user_id = payload.get("sub")
    if not user_id:
        return None
    return db.query(User).filter(User.id == int(user_id), User.is_active == True).first()

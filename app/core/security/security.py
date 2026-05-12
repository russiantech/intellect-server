from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple
from jose import JWTError, jwt
from passlib.context import CryptContext

from app.core.config import get_app_config

pwd_context = CryptContext(schemes=["scrypt", "bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    cfg = get_app_config().security_config
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=cfg.access_token_expire_minutes)
    )
    return jwt.encode(
        {**data, "exp": expire, "type": "access"},
        cfg.auth_jwt_secret_key,
        algorithm=cfg.jwt_algorithm,
    )


def create_refresh_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    cfg = get_app_config().security_config
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=cfg.refresh_token_expire_minutes)
    )
    return jwt.encode(
        {**data, "exp": expire, "type": "refresh"},
        cfg.auth_jwt_secret_key,
        algorithm=cfg.jwt_algorithm,
    )


def decode_token(token: str) -> Optional[dict]:
    cfg = get_app_config().security_config
    try:
        return jwt.decode(token, cfg.auth_jwt_secret_key, algorithms=[cfg.jwt_algorithm])
    except JWTError:
        return None


def create_email_token(user_id: int, token_type: str = "verify") -> Tuple[str, datetime]:
    """Generate a signed token for email verification or password reset."""
    cfg = get_app_config().security_config
    if token_type == "reset":
        minutes = cfg.password_reset_token_expire_minutes
    else:
        minutes = cfg.email_verification_token_expire_minutes
    expire = datetime.now(timezone.utc) + timedelta(minutes=minutes)
    token = jwt.encode(
        {"user_id": user_id, "exp": expire, "type": token_type},
        cfg.auth_jwt_secret_key,
        algorithm=cfg.jwt_algorithm,
    )
    return token, expire


def decode_email_token(token: str, expected_type: str) -> Optional[int]:
    payload = decode_token(token)
    if not payload:
        return None
    if payload.get("type") != expected_type:
        return None
    return payload.get("user_id")

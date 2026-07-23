
# ---------------------------------------------------------------------------
# DRY Helpers For Auth Related
# ---------------------------------------------------------------------------

import base64
import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any

from fastapi.responses import HTMLResponse
import httpx
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models import User, Role, OAuthAccount
from app.core.security.security import (
    hash_password, create_access_token, create_refresh_token,
)
from app.core.config import get_app_config

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


# linking

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

# 

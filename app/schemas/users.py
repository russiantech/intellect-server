from datetime import datetime
from typing import Any, Optional, List, Dict
from pydantic import BaseModel, EmailStr, Field


# class UserPublic(BaseModel):
#     id: int
#     name: Optional[str] = None
#     username: str
#     email: str
#     phone: Optional[str] = None
#     image: Optional[str] = None
#     title: Optional[str] = None
#     gender: Optional[str] = None
#     city: Optional[str] = None
#     country: Optional[str] = None
#     lang: Optional[str] = None
#     about: Optional[str] = None
#     socials: Optional[Dict] = None
#     education: Optional[str] = None
#     expertise: Optional[str] = None
#     is_creator: bool = False
#     creator_approved: bool = False
#     email_verified: bool = False
#     is_online: bool = False
#     last_seen: Optional[datetime] = None
#     primary_role: Optional[str] = None
#     created_at: Optional[datetime] = None

#     class Config:
#         from_attributes = True

class UserPublic(BaseModel):
    id: int
    name: Optional[str] = None
    username: str
    email: str
    phone: Optional[str] = None
    image: Optional[str] = None
    title: Optional[str] = None
    gender: Optional[str] = None
    city: Optional[str] = None
    country: Optional[str] = None
    lang: Optional[str] = None
    about: Optional[str] = None

    socials: Optional[Dict[str, Any]] = None
    education: Optional[Any] = None      # ✅ FIXED (was str)
    expertise: Optional[str] = None
    projects: Optional[Any] = None       # ✅ ADDED

    is_creator: bool = False
    creator_approved: bool = False
    email_verified: bool = False
    is_online: bool = False
    last_seen: Optional[datetime] = None
    primary_role: Optional[str] = None
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class UserUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=150)
    phone: Optional[str] = None
    title: Optional[str] = None
    gender: Optional[str] = None
    city: Optional[str] = None
    country: Optional[str] = None
    lang: Optional[str] = None
    about: Optional[str] = None

    socials: Optional[Dict[str, Any]] = None
    education: Optional[Any] = None      # ✅ FIXED
    expertise: Optional[str] = None
    projects: Optional[Any] = None       # ✅ FIXED (was str)

    creator_bio: Optional[str] = None
    bank_name: Optional[str] = None
    bank_account_number: Optional[str] = None
    bank_account_name: Optional[str] = None


class AdminUserUpdate(UserUpdate):
    """Admin-only user update — allows toggling is_active, roles, etc."""
    is_active: Optional[bool] = None
    is_deleted: Optional[bool] = None
    email_verified: Optional[bool] = None
    is_creator: Optional[bool] = None
    creator_approved: Optional[bool] = None
    roles: Optional[List[str]] = None


class AdminUserCreate(BaseModel):
    name: str
    username: str
    email: EmailStr
    password: str = Field(..., min_length=8)
    phone: Optional[str] = None
    roles: List[str] = ["student"]
    email_verified: bool = True
    is_creator: bool = False


class CreatorApplicationRequest(BaseModel):
    requested_role: str
    motivation: Optional[str] = None
    portfolio_url: Optional[str] = None


class TeamRequestCreate(BaseModel):
    requested_role: str
    motivation: Optional[str] = None
    portfolio_url: Optional[str] = None


class TeamRequestReview(BaseModel):
    approved: bool
    rejection_reason: Optional[str] = None


class InviteCreate(BaseModel):
    email: EmailStr
    role: str = "student"


# Aliases used by routers
UserUpdateRequest = UserUpdate
AdminUpdateUser = AdminUserUpdate


class UserListItem(UserPublic):
    """Slim user for list views."""
    pass

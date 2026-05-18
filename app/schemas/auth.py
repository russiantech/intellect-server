from datetime import datetime
from typing import Optional
from pydantic import BaseModel, EmailStr, Field, field_validator


class SignupRequest(BaseModel):
    name: str = Field(..., min_length=2, max_length=150)
    username: str = Field(..., min_length=3, max_length=50)
    email: EmailStr
    password: str = Field(..., min_length=4)
    phone: Optional[str] = None

    @field_validator("username")
    @classmethod
    def username_alphanumeric(cls, v):
        if not v.replace("_", "").replace("-", "").isalnum():
            raise ValueError("Username may only contain letters, numbers, - and _")
        return v.lower()


# class SigninRequest(BaseModel):
#     email: EmailStr
#     password: str
#     remember_me: bool = False
# v2
class SigninRequest(BaseModel):
    identifier: str = Field(..., min_length=1, description="Email, username or phone number")
    password: str = Field(..., min_length=1)
    remember_me: bool = Field(default=False)

class OAuthAccountOut(BaseModel):
    provider: str
    created_at: Optional[datetime] = Field(default=None)

    class Config:
        from_attributes = True

class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str = Field(..., min_length=4)


class VerifyEmailRequest(BaseModel):
    token: str


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str = Field(..., min_length=4)


class RefreshTokenRequest(BaseModel):
    refresh_token: str

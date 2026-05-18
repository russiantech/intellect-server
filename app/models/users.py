"""
Intellect LMS — User, Role, BrandConfig, EmailToken Models
"""
from datetime import datetime
from typing import Any, Optional, List
from app.models.courses import Course
from sqlalchemy import (
    Integer, String, Text, Boolean, Float, DateTime,
    ForeignKey, JSON, Index,
)
from sqlalchemy.orm import relationship, Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.database import Base
from app.models.base import TimestampMixin
from app.models.association_tables import user_role_assoc

class Role(Base, TimestampMixin):
    __tablename__ = "roles"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(String(255))
    users: Mapped[List["User"]] = relationship(
        "User", secondary=user_role_assoc, back_populates="roles"
    )


class User(Base, TimestampMixin):
    __tablename__ = "users"
    __table_args__ = (
        Index("ix_users_email", "email"),
        Index("ix_users_username", "username"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[Optional[str]] = mapped_column(String(150))
    username: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    phone: Mapped[Optional[str]] = mapped_column(String(20), unique=True)
    password_hash: Mapped[str] = mapped_column(String(500), nullable=False)
    image: Mapped[Optional[str]] = mapped_column(String(500), default="default.svg")
    title: Mapped[Optional[str]] = mapped_column(String(100))
    gender: Mapped[Optional[str]] = mapped_column(String(20))
    city: Mapped[Optional[str]] = mapped_column(String(100))
    country: Mapped[Optional[str]] = mapped_column(String(100))
    lang: Mapped[Optional[str]] = mapped_column(String(50), default="en")
    about: Mapped[Optional[str]] = mapped_column(Text)
    socials: Mapped[Optional[dict]] = mapped_column(JSON)

    # Changed from String(200) → JSON so structured education arrays persist correctly.
    # Old plain-string values (e.g. "Bsc. Business Administration") are handled by
    # safeParseJSON on the frontend — they return [] so the user can re-enter structured data.
    education: Mapped[Optional[Any]] = mapped_column(JSON, nullable=True)

    expertise: Mapped[Optional[str]] = mapped_column(String(500))

    # New column — portfolio projects as a JSON array
    projects: Mapped[Optional[Any]] = mapped_column(JSON, nullable=True)

    # Creator fields
    is_creator: Mapped[bool] = mapped_column(Boolean, default=False)
    creator_bio: Mapped[Optional[str]] = mapped_column(Text)
    creator_approved: Mapped[bool] = mapped_column(Boolean, default=False)
    bank_name: Mapped[Optional[str]] = mapped_column(String(100))
    bank_account_number: Mapped[Optional[str]] = mapped_column(String(20))
    bank_account_name: Mapped[Optional[str]] = mapped_column(String(200))

    # Auth / session
    email_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    is_online: Mapped[bool] = mapped_column(Boolean, default=False)
    last_seen: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    ip: Mapped[Optional[str]] = mapped_column(String(50))

    # ── Relationships ──────────────────────────────────────────────────────────
    oauth_accounts = relationship("OAuthAccount", 
        back_populates="user", cascade="all, delete-orphan")
    
    roles: Mapped[List["Role"]] = relationship(
        "Role", secondary=user_role_assoc, back_populates="users"
    )
    enrollments: Mapped[List["Enrollment"]] = relationship(
        "Enrollment", back_populates="user", foreign_keys="Enrollment.user_id"
    )
    topic_progress: Mapped[List["Topic"]] = relationship(
        "Topic", secondary="user_topic_progress", back_populates="completed_by"
    )
    payments: Mapped[List["Payment"]] = relationship(
        "Payment", back_populates="user", foreign_keys="Payment.user_id"
    )
    feedbacks: Mapped[List["Feedback"]] = relationship(
        "Feedback", back_populates="author", foreign_keys="Feedback.user_id"
    )
    certificates: Mapped[List["Certificate"]] = relationship(
        "Certificate", back_populates="user", foreign_keys="Certificate.user_id"
    )
    notifications: Mapped[List["Notification"]] = relationship(
        "Notification", back_populates="user", foreign_keys="Notification.user_id"
    )
    messages_sent: Mapped[List["Message"]] = relationship(
        "Message", foreign_keys="Message.sender_id", back_populates="sender"
    )
    messages_received: Mapped[List["Message"]] = relationship(
        "Message", foreign_keys="Message.recipient_id", back_populates="recipient"
    )
    courses_created: Mapped[List["Course"]] = relationship(
        "Course", back_populates="creator", foreign_keys="Course.creator_id"
    )
    team_requests: Mapped[List["TeamRequest"]] = relationship(
        "TeamRequest", back_populates="user", foreign_keys="TeamRequest.user_id"
    )
    schedules_as_tutor: Mapped[List["Schedule"]] = relationship(
        "Schedule", back_populates="tutor", foreign_keys="[Schedule.tutor_id]"
    )
    tutor_assignments: Mapped[List["TutorAssignment"]] = relationship(
        "TutorAssignment", back_populates="tutor", foreign_keys="TutorAssignment.tutor_id"
    )

    # ── Helper methods ─────────────────────────────────────────────────────────
    def has_role(self, role_name: str) -> bool:
        return any(r.name == role_name for r in self.roles)

    def is_admin(self) -> bool:
        return self.has_role("admin") or self.has_role("super_admin")

    def primary_role(self) -> str:
        priority = ["super_admin", "admin", "partner", "creator", "tutor", "student"]
        role_names = {r.name for r in self.roles}
        for r in priority:
            if r in role_names:
                return r
        return "student"


class EmailToken(Base):
    __tablename__ = "email_tokens"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    token: Mapped[str] = mapped_column(String(500), unique=True, nullable=False)
    token_type: Mapped[str] = mapped_column(String(50), nullable=False)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, Boolean
from sqlalchemy.orm import relationship
from datetime import datetime, timezone

class OAuthAccount(Base):
    __tablename__ = "oauth_accounts"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    provider = Column(String(50), nullable=False)          # google, github, facebook, linkedin
    provider_account_id = Column(String(255), nullable=False, index=True)
    access_token = Column(Text, nullable=True)
    refresh_token = Column(Text, nullable=True)
    expires_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    user = relationship("User", back_populates="oauth_accounts")


# ─── FEEDBACK ─────────────────────────────────────

# class Feedback(Base, TimestampMixin):
#     __tablename__ = "feedbacks"
#     id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
#     rating: Mapped[int] = mapped_column(Integer, nullable=False)
#     comment: Mapped[Optional[str]] = mapped_column(Text)
#     user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
#     course_id: Mapped[int] = mapped_column(Integer, ForeignKey("courses.id"), nullable=False)
#     author: Mapped["User"] = relationship("User", back_populates="feedbacks")
#     course: Mapped["Course"] = relationship("Course", back_populates="feedbacks")

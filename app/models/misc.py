"""
Intellect LMS — Assessment, Certificate, Schedule, Messaging, Partnership, Team Models
"""
from datetime import datetime
from typing import Optional, List
from sqlalchemy import (
    Integer, String, Text, Boolean, Float, DateTime,
    ForeignKey, JSON, UniqueConstraint
)
from sqlalchemy.orm import relationship, Mapped, mapped_column
from sqlalchemy.sql import func
from sqlalchemy import Enum as SAEnum

from app.db.database import Base
from app.models.base import TimestampMixin

from app.models.courses import Course, LearningPath
from app.models.users import User

from app.enums import (
    NotificationType, BroadcastType,
    TeamRequestStatus, PartnershipStatus,
    TutorAssignmentStatus,
)

# ─── v2 - TUTOR ASSIGNMENTS ──────────────────────────────────────────────────────

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Integer,
    Boolean,
    DateTime,
    ForeignKey,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship, Mapped, mapped_column
from sqlalchemy import Enum as SAEnum

from app.db.database import Base
from app.models.base import TimestampMixin
# from server.app.enums.core import TutorAssignmentStatus


class TutorAssignment(Base, TimestampMixin):
    """
    Scalable tutor assignment model for:
      - Course tutors
      - Student-specific tutors
      - Learning path tutors (optional future scalability)

    Supports:
      - Admin-assigned tutors
      - Tutor self-request workflow
      - Approval/rejection lifecycle
      - Audit trail & revocation
    """

    __tablename__ = "tutor_assignments"

    __table_args__ = (
        UniqueConstraint(
            "tutor_id",
            "course_id",
            "student_id",
            name="uq_tutor_assignment",
        ),
    )

    # ──────────────────────────────────────────────────────────────────────
    # PRIMARY KEY
    # ──────────────────────────────────────────────────────────────────────

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True,
    )

    # ──────────────────────────────────────────────────────────────────────
    # TARGETS
    # Exactly one or more can optionally be assigned
    # ──────────────────────────────────────────────────────────────────────

    course_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("courses.id"),
        nullable=True,
    )

    path_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("learning_paths.id"),
        nullable=True,
    )

    student_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("users.id"),
        nullable=True,
    )

    # ──────────────────────────────────────────────────────────────────────
    # TUTOR INFO
    # ──────────────────────────────────────────────────────────────────────

    tutor_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id"),
        nullable=False,
    )

    # Admin/user who created the assignment
    assigned_by_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("users.id"),
        nullable=True,
    )

    # ──────────────────────────────────────────────────────────────────────
    # ASSIGNMENT STATE
    # ──────────────────────────────────────────────────────────────────────

    status: Mapped[TutorAssignmentStatus] = mapped_column(
        SAEnum(TutorAssignmentStatus),
        default=TutorAssignmentStatus.pending,
        nullable=False,
    )

    admin_assigned: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )

    # ──────────────────────────────────────────────────────────────────────
    # AUDIT / CONTEXT
    # ──────────────────────────────────────────────────────────────────────

    notes: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
    )

    rejection_reason: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
    )

    revoked_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # ──────────────────────────────────────────────────────────────────────
    # RELATIONSHIPS
    # ──────────────────────────────────────────────────────────────────────

    tutor: Mapped["User"] = relationship(
        "User",
        back_populates="tutor_assignments",
        foreign_keys=[tutor_id],
    )

    assigned_by: Mapped[Optional["User"]] = relationship(
        "User",
        foreign_keys=[assigned_by_id],
    )

    student: Mapped[Optional["User"]] = relationship(
        "User",
        foreign_keys=[student_id],
    )

    course: Mapped[Optional["Course"]] = relationship(
        "Course",
        back_populates="tutor_assignments",
        foreign_keys=[course_id],
    )

    path: Mapped[Optional["LearningPath"]] = relationship(
        "LearningPath",
        back_populates="tutor_assignments",
        foreign_keys=[path_id],
    )


# ─── FEEDBACK ─────────────────────────────────────

class Feedback(Base, TimestampMixin):
    __tablename__ = "feedbacks"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    rating: Mapped[int] = mapped_column(Integer, nullable=False)
    comment: Mapped[Optional[str]] = mapped_column(Text)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    course_id: Mapped[int] = mapped_column(Integer, ForeignKey("courses.id"), nullable=False)
    author: Mapped["User"] = relationship("User", back_populates="feedbacks")
    course: Mapped["Course"] = relationship("Course", back_populates="feedbacks")


# ─── MESSAGING ────────────────────────────────────

class Message(Base, TimestampMixin):
    __tablename__ = "messages"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    is_seen: Mapped[bool] = mapped_column(Boolean, default=False)
    sender_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    recipient_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    sender: Mapped["User"] = relationship("User", back_populates="messages_sent", foreign_keys=[sender_id])
    recipient: Mapped["User"] = relationship("User", back_populates="messages_received", foreign_keys=[recipient_id])


class Notification(Base, TimestampMixin):
    __tablename__ = "notifications"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    body: Mapped[Optional[str]] = mapped_column(Text)
    notification_type: Mapped[str] = mapped_column(SAEnum(NotificationType), default=NotificationType.info)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False)
    link: Mapped[Optional[str]] = mapped_column(String(500))
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    user: Mapped["User"] = relationship("User", back_populates="notifications")


class Broadcast(Base, TimestampMixin):
    __tablename__ = "broadcasts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    subject: Mapped[str] = mapped_column(String(500), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    broadcast_type: Mapped[str] = mapped_column(SAEnum(BroadcastType), default=BroadcastType.all)
    sent_via_email: Mapped[bool] = mapped_column(Boolean, default=True)
    sent_via_notification: Mapped[bool] = mapped_column(Boolean, default=True)
    sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    sent_by_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    recipient_ids: Mapped[Optional[dict]] = mapped_column(JSON)


# ─── TEAM & INVITATIONS ───────────────────────────

class TeamRequest(Base, TimestampMixin):
    __tablename__ = "team_requests"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    requested_role: Mapped[str] = mapped_column(String(50), nullable=False)
    motivation: Mapped[Optional[str]] = mapped_column(Text)
    portfolio_url: Mapped[Optional[str]] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(SAEnum(TeamRequestStatus), default=TeamRequestStatus.pending)
    reviewed_by_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("users.id"), nullable=True)
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    rejection_reason: Mapped[Optional[str]] = mapped_column(Text)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    user: Mapped["User"] = relationship("User", back_populates="team_requests", foreign_keys=[user_id])


class Invite(Base, TimestampMixin):
    __tablename__ = "invites"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    token: Mapped[str] = mapped_column(String(200), unique=True, nullable=False)
    role: Mapped[str] = mapped_column(String(50), default="student")
    accepted: Mapped[bool] = mapped_column(Boolean, default=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    sent_by_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)


# ─── PARTNERSHIP ──────────────────────────────────

class Partnership(Base, TimestampMixin):
    __tablename__ = "partnerships"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    org_name: Mapped[str] = mapped_column(String(255), nullable=False)
    org_email: Mapped[str] = mapped_column(String(255), nullable=False)
    org_phone: Mapped[Optional[str]] = mapped_column(String(50))
    org_logo: Mapped[Optional[str]] = mapped_column(String(500))
    contact_person: Mapped[Optional[str]] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(SAEnum(PartnershipStatus), default=PartnershipStatus.pending)
    price_per_student: Mapped[float] = mapped_column(Float, default=0.0)
    max_students: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    active_students: Mapped[int] = mapped_column(Integer, default=0)
    contract_start: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    contract_end: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    managed_by_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("users.id"), nullable=True)
    partner_user_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("users.id"), nullable=True)
    courses: Mapped[List["Course"]] = relationship("Course", secondary="partner_course_assoc")
    paths: Mapped[List["LearningPath"]] = relationship("LearningPath", secondary="partner_path_assoc")
    students: Mapped[List["PartnerStudent"]] = relationship("PartnerStudent", back_populates="partnership")
    payments: Mapped[List["Payment"]] = relationship("Payment", foreign_keys="Payment.partnership_id")


class PartnerStudent(Base, TimestampMixin):
    __tablename__ = "partner_students"
    __table_args__ = (UniqueConstraint("partnership_id", "user_id", name="uq_partner_student"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    partnership_id: Mapped[int] = mapped_column(Integer, ForeignKey("partnerships.id"), nullable=False)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    partnership: Mapped["Partnership"] = relationship("Partnership", back_populates="students")


class BrandConfig(Base):
    __tablename__ = "brand_config"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    site_name: Mapped[str] = mapped_column(String(100), default="Intellect")
    tagline: Mapped[Optional[str]] = mapped_column(String(500))
    logo: Mapped[Optional[str]] = mapped_column(String(500))
    favicon: Mapped[Optional[str]] = mapped_column(String(500))
    email: Mapped[Optional[str]] = mapped_column(String(255))
    phone: Mapped[Optional[str]] = mapped_column(String(50))
    address: Mapped[Optional[str]] = mapped_column(Text)
    socials: Mapped[Optional[dict]] = mapped_column(JSON)
    whatsapp_link: Mapped[Optional[str]] = mapped_column(String(500))
    default_creator_pct: Mapped[float] = mapped_column(Float, default=70.0)
    default_platform_pct: Mapped[float] = mapped_column(Float, default=30.0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


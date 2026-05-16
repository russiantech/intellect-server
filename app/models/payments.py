"""
Intellect LMS — Payment, Enrollment, Discount Models
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
import enum

from app.db.database import Base
from app.models.base import TimestampMixin


class PaymentStatus(str, enum.Enum):
    pending = "pending"
    successful = "successful"
    failed = "failed"
    refunded = "refunded"


class EnrollmentStatus(str, enum.Enum):
    active = "active"
    completed = "completed"
    dropped = "dropped"
    suspended = "suspended"


class Payment(Base, TimestampMixin):
    __tablename__ = "payments"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tx_id: Mapped[Optional[str]] = mapped_column(String(200))
    tx_ref: Mapped[Optional[str]] = mapped_column(String(200), unique=True)
    tx_status: Mapped[str] = mapped_column(SAEnum(PaymentStatus), default=PaymentStatus.pending)
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    currency: Mapped[str] = mapped_column(String(10), default="NGN")
    provider: Mapped[Optional[str]] = mapped_column(String(50))
    payment_type: Mapped[str] = mapped_column(String(30), default="one_time")
    installment_number: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    # Subscription fields
    subscription_code: Mapped[Optional[str]] = mapped_column(String(200))  # Paystack SUB_xxx
    subscription_token: Mapped[Optional[str]] = mapped_column(String(500))  # email token for mgmt
    paystack_plan_code: Mapped[Optional[str]] = mapped_column(String(100))   # PLN_xxx
    next_payment_date: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    # Revenue split
    creator_amount: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    platform_amount: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    course_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("courses.id"), nullable=True)
    path_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("learning_paths.id"), nullable=True)
    partnership_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("partnerships.id"), nullable=True)
    metadata_json: Mapped[Optional[dict]] = mapped_column(JSON)
    user: Mapped["User"] = relationship("User", back_populates="payments")
    course: Mapped[Optional["Course"]] = relationship("Course", back_populates="payments")


class Enrollment(Base, TimestampMixin):
    __tablename__ = "enrollments"
    __table_args__ = (UniqueConstraint("user_id", "course_id", name="uq_enrollment"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    status: Mapped[str] = mapped_column(SAEnum(EnrollmentStatus), default=EnrollmentStatus.active)
    completed_topics: Mapped[int] = mapped_column(Integer, default=0)
    progress_pct: Mapped[float] = mapped_column(Float, default=0.0)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    admin_assigned: Mapped[bool] = mapped_column(Boolean, default=False)
    # Throttle tracking: topics accessed this week/month
    topics_accessed_this_week: Mapped[int] = mapped_column(Integer, default=0)
    topics_accessed_this_month: Mapped[int] = mapped_column(Integer, default=0)
    throttle_week_reset: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    throttle_month_reset: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    course_id: Mapped[int] = mapped_column(Integer, ForeignKey("courses.id"), nullable=False)
    path_enrollment_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("path_enrollments.id"), nullable=True)
    user: Mapped["User"] = relationship("User", back_populates="enrollments", foreign_keys=[user_id])
    course: Mapped["Course"] = relationship("Course", back_populates="enrollments")
    path_enrollment: Mapped[Optional["PathEnrollment"]] = relationship("PathEnrollment", back_populates="course_enrollments")


class PathEnrollment(Base, TimestampMixin):
    __tablename__ = "path_enrollments"
    __table_args__ = (UniqueConstraint("user_id", "path_id", name="uq_path_enrollment"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    path_id: Mapped[int] = mapped_column(Integer, ForeignKey("learning_paths.id"), nullable=False)
    status: Mapped[str] = mapped_column(SAEnum(EnrollmentStatus), default=EnrollmentStatus.active)
    progress_pct: Mapped[float] = mapped_column(Float, default=0.0)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    # user: Mapped["User"] = relationship("User", back_populates="path")
    path: Mapped["LearningPath"] = relationship("LearningPath", back_populates="path_enrollments")
    course_enrollments: Mapped[List["Enrollment"]] = relationship("Enrollment", back_populates="path_enrollment")


class Discount(Base, TimestampMixin):
    __tablename__ = "discounts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(String(500))
    discount_type: Mapped[str] = mapped_column(String(20), default="percentage")
    value: Mapped[float] = mapped_column(Float, nullable=False)
    max_uses: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    used_count: Mapped[int] = mapped_column(Integer, default=0)
    valid_from: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    valid_until: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    applies_to: Mapped[str] = mapped_column(String(20), default="all")
    course_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("courses.id"), nullable=True)
    path_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("learning_paths.id"), nullable=True)
    course: Mapped[Optional["Course"]] = relationship("Course", back_populates="discounts")

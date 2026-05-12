"""
Intellect LMS — Assessment, Certificate, Schedule, Messaging, Partnership, Team Models
"""
from datetime import datetime
from typing import Optional, List
from sqlalchemy import (
    Integer, String, Text, Boolean, Float, DateTime,
    ForeignKey, JSON, UniqueConstraint, Table, Column
)
from sqlalchemy.orm import relationship, Mapped, mapped_column
from sqlalchemy.sql import func
from sqlalchemy import Enum as SAEnum
import enum

from app.db.database import Base
from app.models.base import TimestampMixin

from app.models.courses import Course, LearningPath
from app.models.users import User

from app.enums import (
    NotificationType, BroadcastType,
    TeamRequestStatus, PartnershipStatus,
)

# ─── ENUMS ────────────────────────────────────────

# class AssessmentType(str, enum.Enum):
#     classwork = "classwork"
#     homework = "homework"
#     exam = "exam"
#     quiz = "quiz"
#     quick_check = "quick_check"


# class QuestionType(str, enum.Enum):
#     mcq = "mcq"
#     true_false = "true_false"
#     short_answer = "short_answer"
#     essay = "essay"
#     file_upload = "file_upload"


# class CertStatus(str, enum.Enum):
#     issued = "issued"
#     revoked = "revoked"


# class PartnershipStatus(str, enum.Enum):
#     pending = "pending"
#     active = "active"
#     suspended = "suspended"
#     terminated = "terminated"


# class TeamRequestStatus(str, enum.Enum):
#     pending = "pending"
#     approved = "approved"
#     rejected = "rejected"


# class NotificationType(str, enum.Enum):
#     info = "info"
#     success = "success"
#     warning = "warning"
#     error = "error"


# class BroadcastType(str, enum.Enum):
#     all = "all"
#     students = "students"
#     tutors = "tutors"
#     creators = "creators"
#     partners = "partners"
#     specific = "specific"


# ─── ASSESSMENTS ──────────────────────────────────

# class Assessment(Base, TimestampMixin):
#     __tablename__ = "assessments"
#     id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
#     title: Mapped[str] = mapped_column(String(255), nullable=False)
#     description: Mapped[Optional[str]] = mapped_column(Text)
#     assessment_type: Mapped[str] = mapped_column(SAEnum(AssessmentType), nullable=False)
#     total_marks: Mapped[float] = mapped_column(Float, default=100.0)
#     pass_mark: Mapped[float] = mapped_column(Float, default=50.0)
#     time_limit_minutes: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
#     due_date: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
#     is_auto_graded: Mapped[bool] = mapped_column(Boolean, default=True)
#     show_answers_after: Mapped[bool] = mapped_column(Boolean, default=True)
#     attempts_allowed: Mapped[int] = mapped_column(Integer, default=1)
#     shuffle_questions: Mapped[bool] = mapped_column(Boolean, default=False)
#     course_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("courses.id"), nullable=True)
#     topic_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("topics.id"), nullable=True)
#     created_by_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
#     course: Mapped[Optional["Course"]] = relationship("Course", back_populates="assessments")
#     topic: Mapped[Optional["Topic"]] = relationship("Topic", back_populates="quick_assessments", foreign_keys=[topic_id])
#     questions: Mapped[List["Question"]] = relationship("Question", back_populates="assessment", cascade="all, delete-orphan")
#     submissions: Mapped[List["AssessmentSubmission"]] = relationship("AssessmentSubmission", back_populates="assessment")


# class Question(Base, TimestampMixin):
#     __tablename__ = "questions"
#     id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
#     body: Mapped[str] = mapped_column(Text, nullable=False)
#     question_type: Mapped[str] = mapped_column(SAEnum(QuestionType), nullable=False)
#     options: Mapped[Optional[dict]] = mapped_column(JSON)
#     correct_answer: Mapped[Optional[str]] = mapped_column(Text)
#     explanation: Mapped[Optional[str]] = mapped_column(Text)
#     marks: Mapped[float] = mapped_column(Float, default=1.0)
#     order_index: Mapped[int] = mapped_column(Integer, default=0)
#     assessment_id: Mapped[int] = mapped_column(Integer, ForeignKey("assessments.id"), nullable=False)
#     assessment: Mapped["Assessment"] = relationship("Assessment", back_populates="questions")
#     answers: Mapped[List["Answer"]] = relationship("Answer", back_populates="question")


# class AssessmentSubmission(Base, TimestampMixin):
#     __tablename__ = "assessment_submissions"
#     id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
#     status: Mapped[str] = mapped_column(String(50), default="submitted")
#     score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
#     percentage: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
#     passed: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
#     ai_feedback: Mapped[Optional[str]] = mapped_column(Text)
#     tutor_feedback: Mapped[Optional[str]] = mapped_column(Text)
#     attempt_number: Mapped[int] = mapped_column(Integer, default=1)
#     submitted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
#     graded_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
#     student_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
#     assessment_id: Mapped[int] = mapped_column(Integer, ForeignKey("assessments.id"), nullable=False)
#     graded_by_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("users.id"), nullable=True)
#     student: Mapped["User"] = relationship("User", back_populates="assessment_submissions", foreign_keys=[student_id])
#     assessment: Mapped["Assessment"] = relationship("Assessment", back_populates="submissions")
#     answers: Mapped[List["Answer"]] = relationship("Answer", back_populates="submission")


# class Answer(Base, TimestampMixin):
#     __tablename__ = "answers"
#     id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
#     response: Mapped[Optional[str]] = mapped_column(Text)
#     file_path: Mapped[Optional[str]] = mapped_column(String(500))
#     score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
#     is_correct: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
#     ai_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
#     ai_feedback: Mapped[Optional[str]] = mapped_column(Text)
#     question_id: Mapped[int] = mapped_column(Integer, ForeignKey("questions.id"), nullable=False)
#     submission_id: Mapped[int] = mapped_column(Integer, ForeignKey("assessment_submissions.id"), nullable=False)
#     question: Mapped["Question"] = relationship("Question", back_populates="answers")
#     submission: Mapped["AssessmentSubmission"] = relationship("AssessmentSubmission", back_populates="answers")


# ─── CERTIFICATES ─────────────────────────────────

# class Certificate(Base, TimestampMixin):
#     __tablename__ = "certificates"
#     id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
#     cert_number: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
#     cert_url: Mapped[Optional[str]] = mapped_column(String(500))
#     status: Mapped[str] = mapped_column(SAEnum(CertStatus), default=CertStatus.issued)
#     issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
#     user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
#     course_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("courses.id"), nullable=True)
#     path_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("learning_paths.id"), nullable=True)
#     user: Mapped["User"] = relationship("User", back_populates="certificates")
#     course: Mapped[Optional["Course"]] = relationship("Course", back_populates="certificates")


# ─── SCHEDULES & ATTENDANCE ───────────────────────

# class Schedule(Base, TimestampMixin):
#     __tablename__ = "schedules"
#     id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
#     title: Mapped[str] = mapped_column(String(255), nullable=False)
#     description: Mapped[Optional[str]] = mapped_column(Text)
#     start_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
#     end_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
#     meeting_link: Mapped[Optional[str]] = mapped_column(String(500))
#     is_recurring: Mapped[bool] = mapped_column(Boolean, default=False)
#     recurrence_rule: Mapped[Optional[str]] = mapped_column(String(200))
#     course_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("courses.id"), nullable=True)
#     tutor_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("users.id"), nullable=True)
#     course: Mapped[Optional["Course"]] = relationship("Course", back_populates="schedules")
#     tutor: Mapped[Optional["User"]] = relationship("User", back_populates="schedules_as_tutor", foreign_keys=[tutor_id])
#     attendance_records: Mapped[List["AttendanceRecord"]] = relationship("AttendanceRecord", back_populates="schedule")


# class AttendanceRecord(Base, TimestampMixin):
#     __tablename__ = "attendance_records"
#     __table_args__ = (UniqueConstraint("student_id", "schedule_id", name="uq_attendance"),)
#     id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
#     present: Mapped[bool] = mapped_column(Boolean, default=False)
#     marked_by_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("users.id"), nullable=True)
#     notes: Mapped[Optional[str]] = mapped_column(String(500))
#     student_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
#     schedule_id: Mapped[int] = mapped_column(Integer, ForeignKey("schedules.id"), nullable=False)
#     student: Mapped["User"] = relationship("User", back_populates="attendance_records", foreign_keys=[student_id])
#     schedule: Mapped["Schedule"] = relationship("Schedule", back_populates="attendance_records")


# ─── TUTOR ASSIGNMENTS ────────────────────────────

class TutorAssignment(Base, TimestampMixin):
    __tablename__ = "tutor_assignments"
    __table_args__ = (UniqueConstraint("tutor_id", "course_id", "student_id", name="uq_tutor_assignment"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tutor_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    course_id: Mapped[int] = mapped_column(Integer, ForeignKey("courses.id"), nullable=False)
    student_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("users.id"), nullable=True)
    assigned_by_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    tutor: Mapped["User"] = relationship("User", back_populates="tutor_assignments", foreign_keys=[tutor_id])
    course: Mapped["Course"] = relationship("Course", back_populates="tutor_assignments")


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


"""
app/enums/__init__.py
=====================
Single source of truth for every enum used across the Intellect LMS.

Import pattern (models, schemas, routes all use this):
    from app.enums import QuizQuestionType, SubmissionStatus, ...

Design rules
------------
- ONE definition per concept.  No duplicates.
- str-enum so SQLAlchemy SAEnum, Pydantic, and JSON serialisation all work.
- Organised into logical groups with section comments.
"""

from app.enums.core import (
    # Users
    UserRole,
    # Courses
    CourseStatus,
    CourseLevel,
    ContentType,
    PaymentType,
    SubscriptionInterval,
    # Payments / Enrollments
    PaymentStatus,
    EnrollmentStatus,
    # Certs / Partnerships / Comms
    CertStatus,
    PartnershipStatus,
    TeamRequestStatus,
    NotificationType,
    BroadcastType,
)

from app.enums.assessments import (
    # Questions
    QuizQuestionType,
    AssessmentType,
    QuestionType,
    # Quiz lifecycle
    QuizAttemptStatus,
    # Submissions (projects & lesson assessments)
    SubmissionStatus,
    # Attendance
    AttendanceStatus,
)

__all__ = [
    # ── Core ──────────────────────────────────────────────────────
    "UserRole",
    "CourseStatus",
    "CourseLevel",
    "ContentType",
    "PaymentType",
    "SubscriptionInterval",
    "PaymentStatus",
    "EnrollmentStatus",
    "CertStatus",
    "PartnershipStatus",
    "TeamRequestStatus",
    "NotificationType",
    "BroadcastType",
    # ── Assessments ───────────────────────────────────────────────
    "QuizQuestionType",
    "AssessmentType",
    "QuestionType",
    "QuizAttemptStatus",
    "SubmissionStatus",
    "AttendanceStatus",
]

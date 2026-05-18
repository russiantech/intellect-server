"""
app/models/__init__.py
======================
Intellect LMS — Models Package

Re-exports every ORM model in dependency order so that
``from app.models import X`` always works throughout the codebase.

Import order: base → users → courses → quizzes → payments → misc
(SQLAlchemy resolves FKs lazily, but keeping this order avoids
 accidental forward-reference headaches.)
"""

# ── Base mixin ────────────────────────────────────────────────────
from app.models.base import TimestampMixin

# ── Users ─────────────────────────────────────────────────────────
from app.models.users import (
    user_role_assoc,
    Role, User, EmailToken, OAuthAccount,
)

# ── Courses ───────────────────────────────────────────────────────
from app.models.courses import (
    Category, Tag, SubscriptionPlan,
    Course, Lesson, Topic, TopicContent,
    LearningPath, Certificate,
)

# ── Assessment layer (quizzes, lesson assessments, projects, attendance)
from app.models.quizzes import (
    # Topic-level quiz
    Quiz, QuizQuestion, QuizAttempt,
    # Lesson-level assessments (classwork / homework)
    LessonAssessment, LessonAssessmentQuestion, LessonAssessmentSubmission,
    # Course-level project
    Project, ProjectSubmission,
    
    # Schedule & attendance
    Schedule, AttendanceRecord, AttendanceCheckInCode,
    
    # Legacy models (backwards compat — do not use for new features)
    # Assessment, LegacyQuestion, LegacyAssessmentSubmission, LegacyAnswer,
)

# ── Payments & Enrollments ────────────────────────────────────────
from app.models.payments import (
    Payment, Enrollment, PathEnrollment, Discount,
)

# ── Association tables ────────────────────────────────────────────
from app.models.association_tables import (
    user_role_assoc,
    course_tag_assoc,
    course_category_assoc,
    path_category_assoc,
    path_course_assoc,
    user_topic_progress,
    partner_course_assoc,
    partner_path_assoc,
)

# ── Misc (messaging, partnerships, team) ─────────────────────────
# These are still in misc.py; import selectively to avoid circular deps.
# Routes that need them import directly: from app.models.misc import X

from app.models.misc import (
    Notification, Message, Broadcast,
    Partnership, PartnerStudent, TeamRequest, Invite,
    TutorAssignment, Feedback, BrandConfig
)

__all__ = [
    # Base
    "TimestampMixin",

    # Users
    "user_role_assoc",
    "Role", "User", "EmailToken", "OAuthAccount",

    # Courses
    "Category", "Tag", "SubscriptionPlan",
    "Course", "Lesson", "Topic", "TopicContent",
    "LearningPath", "Certificate",

    # Quiz (topic-level)
    "Quiz", "QuizQuestion", "QuizAttempt",

    # Lesson assessments (classwork / homework)
    "LessonAssessment", "LessonAssessmentQuestion", "LessonAssessmentSubmission",

    # Project (course-level)
    "Project", "ProjectSubmission",

    # Schedule & attendance
    "Schedule", "AttendanceRecord", "AttendanceCheckInCode",

    # Legacy assessment models
    # "Assessment", "LegacyQuestion", "LegacyAssessmentSubmission", "LegacyAnswer",

    # Payments
    "Payment", "Enrollment", "PathEnrollment", "Discount",
    
    # Messaging, partnerships, team
    "Notification", "Message", "Broadcast",
    "Partnership", "PartnerStudent", "TeamRequest", "Invite",
    "TutorAssignment", "Feedback", "BrandConfig",

    # Association tables
    "course_tag_assoc", "course_category_assoc",
    "path_category_assoc", "path_course_assoc", "user_topic_progress",
    "partner_course_assoc", "partner_path_assoc",
]

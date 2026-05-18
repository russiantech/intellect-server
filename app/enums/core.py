"""
app/enums/core.py
=================
Core platform enums: users, courses, payments, partnerships, comms.
"""
import enum


# ──────────────────────────────────────────────────────────────────
#  Users
# ──────────────────────────────────────────────────────────────────

class UserRole(str, enum.Enum):
    super_admin = "super_admin"
    admin       = "admin"
    tutor       = "tutor"
    student     = "student"
    creator     = "creator"
    partner     = "partner"


# ──────────────────────────────────────────────────────────────────
#  Courses
# ──────────────────────────────────────────────────────────────────

class CourseStatus(str, enum.Enum):
    draft       = "draft"
    pending     = "pending"       # awaiting admin approval
    published   = "published"
    unpublished = "unpublished"
    rejected    = "rejected"

class TutorAssignmentStatus(str, enum.Enum):
    pending  = "pending"
    approved = "approved"
    rejected = "rejected"
    revoked  = "revoked"
    inactive = "inactive"

class CourseLevel(str, enum.Enum):
    novice        = "novice"
    beginner      = "beginner"
    intermediate  = "intermediate"
    professional  = "professional"
    expert        = "expert"
    advanced      = "advanced"


class ContentType(str, enum.Enum):
    video = "video"
    pdf   = "pdf"
    image = "image"
    ppt   = "ppt"
    doc   = "doc"
    audio = "audio"
    text  = "text"
    quiz  = "quiz"
    link  = "link"


# ──────────────────────────────────────────────────────────────────
#  Payments & Enrollments
# ──────────────────────────────────────────────────────────────────

class PaymentType(str, enum.Enum):
    one_time       = "one_time"
    subscription   = "subscription"
    pay_as_you_go  = "pay_as_you_go"
    free           = "free"


class SubscriptionInterval(str, enum.Enum):
    daily   = "daily"
    weekly  = "weekly"
    monthly = "monthly"
    yearly  = "yearly"


class PaymentStatus(str, enum.Enum):
    pending    = "pending"
    successful = "successful"
    failed     = "failed"
    refunded   = "refunded"


class EnrollmentStatus(str, enum.Enum):
    active    = "active"
    completed = "completed"
    dropped   = "dropped"
    suspended = "suspended"


# ──────────────────────────────────────────────────────────────────
#  Certificates
# ──────────────────────────────────────────────────────────────────

class CertStatus(str, enum.Enum):
    issued  = "issued"
    revoked = "revoked"


# ──────────────────────────────────────────────────────────────────
#  Partnerships & Teams
# ──────────────────────────────────────────────────────────────────

class PartnershipStatus(str, enum.Enum):
    pending    = "pending"
    active     = "active"
    suspended  = "suspended"
    terminated = "terminated"


class TeamRequestStatus(str, enum.Enum):
    pending  = "pending"
    approved = "approved"
    rejected = "rejected"


# ──────────────────────────────────────────────────────────────────
#  Messaging & Notifications
# ──────────────────────────────────────────────────────────────────

class NotificationType(str, enum.Enum):
    info    = "info"
    success = "success"
    warning = "warning"
    error   = "error"


class BroadcastType(str, enum.Enum):
    all      = "all"
    students = "students"
    tutors   = "tutors"
    creators = "creators"
    partners = "partners"
    specific = "specific"

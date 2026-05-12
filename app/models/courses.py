# """
# Intellect LMS — Course, Lesson, Topic, Content, Category, Tag Models
# """

# from datetime import datetime
# from typing import Optional, List
# from sqlalchemy import (
#     Integer, String, Text, Boolean, Float, DateTime,
#     ForeignKey
# )
# from sqlalchemy.orm import relationship, Mapped, mapped_column
# from sqlalchemy import Enum as SAEnum, func

# from app.enums import (
#     CourseStatus, CourseLevel, ContentType, PaymentType, 
#     SubscriptionInterval, CertStatus,
# )

# from app.models.association_tables import (
#     course_tag_assoc, course_category_assoc, 
#     path_course_assoc, user_topic_progress
# )

# from app.db.database import Base
# from app.models.base import TimestampMixin
# from app.models.quizzes import LessonAssessment


# class Category(Base, TimestampMixin):
#     __tablename__ = "categories"
#     id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
#     title: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
#     description: Mapped[Optional[str]] = mapped_column(String(500))
#     image: Mapped[Optional[str]] = mapped_column(String(500))
#     icon: Mapped[Optional[str]] = mapped_column(String(100))
#     slug: Mapped[Optional[str]] = mapped_column(String(150), unique=True)
#     courses: Mapped[List["Course"]] = relationship("Course", secondary=course_category_assoc, back_populates="categories")


# class Tag(Base, TimestampMixin):
#     __tablename__ = "tags"
#     id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
#     name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
#     courses: Mapped[List["Course"]] = relationship("Course", secondary=course_tag_assoc, back_populates="tags")


# class SubscriptionPlan(Base, TimestampMixin):
#     """Paystack subscription plans linked to courses/paths."""
#     __tablename__ = "subscription_plans"
#     id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
#     name: Mapped[str] = mapped_column(String(200), nullable=False)
#     paystack_plan_code: Mapped[Optional[str]] = mapped_column(String(100), unique=True)  # PLN_xxx from Paystack
#     interval: Mapped[str] = mapped_column(SAEnum(SubscriptionInterval), nullable=False)
#     amount: Mapped[float] = mapped_column(Float, nullable=False)
#     currency: Mapped[str] = mapped_column(String(10), default="NGN")
#     course_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("courses.id"), nullable=True)
#     path_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("learning_paths.id"), nullable=True)
#     is_active: Mapped[bool] = mapped_column(Boolean, default=True)


# class Course(Base, TimestampMixin):
#     __tablename__ = "courses"
#     id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
#     title: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
#     slug: Mapped[Optional[str]] = mapped_column(String(300), unique=True)
#     description: Mapped[Optional[str]] = mapped_column(Text)
#     short_description: Mapped[Optional[str]] = mapped_column(String(500))
#     thumbnail: Mapped[Optional[str]] = mapped_column(String(500))
#     preview_video: Mapped[Optional[str]] = mapped_column(String(1000))
#     fee: Mapped[float] = mapped_column(Float, default=0.0)
#     payment_type: Mapped[str] = mapped_column(SAEnum(PaymentType), default=PaymentType.one_time)
#     subscription_interval: Mapped[Optional[str]] = mapped_column(SAEnum(SubscriptionInterval), nullable=True)
#     subscription_installments: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
#     # Content throttle: how many topics can be unlocked per period
#     weekly_topic_limit: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)   # e.g. 3 topics/week
#     monthly_topic_limit: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)  # e.g. 10 topics/month
#     throttle_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
#     lang: Mapped[str] = mapped_column(String(20), default="en")
#     duration_weeks: Mapped[Optional[int]] = mapped_column(Integer)
#     level: Mapped[str] = mapped_column(SAEnum(CourseLevel), default=CourseLevel.beginner)
#     status: Mapped[str] = mapped_column(SAEnum(CourseStatus), default=CourseStatus.draft, nullable=False)
#     views: Mapped[int] = mapped_column(Integer, default=0)
#     featured: Mapped[bool] = mapped_column(Boolean, default=False)
#     requirements: Mapped[Optional[str]] = mapped_column(Text)
#     what_you_learn: Mapped[Optional[str]] = mapped_column(Text)
#     creator_pct: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
#     platform_pct: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
#     approved_by_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("users.id"), nullable=True)
#     approved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
#     rejection_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
#     creator_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("users.id"), nullable=True)

#     creator: Mapped[Optional["User"]] = relationship("User", back_populates="courses_created", foreign_keys=[creator_id])
#     approved_by: Mapped[Optional["User"]] = relationship("User", foreign_keys=[approved_by_id])
#     categories: Mapped[List["Category"]] = relationship("Category", secondary=course_category_assoc, back_populates="courses")
#     tags: Mapped[List["Tag"]] = relationship("Tag", secondary=course_tag_assoc, back_populates="courses")
#     lessons: Mapped[List["Lesson"]] = relationship("Lesson", back_populates="course", cascade="all, delete-orphan", order_by="Lesson.order_index")
#     topics: Mapped[List["Topic"]] = relationship("Topic", back_populates="course")
#     enrollments: Mapped[List["Enrollment"]] = relationship("Enrollment", back_populates="course")
#     feedbacks: Mapped[List["Feedback"]] = relationship("Feedback", back_populates="course")
#     payments: Mapped[List["Payment"]] = relationship("Payment", back_populates="course")
#     certificates: Mapped[List["Certificate"]] = relationship("Certificate", back_populates="course")
#     # assessments: Mapped[List["LessonAssessment"]] = relationship(
#     #     "LessonAssessment", back_populates="course",
#     #     cascade="all, delete-orphan",
#     # )
#     tutor_assignments: Mapped[List["TutorAssignment"]] = relationship("TutorAssignment", back_populates="course")
    
#     schedules: Mapped[List["Schedule"]] = relationship(
#         "Schedule", back_populates="course",
#         cascade="all, delete-orphan",
#     )
#     discounts: Mapped[List["Discount"]] = relationship("Discount", back_populates="course")
#     learning_paths: Mapped[List["LearningPath"]] = relationship("LearningPath", secondary=path_course_assoc, back_populates="courses")
#     subscription_plans: Mapped[List["SubscriptionPlan"]] = relationship("SubscriptionPlan", foreign_keys=[SubscriptionPlan.course_id])


# class Lesson(Base, TimestampMixin):
#     __tablename__ = "lessons"
#     id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
#     title: Mapped[str] = mapped_column(String(255), nullable=False)
#     description: Mapped[Optional[str]] = mapped_column(Text)
#     order_index: Mapped[int] = mapped_column(Integer, default=0)
#     slug: Mapped[Optional[str]] = mapped_column(String(300))
#     course_id: Mapped[int] = mapped_column(Integer, ForeignKey("courses.id"), nullable=False)
#     course: Mapped["Course"] = relationship("Course", back_populates="lessons")
#     topics: Mapped[List["Topic"]] = relationship("Topic", back_populates="lesson", cascade="all, delete-orphan", order_by="Topic.order_index")
#     assessments: Mapped[List["LessonAssessment"]] = relationship(
#         "LessonAssessment",
#         back_populates="lesson",
#         cascade="all, delete-orphan",
#     )


# class Topic(Base, TimestampMixin):
#     __tablename__ = "topics"
#     id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
#     title: Mapped[str] = mapped_column(String(255), nullable=False)
#     description: Mapped[Optional[str]] = mapped_column(Text)
#     order_index: Mapped[int] = mapped_column(Integer, default=0)
#     slug: Mapped[Optional[str]] = mapped_column(String(300))
#     duration_minutes: Mapped[Optional[int]] = mapped_column(Integer)
#     is_free_preview: Mapped[bool] = mapped_column(Boolean, default=False)
#     lesson_id: Mapped[int] = mapped_column(Integer, ForeignKey("lessons.id"), nullable=False)
#     lesson: Mapped["Lesson"] = relationship("Lesson", back_populates="topics")
#     course_id: Mapped[int] = mapped_column(Integer, ForeignKey("courses.id"), nullable=False)
#     course: Mapped["Course"] = relationship("Course", back_populates="topics")
#     contents: Mapped[List["TopicContent"]] = relationship("TopicContent", back_populates="topic", cascade="all, delete-orphan", order_by="TopicContent.order_index")
#     completed_by: Mapped[List["User"]] = relationship("User", secondary=user_topic_progress, back_populates="topic_progress")
#     # quick_assessments: Mapped[List["Assessment"]] = relationship("Assessment", back_populates="topic", foreign_keys="Assessment.topic_id")
#     # quiz: Mapped[Optional["Quiz"]] = relationship(
#     #     "Quiz",
#     #     back_populates="topic",
#     #     cascade="all, delete-orphan",
#     #     uselist=False,
#     # )
    
#     quizzes: Mapped[Optional["Quiz"]] = relationship(
#         "Quiz",
#         back_populates="topic",
#         cascade="all, delete-orphan",
#         uselist=False,
#     )
    
#     # quick_assessments: Mapped[List["LessonAssessment"]] = relationship(
#     #     "LessonAssessment",
#     #     back_populates="topic",
#     #     foreign_keys="LessonAssessment.topic_id",
#     # )


# class TopicContent(Base, TimestampMixin):
#     __tablename__ = "topic_contents"
#     id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
#     title: Mapped[Optional[str]] = mapped_column(String(255))
#     body: Mapped[Optional[str]] = mapped_column(Text)
#     content_type: Mapped[str] = mapped_column(SAEnum(ContentType), nullable=False)
#     file_path: Mapped[Optional[str]] = mapped_column(String(1000))
#     url: Mapped[Optional[str]] = mapped_column(String(1000))
#     body: Mapped[Optional[str]] = mapped_column(Text)
#     duration_seconds: Mapped[Optional[int]] = mapped_column(Integer)
#     file_size_bytes: Mapped[Optional[int]] = mapped_column(Integer)
#     mime_type: Mapped[Optional[str]] = mapped_column(String(100))
#     order_index: Mapped[int] = mapped_column(Integer, default=0)
#     topic_id: Mapped[int] = mapped_column(Integer, ForeignKey("topics.id"), nullable=False)
#     topic: Mapped["Topic"] = relationship("Topic", back_populates="contents")


# class LearningPath(Base, TimestampMixin):
#     __tablename__ = "learning_paths"
#     id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
#     title: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
#     description: Mapped[Optional[str]] = mapped_column(Text)
#     thumbnail: Mapped[Optional[str]] = mapped_column(String(500))
#     slug: Mapped[Optional[str]] = mapped_column(String(300), unique=True)
#     fee: Mapped[float] = mapped_column(Float, default=0.0)
#     payment_type: Mapped[str] = mapped_column(SAEnum(PaymentType), default=PaymentType.one_time)
#     status: Mapped[str] = mapped_column(SAEnum(CourseStatus), default=CourseStatus.published)
#     # Certificate on path completion
#     issues_certificate: Mapped[bool] = mapped_column(Boolean, default=True)
#     created_by_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("users.id"), nullable=True)
#     courses: Mapped[List["Course"]] = relationship("Course", secondary=path_course_assoc, back_populates="learning_paths")
#     path_enrollments: Mapped[List["PathEnrollment"]] = relationship("PathEnrollment", back_populates="path")
#     subscription_plans: Mapped[List["SubscriptionPlan"]] = relationship("SubscriptionPlan", foreign_keys=[SubscriptionPlan.path_id])


# # ─────────────────────────────────────────────
# #  CERTIFICATES
# # ─────────────────────────────────────────────

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





# v2
"""
Intellect LMS — Course, Lesson, Topic, Content, Category, Tag Models

Changes vs previous version
────────────────────────────
Course
  + instructor_led_fee   Float   — extra fee when student opts into instructor-led mode
                                   0.0 = feature disabled for this course
                                   Admin sets per course; students toggle on CourseDetail
  + access_period_days   Integer — how many days of access one pay-as-you-go payment buys
                                   Only meaningful when payment_type = pay_as_you_go
                                   Default 30; admin overrides per course

LearningPath
  + instructor_led_fee   Float   — same semantics as Course.instructor_led_fee
  + access_period_days   Integer — same semantics as Course.access_period_days

SubscriptionPlan
  + is_deleted           Boolean — soft-delete flag (was missing; router uses it)

TopicContent
  - duplicate body column removed (was silently shadowed by SQLAlchemy — safe to drop)

LearningPath
  + is_active, is_deleted  — routers reference these; they come from TimestampMixin only
                             if TimestampMixin defines them.  Added explicitly here for
                             clarity and to guarantee they exist on the table.
"""

from datetime import datetime
from typing import Optional, List
from sqlalchemy import (
    Integer, String, Text, Boolean, Float, DateTime,
    ForeignKey,
)
from sqlalchemy.orm import relationship, Mapped, mapped_column
from sqlalchemy import Enum as SAEnum, func

from app.enums import (
    CourseStatus, CourseLevel, ContentType, PaymentType,
    SubscriptionInterval, CertStatus,
)
from app.models.association_tables import (
    course_tag_assoc, course_category_assoc,
    path_course_assoc, user_topic_progress,
)
from app.db.database import Base
from app.models.base import TimestampMixin
from app.models.quizzes import LessonAssessment


# ─────────────────────────────────────────────
#  CATEGORY
# ─────────────────────────────────────────────

class Category(Base, TimestampMixin):
    __tablename__ = "categories"

    id:          Mapped[int]           = mapped_column(Integer, primary_key=True, autoincrement=True)
    title:       Mapped[str]           = mapped_column(String(100), unique=True, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(String(500))
    image:       Mapped[Optional[str]] = mapped_column(String(500))
    icon:        Mapped[Optional[str]] = mapped_column(String(100))
    slug:        Mapped[Optional[str]] = mapped_column(String(150), unique=True)

    courses: Mapped[List["Course"]] = relationship(
        "Course", secondary=course_category_assoc, back_populates="categories",
    )


# ─────────────────────────────────────────────
#  TAG
# ─────────────────────────────────────────────

class Tag(Base, TimestampMixin):
    __tablename__ = "tags"

    id:   Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)

    courses: Mapped[List["Course"]] = relationship(
        "Course", secondary=course_tag_assoc, back_populates="tags",
    )


# ─────────────────────────────────────────────
#  SUBSCRIPTION PLAN
# ─────────────────────────────────────────────

class SubscriptionPlan(Base, TimestampMixin):
    """
    Paystack subscription plans linked to a course or learning path.
    One course can have multiple plans (e.g. monthly + yearly).
    """
    __tablename__ = "subscription_plans"

    id:                  Mapped[int]           = mapped_column(Integer, primary_key=True, autoincrement=True)
    name:                Mapped[str]           = mapped_column(String(200), nullable=False)
    paystack_plan_code:  Mapped[Optional[str]] = mapped_column(String(100), unique=True)   # PLN_xxx from Paystack
    interval:            Mapped[str]           = mapped_column(SAEnum(SubscriptionInterval), nullable=False)
    amount:              Mapped[float]         = mapped_column(Float, nullable=False)
    currency:            Mapped[str]           = mapped_column(String(10), default="NGN")
    course_id:           Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("courses.id"), nullable=True)
    path_id:             Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("learning_paths.id"), nullable=True)
    is_active:           Mapped[bool]          = mapped_column(Boolean, default=True)
    is_deleted:          Mapped[bool]          = mapped_column(Boolean, default=False)   # ← added; router uses this


# ─────────────────────────────────────────────
#  COURSE
# ─────────────────────────────────────────────

class Course(Base, TimestampMixin):
    __tablename__ = "courses"

    # ── Identity ─────────────────────────────────────────────────────────────
    id:                Mapped[int]           = mapped_column(Integer, primary_key=True, autoincrement=True)
    title:             Mapped[str]           = mapped_column(String(255), unique=True, nullable=False)
    slug:              Mapped[Optional[str]] = mapped_column(String(300), unique=True)
    description:       Mapped[Optional[str]] = mapped_column(Text)
    short_description: Mapped[Optional[str]] = mapped_column(String(500))

    # ── Media ────────────────────────────────────────────────────────────────
    thumbnail:     Mapped[Optional[str]] = mapped_column(String(500))
    preview_video: Mapped[Optional[str]] = mapped_column(String(1000))

    # ── Pricing ──────────────────────────────────────────────────────────────
    fee:                      Mapped[float]         = mapped_column(Float, default=0.0)
    payment_type:             Mapped[str]           = mapped_column(SAEnum(PaymentType), default=PaymentType.one_time)
    subscription_interval:    Mapped[Optional[str]] = mapped_column(SAEnum(SubscriptionInterval), nullable=True)
    subscription_installments: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # ── Instructor-led mode ───────────────────────────────────────────────────
    # When > 0 the CourseDetail page shows a toggle that students can opt into.
    # If toggled, this fee is added on top of the base fee at payment time.
    # Set to 0.0 (default) to disable the feature for this course.
    # Admin controls this per course; fee varies by course/difficulty level.
    instructor_led_fee: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)

    # ── Pay-as-you-go: access window ─────────────────────────────────────────
    # How many days of access one pay-as-you-go payment purchases.
    # Ignored for one_time and subscription payment types.
    # Combined with weekly_topic_limit / monthly_topic_limit to control
    # consumption: student buys N days, throttle limits how many topics
    # they can unlock per week/month within that window.
    access_period_days: Mapped[int] = mapped_column(Integer, default=30, nullable=False)

    # ── Content throttle ─────────────────────────────────────────────────────
    throttle_enabled:    Mapped[bool]          = mapped_column(Boolean, default=False)
    weekly_topic_limit:  Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    monthly_topic_limit: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # ── Metadata ──────────────────────────────────────────────────────────────
    lang:           Mapped[str]           = mapped_column(String(20), default="en")
    duration_weeks: Mapped[Optional[int]] = mapped_column(Integer)
    level:          Mapped[str]           = mapped_column(SAEnum(CourseLevel), default=CourseLevel.beginner)
    status:         Mapped[str]           = mapped_column(SAEnum(CourseStatus), default=CourseStatus.draft, nullable=False)
    views:          Mapped[int]           = mapped_column(Integer, default=0)
    featured:       Mapped[bool]          = mapped_column(Boolean, default=False)
    requirements:   Mapped[Optional[str]] = mapped_column(Text)
    what_you_learn: Mapped[Optional[str]] = mapped_column(Text)

    # ── Revenue split (override platform default) ─────────────────────────────
    creator_pct:  Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    platform_pct: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # ── Approval ─────────────────────────────────────────────────────────────
    approved_by_id:   Mapped[Optional[int]]      = mapped_column(Integer, ForeignKey("users.id"), nullable=True)
    approved_at:      Mapped[Optional[datetime]]  = mapped_column(DateTime(timezone=True), nullable=True)
    rejection_reason: Mapped[Optional[str]]       = mapped_column(Text, nullable=True)

    # ── Owner ────────────────────────────────────────────────────────────────
    creator_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("users.id"), nullable=True)

    # ── Relationships ─────────────────────────────────────────────────────────
    creator:     Mapped[Optional["User"]] = relationship("User", back_populates="courses_created", foreign_keys=[creator_id])
    approved_by: Mapped[Optional["User"]] = relationship("User", foreign_keys=[approved_by_id])

    categories: Mapped[List["Category"]] = relationship(
        "Category", secondary=course_category_assoc, back_populates="courses",
    )
    tags: Mapped[List["Tag"]] = relationship(
        "Tag", secondary=course_tag_assoc, back_populates="courses",
    )
    lessons: Mapped[List["Lesson"]] = relationship(
        "Lesson", back_populates="course",
        cascade="all, delete-orphan",
        order_by="Lesson.order_index",
    )
    topics:         Mapped[List["Topic"]]          = relationship("Topic",         back_populates="course")
    enrollments:    Mapped[List["Enrollment"]]      = relationship("Enrollment",    back_populates="course")
    feedbacks:      Mapped[List["Feedback"]]        = relationship("Feedback",      back_populates="course")
    payments:       Mapped[List["Payment"]]         = relationship("Payment",       back_populates="course")
    certificates:   Mapped[List["Certificate"]]     = relationship("Certificate",   back_populates="course")
    tutor_assignments: Mapped[List["TutorAssignment"]] = relationship("TutorAssignment", back_populates="course")
    schedules:      Mapped[List["Schedule"]]        = relationship(
        "Schedule", back_populates="course", cascade="all, delete-orphan",
    )
    discounts:      Mapped[List["Discount"]]        = relationship("Discount",      back_populates="course")
    learning_paths: Mapped[List["LearningPath"]]    = relationship(
        "LearningPath", secondary=path_course_assoc, back_populates="courses",
    )
    subscription_plans: Mapped[List["SubscriptionPlan"]] = relationship(
        "SubscriptionPlan", foreign_keys=[SubscriptionPlan.course_id],
    )


# ─────────────────────────────────────────────
#  LESSON
# ─────────────────────────────────────────────

class Lesson(Base, TimestampMixin):
    __tablename__ = "lessons"

    id:          Mapped[int]           = mapped_column(Integer, primary_key=True, autoincrement=True)
    title:       Mapped[str]           = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    order_index: Mapped[int]           = mapped_column(Integer, default=0)
    slug:        Mapped[Optional[str]] = mapped_column(String(300))
    course_id:   Mapped[int]           = mapped_column(Integer, ForeignKey("courses.id"), nullable=False)

    course:  Mapped["Course"]              = relationship("Course",  back_populates="lessons")
    topics:  Mapped[List["Topic"]]         = relationship(
        "Topic", back_populates="lesson",
        cascade="all, delete-orphan",
        order_by="Topic.order_index",
    )
    assessments: Mapped[List["LessonAssessment"]] = relationship(
        "LessonAssessment", back_populates="lesson", cascade="all, delete-orphan",
    )


# ─────────────────────────────────────────────
#  TOPIC
# ─────────────────────────────────────────────

class Topic(Base, TimestampMixin):
    __tablename__ = "topics"

    id:               Mapped[int]           = mapped_column(Integer, primary_key=True, autoincrement=True)
    title:            Mapped[str]           = mapped_column(String(255), nullable=False)
    description:      Mapped[Optional[str]] = mapped_column(Text)
    order_index:      Mapped[int]           = mapped_column(Integer, default=0)
    slug:             Mapped[Optional[str]] = mapped_column(String(300))
    duration_minutes: Mapped[Optional[int]] = mapped_column(Integer)
    is_free_preview:  Mapped[bool]          = mapped_column(Boolean, default=False)
    lesson_id:        Mapped[int]           = mapped_column(Integer, ForeignKey("lessons.id"), nullable=False)
    course_id:        Mapped[int]           = mapped_column(Integer, ForeignKey("courses.id"), nullable=False)

    lesson:   Mapped["Lesson"]              = relationship("Lesson",  back_populates="topics")
    course:   Mapped["Course"]              = relationship("Course",  back_populates="topics")
    contents: Mapped[List["TopicContent"]]  = relationship(
        "TopicContent", back_populates="topic",
        cascade="all, delete-orphan",
        order_by="TopicContent.order_index",
    )
    completed_by: Mapped[List["User"]] = relationship(
        "User", secondary=user_topic_progress, back_populates="topic_progress",
    )
    quizzes: Mapped[Optional["Quiz"]] = relationship(
        "Quiz", back_populates="topic",
        cascade="all, delete-orphan",
        uselist=False,
    )


# ─────────────────────────────────────────────
#  TOPIC CONTENT
# ─────────────────────────────────────────────

class TopicContent(Base, TimestampMixin):
    """
    A single piece of content attached to a topic.
    content_type drives how the frontend renders it.

    File-based content (video, pdf, image, audio, ppt, doc):
        file_path  — bare filename stored on disk; served via signed token URL
        mime_type  — original MIME type
        file_size_bytes — for display / quota checks
        duration_seconds — for video / audio

    Text / article content:
        body       — rich HTML or Markdown; returned inline in the API response
        file_path is null for text content

    url:
        Legacy field kept for backwards compatibility.
        New code always generates signed token URLs at query time;
        this column is no longer written to.
    """
    __tablename__ = "topic_contents"

    id:               Mapped[int]           = mapped_column(Integer, primary_key=True, autoincrement=True)
    title:            Mapped[Optional[str]] = mapped_column(String(255))
    content_type:     Mapped[str]           = mapped_column(SAEnum(ContentType), nullable=False)

    # ── File-based ───────────────────────────────────────────────────────────
    file_path:        Mapped[Optional[str]] = mapped_column(String(1000))
    mime_type:        Mapped[Optional[str]] = mapped_column(String(100))
    file_size_bytes:  Mapped[Optional[int]] = mapped_column(Integer)
    duration_seconds: Mapped[Optional[int]] = mapped_column(Integer)

    # ── Text / article ───────────────────────────────────────────────────────
    # NOTE: was defined twice in previous model (duplicate mapped_column).
    # SQLAlchemy used the last definition silently.  Fixed: defined exactly once.
    body:             Mapped[Optional[str]] = mapped_column(Text)

    # ── Legacy / computed ────────────────────────────────────────────────────
    url:              Mapped[Optional[str]] = mapped_column(String(1000))

    # ── Ordering ─────────────────────────────────────────────────────────────
    order_index:      Mapped[int]           = mapped_column(Integer, default=0)

    # ── Foreign key ──────────────────────────────────────────────────────────
    topic_id: Mapped[int]    = mapped_column(Integer, ForeignKey("topics.id"), nullable=False)
    topic:    Mapped["Topic"] = relationship("Topic", back_populates="contents")


# ─────────────────────────────────────────────
#  LEARNING PATH
# ─────────────────────────────────────────────

class LearningPath(Base, TimestampMixin):
    """
    An ordered collection of courses sold as a bundle.

    Instructor-led and pay-as-you-go semantics mirror the Course model:
    instructor_led_fee  — extra fee when student opts into instructor-led mode
    access_period_days  — days of access per pay-as-you-go payment on this path
    """
    __tablename__ = "learning_paths"

    id:          Mapped[int]           = mapped_column(Integer, primary_key=True, autoincrement=True)
    title:       Mapped[str]           = mapped_column(String(255), unique=True, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    thumbnail:   Mapped[Optional[str]] = mapped_column(String(500))
    slug:        Mapped[Optional[str]] = mapped_column(String(300), unique=True)

    # ── Pricing ───────────────────────────────────────────────────────────────
    fee:          Mapped[float] = mapped_column(Float, default=0.0)
    payment_type: Mapped[str]   = mapped_column(SAEnum(PaymentType), default=PaymentType.one_time)

    # ── Instructor-led / pay-as-you-go (same semantics as Course) ────────────
    instructor_led_fee: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    access_period_days: Mapped[int]   = mapped_column(Integer, default=30, nullable=False)

    # ── Status / soft-delete ─────────────────────────────────────────────────
    status:     Mapped[str]  = mapped_column(SAEnum(CourseStatus), default=CourseStatus.published)
    is_active:  Mapped[bool] = mapped_column(Boolean, default=True)   # routers filter on this
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False)  # routers set this on delete

    # ── Certificate on path completion ───────────────────────────────────────
    issues_certificate: Mapped[bool] = mapped_column(Boolean, default=True)

    # ── Owner ────────────────────────────────────────────────────────────────
    created_by_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("users.id"), nullable=True)

    # ── Relationships ─────────────────────────────────────────────────────────
    courses: Mapped[List["Course"]] = relationship(
        "Course", secondary=path_course_assoc, back_populates="learning_paths",
    )
    path_enrollments: Mapped[List["PathEnrollment"]] = relationship(
        "PathEnrollment", back_populates="path",
    )
    subscription_plans: Mapped[List["SubscriptionPlan"]] = relationship(
        "SubscriptionPlan", foreign_keys=[SubscriptionPlan.path_id],
    )


# ─────────────────────────────────────────────
#  CERTIFICATE
# ─────────────────────────────────────────────

class Certificate(Base, TimestampMixin):
    __tablename__ = "certificates"

    id:          Mapped[int]           = mapped_column(Integer, primary_key=True, autoincrement=True)
    cert_number: Mapped[str]           = mapped_column(String(100), unique=True, nullable=False)
    cert_url:    Mapped[Optional[str]] = mapped_column(String(500))
    status:      Mapped[str]           = mapped_column(SAEnum(CertStatus), default=CertStatus.issued)
    issued_at:   Mapped[datetime]      = mapped_column(DateTime(timezone=True), server_default=func.now())

    user_id:   Mapped[int]           = mapped_column(Integer, ForeignKey("users.id"),          nullable=False)
    course_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("courses.id"),        nullable=True)
    path_id:   Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("learning_paths.id"), nullable=True)

    user:   Mapped["User"]              = relationship("User",   back_populates="certificates")
    course: Mapped[Optional["Course"]]  = relationship("Course", back_populates="certificates")


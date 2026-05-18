from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field

from app.enums import (
    CourseStatus, CourseLevel, ContentType, 
    PaymentType, SubscriptionInterval,
)
from app.schemas.categories import CategoryOut

class TutorAssignRequest(BaseModel):
    tutor_id: int
    course_id:     Optional[int] = None
    path_id:       Optional[int] = None
    student_id:       Optional[int] = None
    notes:         Optional[str] = None

class TutorAssignmentReview(BaseModel):
    approved:         bool
    rejection_reason: Optional[str] = None


class TagCreate(BaseModel):
    name: str = Field(..., max_length=100)


class TagOut(BaseModel):
    id: int
    name: str

    class Config:
        from_attributes = True


# ── Subscription Plan ─────────────────────────────────────────────────────────

class SubscriptionPlanCreate(BaseModel):
    name: str
    interval: SubscriptionInterval
    amount: float = Field(..., gt=0)
    currency: str = "NGN"
    course_id: Optional[int] = None
    path_id: Optional[int] = None


class SubscriptionPlanUpdate(BaseModel):
    name: Optional[str] = None
    amount: Optional[float] = None
    is_active: Optional[bool] = None


class SubscriptionPlanOut(BaseModel):
    id: int
    name: str
    paystack_plan_code: Optional[str] = None
    interval: str
    amount: float
    currency: str
    course_id: Optional[int] = None
    path_id: Optional[int] = None
    is_active: bool

    class Config:
        from_attributes = True


# ── Course ────────────────────────────────────────────────────────────────────

# After — use a validator to coerce empty string → None
from pydantic import BaseModel, Field, field_validator

class CourseCreate(BaseModel):
    title: str = Field(..., min_length=3, max_length=255)
    description: Optional[str] = None
    short_description: Optional[str] = None
    fee: float = 0.0
    payment_type: PaymentType = PaymentType.one_time
    subscription_interval: Optional[SubscriptionInterval] = None
    subscription_installments: Optional[int] = None
    lang: str = "en"
    duration_weeks: Optional[int] = None
    level: CourseLevel = CourseLevel.beginner
    requirements: Optional[str] = None
    what_you_learn: Optional[str] = None
    throttle_enabled: bool = False
    weekly_topic_limit: Optional[int] = None
    monthly_topic_limit: Optional[int] = None
    category_ids: List[int] = []
    tag_ids: List[int] = []
    preview_video: Optional[str] = None
    creator_pct: Optional[float] = Field(None, ge=0, le=100)
    # Instructor-led fee
    instructor_led_fee: Optional[float] = Field(
        None,
        ge=0,
        description=(
            "Extra fee for instructor-led mode. 0 = feature disabled. "
            "Admin sets this per course; students can opt in on CourseDetail."
        ),
    )
    access_period_days: Optional[int] = Field(
        30,
        ge=1,
        description=(
            "Days of access bought by each pay-as-you-go payment. "
            "Only used when payment_type = pay_as_you_go."
        ),
    )

    @field_validator("subscription_interval", "preview_video", mode="before")
    @classmethod
    def empty_str_to_none(cls, v):
        # The frontend sends '' when these fields are not applicable.
        # Coerce to None so the enum validator doesn't choke.
        if v == "":
            return None
        return v


# class CourseUpdate(BaseModel):
#     title: Optional[str] = None
#     description: Optional[str] = None
#     short_description: Optional[str] = None
#     fee: Optional[float] = None
#     payment_type: Optional[PaymentType] = None
#     subscription_interval: Optional[SubscriptionInterval] = None
#     subscription_installments: Optional[int] = None
#     lang: Optional[str] = None
#     duration_weeks: Optional[int] = None
#     level: Optional[CourseLevel] = None
#     requirements: Optional[str] = None
#     what_you_learn: Optional[str] = None
#     throttle_enabled: Optional[bool] = None
#     weekly_topic_limit: Optional[int] = None
#     monthly_topic_limit: Optional[int] = None
#     category_ids: Optional[List[int]] = None
#     tag_ids: Optional[List[int]] = None
#     preview_video: Optional[str] = None
#     creator_pct: Optional[float] = Field(None, ge=0, le=100)
#     featured: Optional[bool] = None
#     status: Optional[CourseStatus] = None
#     # Instructor-led fee
#     instructor_led_fee: Optional[float] = Field(
#         None,
#         ge=0,
#         description=(
#             "Extra fee for instructor-led mode. 0 = feature disabled. "
#             "Admin sets this per course; students can opt in on CourseDetail."
#         ),
#     )
#     access_period_days: Optional[int] = Field(
#         30,
#         ge=1,
#         description=(
#             "Days of access bought by each pay-as-you-go payment. "
#             "Only used when payment_type = pay_as_you_go."
#         ),
#     )

#     @field_validator("subscription_interval", "preview_video", mode="before")
#     @classmethod
#     def empty_str_to_none(cls, v):
#         if v == "":
#             return None
#         return v

# v2
class CourseUpdate(BaseModel):
    # ── Core metadata ─────────────────────────────
    title: Optional[str] = None
    description: Optional[str] = None
    short_description: Optional[str] = None
    lang: Optional[str] = None
    duration_weeks: Optional[int] = None
    level: Optional[CourseLevel] = None
    requirements: Optional[str] = None
    what_you_learn: Optional[str] = None
    preview_video: Optional[str] = None

    # ── Legacy / base pricing ─────────────────────
    fee: Optional[float] = None
    payment_type: Optional[PaymentType] = None

    # ── Subscription model ────────────────────────
    subscription_fee: Optional[float] = None
    subscription_enabled: Optional[bool] = None
    subscription_interval: Optional[SubscriptionInterval] = None
    subscription_installments: Optional[int] = None

    # ── Pay-as-you-go model ───────────────────────
    pay_as_you_go_fee: Optional[float] = None
    pay_as_you_go_enabled: Optional[bool] = None
    access_period_days: Optional[int] = Field(
        None,
        ge=1,
        description="Days of access per PAYG payment"
    )

    # ── Installment model ─────────────────────────
    installment_enabled: Optional[bool] = None
    installment_count: Optional[int] = None
    installment_fee: Optional[float] = None

    # ── Instructor-led add-on ─────────────────────
    instructor_led_fee: Optional[float] = Field(
        None,
        ge=0,
        description="Extra fee for instructor-led mode"
    )

    # ── Throttling / limits ───────────────────────
    throttle_enabled: Optional[bool] = None
    weekly_topic_limit: Optional[int] = None
    monthly_topic_limit: Optional[int] = None

    # ── Classification ────────────────────────────
    category_ids: Optional[List[int]] = None
    tag_ids: Optional[List[int]] = None
    featured: Optional[bool] = None
    status: Optional[CourseStatus] = None

    # ── Revenue share ─────────────────────────────
    creator_pct: Optional[float] = Field(None, ge=0, le=100)

    # ── Cleanup helper ────────────────────────────
    @field_validator("subscription_interval", "preview_video", mode="before")
    @classmethod
    def empty_str_to_none(cls, v):
        if v == "":
            return None
        return v

class CourseApproval(BaseModel):
    approved: bool
    rejection_reason: Optional[str] = None


class CourseThrottleUpdate(BaseModel):
    throttle_enabled: bool
    weekly_topic_limit: Optional[int] = None
    monthly_topic_limit: Optional[int] = None


class CourseListItem(BaseModel):
    id: int
    title: str
    slug: Optional[str] = None
    thumbnail: Optional[str] = None
    fee: float
    level: str
    status: str
    payment_type: str
    views: int = 0
    featured: bool = False
    categories: List[CategoryOut] = []
    creator_id: Optional[int] = None
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class CourseDetail(CourseListItem):
    description: Optional[str] = None
    short_description: Optional[str] = None
    requirements: Optional[str] = None
    what_you_learn: Optional[str] = None
    lang: str = "en"
    duration_weeks: Optional[int] = None
    subscription_interval: Optional[str] = None
    subscription_installments: Optional[int] = None
    throttle_enabled: bool = False
    weekly_topic_limit: Optional[int] = None
    monthly_topic_limit: Optional[int] = None
    preview_video: Optional[str] = None
    tags: List[TagOut] = []
    lessons_count: int = 0
    topics_count: int = 0
    enrollments_count: int = 0


# ── Lesson ────────────────────────────────────────────────────────────────────

class LessonCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    order_index: int = 0


class LessonUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    order_index: Optional[int] = None


class LessonOut(BaseModel):
    id: int
    title: str
    description: Optional[str] = None
    order_index: int
    slug: Optional[str] = None
    course_id: int
    topics_count: int = 0

    class Config:
        from_attributes = True


# ── Topic ─────────────────────────────────────────────────────────────────────

class TopicCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    order_index: int = 0
    duration_minutes: Optional[int] = None
    is_free_preview: bool = False
    lesson_id: int


class TopicUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    order_index: Optional[int] = None
    duration_minutes: Optional[int] = None
    is_free_preview: Optional[bool] = None


class TopicOut(BaseModel):
    id: int
    title: str
    description: Optional[str] = None
    order_index: int
    duration_minutes: Optional[int] = None
    is_free_preview: bool
    lesson_id: int
    course_id: int
    contents_count: int = 0
    is_completed: Optional[bool] = None  # per current user

    class Config:
        from_attributes = True


# ── Topic Content ─────────────────────────────────────────────────────────────

class TopicContentCreate(BaseModel):
    title: Optional[str] = None
    content_type: ContentType
    url: Optional[str] = None
    body: Optional[str] = None   # Rich HTML/text for text type
    order_index: int = 0


class TopicContentUpdate(BaseModel):
    title: Optional[str] = None
    url: Optional[str] = None
    body: Optional[str] = None
    order_index: Optional[int] = None


class TopicContentOut(BaseModel):
    id: int
    title: Optional[str] = None
    content_type: str
    file_path: Optional[str] = None
    url: Optional[str] = None
    body: Optional[str] = None
    duration_seconds: Optional[int] = None
    file_size_bytes: Optional[int] = None
    mime_type: Optional[str] = None
    order_index: int
    topic_id: int

    class Config:
        from_attributes = True


# ─── Schema for topic text-contents ──────────────────────────────────────────────────


class TopicTextContentCreate(BaseModel):
    title: Optional[str] = None
    body: Optional[str] = None


class ContentReorderItem(BaseModel):
    id: int
    order_index: int


# ================================================================
#  Reorder handlers
# ================================================================

# class ReorderItem(BaseModel):
#     id:          int
#     order_index: int

# ── Learning Path ─────────────────────────────────────────────────────────────

# class PathCreate(BaseModel):
#     title: str = Field(..., min_length=3, max_length=255)
#     description: Optional[str] = None
#     fee: float = 0.0
#     payment_type: PaymentType = PaymentType.one_time
#     issues_certificate: bool = True
#     course_ids: List[int] = []
#     status: Optional[CourseStatus] = CourseStatus.published


# class PathUpdate(BaseModel):
#     title: Optional[str] = None
#     description: Optional[str] = None
#     fee: Optional[float] = None
#     payment_type: Optional[PaymentType] = None
#     issues_certificate: Optional[bool] = None
#     course_ids: Optional[List[int]] = None
#     status: Optional[CourseStatus] = None


# v2
# ── Learning Path Schemas ────────────────────────────────────────────────────

class PathCreate(BaseModel):
    title: str = Field(..., min_length=3, max_length=255)
    description: Optional[str] = Field(default=None)

    fee: float = Field(default=0.0, ge=0)
    payment_type: PaymentType = Field(default=PaymentType.one_time)

    course_ids: List[int] = Field(default_factory=list)

    issues_certificate: bool = Field(default=True)

    duration_weeks: Optional[int] = Field(default=None, ge=1)

    instructor_led_fee: float = Field(default=0.0, ge=0)

    subscription_enabled: bool = Field(default=False)

    subscription_interval: Optional[str] = Field(
        default="monthly",
        max_length=50,
    )

    subscription_fee: Optional[float] = Field(
        default=None,
        ge=0,
    )

    pay_as_you_go_enabled: bool = Field(default=False)

    pay_as_you_go_fee: Optional[float] = Field(
        default=None,
        ge=0,
    )

    access_period_days: int = Field(
        default=30,
        ge=1,
    )

    what_you_achieve: Optional[str] = Field(default=None)

    status: CourseStatus = Field(
        default=CourseStatus.published,
    )

    is_active: bool = Field(default=True)


class PathUpdate(BaseModel):
    title: Optional[str] = Field(
        default=None,
        min_length=3,
        max_length=255,
    )

    description: Optional[str] = Field(default=None)

    fee: Optional[float] = Field(
        default=None,
        ge=0,
    )

    payment_type: Optional[PaymentType] = Field(default=None)

    course_ids: Optional[List[int]] = Field(default=None)

    issues_certificate: Optional[bool] = Field(default=None)

    duration_weeks: Optional[int] = Field(
        default=None,
        ge=1,
    )

    instructor_led_fee: Optional[float] = Field(
        default=None,
        ge=0,
    )

    subscription_enabled: Optional[bool] = Field(default=None)

    subscription_interval: Optional[str] = Field(
        default=None,
        max_length=50,
    )

    subscription_fee: Optional[float] = Field(
        default=None,
        ge=0,
    )

    pay_as_you_go_enabled: Optional[bool] = Field(default=None)

    pay_as_you_go_fee: Optional[float] = Field(
        default=None,
        ge=0,
    )

    access_period_days: Optional[int] = Field(
        default=None,
        ge=1,
    )

    what_you_achieve: Optional[str] = Field(default=None)

    status: Optional[CourseStatus] = Field(default=None)

    is_active: Optional[bool] = Field(default=None)


# ── Schedule ──────────────────────────────────────────────────────────────────

class ScheduleCreate(BaseModel):
    title: str
    description: Optional[str] = None
    start_time: datetime
    end_time: datetime
    meeting_link: Optional[str] = None
    is_recurring: bool = False
    recurrence_rule: Optional[str] = None
    course_id: Optional[int] = None
    tutor_id: Optional[int] = None


class ScheduleUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    meeting_link: Optional[str] = None
    is_recurring: Optional[bool] = None
    recurrence_rule: Optional[str] = None


class MarkAttendance(BaseModel):
    schedule_id: int
    student_ids: List[int]
    present: bool = True


# class TutorAssignRequest(BaseModel):
#     tutor_id: int
#     course_id: int
#     student_id: Optional[int] = None


# ── Feedback ──────────────────────────────────────────────────────────────────

class FeedbackCreate(BaseModel):
    course_id: int
    rating: int = Field(..., ge=1, le=5)
    comment: Optional[str] = None

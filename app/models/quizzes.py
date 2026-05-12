"""
app/models/quizzes.py
=====================
SQLAlchemy ORM models for the Intellect LMS assessment layer.

Hierarchy
---------
Course
  └── Topic  (via Lesson)
        └── Quiz                    ← one optional quiz per topic
              ├── QuizQuestion[]
              └── QuizAttempt[]     (per student, per attempt)
  └── Lesson
        └── LessonAssessment        ← classwork / homework
              ├── LessonAssessmentQuestion[]
              └── LessonAssessmentSubmission[]  (per student)
  └── Project                       ← course-end project brief
        └── ProjectSubmission[]     (per student; AI + tutor graded)
  └── Schedule                      ← live class session
        ├── AttendanceRecord[]      (per student)
        └── AttendanceCheckInCode   (OTP for self-check-in)

Legacy models (kept for data compatibility)
-------------------------------------------
  Assessment, LegacyQuestion, LegacyAssessmentSubmission, LegacyAnswer
  These map to the original "assessments / questions / assessment_submissions /
  answers" tables. New feature code must NOT add to them; use the new models.

Import pattern
--------------
    from app.models.quizzes import (
        Quiz, QuizQuestion, QuizAttempt,
        LessonAssessment, LessonAssessmentQuestion, LessonAssessmentSubmission,
        Project, ProjectSubmission,
        Schedule, AttendanceRecord, AttendanceCheckInCode,
        Assessment, LegacyQuestion, LegacyAssessmentSubmission, LegacyAnswer,
    )

Migration
---------
    alembic revision --autogenerate -m "assessment_layer_v2"
    alembic upgrade head
"""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from sqlalchemy import (
    Boolean, DateTime, Float, ForeignKey,
    Integer, JSON, String, Text, UniqueConstraint,
)
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base
from app.models.base import TimestampMixin
from app.enums import (
    AttendanceStatus,
    QuizAttemptStatus,
    QuizQuestionType,
    SubmissionStatus,
    AssessmentType,
    QuestionType,
)


# ══════════════════════════════════════════════════════════════════
#  SECTION 1 — Topic-level Quiz
# ══════════════════════════════════════════════════════════════════

class Quiz(Base, TimestampMixin):
    """
    One optional quiz per Topic.

    Completion gate
    ---------------
    When ``required_for_completion`` is True the front-end disables
    "Mark as Complete" until the student achieves a passing attempt.
    This is enforced server-side in enrollments.mark_progress too.

    Attempt limits
    --------------
    ``max_attempts = 0`` means unlimited.
    """
    __tablename__ = "quizzes"
    __table_args__ = (
        UniqueConstraint("topic_id", name="uq_quiz_topic"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    title:        Mapped[str]           = mapped_column(String(255), nullable=False, default="Topic Quiz")
    instructions: Mapped[Optional[str]] = mapped_column(Text, nullable=True,
        comment="Shown to the student before they start.")

    # ── Scoring ───────────────────────────────────────────────────
    pass_score:   Mapped[float] = mapped_column(Float, default=70.0,
        comment="Minimum percentage (0-100) required to pass.")
    max_attempts: Mapped[int]   = mapped_column(Integer, default=3,
        comment="0 = unlimited attempts.")

    # ── Behaviour flags ───────────────────────────────────────────
    shuffle_questions:       Mapped[bool] = mapped_column(Boolean, default=False)
    show_correct_after:      Mapped[bool] = mapped_column(Boolean, default=True,
        comment="Reveal correct answers and explanations after submission.")
    required_for_completion: Mapped[bool] = mapped_column(Boolean, default=False,
        comment="Student must pass before marking the topic complete.")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True,
        comment="Soft-disable without deleting (e.g. while editing).")

    # ── Foreign keys ──────────────────────────────────────────────
    topic_id:  Mapped[int] = mapped_column(Integer, ForeignKey("topics.id"),  nullable=False)
    course_id: Mapped[int] = mapped_column(Integer, ForeignKey("courses.id"), nullable=False,
        comment="Denormalised from topic.course_id for efficient queries.")

    # ── Relationships ─────────────────────────────────────────────
    topic = relationship("Topic", back_populates="quizzes")
    questions: Mapped[List["QuizQuestion"]] = relationship(
        "QuizQuestion", back_populates="quiz",
        cascade="all, delete-orphan",
        order_by="QuizQuestion.order_index",
    )
    attempts: Mapped[List["QuizAttempt"]] = relationship(
        "QuizAttempt", back_populates="quiz",
        cascade="all, delete-orphan",
    )


class QuizQuestion(Base, TimestampMixin):
    """
    One question in a Quiz.

    options JSON format
    -------------------
    mcq / multi_select:
        [{"text": "Option A", "is_correct": true}, ...]
    true_false / short_answer / essay / fill_blank / file_upload:
        None  (correct_answer field holds the reference)

    correct_answer format
    ---------------------
    mcq:          exact text of the single correct option
    multi_select: JSON-encoded list, e.g. '["A","C"]'
    true_false:   "True" or "False"
    short_answer: model answer string (keyword match or AI comparison)
    essay:        grading rubric notes (never shown to student)
    fill_blank:   expected answer string (case-insensitive match)
    file_upload:  None (graded manually or by AI)
    """
    __tablename__ = "quiz_questions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    body:          Mapped[str]           = mapped_column(Text, nullable=False)
    question_type: Mapped[str]           = mapped_column(SAEnum(QuizQuestionType), nullable=False)
    options:       Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    correct_answer: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    explanation:    Mapped[Optional[str]] = mapped_column(Text, nullable=True,
        comment="Shown to student after submission when show_correct_after=True.")

    marks:          Mapped[float] = mapped_column(Float, default=1.0)
    partial_credit: Mapped[bool]  = mapped_column(Boolean, default=False,
        comment="If True, multi_select awards proportional marks.")
    order_index:    Mapped[int]   = mapped_column(Integer, default=0)

    quiz_id: Mapped[int] = mapped_column(Integer, ForeignKey("quizzes.id"), nullable=False)

    quiz: Mapped["Quiz"] = relationship("Quiz", back_populates="questions")


class QuizAttempt(Base, TimestampMixin):
    """
    One student attempt at a Quiz.

    Grading pipeline
    ----------------
    1. submitted   – answers received; auto-grader runs immediately
    2. auto_graded – MCQ/T-F/fill_blank scored; essay/short_answer pending
    3. ai_graded   – AI has graded open-ended questions
    4. reviewed    – tutor has reviewed / overridden AI grades
    5. returned    – student can see full results and feedback

    answers JSON:  {str(question_id): "answer string"}
    result_detail: list of per-question dicts (see _auto_grade in service)
    """
    __tablename__ = "quiz_attempts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    answers:       Mapped[Optional[dict]] = mapped_column(JSON, nullable=True,
        comment="{question_id: answer_string} — raw student input.")
    result_detail: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True,
        comment="Per-question grading breakdown list.")

    # ── Scoring summary ───────────────────────────────────────────
    score:     Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    max_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    pct:       Mapped[Optional[float]] = mapped_column(Float, nullable=True,
        comment="score / max_score * 100, rounded to 1 decimal.")
    passed:    Mapped[Optional[bool]]  = mapped_column(Boolean, nullable=True)

    # ── Feedback ──────────────────────────────────────────────────
    ai_feedback:    Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    tutor_feedback: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # ── Lifecycle ─────────────────────────────────────────────────
    status: Mapped[str] = mapped_column(
        SAEnum(QuizAttemptStatus), default=QuizAttemptStatus.submitted)
    
    attempt_number: Mapped[int] = mapped_column(Integer, default=1,
        comment="1-based counter per (quiz_id, user_id) pair.")
    submitted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    graded_at:    Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # ── Foreign keys ──────────────────────────────────────────────
    quiz_id: Mapped[int] = mapped_column(Integer, ForeignKey("quizzes.id"), nullable=False)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"),   nullable=False)

    quiz: Mapped["Quiz"] = relationship("Quiz", back_populates="attempts")
    user = relationship("User", foreign_keys=[user_id])


# ══════════════════════════════════════════════════════════════════
#  SECTION 2 — Lesson-level Assessment (Classwork & Homework)
# ══════════════════════════════════════════════════════════════════

class LessonAssessment(Base, TimestampMixin):
    """
    A formal assessment (classwork or homework) attached to a Lesson.

    Differences from Quiz
    ---------------------
    - Linked to a Lesson (not a Topic).
    - Has a due_date and time_limit_minutes.
    - assessment_type distinguishes 'classwork' vs 'homework' vs 'exam'.
    - Supports all QuizQuestionType values (including essay & file_upload).
    - AI auto-grades open-ended questions; tutor may override.

    Grading pipeline (same lifecycle as ProjectSubmission)
    -------------------------------------------------------
    pending → reviewing → ai_graded → returned / resubmit
    """
    __tablename__ = "lesson_assessments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    title:           Mapped[str]           = mapped_column(String(255), nullable=False)
    instructions:    Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    assessment_type: Mapped[str]           = mapped_column(
        SAEnum(AssessmentType), nullable=False,
        comment="classwork | homework | exam | quiz | quick_check")

    # ── Timing ────────────────────────────────────────────────────
    time_limit_minutes: Mapped[Optional[int]] = mapped_column(Integer, nullable=True,
        comment="0 or None = no time limit.")
    due_date: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True,
        comment="Submission deadline (UTC).  None = no deadline.")

    # ── Scoring ───────────────────────────────────────────────────
    total_marks:  Mapped[float] = mapped_column(Float, default=10.0)
    pass_mark:    Mapped[float] = mapped_column(Float, default=5.0)
    max_attempts: Mapped[int]   = mapped_column(Integer, default=1,
        comment="Classwork usually 1; homework may allow retakes.")

    # ── Behaviour ─────────────────────────────────────────────────
    shuffle_questions:  Mapped[bool] = mapped_column(Boolean, default=False)
    show_answers_after: Mapped[bool] = mapped_column(Boolean, default=True)
    is_auto_graded:     Mapped[bool] = mapped_column(Boolean, default=True,
        comment="Auto-grade MCQ/T-F; AI grades short_answer/essay.")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    # ── Foreign keys ──────────────────────────────────────────────
    lesson_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("lessons.id"), nullable=True,
        comment="None for course-level assessments (rare).")
    course_id: Mapped[int] = mapped_column(Integer, ForeignKey("courses.id"), nullable=False)

    # ── Relationships ─────────────────────────────────────────────
    lesson = relationship("Lesson", back_populates="assessments")
    questions: Mapped[List["LessonAssessmentQuestion"]] = relationship(
        "LessonAssessmentQuestion", back_populates="assessment",
        cascade="all, delete-orphan",
        order_by="LessonAssessmentQuestion.order_index",
    )
    submissions: Mapped[List["LessonAssessmentSubmission"]] = relationship(
        "LessonAssessmentSubmission", back_populates="assessment",
        cascade="all, delete-orphan",
    )


class LessonAssessmentQuestion(Base, TimestampMixin):
    """
    One question in a LessonAssessment.
    Shares option / correct_answer conventions with QuizQuestion.
    """
    __tablename__ = "lesson_assessment_questions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    body:           Mapped[str]            = mapped_column(Text, nullable=False)
    question_type:  Mapped[str]            = mapped_column(SAEnum(QuizQuestionType), nullable=False)
    options:        Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    correct_answer: Mapped[Optional[str]]  = mapped_column(Text, nullable=True)
    explanation:    Mapped[Optional[str]]  = mapped_column(Text, nullable=True)

    marks:          Mapped[float] = mapped_column(Float, default=1.0)
    partial_credit: Mapped[bool]  = mapped_column(Boolean, default=False)
    order_index:    Mapped[int]   = mapped_column(Integer, default=0)

    assessment_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("lesson_assessments.id"), nullable=False)

    assessment: Mapped["LessonAssessment"] = relationship(
        "LessonAssessment", back_populates="questions")


class LessonAssessmentSubmission(Base, TimestampMixin):
    """
    One student submission for a LessonAssessment.

    answers JSON:    {str(question_id): "answer_string"}
    result_detail:   per-question grading breakdown (same shape as QuizAttempt)
    file_path:       set when the student uploads a file answer
    """
    __tablename__ = "lesson_assessment_submissions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # ── Student input ─────────────────────────────────────────────
    answers:   Mapped[Optional[dict]] = mapped_column(JSON, nullable=True,
        comment="{question_id: answer_string}")
    file_path: Mapped[Optional[str]]  = mapped_column(String(1000), nullable=True,
        comment="Uploaded file path for file_upload question types.")
    file_name: Mapped[Optional[str]]  = mapped_column(String(500), nullable=True)

    # ── Scoring ───────────────────────────────────────────────────
    score:         Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    max_score:     Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    percentage:    Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    passed:        Mapped[Optional[bool]]  = mapped_column(Boolean, nullable=True)
    result_detail: Mapped[Optional[dict]]  = mapped_column(JSON, nullable=True)

    # ── Feedback ──────────────────────────────────────────────────
    ai_feedback:    Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    tutor_feedback: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # ── Lifecycle ─────────────────────────────────────────────────
    status: Mapped[str] = mapped_column(
        SAEnum(SubmissionStatus), default=SubmissionStatus.pending)
    attempt_number: Mapped[int]              = mapped_column(Integer, default=1)
    submitted_at:   Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    graded_at:      Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # ── Foreign keys ──────────────────────────────────────────────
    assessment_id: Mapped[int]          = mapped_column(
        Integer, ForeignKey("lesson_assessments.id"), nullable=False)
    user_id: Mapped[int]                = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    graded_by_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("users.id"), nullable=True)

    # ── Relationships ─────────────────────────────────────────────
    assessment: Mapped["LessonAssessment"] = relationship(
        "LessonAssessment", back_populates="submissions")
    user      = relationship("User", foreign_keys=[user_id])
    graded_by = relationship("User", foreign_keys=[graded_by_id])


# ══════════════════════════════════════════════════════════════════
#  SECTION 3 — Course-level Project
# ══════════════════════════════════════════════════════════════════

class Project(Base, TimestampMixin):
    """
    A project brief created by a course creator or admin.

    Students submit at the end of (or during) the course.
    One course can have multiple briefs; typically there is one.

    Rubric: stored as Markdown, shown to students and passed to AI grader.
    allowed_formats: comma-separated extension list, e.g. "pdf,zip,docx".
    """
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    title:       Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False,
        comment="Full project brief shown to students.")
    rubric: Mapped[Optional[str]] = mapped_column(Text, nullable=True,
        comment="Grading rubric in Markdown.  Passed to AI grader.")

    due_date:         Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    max_file_size_mb: Mapped[int]                = mapped_column(Integer, default=50)
    allowed_formats:  Mapped[Optional[str]]      = mapped_column(String(200), nullable=True,
        comment="Comma-separated extension list e.g. 'pdf,zip,docx'. None = any.")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    course_id: Mapped[int]          = mapped_column(Integer, ForeignKey("courses.id"), nullable=False)
    lesson_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("lessons.id"), nullable=True,
        comment="Set only for lesson-scoped mid-course projects.")

    course = relationship("Course")
    lesson = relationship("Lesson")
    submissions: Mapped[List["ProjectSubmission"]] = relationship(
        "ProjectSubmission", back_populates="project",
        cascade="all, delete-orphan",
    )


class ProjectSubmission(Base, TimestampMixin):
    """
    A student submission for a Project brief.

    The student may provide any combination of:
      note         – written description / reflection
      external_url – GitHub repo, live demo, Figma link, etc.
      file_path    – uploaded file stored in /projects/ on disk

    At least one must be present (enforced at the API layer).

    Grading pipeline
    ----------------
    pending → reviewing → ai_graded → returned / resubmit
    """
    __tablename__ = "project_submissions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # ── Submission artefacts ──────────────────────────────────────
    title:        Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    note:         Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    external_url: Mapped[Optional[str]] = mapped_column(String(2000), nullable=True)
    file_path:    Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
    file_name:    Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    mime_type:    Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    file_size_bytes: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # ── Grading ───────────────────────────────────────────────────
    score:     Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    max_score: Mapped[float]           = mapped_column(Float, default=100.0)
    passed:    Mapped[Optional[bool]]  = mapped_column(Boolean, nullable=True)

    ai_feedback:     Mapped[Optional[str]]  = mapped_column(Text, nullable=True)
    ai_strengths:    Mapped[Optional[dict]] = mapped_column(JSON, nullable=True,
        comment='List of strength strings e.g. ["Clean code", "Good docs"].')
    ai_improvements: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True,
        comment='List of improvement strings.')
    tutor_feedback:  Mapped[Optional[str]]  = mapped_column(Text, nullable=True)

    # ── Lifecycle ─────────────────────────────────────────────────
    status:    Mapped[str]              = mapped_column(SAEnum(SubmissionStatus), default=SubmissionStatus.pending)
    graded_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # ── Foreign keys ──────────────────────────────────────────────
    project_id:    Mapped[int]          = mapped_column(Integer, ForeignKey("projects.id"), nullable=False)
    user_id:       Mapped[int]          = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    graded_by_id:  Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("users.id"), nullable=True,
        comment="NULL = AI-only grade; set to tutor user_id after human review.")

    project:   Mapped["Project"] = relationship("Project", back_populates="submissions")
    user       = relationship("User", foreign_keys=[user_id])
    graded_by  = relationship("User", foreign_keys=[graded_by_id])


# ══════════════════════════════════════════════════════════════════
#  SECTION 4 — Schedule & Attendance
# ══════════════════════════════════════════════════════════════════

class Schedule(Base, TimestampMixin):
    """Live class / timetable entry."""
    __tablename__ = "schedules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    title:           Mapped[str]           = mapped_column(String(255), nullable=False)
    description:     Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    start_time:      Mapped[datetime]      = mapped_column(DateTime(timezone=True), nullable=False)
    end_time:        Mapped[datetime]      = mapped_column(DateTime(timezone=True), nullable=False)
    meeting_link:    Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    is_recurring:    Mapped[bool]          = mapped_column(Boolean, default=False)
    recurrence_rule: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)

    course_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("courses.id"), nullable=True)
    tutor_id:  Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("users.id"),   nullable=True)

    course = relationship("Course", back_populates="schedules")
    tutor  = relationship("User", back_populates="schedules_as_tutor", foreign_keys=[tutor_id])
    attendance_records: Mapped[List["AttendanceRecord"]] = relationship(
        "AttendanceRecord", back_populates="schedule")
    checkin_codes: Mapped[List["AttendanceCheckInCode"]] = relationship(
        "AttendanceCheckInCode", back_populates="schedule")


class AttendanceRecord(Base, TimestampMixin):
    """
    Per-student attendance for a scheduled session.

    Unique constraint: one record per (schedule_id, user_id).
    Upserted on repeat check-in or tutor re-mark.
    """
    __tablename__ = "attendance_records"
    __table_args__ = (
        UniqueConstraint("schedule_id", "user_id", name="uq_attendance_schedule_user"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    status: Mapped[str] = mapped_column(SAEnum(AttendanceStatus),
        default=AttendanceStatus.absent,
        comment="present | absent | late | excused")
    check_in_time: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    note:          Mapped[Optional[str]]      = mapped_column(String(500), nullable=True,
        comment="Tutor note, e.g. reason for excusal.")

    schedule_id:   Mapped[int]          = mapped_column(Integer, ForeignKey("schedules.id"), nullable=False)
    user_id:       Mapped[int]          = mapped_column(Integer, ForeignKey("users.id"),     nullable=False)
    marked_by_id:  Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("users.id"),   nullable=True,
        comment="NULL = self-check-in; tutor/admin user_id for manual mark.")

    schedule  = relationship("Schedule", back_populates="attendance_records")
    user      = relationship("User", foreign_keys=[user_id])
    marked_by = relationship("User", foreign_keys=[marked_by_id])


class AttendanceCheckInCode(Base, TimestampMixin):
    """
    Short-lived OTP generated by a tutor for a Schedule.

    Students enter this code to self-check-in.
    Only one active code per schedule (old codes deactivated before issuing new one).
    Default TTL: 30 minutes.  Code format: 6-char alphanumeric.
    """
    __tablename__ = "attendance_checkin_codes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    code:       Mapped[str]      = mapped_column(String(20), nullable=False, unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    is_active:  Mapped[bool]     = mapped_column(Boolean, default=True)

    schedule_id: Mapped[int] = mapped_column(Integer, ForeignKey("schedules.id"), nullable=False)

    schedule = relationship("Schedule", back_populates="checkin_codes")


# ══════════════════════════════════════════════════════════════════
#  SECTION 5 — Legacy Assessment models (backwards compatibility)
#
#  These map to the ORIGINAL "assessments / questions /
#  assessment_submissions / answers" tables created before the
#  LessonAssessment system was built.  Keep them to avoid breaking
#  existing data and migration history.
#
#  DO NOT add new features here.  Use LessonAssessment instead.
# ══════════════════════════════════════════════════════════════════

# class Assessment(Base, TimestampMixin):
#     """Legacy assessment model. Use LessonAssessment for new code."""
#     __tablename__ = "assessments"

#     id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

#     title:           Mapped[str]           = mapped_column(String(255), nullable=False)
#     description:     Mapped[Optional[str]] = mapped_column(Text, nullable=True)
#     assessment_type: Mapped[str]           = mapped_column(SAEnum(AssessmentType), nullable=False)
#     total_marks:     Mapped[float]         = mapped_column(Float, default=100.0)
#     pass_mark:       Mapped[float]         = mapped_column(Float, default=50.0)
#     time_limit_minutes: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
#     due_date:        Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
#     is_auto_graded:  Mapped[bool]          = mapped_column(Boolean, default=True)
#     show_answers_after: Mapped[bool]       = mapped_column(Boolean, default=True)
#     attempts_allowed:   Mapped[int]        = mapped_column(Integer, default=1)
#     shuffle_questions:  Mapped[bool]       = mapped_column(Boolean, default=False)
#     is_active:          Mapped[bool]       = mapped_column(Boolean, default=True)

#     course_id:     Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("courses.id"), nullable=True)
#     topic_id:      Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("topics.id"),  nullable=True)
#     created_by_id: Mapped[int]           = mapped_column(Integer, ForeignKey("users.id"),   nullable=False)

#     course = relationship("Course", back_populates="assessments")
#     topic  = relationship("Topic",  back_populates="quick_assessments", foreign_keys=[topic_id])
#     questions:   Mapped[List["LegacyQuestion"]]            = relationship(
#         "LegacyQuestion", back_populates="assessment", cascade="all, delete-orphan")
#     submissions: Mapped[List["LegacyAssessmentSubmission"]] = relationship(
#         "LegacyAssessmentSubmission", back_populates="assessment")


# class LegacyQuestion(Base, TimestampMixin):
#     """Legacy question model. Use LessonAssessmentQuestion for new code."""
#     __tablename__ = "questions"

#     id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

#     body:           Mapped[str]            = mapped_column(Text, nullable=False)
#     question_type:  Mapped[str]            = mapped_column(SAEnum(QuestionType), nullable=False)
#     options:        Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
#     correct_answer: Mapped[Optional[str]]  = mapped_column(Text, nullable=True)
#     explanation:    Mapped[Optional[str]]  = mapped_column(Text, nullable=True)
#     marks:          Mapped[float]          = mapped_column(Float, default=1.0)
#     order_index:    Mapped[int]            = mapped_column(Integer, default=0)

#     assessment_id: Mapped[int] = mapped_column(Integer, ForeignKey("assessments.id"), nullable=False)

#     assessment: Mapped["Assessment"]     = relationship("Assessment", back_populates="questions")
#     answers:    Mapped[List["LegacyAnswer"]] = relationship("LegacyAnswer", back_populates="question")


# class LegacyAssessmentSubmission(Base, TimestampMixin):
#     """Legacy submission model. Use LessonAssessmentSubmission for new code."""
#     __tablename__ = "assessment_submissions"

#     id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

#     status:         Mapped[str]            = mapped_column(String(50), default="submitted")
#     score:          Mapped[Optional[float]] = mapped_column(Float, nullable=True)
#     percentage:     Mapped[Optional[float]] = mapped_column(Float, nullable=True)
#     passed:         Mapped[Optional[bool]]  = mapped_column(Boolean, nullable=True)
#     ai_feedback:    Mapped[Optional[str]]   = mapped_column(Text, nullable=True)
#     tutor_feedback: Mapped[Optional[str]]   = mapped_column(Text, nullable=True)
#     attempt_number: Mapped[int]             = mapped_column(Integer, default=1)
#     submitted_at:   Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
#     graded_at:      Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

#     student_id:    Mapped[int]          = mapped_column(Integer, ForeignKey("users.id"),       nullable=False)
#     assessment_id: Mapped[int]          = mapped_column(Integer, ForeignKey("assessments.id"), nullable=False)
#     graded_by_id:  Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("users.id"),     nullable=True)

#     student:    Mapped["User"]        = relationship("User", back_populates="assessment_submissions", foreign_keys=[student_id])
#     assessment: Mapped["Assessment"]  = relationship("Assessment", back_populates="submissions")
#     answers:    Mapped[List["LegacyAnswer"]] = relationship("LegacyAnswer", back_populates="submission")
#     graded_by  = relationship("User", foreign_keys=[graded_by_id])


# class LegacyAnswer(Base, TimestampMixin):
#     """Legacy answer model. Use result_detail JSON on LessonAssessmentSubmission for new code."""
#     __tablename__ = "answers"

#     id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

#     response:    Mapped[Optional[str]]   = mapped_column(Text, nullable=True)
#     file_path:   Mapped[Optional[str]]   = mapped_column(String(500), nullable=True)
#     score:       Mapped[Optional[float]] = mapped_column(Float, nullable=True)
#     is_correct:  Mapped[Optional[bool]]  = mapped_column(Boolean, nullable=True)
#     ai_score:    Mapped[Optional[float]] = mapped_column(Float, nullable=True)
#     ai_feedback: Mapped[Optional[str]]   = mapped_column(Text, nullable=True)

#     question_id:   Mapped[int] = mapped_column(Integer, ForeignKey("questions.id"),              nullable=False)
#     submission_id: Mapped[int] = mapped_column(Integer, ForeignKey("assessment_submissions.id"), nullable=False)

#     question:   Mapped["LegacyQuestion"]            = relationship("LegacyQuestion",            back_populates="answers")
#     submission: Mapped["LegacyAssessmentSubmission"] = relationship("LegacyAssessmentSubmission", back_populates="answers")


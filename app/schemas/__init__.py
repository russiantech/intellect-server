"""
app/schemas/__init__.py
=======================
Intellect LMS — Schemas Package

Re-exports all Pydantic schemas used by the API layer.
Import from here:  from app.schemas import AssessmentCreate, QuizCreate, ...
"""

# ── Core schemas (pre-existing) ───────────────────────────────────
from app.schemas.auth import *
from app.schemas.users import *
from app.schemas.courses import *
from app.schemas.categories import *
from app.schemas.enrollments import *
from app.schemas.payments import *
from app.schemas.social import *
from app.schemas.partnerships import *
from app.schemas.common import *

# ── Assessment layer schemas (new, canonical) ─────────────────────
from app.schemas.quizzes import (
    QuizOptionCreate,
    QuizQuestionCreate,
    QuizCreate,
    QuizUpdate,
    QuizAnswerItem,
    QuizAttemptSubmit,
    TutorQuizGrade,
)

from app.schemas.lesson_assessments import (
    LessonAssessmentOptionCreate,
    LessonAssessmentQuestionCreate,
    LessonAssessmentCreate,
    LessonAssessmentUpdate,
    LessonAnswerItem,
    LessonAssessmentSubmit,
    LessonTutorGradeAnswer,
    LessonTutorGradeRequest,
)

from app.schemas.projects import (
    ProjectCreate,
    ProjectUpdate,
    ProjectSubmissionCreate,
    ProjectTutorReview,
    AttendanceRecordItem,
    AttendanceMarkRequest,
    AttendanceSelfCheckIn,
)

# ── Lesson assessment schemas (kept for backwards compat) ─────────
from app.schemas.legacy_assessments import (
    LegacyAssessmentCreate,
    LegacyAssessmentUpdate,
    LegacyAssessmentSubmit,
    LegacyTutorGradeRequest,
)

# ── Enums re-exported for convenience ────────────────────────────
from app.enums import *

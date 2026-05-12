"""Assessment schemas"""
from datetime import datetime
from typing import Optional, List, Dict
from pydantic import BaseModel
from app.enums import AssessmentType, QuestionType

class QuestionCreate(BaseModel):
    body: str
    question_type: QuestionType
    options: Optional[Dict] = None   # {"A": "...", "B": "...", "correct": "A"}
    correct_answer: Optional[str] = None
    explanation: Optional[str] = None
    marks: float = 1.0
    order_index: int = 0


class QuestionUpdate(BaseModel):
    body: Optional[str] = None
    question_type: Optional[QuestionType] = None
    options: Optional[Dict] = None
    correct_answer: Optional[str] = None
    explanation: Optional[str] = None
    marks: Optional[float] = None
    order_index: Optional[int] = None


class AssessmentCreate(BaseModel):
    title: str
    description: Optional[str] = None
    assessment_type: AssessmentType
    total_marks: float = 100.0
    pass_mark: float = 50.0
    time_limit_minutes: Optional[int] = None
    due_date: Optional[datetime] = None
    is_auto_graded: bool = True
    show_answers_after: bool = True
    attempts_allowed: int = 1
    shuffle_questions: bool = False
    course_id: Optional[int] = None
    topic_id: Optional[int] = None
    questions: List[QuestionCreate] = []


class AssessmentUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    total_marks: Optional[float] = None
    pass_mark: Optional[float] = None
    time_limit_minutes: Optional[int] = None
    due_date: Optional[datetime] = None
    is_auto_graded: Optional[bool] = None
    show_answers_after: Optional[bool] = None
    attempts_allowed: Optional[int] = None
    shuffle_questions: Optional[bool] = None


class AnswerSubmit(BaseModel):
    question_id: int
    response: Optional[str] = None


class AssessmentSubmit(BaseModel):
    assessment_id: int
    answers: List[AnswerSubmit]


class GradeSubmission(BaseModel):
    submission_id: int
    scores: Dict[int, float]  # question_id → score
    tutor_feedback: Optional[str] = None


# Alias
TutorGradeRequest = GradeSubmission


# For attendance marking & MAIN

"""
schemas/assessments_ext.py
Extended schemas for:
  - Topic-level interactive quizzes
  - Lesson-level assessments (classwork / homework)
  - Course-level project submissions
  - Attendance records
"""
from datetime import datetime
from typing import Any, List, Optional
from pydantic import BaseModel, Field


# ═══════════════════════════════════════════
#  Quiz (topic-level, inline interactive)
# ═══════════════════════════════════════════

class QuizOptionCreate(BaseModel):
    text: str
    is_correct: bool = False


class QuizQuestionCreate(BaseModel):
    body: str
    question_type: str = "mcq"          # mcq | true_false | short_answer
    options: Optional[List[QuizOptionCreate]] = None
    correct_answer: Optional[str] = None  # for true_false / short_answer
    explanation: Optional[str] = None
    marks: int = 1
    order_index: int = 0


class QuizCreate(BaseModel):
    title: str
    description: Optional[str] = None
    pass_mark_pct: int = 70             # 0-100
    shuffle_questions: bool = False
    show_answers_after: bool = True
    attempts_allowed: int = 3
    questions: List[QuizQuestionCreate] = []


class QuizSubmitAnswer(BaseModel):
    question_id: int
    response: str                        # selected option text, "True"/"False", or short text


class QuizSubmitRequest(BaseModel):
    quiz_id: int
    answers: List[QuizSubmitAnswer]


# ═══════════════════════════════════════════
#  Assessment (lesson-level)
# ═══════════════════════════════════════════

class AssessmentQuestionCreate(BaseModel):
    body: str
    question_type: str                   # mcq | true_false | short_answer | essay | file_upload
    options: Optional[List[str]] = None  # for MCQ
    correct_answer: Optional[str] = None
    explanation: Optional[str] = None
    marks: int = 1
    order_index: int = 0


class AssessmentCreate(BaseModel):
    title: str
    description: Optional[str] = None
    assessment_type: str                 # classwork | homework
    lesson_id: Optional[int] = None
    course_id: int
    total_marks: int = 10
    pass_mark: int = 5
    time_limit_minutes: Optional[int] = None
    due_date: Optional[datetime] = None
    is_auto_graded: bool = True
    show_answers_after: bool = True
    attempts_allowed: int = 1
    shuffle_questions: bool = False
    questions: List[AssessmentQuestionCreate] = []


class AssessmentUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    is_auto_graded: Optional[bool] = None
    show_answers_after: Optional[bool] = None
    attempts_allowed: Optional[int] = None
    shuffle_questions: Optional[bool] = None
    due_date: Optional[datetime] = None
    time_limit_minutes: Optional[int] = None


class AssessmentSubmitAnswer(BaseModel):
    question_id: int
    response: str


class AssessmentSubmitRequest(BaseModel):
    assessment_id: int
    answers: List[AssessmentSubmitAnswer]


class AIGradeRequest(BaseModel):
    submission_id: int


class TutorGradeAnswer(BaseModel):
    question_id: int
    score: float
    feedback: Optional[str] = None


class TutorGradeRequest(BaseModel):
    submission_id: int
    answers: List[TutorGradeAnswer]
    overall_feedback: Optional[str] = None


# ═══════════════════════════════════════════
#  Project Submission (course-level)
# ═══════════════════════════════════════════

class ProjectCreate(BaseModel):
    """Admin/creator creates a project brief for a course."""
    title: str
    description: str
    course_id: int
    due_date: Optional[datetime] = None
    max_file_size_mb: int = 50
    allowed_formats: Optional[str] = None   # e.g. "pdf,zip,docx"
    rubric: Optional[str] = None            # markdown rubric


class ProjectUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    due_date: Optional[datetime] = None
    rubric: Optional[str] = None


class ProjectReview(BaseModel):
    submission_id: int
    score: Optional[float] = None
    feedback: str
    passed: Optional[bool] = None


# ═══════════════════════════════════════════
#  Attendance
# ═══════════════════════════════════════════

class AttendanceMarkRequest(BaseModel):
    schedule_id: int
    records: List[dict]          # [{user_id, status: "present"|"absent"|"late"}]


class AttendanceSelfCheckIn(BaseModel):
    schedule_id: int
    check_in_code: str           # OTP or QR code value shown by tutor


# ═══════════════════════════════════════════
#  Text content edit
# ═══════════════════════════════════════════

class TextContentUpdate(BaseModel):
    title: Optional[str] = None
    body: Optional[str] = None

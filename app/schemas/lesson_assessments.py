"""
app/schemas/lesson_assessments.py
==================================
Pydantic request / response schemas for LessonAssessment
(classwork, homework, exam) and its submission / grading pipeline.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from app.enums import AssessmentType, QuizQuestionType


# ──────────────────────────────────────────────────────────────────
#  Questions
# ──────────────────────────────────────────────────────────────────

class LessonAssessmentOptionCreate(BaseModel):
    text:       str
    is_correct: bool = False


class LessonAssessmentQuestionCreate(BaseModel):
    body:           str
    question_type:  QuizQuestionType
    options:        Optional[List[LessonAssessmentOptionCreate]] = None
    correct_answer: Optional[str] = None
    explanation:    Optional[str] = None
    marks:          float = Field(default=1.0, ge=0)
    partial_credit: bool  = False
    order_index:    int   = 0


# ──────────────────────────────────────────────────────────────────
#  Assessment CRUD
# ──────────────────────────────────────────────────────────────────

class LessonAssessmentCreate(BaseModel):
    title:           str
    instructions:    Optional[str] = None
    assessment_type: AssessmentType
    lesson_id:       Optional[int] = None
    course_id:       int

    total_marks:        float = Field(default=10.0, ge=0)
    pass_mark:          float = Field(default=5.0,  ge=0)
    max_attempts:       int   = Field(default=1,    ge=1)
    time_limit_minutes: Optional[int] = None
    due_date:           Optional[datetime] = None

    shuffle_questions:  bool = False
    show_answers_after: bool = True
    is_auto_graded:     bool = True

    questions: List[LessonAssessmentQuestionCreate] = []


class LessonAssessmentUpdate(BaseModel):
    title:              Optional[str]   = None
    instructions:       Optional[str]   = None
    total_marks:        Optional[float] = None
    pass_mark:          Optional[float] = None
    max_attempts:       Optional[int]   = None
    time_limit_minutes: Optional[int]   = None
    due_date:           Optional[datetime] = None
    shuffle_questions:  Optional[bool]  = None
    show_answers_after: Optional[bool]  = None
    is_auto_graded:     Optional[bool]  = None
    is_active:          Optional[bool]  = None


# ──────────────────────────────────────────────────────────────────
#  Student submission
# ──────────────────────────────────────────────────────────────────

class LessonAnswerItem(BaseModel):
    question_id: int
    response:    str


class LessonAssessmentSubmit(BaseModel):
    assessment_id: int
    answers:       List[LessonAnswerItem]


# ──────────────────────────────────────────────────────────────────
#  Grading
# ──────────────────────────────────────────────────────────────────

class LessonTutorGradeAnswer(BaseModel):
    question_id: int
    score:       float
    feedback:    Optional[str] = None


class LessonTutorGradeRequest(BaseModel):
    submission_id:    int
    answers:          List[LessonTutorGradeAnswer] = []
    overall_feedback: Optional[str] = None
    score_override:   Optional[float] = None   # force total score

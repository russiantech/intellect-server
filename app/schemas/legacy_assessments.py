"""
app/schemas/legacy_assessments.py
==================================
Pydantic schemas for the legacy Assessment / Question / Answer models.

These back the existing /assessments endpoint which uses the original
"assessments" + "questions" + "assessment_submissions" + "answers" tables.

New feature code should use app/schemas/lesson_assessments.py instead.
"""
from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Optional
from pydantic import BaseModel

from app.enums import AssessmentType, QuestionType


class LegacyQuestionCreate(BaseModel):
    body:           str
    question_type:  QuestionType
    options:        Optional[Dict] = None   # {"A": "...", "B": "...", "correct": "A"}
    correct_answer: Optional[str] = None
    explanation:    Optional[str] = None
    marks:          float = 1.0
    order_index:    int   = 0


class LegacyAssessmentCreate(BaseModel):
    title:              str
    description:        Optional[str]      = None
    assessment_type:    AssessmentType
    total_marks:        float              = 100.0
    pass_mark:          float              = 50.0
    time_limit_minutes: Optional[int]      = None
    due_date:           Optional[datetime] = None
    is_auto_graded:     bool               = True
    show_answers_after: bool               = True
    attempts_allowed:   int                = 1
    shuffle_questions:  bool               = False
    course_id:          Optional[int]      = None
    topic_id:           Optional[int]      = None
    questions:          List[LegacyQuestionCreate] = []


class LegacyAssessmentUpdate(BaseModel):
    title:              Optional[str]   = None
    description:        Optional[str]   = None
    total_marks:        Optional[float] = None
    pass_mark:          Optional[float] = None
    time_limit_minutes: Optional[int]   = None
    due_date:           Optional[datetime] = None
    is_auto_graded:     Optional[bool]  = None
    show_answers_after: Optional[bool]  = None
    attempts_allowed:   Optional[int]   = None
    shuffle_questions:  Optional[bool]  = None


class LegacyAnswerSubmit(BaseModel):
    question_id: int
    response:    Optional[str] = None


class LegacyAssessmentSubmit(BaseModel):
    assessment_id: int
    answers:       List[LegacyAnswerSubmit]


class LegacyTutorGradeItem(BaseModel):
    question_id: int
    score:       float
    feedback:    Optional[str] = None


class LegacyTutorGradeRequest(BaseModel):
    submission_id:  int
    scores:         Dict[int, float]   # question_id → score
    tutor_feedback: Optional[str] = None

    # Alias used internally
    @property
    def score(self) -> float:
        return sum(self.scores.values())

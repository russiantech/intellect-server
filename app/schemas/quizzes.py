"""
app/schemas/quizzes.py
======================
Pydantic request / response schemas for the Topic-level Quiz system.

All schemas in this file are intentionally thin — the API layer owns
the response serialisation (via _serialize_quiz / _serialize_attempt helpers).
"""
from __future__ import annotations

from typing import List, Optional
from pydantic import BaseModel, Field

from app.enums import QuizQuestionType


# ──────────────────────────────────────────────────────────────────
#  Quiz CRUD
# ──────────────────────────────────────────────────────────────────

class QuizOptionCreate(BaseModel):
    text:       str
    is_correct: bool = False


class QuizQuestionCreate(BaseModel):
    body:           str
    question_type:  QuizQuestionType = QuizQuestionType.mcq
    options:        Optional[List[QuizOptionCreate]] = None
    correct_answer: Optional[str] = None
    explanation:    Optional[str] = None
    marks:          float = Field(default=1.0, ge=0)
    partial_credit: bool  = False
    order_index:    int   = 0


class QuizCreate(BaseModel):
    title:                   str   = "Topic Quiz"
    instructions:            Optional[str] = None
    pass_score:              float = Field(default=70.0, ge=0, le=100)
    max_attempts:            int   = Field(default=3, ge=0)   # 0 = unlimited
    shuffle_questions:       bool  = False
    show_correct_after:      bool  = True
    required_for_completion: bool  = False
    questions:               List[QuizQuestionCreate] = []


class QuizUpdate(BaseModel):
    title:                   Optional[str]   = None
    instructions:            Optional[str]   = None
    pass_score:              Optional[float] = None
    max_attempts:            Optional[int]   = None
    shuffle_questions:       Optional[bool]  = None
    show_correct_after:      Optional[bool]  = None
    required_for_completion: Optional[bool]  = None
    is_active:               Optional[bool]  = None


# ──────────────────────────────────────────────────────────────────
#  Quiz Attempt (student submission)
# ──────────────────────────────────────────────────────────────────

class QuizAnswerItem(BaseModel):
    question_id: int
    response: Optional[str] = None   # None for unanswered questions / supports option text, "True"/"False", or free text


class QuizAttemptSubmit(BaseModel):
    """
    Body for POST /quizzes/{quiz_id}/attempt
    quiz_id comes from the URL path, not the body.
    """
    answers: List[QuizAnswerItem]
    # REMOVE this line if it exists:
    # quiz_id: int   ← ❌ causes 422 because client doesn't send it

# ──────────────────────────────────────────────────────────
#  Tutor grading (for essay / short-answer questions)
# ──────────────────────────────────────────────────────────

class TutorGradeAttempt(BaseModel):
    attempt_id:     int
    tutor_feedback: Optional[str]  = None
    score_override: Optional[float] = None   # manual override of AI score


# ──────────────────────────────────────────────────────────────────
#  Grading overrides
# ──────────────────────────────────────────────────────────────────

class TutorQuizGrade(BaseModel):
    """Tutor override / review of AI grading on a quiz attempt."""
    overall_feedback: str
    per_question:     Optional[List[dict]] = None   # [{question_id, score, feedback}]
    score_override:   Optional[float]      = None   # override total score if needed

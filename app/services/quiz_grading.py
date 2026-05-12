"""
app/services/quiz_grading.py
=============================
Auto-grading logic for QuizAttempt and LessonAssessmentSubmission.

Extracted from the route handlers to keep routes thin and testable.

Public API
----------
auto_grade_quiz(quiz, answers)  → (score, max_score, result_detail)
auto_grade_assessment(assessment, answers) → (score, max_score, result_detail)
"""

from __future__ import annotations

import json
import logging
from typing import Optional

from app.enums import QuizQuestionType

logger = logging.getLogger(__name__)


def auto_grade_quiz(quiz, answers: dict[int, str]) -> tuple[float, float, list[dict]]:
    """
    Auto-grade a quiz attempt for MCQ, true_false, fill_blank, and multi_select.
    short_answer / essay / file_upload → deferred (is_correct=None, points_earned=0).

    Parameters
    ----------
    quiz    : Quiz ORM instance with .questions loaded
    answers : {question_id: response_string}

    Returns
    -------
    (score, max_score, result_detail)
    """
    return _grade_questions(quiz.questions, answers)


def auto_grade_assessment(assessment, answers: dict[int, str]) -> tuple[float, float, list[dict]]:
    """
    Same logic as auto_grade_quiz but operates on LessonAssessment questions.
    """
    return _grade_questions(assessment.questions, answers)


# ──────────────────────────────────────────────────────────────────
#  Internal
# ──────────────────────────────────────────────────────────────────

def _grade_questions(questions, answers: dict[int, str]) -> tuple[float, float, list[dict]]:
    score: float = 0.0
    max_score: float = 0.0
    detail: list[dict] = []

    for q in questions:
        max_score += q.marks
        response = answers.get(q.id, "").strip()
        is_correct: Optional[bool] = None
        points_earned: float = 0.0

        qt = q.question_type

        if qt == QuizQuestionType.mcq:
            correct_texts = {
                opt["text"].strip().lower()
                for opt in (q.options or [])
                if opt.get("is_correct")
            }
            is_correct = response.lower() in correct_texts
            points_earned = q.marks if is_correct else 0.0

        elif qt == QuizQuestionType.true_false:
            expected = (q.correct_answer or "").strip().lower()
            is_correct = response.lower() == expected
            points_earned = q.marks if is_correct else 0.0

        elif qt == QuizQuestionType.fill_blank:
            expected = (q.correct_answer or "").strip().lower()
            is_correct = bool(expected) and expected in response.lower()
            points_earned = q.marks if is_correct else 0.0

        elif qt == QuizQuestionType.multi_select:
            try:
                correct_set = set(json.loads(q.correct_answer or "[]"))
            except Exception:
                correct_set = set()
            chosen = {s.strip() for s in response.split(",") if s.strip()}
            if correct_set:
                if q.partial_credit:
                    overlap = len(chosen & correct_set)
                    points_earned = round(q.marks * overlap / len(correct_set), 2)
                    is_correct = overlap == len(correct_set)
                else:
                    is_correct = chosen == correct_set
                    points_earned = q.marks if is_correct else 0.0

        # short_answer / essay / file_upload → deferred to AI / tutor
        # is_correct stays None, points_earned stays 0.0

        score += points_earned
        detail.append({
            "question_id":    q.id,
            "body":           q.body,
            "question_type":  qt,
            "response":       response,
            "is_correct":     is_correct,
            "points_earned":  points_earned,
            "max_points":     q.marks,
            "correct_answer": None,   # populated by caller if show_correct_after
            "explanation":    None,
            "ai_feedback":    None,
        })

    return score, max_score, detail

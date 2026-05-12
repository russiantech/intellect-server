"""
app/services/__init__.py
========================
Service layer public API.

Import from here to avoid knowing internal file layout:
    from app.services import grade_single_answer, grade_project_submission, ...
"""

from app.services.ai_grading import (
    grade_single_answer,
    grade_question_batch,
    grade_project_submission,
    generate_quiz_questions,
    generate_assessment_questions,
)

from app.services.quiz_grading import (
    auto_grade_quiz,
    auto_grade_assessment,
)

__all__ = [
    # AI grading
    "grade_single_answer",
    "grade_question_batch",
    "grade_project_submission",
    "generate_quiz_questions",
    "generate_assessment_questions",
    # Auto grading
    "auto_grade_quiz",
    "auto_grade_assessment",
]

"""
app/services/ai_grading.py
===========================
AI grading service using Anthropic Claude.

Used by:
  - QuizAttempt AI grading  (POST /quizzes/attempt/{id}/ai-grade)
  - LessonAssessment AI grading (POST /lesson-assessments/submissions/{id}/ai-grade)
  - ProjectSubmission AI grading (POST /projects/submissions/{id}/ai-grade)
  - Legacy Assessment inline auto-grading (POST /assessments/submit)

Design
------
- All functions are synchronous (blocking); wrap in asyncio.to_thread()
  from async route handlers if you need non-blocking behaviour.
- Never raise — always return a safe fallback dict on error.
- Model default: claude-haiku-4-5-20251001  (fast, cheap, good at grading)
"""

from __future__ import annotations

import json
import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

_DEFAULT_MODEL = "claude-haiku-4-5-20251001"


# ──────────────────────────────────────────────────────────────────
#  Low-level helper: grade a single open-ended answer
# ──────────────────────────────────────────────────────────────────

def grade_single_answer(
    question_body: str,
    student_answer: str,
    max_marks: float,
    correct_answer_hint: Optional[str] = None,
    api_key: Optional[str] = None,
    model: str = _DEFAULT_MODEL,
) -> dict:
    """
    Grade one open-ended answer with Claude.

    Returns
    -------
    {
        "score":        float,   # 0 … max_marks
        "is_correct":   bool,
        "feedback":     str,
        "strengths":    str,
        "improvements": str,
    }
    On any error a safe zero-score fallback is returned — never raises.
    """
    _api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
    if not _api_key:
        return _fallback("AI grading not configured (missing ANTHROPIC_API_KEY).")

    if not student_answer or not student_answer.strip():
        return _fallback("No answer provided.", is_correct=False)

    hint_line = (
        f"\nEXPECTED ANSWER GUIDANCE: {correct_answer_hint}"
        if correct_answer_hint else ""
    )

    prompt = f"""You are an expert educational assessor. Grade the following student answer.

QUESTION: {question_body}{hint_line}

STUDENT ANSWER: {student_answer}

MAXIMUM MARKS: {max_marks}

Respond ONLY with valid JSON — no markdown, no prose outside the JSON:
{{
  "score": <number 0 to {max_marks}>,
  "feedback": "<2-3 sentence constructive feedback for the student>",
  "strengths": "<what the student did well>",
  "improvements": "<what could be improved>",
  "is_correct": <true if substantially correct, false otherwise>
}}

Award partial credit where deserved. Be fair and educational."""

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=_api_key)
        response = client.messages.create(
            model=model,
            max_tokens=512,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = response.content[0].text.strip()
        raw = _strip_fences(raw)
        result = json.loads(raw)
        score = float(result.get("score", 0))
        score = max(0.0, min(float(max_marks), score))
        return {
            "score":        score,
            "is_correct":   bool(result.get("is_correct", score >= max_marks * 0.5)),
            "feedback":     result.get("feedback", ""),
            "strengths":    result.get("strengths", ""),
            "improvements": result.get("improvements", ""),
        }
    except Exception as exc:
        logger.error("grade_single_answer failed: %s", exc)
        return _fallback("AI grading failed — manual review required.")


# ──────────────────────────────────────────────────────────────────
#  Grade a batch of questions (used by quiz & lesson assessment)
# ──────────────────────────────────────────────────────────────────

def grade_question_batch(
    items: list[dict],
    quiz_title: str = "",
    pass_score: float = 70.0,
    api_key: Optional[str] = None,
    model: str = _DEFAULT_MODEL,
) -> list[dict]:
    """
    Grade multiple open-ended questions in a single Claude call.

    items element format:
        {
            "question_id": int,
            "question_type": str,
            "body": str,
            "max_points": float,
            "response": str,
            "correct_answer": str | None,   # model answer / rubric
        }

    Returns a list in the same order as ``items``:
        {
            "question_id": int,
            "points_earned": float,
            "is_correct": bool,
            "feedback": str,
        }
    On failure returns zero-score fallbacks for each item.
    """
    _api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
    if not _api_key or not items:
        return [_batch_fallback(i) for i in items]

    items_text = "\n".join(
        f"Q{idx + 1} [{item['question_type']}] (max {item['max_points']} pts):\n"
        f"  Question: {item['body']}\n"
        f"  Model answer: {item.get('correct_answer') or 'N/A'}\n"
        f"  Student answer: {item['response']}"
        for idx, item in enumerate(items)
    )

    prompt = f"""You are grading a student quiz.

Quiz: {quiz_title}
Pass score: {pass_score}%

Questions to grade:
{items_text}

Return ONLY a valid JSON array (same order as above, no markdown):
[
  {{
    "question_id": <int>,
    "points_earned": <float 0 to max_points>,
    "is_correct": <bool>,
    "feedback": "<short explanation>"
  }},
  ...
]"""

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=_api_key)
        response = client.messages.create(
            model=model,
            max_tokens=1200,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = _strip_fences(response.content[0].text.strip())
        return json.loads(raw)
    except Exception as exc:
        logger.error("grade_question_batch failed: %s", exc)
        return [_batch_fallback(i) for i in items]


# ──────────────────────────────────────────────────────────────────
#  Grade a project submission
# ──────────────────────────────────────────────────────────────────

def grade_project_submission(
    project_title: str,
    project_description: str,
    rubric: Optional[str],
    student_note: Optional[str],
    external_url: Optional[str],
    file_name: Optional[str],
    max_score: float = 100.0,
    api_key: Optional[str] = None,
    model: str = _DEFAULT_MODEL,
) -> dict:
    """
    Grade a project submission narrative using Claude.

    Returns
    -------
    {
        "score":        float,
        "passed":       bool,
        "feedback":     str,
        "strengths":    list[str],
        "improvements": list[str],
    }
    """
    _api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
    if not _api_key:
        return _project_fallback("AI grading not configured.", max_score)

    submission_parts: list[str] = []
    if student_note:
        submission_parts.append(f"Student note:\n{student_note}")
    if external_url:
        submission_parts.append(f"External URL: {external_url}")
    if file_name:
        submission_parts.append(f"Uploaded file: {file_name}")
    if not submission_parts:
        return _project_fallback("No submission content to grade.", max_score)

    rubric_section = f"\nRUBRIC:\n{rubric}" if rubric else ""

    prompt = f"""You are grading a course project submission.

PROJECT: {project_title}
DESCRIPTION: {project_description}{rubric_section}

STUDENT SUBMISSION:
{chr(10).join(submission_parts)}

MAXIMUM SCORE: {max_score}

Respond ONLY with valid JSON — no markdown:
{{
  "score": <number 0 to {max_score}>,
  "feedback": "<paragraph of constructive feedback>",
  "strengths": ["<strength 1>", "<strength 2>", ...],
  "improvements": ["<improvement 1>", "<improvement 2>", ...]
}}

Be detailed, fair, and constructive. Award partial credit appropriately."""

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=_api_key)
        response = client.messages.create(
            model=model,
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = _strip_fences(response.content[0].text.strip())
        result = json.loads(raw)
        score = max(0.0, min(float(max_score), float(result.get("score", 0))))
        return {
            "score":        score,
            "passed":       score >= max_score * 0.5,
            "feedback":     result.get("feedback", ""),
            "strengths":    result.get("strengths", []),
            "improvements": result.get("improvements", []),
        }
    except Exception as exc:
        logger.error("grade_project_submission failed: %s", exc)
        return _project_fallback("AI grading failed — tutor review required.", max_score)


# ──────────────────────────────────────────────────────────────────
#  AI question generation
# ──────────────────────────────────────────────────────────────────

def generate_quiz_questions(
    topic_title: str,
    count: int = 5,
    question_types: str = "mcq,true_false",
    api_key: Optional[str] = None,
    model: str = _DEFAULT_MODEL,
) -> list[dict]:
    """
    Generate draft quiz questions for a topic using Claude.
    Returns a list of question dicts (not persisted).
    """
    _api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
    if not _api_key:
        return []

    types_label = question_types.replace(",", ", ")
    prompt = f"""Generate {count} quiz questions for a course topic titled: "{topic_title}".

Question types to use: {types_label}.

Return ONLY a valid JSON array — no markdown, no prose:
[
  {{
    "body": "Question stem",
    "question_type": "mcq" | "true_false" | "short_answer" | "fill_blank",
    "options": [{{"text": "...", "is_correct": true/false}}],
    "correct_answer": "...",
    "explanation": "Brief explanation shown after submission",
    "marks": 1.0
  }},
  ...
]

For true_false and non-MCQ types, omit or set options to [].
For mcq, include 4 options with exactly one is_correct=true."""

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=_api_key)
        response = client.messages.create(
            model=model,
            max_tokens=2500,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = _strip_fences(response.content[0].text.strip())
        return json.loads(raw)
    except Exception as exc:
        logger.error("generate_quiz_questions failed (topic=%s): %s", topic_title, exc)
        return []


def generate_assessment_questions(
    lesson_title: str,
    assessment_type: str,
    count: int = 10,
    question_types: str = "mcq,short_answer,essay",
    api_key: Optional[str] = None,
    model: str = _DEFAULT_MODEL,
) -> list[dict]:
    """
    Generate draft questions for a LessonAssessment using Claude.
    Returns a list of question dicts (not persisted).
    """
    _api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
    if not _api_key:
        return []

    types_label = question_types.replace(",", ", ")
    prompt = f"""Generate {count} {assessment_type} questions for a lesson titled: "{lesson_title}".

Question types to use: {types_label}.

Return ONLY a valid JSON array — no markdown, no prose:
[
  {{
    "body": "Question stem",
    "question_type": "mcq" | "true_false" | "short_answer" | "essay" | "fill_blank",
    "options": [{{"text": "...", "is_correct": true/false}}],
    "correct_answer": "...",
    "explanation": "Brief explanation",
    "marks": 1.0
  }},
  ...
]"""

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=_api_key)
        response = client.messages.create(
            model=model,
            max_tokens=3000,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = _strip_fences(response.content[0].text.strip())
        return json.loads(raw)
    except Exception as exc:
        logger.error("generate_assessment_questions failed: %s", exc)
        return []


# ──────────────────────────────────────────────────────────────────
#  Private helpers
# ──────────────────────────────────────────────────────────────────

def _strip_fences(text: str) -> str:
    """Remove markdown code fences if present."""
    if text.startswith("```"):
        parts = text.split("```")
        inner = parts[1] if len(parts) > 1 else text
        if inner.startswith("json"):
            inner = inner[4:]
        return inner.strip()
    return text


def _fallback(reason: str, is_correct: Optional[bool] = None) -> dict:
    return {
        "score":        0.0,
        "is_correct":   is_correct,
        "feedback":     reason,
        "strengths":    "",
        "improvements": "",
    }


def _batch_fallback(item: dict) -> dict:
    return {
        "question_id":   item.get("question_id"),
        "points_earned": 0.0,
        "is_correct":    None,
        "feedback":      "AI grading unavailable — manual review required.",
    }


def _project_fallback(reason: str, max_score: float) -> dict:
    return {
        "score":        0.0,
        "passed":       False,
        "feedback":     reason,
        "strengths":    [],
        "improvements": [],
    }

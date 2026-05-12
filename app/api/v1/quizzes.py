"""
app/api/v1/quizzes.py
=====================
Topic-level interactive quiz routes.

All routes are prefixed /quizzes (registered in app/api/router.py).

Grading pipeline per attempt
-----------------------------
1. POST /{quiz_id}/attempt       → auto-grades MCQ / T-F / fill_blank
                                   short_answer / essay → status=submitted
2. POST /attempt/{id}/ai-grade   → AI grades remaining open-ended questions
3. POST /attempt/{id}/tutor-grade → tutor overrides / supplements AI feedback
4. Status chain: submitted → auto_graded → ai_graded → reviewed → returned

Creator / Admin management
---------------------------
GET  /topic/{id}/manage          → get quiz with correct answers
POST /topic/{id}                 → create or replace quiz
PUT  /{quiz_id}                  → update settings / questions
DELETE /{quiz_id}                → delete quiz
POST /topic/{id}/ai-generate     → AI-generate draft questions
"""

from __future__ import annotations

import logging
import os
import random
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.deps.auth import (
    get_current_user,
    require_creator_or_admin,
)
from app.db.database import get_db
from app.enums import QuizAttemptStatus, QuizQuestionType
from app.models import Course, Enrollment, Topic, User
from app.models.quizzes import Quiz, QuizAttempt, QuizQuestion
from app.schemas.quizzes import (
    QuizCreate,
    QuizUpdate,
    QuizAttemptSubmit,
    TutorQuizGrade,
)
from app.services.ai_grading import (
    grade_question_batch,
    generate_quiz_questions,
)
from app.services.quiz_grading import auto_grade_quiz
from app.core.config import get_app_config

router = APIRouter(prefix="/quizzes", tags=["Quizzes"])
logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════
#  Serialisation helpers
# ══════════════════════════════════════════════════════════════════

def _serialize_quiz(quiz: Quiz, include_answers: bool = False) -> dict:
    """Serialise a Quiz for API responses."""
    questions = []
    for q in quiz.questions:
        qd: dict = {
            "id":             q.id,
            "body":           q.body,
            "question_type":  q.question_type,
            "marks":          q.marks,
            "partial_credit": q.partial_credit,
            "order_index":    q.order_index,
        }
        if include_answers:
            qd["options"]        = q.options or []
            qd["correct_answer"] = q.correct_answer
            qd["explanation"]    = q.explanation
        else:
            raw_opts = q.options or []
            qd["options"] = [{"text": o["text"]} for o in raw_opts]
        questions.append(qd)

    return {
        "id":                      quiz.id,
        "title":                   quiz.title,
        "instructions":            quiz.instructions,
        "topic_id":                quiz.topic_id,
        "pass_score":              quiz.pass_score,
        "max_attempts":            quiz.max_attempts,
        "shuffle_questions":       quiz.shuffle_questions,
        "show_correct_after":      quiz.show_correct_after,
        "required_for_completion": quiz.required_for_completion,
        "is_active":               quiz.is_active,
        "questions":               questions,
        "questions_count":         len(questions),
    }


def _serialize_attempt(attempt: QuizAttempt, show_detail: bool = True) -> dict:
    return {
        "id":             attempt.id,
        "quiz_id":        attempt.quiz_id,
        "user_id":        attempt.user_id,
        "score":          attempt.score,
        "max_score":      attempt.max_score,
        "pct":            attempt.pct,
        "passed":         attempt.passed,
        "status":         attempt.status,
        "attempt_number": attempt.attempt_number,
        "ai_feedback":    attempt.ai_feedback,
        "tutor_feedback": attempt.tutor_feedback,
        "submitted_at":   attempt.submitted_at,
        "graded_at":      attempt.graded_at,
        "result_detail":  attempt.result_detail if show_detail else None,
    }


# ══════════════════════════════════════════════════════════════════
#  Auth / access helpers
# ══════════════════════════════════════════════════════════════════

def _require_enrollment(topic: Topic, user: User, db: Session) -> None:
    if topic.is_free_preview or user.is_admin():
        return
    course = db.query(Course).filter(Course.id == topic.course_id).first()
    if course and course.creator_id == user.id:
        return
    enrolled = db.query(Enrollment).filter(
        Enrollment.user_id == user.id,
        Enrollment.course_id == topic.course_id,
    ).first()
    if not enrolled:
        raise HTTPException(403, "Enrollment required to access this quiz")


def _can_manage(quiz: Quiz, user: User, db: Session) -> bool:
    if user.is_admin():
        return True
    course = db.query(Course).filter(Course.id == quiz.course_id).first()
    return bool(course and course.creator_id == user.id)


# ══════════════════════════════════════════════════════════════════
#  Student Routes
# ══════════════════════════════════════════════════════════════════

@router.get("/topic/{topic_id}", summary="Get quiz for a topic (student)")
async def get_topic_quiz(
    topic_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Return the active quiz for a topic with previous attempt summary.
    Correct answers are never sent to students.
    Questions shuffled server-side when quiz.shuffle_questions=True.
    """
    topic = db.query(Topic).filter(Topic.id == topic_id).first()
    if not topic:
        raise HTTPException(404, "Topic not found")
    _require_enrollment(topic, user, db)

    quiz = db.query(Quiz).filter(
        Quiz.topic_id == topic_id, Quiz.is_active == True
    ).first()
    if not quiz:
        return {"quiz": None}

    data = _serialize_quiz(quiz, include_answers=False)
    if quiz.shuffle_questions:
        random.shuffle(data["questions"])

    attempts = (
        db.query(QuizAttempt)
        .filter(QuizAttempt.quiz_id == quiz.id, QuizAttempt.user_id == user.id)
        .order_by(QuizAttempt.attempt_number.desc())
        .all()
    )
    latest = attempts[0] if attempts else None
    data["attempts_used"]    = len(attempts)
    data["attempts_allowed"] = quiz.max_attempts
    data["previous_attempt"] = (
        {
            "attempt_number": latest.attempt_number,
            "score":          latest.score,
            "pct":            latest.pct,
            "passed":         latest.passed,
            "status":         latest.status,
            "submitted_at":   latest.submitted_at,
        }
        if latest else None
    )
    return {"quiz": data}


@router.post("/{quiz_id}/attempt", status_code=201, summary="Submit a quiz attempt")
async def submit_quiz_attempt(
    quiz_id: int,
    payload: QuizAttemptSubmit,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Accept student answers, auto-grade MCQ/T-F/fill_blank, persist attempt.
    short_answer / essay answers are saved but left for AI or tutor grading.
    """
    quiz = db.query(Quiz).filter(Quiz.id == quiz_id, Quiz.is_active == True).first()
    if not quiz:
        raise HTTPException(404, "Quiz not found")

    topic = db.query(Topic).filter(Topic.id == quiz.topic_id).first()
    _require_enrollment(topic, user, db)

    prev_count = (
        db.query(QuizAttempt)
        .filter(QuizAttempt.quiz_id == quiz_id, QuizAttempt.user_id == user.id)
        .count()
    )
    if quiz.max_attempts > 0 and prev_count >= quiz.max_attempts:
        raise HTTPException(403, f"Maximum attempts ({quiz.max_attempts}) reached for this quiz.")

    answer_map = {a.question_id: a.response for a in payload.answers}
    score, max_score, detail = auto_grade_quiz(quiz, answer_map)

    needs_human_review = False
    for row in detail:
        q = next((q for q in quiz.questions if q.id == row["question_id"]), None)
        if q is None:
            continue
        if quiz.show_correct_after:
            row["correct_answer"] = q.correct_answer
            row["explanation"]    = q.explanation
        if row["is_correct"] is None:
            needs_human_review = True

    pct    = round(score / max_score * 100, 1) if max_score else 0.0
    passed = pct >= quiz.pass_score

    if needs_human_review:
        status = QuizAttemptStatus.submitted
    elif quiz.show_correct_after:
        status = QuizAttemptStatus.returned
    else:
        status = QuizAttemptStatus.auto_graded

    attempt = QuizAttempt(
        quiz_id=quiz_id,
        user_id=user.id,
        answers=answer_map,
        score=score,
        max_score=max_score,
        pct=pct,
        passed=passed,
        result_detail=detail,
        status=status,
        attempt_number=prev_count + 1,
        submitted_at=datetime.now(timezone.utc),
        graded_at=datetime.now(timezone.utc) if not needs_human_review else None,
    )
    db.add(attempt)
    db.commit()
    db.refresh(attempt)
    return _serialize_attempt(attempt, show_detail=quiz.show_correct_after)


@router.get("/attempt/{attempt_id}", summary="Get a specific attempt (owner or staff)")
async def get_attempt(
    attempt_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    attempt = db.query(QuizAttempt).filter(QuizAttempt.id == attempt_id).first()
    if not attempt:
        raise HTTPException(404, "Attempt not found")
    quiz     = db.query(Quiz).filter(Quiz.id == attempt.quiz_id).first()
    is_owner = attempt.user_id == user.id
    is_staff = _can_manage(quiz, user, db)
    if not is_owner and not is_staff:
        raise HTTPException(403, "Access denied")
    return _serialize_attempt(attempt, show_detail=is_staff or quiz.show_correct_after)


# ══════════════════════════════════════════════════════════════════
#  AI Grading Route
# ══════════════════════════════════════════════════════════════════

@router.post("/attempt/{attempt_id}/ai-grade", summary="AI-grade short_answer / essay questions")
async def ai_grade_attempt(
    attempt_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Use Claude Haiku to grade open-ended questions in an attempt.
    Requires ANTHROPIC_API_KEY.  Only owner or quiz staff can trigger.
    """
    attempt = db.query(QuizAttempt).filter(QuizAttempt.id == attempt_id).first()
    if not attempt:
        raise HTTPException(404, "Attempt not found")
    quiz     = db.query(Quiz).filter(Quiz.id == attempt.quiz_id).first()
    is_owner = attempt.user_id == user.id
    if not is_owner and not _can_manage(quiz, user, db):
        raise HTTPException(403, "Access denied")

    detail = attempt.result_detail or []
    q_map  = {q.id: q for q in quiz.questions}

    pending_types = {
        QuizQuestionType.short_answer,
        QuizQuestionType.essay,
        QuizQuestionType.fill_blank,
    }
    pending = [
        row for row in detail
        if row.get("is_correct") is None
        and row.get("question_type") in pending_types
    ]
    if not pending:
        return {"message": "No questions require AI grading", "attempt": _serialize_attempt(attempt)}

    items = [
        {
            "question_id":   row["question_id"],
            "question_type": row["question_type"],
            "body":          row["body"],
            "max_points":    row["max_points"],
            "response":      row["response"],
            "correct_answer": q_map[row["question_id"]].correct_answer
                              if row["question_id"] in q_map else None,
        }
        for row in pending
    ]

    cfg     = get_app_config()
    api_key = getattr(cfg.ai_config, "anthropic_api_key", "") or os.environ.get("ANTHROPIC_API_KEY", "")

    ai_results = grade_question_batch(
        items=items,
        quiz_title=quiz.title,
        pass_score=quiz.pass_score,
        api_key=api_key,
    )

    if not ai_results:
        raise HTTPException(502, "AI grading unavailable — please grade manually")

    ai_map     = {r["question_id"]: r for r in ai_results}
    extra_score = 0.0
    for row in detail:
        ai = ai_map.get(row["question_id"])
        if ai:
            row["points_earned"] = ai["points_earned"]
            row["is_correct"]    = ai["is_correct"]
            row["ai_feedback"]   = ai.get("feedback", "")
            extra_score         += ai["points_earned"]

    new_score = (attempt.score or 0.0) + extra_score
    new_pct   = round(new_score / (attempt.max_score or 1) * 100, 1)

    attempt.result_detail = detail
    attempt.score         = new_score
    attempt.pct           = new_pct
    attempt.passed        = new_pct >= quiz.pass_score
    attempt.status        = QuizAttemptStatus.ai_graded
    attempt.graded_at     = datetime.now(timezone.utc)
    db.commit()
    db.refresh(attempt)
    return _serialize_attempt(attempt)


# ══════════════════════════════════════════════════════════════════
#  Tutor / Admin Routes
# ══════════════════════════════════════════════════════════════════

@router.post("/attempt/{attempt_id}/tutor-grade", summary="Tutor override / review AI grade")
async def tutor_grade_attempt(
    attempt_id: int,
    payload: TutorQuizGrade,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    attempt = db.query(QuizAttempt).filter(QuizAttempt.id == attempt_id).first()
    if not attempt:
        raise HTTPException(404, "Attempt not found")
    quiz = db.query(Quiz).filter(Quiz.id == attempt.quiz_id).first()
    if not _can_manage(quiz, user, db):
        raise HTTPException(403, "Access denied")

    if payload.per_question:
        detail         = attempt.result_detail or []
        q_override_map = {item["question_id"]: item for item in payload.per_question}
        for row in detail:
            override = q_override_map.get(row["question_id"])
            if override:
                row["points_earned"]  = override.get("score", row["points_earned"])
                row["tutor_feedback"] = override.get("feedback", "")
                row["is_correct"]     = row["points_earned"] >= row["max_points"]
        attempt.result_detail = detail
        attempt.score         = sum(r.get("points_earned", 0.0) for r in detail)
    elif payload.score_override is not None:
        attempt.score = payload.score_override

    if attempt.score is not None and attempt.max_score:
        attempt.pct    = round(attempt.score / attempt.max_score * 100, 1)
        attempt.passed = attempt.pct >= quiz.pass_score

    attempt.tutor_feedback = payload.overall_feedback
    attempt.status         = QuizAttemptStatus.returned
    attempt.graded_at      = datetime.now(timezone.utc)
    db.commit()
    db.refresh(attempt)
    return _serialize_attempt(attempt)


@router.get("/{quiz_id}/attempts", summary="List all attempts for a quiz (staff only)")
async def list_quiz_attempts(
    quiz_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    quiz = db.query(Quiz).filter(Quiz.id == quiz_id).first()
    if not quiz:
        raise HTTPException(404, "Quiz not found")
    if not _can_manage(quiz, user, db):
        raise HTTPException(403, "Access denied")
    attempts = (
        db.query(QuizAttempt)
        .filter(QuizAttempt.quiz_id == quiz_id)
        .order_by(QuizAttempt.user_id, QuizAttempt.attempt_number)
        .all()
    )
    return [_serialize_attempt(a) for a in attempts]


# ══════════════════════════════════════════════════════════════════
#  Creator / Admin CRUD
# ══════════════════════════════════════════════════════════════════

@router.get("/topic/{topic_id}/manage", summary="Get quiz with answers (creator/admin)")
async def get_topic_quiz_for_creator(
    topic_id: int,
    user: User = Depends(require_creator_or_admin),
    db: Session = Depends(get_db),
):
    topic = db.query(Topic).filter(Topic.id == topic_id).first()
    if not topic:
        raise HTTPException(404, "Topic not found")
    quiz = db.query(Quiz).filter(Quiz.topic_id == topic_id).first()
    return {"quiz": _serialize_quiz(quiz, include_answers=True) if quiz else None}


@router.post("/topic/{topic_id}", status_code=201, summary="Create or replace quiz for a topic")
async def create_topic_quiz(
    topic_id: int,
    payload: QuizCreate,
    user: User = Depends(require_creator_or_admin),
    db: Session = Depends(get_db),
):
    topic = db.query(Topic).filter(Topic.id == topic_id).first()
    if not topic:
        raise HTTPException(404, "Topic not found")
    course = db.query(Course).filter(Course.id == topic.course_id).first()
    if not user.is_admin() and course.creator_id != user.id:
        raise HTTPException(403, "Access denied")

    existing = db.query(Quiz).filter(Quiz.topic_id == topic_id).first()
    if existing:
        existing.is_active = False
        db.flush()

    quiz = Quiz(
        title=payload.title,
        instructions=payload.instructions,
        topic_id=topic_id,
        course_id=topic.course_id,
        pass_score=payload.pass_score,
        max_attempts=payload.max_attempts,
        shuffle_questions=payload.shuffle_questions,
        show_correct_after=payload.show_correct_after,
        required_for_completion=payload.required_for_completion,
    )
    db.add(quiz)
    db.flush()

    for i, q in enumerate(payload.questions):
        opts = (
            [{"text": o.text, "is_correct": o.is_correct} for o in q.options]
            if q.options else None
        )
        db.add(QuizQuestion(
            quiz_id=quiz.id,
            body=q.body,
            question_type=q.question_type,
            options=opts,
            correct_answer=q.correct_answer,
            explanation=q.explanation,
            marks=q.marks,
            partial_credit=q.partial_credit,
            order_index=q.order_index if q.order_index is not None else i,
        ))

    db.commit()
    db.refresh(quiz)
    return _serialize_quiz(quiz, include_answers=True)


@router.put("/{quiz_id}", summary="Update quiz settings and questions (creator/admin)")
async def update_quiz(
    quiz_id: int,
    payload: QuizCreate,
    user: User = Depends(require_creator_or_admin),
    db: Session = Depends(get_db),
):
    quiz = db.query(Quiz).filter(Quiz.id == quiz_id).first()
    if not quiz:
        raise HTTPException(404, "Quiz not found")
    if not _can_manage(quiz, user, db):
        raise HTTPException(403, "Access denied")

    quiz.title                   = payload.title
    quiz.instructions            = payload.instructions
    quiz.pass_score              = payload.pass_score
    quiz.max_attempts            = payload.max_attempts
    quiz.shuffle_questions       = payload.shuffle_questions
    quiz.show_correct_after      = payload.show_correct_after
    quiz.required_for_completion = payload.required_for_completion

    db.query(QuizQuestion).filter(QuizQuestion.quiz_id == quiz_id).delete()
    for i, q in enumerate(payload.questions):
        opts = (
            [{"text": o.text, "is_correct": o.is_correct} for o in q.options]
            if q.options else None
        )
        db.add(QuizQuestion(
            quiz_id=quiz_id,
            body=q.body,
            question_type=q.question_type,
            options=opts,
            correct_answer=q.correct_answer,
            explanation=q.explanation,
            marks=q.marks,
            partial_credit=q.partial_credit,
            order_index=q.order_index if q.order_index is not None else i,
        ))

    db.commit()
    db.refresh(quiz)
    return _serialize_quiz(quiz, include_answers=True)


@router.delete("/{quiz_id}", summary="Delete a quiz (creator/admin)")
async def delete_quiz(
    quiz_id: int,
    user: User = Depends(require_creator_or_admin),
    db: Session = Depends(get_db),
):
    quiz = db.query(Quiz).filter(Quiz.id == quiz_id).first()
    if not quiz:
        raise HTTPException(404, "Quiz not found")
    if not _can_manage(quiz, user, db):
        raise HTTPException(403, "Access denied")
    db.delete(quiz)
    db.commit()
    return {"message": "Quiz deleted"}


# ══════════════════════════════════════════════════════════════════
#  AI Question Generation
# ══════════════════════════════════════════════════════════════════

@router.post("/topic/{topic_id}/ai-generate", summary="AI-generate quiz questions (creator/admin)")
async def ai_generate_questions(
    topic_id: int,
    count: int = Query(5, ge=1, le=20),
    question_types: str = Query("mcq,true_false"),
    user: User = Depends(require_creator_or_admin),
    db: Session = Depends(get_db),
):
    """
    Use Claude Haiku to generate draft questions for a topic.
    Returns raw question objects — nothing is persisted here.
    """
    topic = db.query(Topic).filter(Topic.id == topic_id).first()
    if not topic:
        raise HTTPException(404, "Topic not found")

    cfg     = get_app_config()
    api_key = getattr(cfg.ai_config, "anthropic_api_key", "") or os.environ.get("ANTHROPIC_API_KEY", "")

    questions = generate_quiz_questions(
        topic_title=topic.title,
        count=count,
        question_types=question_types,
        api_key=api_key,
    )
    if not questions:
        raise HTTPException(502, "AI generation failed — add questions manually")
    return {"questions": questions, "count": len(questions)}

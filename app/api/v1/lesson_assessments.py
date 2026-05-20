# """
# app/api/v1/lesson_assessments.py
# =================================
# Lesson-level assessment routes (classwork, homework, exams).

# All routes are prefixed /lesson-assessments.

# Endpoints
# ---------
# Student
#   GET  /lesson/{lesson_id}                    – list active assessments for a lesson
#   GET  /{assessment_id}                       – get assessment (strips answers)
#   POST /{assessment_id}/submit                – submit answers
#   GET  /submissions/my                        – student's own submissions
#   GET  /submissions/{submission_id}           – detail view of one submission

# AI grading
#   POST /submissions/{submission_id}/ai-grade  – AI grades open-ended questions

# Tutor / Admin
#   POST /submissions/{submission_id}/tutor-grade – tutor override
#   GET  /course/{course_id}/submissions         – all submissions for a course

# Creator / Admin CRUD
#   POST /                                      – create assessment
#   PUT  /{assessment_id}                       – update settings (replaces questions)
#   DELETE /{assessment_id}                     – soft-delete
#   POST /{assessment_id}/ai-generate-questions – AI-generate questions
# """

# from __future__ import annotations

# import logging
# import os
# import random
# from datetime import datetime, timezone
# from typing import Optional

# from fastapi import APIRouter, Depends, HTTPException, Query
# from sqlalchemy.orm import Session

# from app.api.deps.auth import (
#     get_current_user,
#     require_tutor_or_admin,
#     require_creator_or_admin,
# )
# from app.core.config import get_app_config
# from app.db.database import get_db
# from app.enums import SubmissionStatus, QuizQuestionType
# from app.models import Course, Enrollment, Lesson, User
# from app.models.quizzes import (
#     LessonAssessment,
#     LessonAssessmentQuestion,
#     LessonAssessmentSubmission,
# )
# from app.schemas.lesson_assessments import (
#     LessonAssessmentCreate,
#     LessonAssessmentUpdate,
#     LessonAssessmentSubmit,
#     LessonTutorGradeRequest,
# )
# from app.services.ai_grading import (
#     grade_question_batch,
#     generate_assessment_questions,
# )
# from app.services.quiz_grading import auto_grade_assessment

# router = APIRouter(prefix="/lesson-assessments", tags=["Lesson Assessments"])
# logger = logging.getLogger(__name__)


# # ══════════════════════════════════════════════════════════════════
# #  Serialisation helpers
# # ══════════════════════════════════════════════════════════════════

# def _serialize_assessment(a: LessonAssessment, include_answers: bool = False) -> dict:
#     questions = []
#     for q in a.questions:
#         qd: dict = {
#             "id":             q.id,
#             "body":           q.body,
#             "question_type":  q.question_type,
#             "marks":          q.marks,
#             "partial_credit": q.partial_credit,
#             "order_index":    q.order_index,
#         }
#         if include_answers:
#             qd["options"]        = q.options or []
#             qd["correct_answer"] = q.correct_answer
#             qd["explanation"]    = q.explanation
#         else:
#             raw = q.options or []
#             qd["options"] = [{"text": o["text"]} for o in raw]
#         questions.append(qd)

#     return {
#         "id":                  a.id,
#         "title":               a.title,
#         "instructions":        a.instructions,
#         "assessment_type":     a.assessment_type,
#         "lesson_id":           a.lesson_id,
#         "course_id":           a.course_id,
#         "total_marks":         a.total_marks,
#         "pass_mark":           a.pass_mark,
#         "max_attempts":        a.max_attempts,
#         "time_limit_minutes":  a.time_limit_minutes,
#         "due_date":            a.due_date,
#         "shuffle_questions":   a.shuffle_questions,
#         "show_answers_after":  a.show_answers_after,
#         "is_auto_graded":      a.is_auto_graded,
#         "is_active":           a.is_active,
#         "questions":           questions,
#         "questions_count":     len(questions),
#     }


# def _serialize_submission(sub: LessonAssessmentSubmission, show_detail: bool = True) -> dict:
#     return {
#         "id":             sub.id,
#         "assessment_id":  sub.assessment_id,
#         "user_id":        sub.user_id,
#         "score":          sub.score,
#         "max_score":      sub.max_score,
#         "percentage":     sub.percentage,
#         "passed":         sub.passed,
#         "status":         sub.status,
#         "attempt_number": sub.attempt_number,
#         "ai_feedback":    sub.ai_feedback,
#         "tutor_feedback": sub.tutor_feedback,
#         "submitted_at":   sub.submitted_at,
#         "graded_at":      sub.graded_at,
#         "result_detail":  sub.result_detail if show_detail else None,
#     }


# # ══════════════════════════════════════════════════════════════════
# #  Access helpers
# # ══════════════════════════════════════════════════════════════════

# def _is_staff(assessment: LessonAssessment, user: User, db: Session) -> bool:
#     if user.is_admin():
#         return True
#     course = db.query(Course).filter(Course.id == assessment.course_id).first()
#     return bool(course and course.creator_id == user.id)


# def _get_api_key(cfg) -> str:
#     return getattr(cfg.ai_config, "anthropic_api_key", "") or os.environ.get("ANTHROPIC_API_KEY", "")


# # ══════════════════════════════════════════════════════════════════
# #  Student Routes
# # ══════════════════════════════════════════════════════════════════

# @router.get("/lesson/{lesson_id}", summary="List assessments for a lesson (student)")
# async def get_lesson_assessments(
#     lesson_id: int,
#     user: User = Depends(get_current_user),
#     db: Session = Depends(get_db),
# ):
#     """Return active assessments for the given lesson (answers stripped for students)."""
#     lesson = db.query(Lesson).filter(Lesson.id == lesson_id).first()
#     if not lesson:
#         raise HTTPException(404, "Lesson not found")

#     assessments = (
#         db.query(LessonAssessment)
#         .filter(
#             LessonAssessment.lesson_id == lesson_id,
#             LessonAssessment.is_active == True,
#         )
#         .all()
#     )

#     is_privileged = user.is_admin() or user.has_role("tutor")
#     return [_serialize_assessment(a, include_answers=is_privileged) for a in assessments]


# @router.get("/{assessment_id}", summary="Get assessment detail (student)")
# async def get_assessment(
#     assessment_id: int,
#     user: User = Depends(get_current_user),
#     db: Session = Depends(get_db),
# ):
#     a = db.query(LessonAssessment).filter(LessonAssessment.id == assessment_id).first()
#     if not a:
#         raise HTTPException(404, "Assessment not found")
#     is_privileged = _is_staff(a, user, db)
#     data = _serialize_assessment(a, include_answers=is_privileged)
#     if a.shuffle_questions and not is_privileged:
#         random.shuffle(data["questions"])
#     return data


# @router.post("/{assessment_id}/submit", status_code=201, summary="Submit assessment answers")
# async def submit_assessment(
#     assessment_id: int,
#     payload: LessonAssessmentSubmit,
#     user: User = Depends(get_current_user),
#     db: Session = Depends(get_db),
# ):
#     """
#     Accept answers, auto-grade MCQ/T-F/fill_blank, optionally trigger AI
#     grading for open-ended questions if is_auto_graded=True.
#     """
#     a = db.query(LessonAssessment).filter(
#         LessonAssessment.id == assessment_id,
#         LessonAssessment.is_active == True,
#     ).first()
#     if not a:
#         raise HTTPException(404, "Assessment not found")

#     # Check attempt limit
#     prev_count = db.query(LessonAssessmentSubmission).filter(
#         LessonAssessmentSubmission.assessment_id == assessment_id,
#         LessonAssessmentSubmission.user_id == user.id,
#     ).count()
#     if prev_count >= a.max_attempts:
#         raise HTTPException(403, f"Maximum attempts ({a.max_attempts}) reached.")

#     # Check due date
#     if a.due_date and datetime.now(timezone.utc) > a.due_date:
#         raise HTTPException(400, "Submission deadline has passed.")

#     answer_map = {ans.question_id: ans.response for ans in payload.answers}
#     score, max_score, detail = auto_grade_assessment(a, answer_map)

#     needs_open = any(row["is_correct"] is None for row in detail)

#     if a.show_answers_after:
#         q_map = {q.id: q for q in a.questions}
#         for row in detail:
#             q = q_map.get(row["question_id"])
#             if q:
#                 row["correct_answer"] = q.correct_answer
#                 row["explanation"]    = q.explanation

#     percentage = round(score / max_score * 100, 1) if max_score else 0.0
#     passed     = percentage >= a.pass_mark

#     # Inline AI grading for open-ended if auto-graded
#     if needs_open and a.is_auto_graded:
#         cfg     = get_app_config()
#         api_key = _get_api_key(cfg)
#         q_map   = {q.id: q for q in a.questions}
#         items   = [
#             {
#                 "question_id":   row["question_id"],
#                 "question_type": row["question_type"],
#                 "body":          row["body"],
#                 "max_points":    row["max_points"],
#                 "response":      row["response"],
#                 "correct_answer": q_map[row["question_id"]].correct_answer
#                                   if row["question_id"] in q_map else None,
#             }
#             for row in detail
#             if row["is_correct"] is None
#         ]
#         ai_results = grade_question_batch(
#             items=items,
#             quiz_title=a.title,
#             pass_score=a.pass_mark / a.total_marks * 100 if a.total_marks else 70,
#             api_key=api_key,
#         )
#         ai_map = {r["question_id"]: r for r in ai_results}
#         for row in detail:
#             ai = ai_map.get(row["question_id"])
#             if ai:
#                 row["points_earned"] = ai["points_earned"]
#                 row["is_correct"]    = ai["is_correct"]
#                 row["ai_feedback"]   = ai.get("feedback", "")
#                 score               += ai["points_earned"]

#         percentage = round(score / max_score * 100, 1) if max_score else 0.0
#         passed     = percentage >= a.pass_mark
#         status     = SubmissionStatus.ai_graded
#     else:
#         status = SubmissionStatus.reviewing if needs_open else SubmissionStatus.returned

#     sub = LessonAssessmentSubmission(
#         assessment_id=assessment_id,
#         user_id=user.id,
#         answers=answer_map,
#         score=score,
#         max_score=max_score,
#         percentage=percentage,
#         passed=passed,
#         result_detail=detail,
#         status=status,
#         attempt_number=prev_count + 1,
#         submitted_at=datetime.now(timezone.utc),
#         graded_at=datetime.now(timezone.utc) if not needs_open else None,
#     )
#     db.add(sub)
#     db.commit()
#     db.refresh(sub)
#     return _serialize_submission(sub, show_detail=a.show_answers_after)


# @router.get("/submissions/my", summary="My submissions")
# async def my_submissions(
#     course_id: Optional[int] = None,
#     assessment_type: Optional[str] = None,
#     user: User = Depends(get_current_user),
#     db: Session = Depends(get_db),
# ):
#     q = db.query(LessonAssessmentSubmission).filter(
#         LessonAssessmentSubmission.user_id == user.id
#     )
#     if course_id:
#         q = q.join(LessonAssessmentSubmission.assessment).filter(
#             LessonAssessment.course_id == course_id
#         )
#     if assessment_type:
#         q = q.join(LessonAssessmentSubmission.assessment).filter(
#             LessonAssessment.assessment_type == assessment_type
#         )
#     subs = q.order_by(LessonAssessmentSubmission.submitted_at.desc()).all()
#     return [_serialize_submission(s, show_detail=False) for s in subs]


# @router.get("/submissions/{submission_id}", summary="Get submission detail")
# async def get_submission(
#     submission_id: int,
#     user: User = Depends(get_current_user),
#     db: Session = Depends(get_db),
# ):
#     sub = db.query(LessonAssessmentSubmission).filter(
#         LessonAssessmentSubmission.id == submission_id
#     ).first()
#     if not sub:
#         raise HTTPException(404, "Submission not found")
#     a        = db.query(LessonAssessment).filter(LessonAssessment.id == sub.assessment_id).first()
#     is_owner = sub.user_id == user.id
#     is_staff = _is_staff(a, user, db)
#     if not is_owner and not is_staff:
#         raise HTTPException(403, "Access denied")
#     show = is_staff or (a.show_answers_after and sub.status in (
#         SubmissionStatus.ai_graded, SubmissionStatus.returned
#     ))
#     return _serialize_submission(sub, show_detail=show)


# # ══════════════════════════════════════════════════════════════════
# #  AI Grading
# # ══════════════════════════════════════════════════════════════════

# @router.post("/submissions/{submission_id}/ai-grade", summary="AI-grade open-ended answers")
# async def ai_grade_submission(
#     submission_id: int,
#     user: User = Depends(get_current_user),
#     db: Session = Depends(get_db),
# ):
#     """
#     (Re-)run AI grading on all unanswered open-ended questions.
#     Only owner or staff can trigger.
#     """
#     sub = db.query(LessonAssessmentSubmission).filter(
#         LessonAssessmentSubmission.id == submission_id
#     ).first()
#     if not sub:
#         raise HTTPException(404, "Submission not found")
#     a = db.query(LessonAssessment).filter(LessonAssessment.id == sub.assessment_id).first()
#     is_owner = sub.user_id == user.id
#     if not is_owner and not _is_staff(a, user, db):
#         raise HTTPException(403, "Access denied")

#     detail = sub.result_detail or []
#     q_map  = {q.id: q for q in a.questions}
#     pending = [
#         row for row in detail
#         if row.get("is_correct") is None
#     ]
#     if not pending:
#         return {"message": "No questions require AI grading", "submission": _serialize_submission(sub)}

#     cfg     = get_app_config()
#     api_key = _get_api_key(cfg)
#     items   = [
#         {
#             "question_id":   row["question_id"],
#             "question_type": row["question_type"],
#             "body":          row["body"],
#             "max_points":    row["max_points"],
#             "response":      row["response"],
#             "correct_answer": q_map[row["question_id"]].correct_answer
#                               if row["question_id"] in q_map else None,
#         }
#         for row in pending
#     ]

#     ai_results = grade_question_batch(
#         items=items,
#         quiz_title=a.title,
#         pass_score=a.pass_mark / a.total_marks * 100 if a.total_marks else 70,
#         api_key=api_key,
#     )
#     if not ai_results:
#         raise HTTPException(502, "AI grading unavailable — please grade manually")

#     ai_map      = {r["question_id"]: r for r in ai_results}
#     extra_score = 0.0
#     for row in detail:
#         ai = ai_map.get(row["question_id"])
#         if ai:
#             row["points_earned"] = ai["points_earned"]
#             row["is_correct"]    = ai["is_correct"]
#             row["ai_feedback"]   = ai.get("feedback", "")
#             extra_score         += ai["points_earned"]

#     new_score  = (sub.score or 0.0) + extra_score
#     new_pct    = round(new_score / (sub.max_score or 1) * 100, 1)
#     sub.result_detail = detail
#     sub.score         = new_score
#     sub.percentage    = new_pct
#     sub.passed        = new_pct >= a.pass_mark
#     sub.status        = SubmissionStatus.ai_graded
#     sub.graded_at     = datetime.now(timezone.utc)
#     db.commit()
#     db.refresh(sub)
#     return _serialize_submission(sub)


# # ══════════════════════════════════════════════════════════════════
# #  Tutor / Admin Routes
# # ══════════════════════════════════════════════════════════════════

# @router.post("/submissions/{submission_id}/tutor-grade", summary="Tutor override / review")
# async def tutor_grade_submission(
#     submission_id: int,
#     payload: LessonTutorGradeRequest,
#     user: User = Depends(get_current_user),
#     db: Session = Depends(get_db),
# ):
#     sub = db.query(LessonAssessmentSubmission).filter(
#         LessonAssessmentSubmission.id == submission_id
#     ).first()
#     if not sub:
#         raise HTTPException(404, "Submission not found")
#     a = db.query(LessonAssessment).filter(LessonAssessment.id == sub.assessment_id).first()
#     if not _is_staff(a, user, db):
#         raise HTTPException(403, "Access denied")

#     if payload.answers:
#         detail = sub.result_detail or []
#         q_override = {item.question_id: item for item in payload.answers}
#         for row in detail:
#             override = q_override.get(row["question_id"])
#             if override:
#                 row["points_earned"]  = override.score
#                 row["tutor_feedback"] = override.feedback or ""
#                 row["is_correct"]     = override.score >= row["max_points"]
#         sub.result_detail = detail
#         sub.score         = sum(r.get("points_earned", 0.0) for r in detail)
#     elif payload.score_override is not None:
#         sub.score = payload.score_override

#     if sub.score is not None and sub.max_score:
#         sub.percentage = round(sub.score / sub.max_score * 100, 1)
#         sub.passed     = sub.percentage >= a.pass_mark

#     sub.tutor_feedback = payload.overall_feedback
#     sub.graded_by_id   = user.id
#     sub.status         = SubmissionStatus.returned
#     sub.graded_at      = datetime.now(timezone.utc)
#     db.commit()
#     db.refresh(sub)
#     return _serialize_submission(sub)


# @router.get("/course/{course_id}/submissions", summary="All submissions for a course (staff)")
# async def get_course_submissions(
#     course_id: int,
#     assessment_type: Optional[str] = None,
#     status: Optional[str] = None,
#     user: User = Depends(require_tutor_or_admin),
#     db: Session = Depends(get_db),
# ):
#     q = db.query(LessonAssessmentSubmission).join(
#         LessonAssessment,
#         LessonAssessmentSubmission.assessment_id == LessonAssessment.id,
#     ).filter(LessonAssessment.course_id == course_id)

#     if assessment_type:
#         q = q.filter(LessonAssessment.assessment_type == assessment_type)
#     if status:
#         q = q.filter(LessonAssessmentSubmission.status == status)

#     subs = q.order_by(LessonAssessmentSubmission.submitted_at.desc()).all()
#     return [_serialize_submission(s) for s in subs]


# # ══════════════════════════════════════════════════════════════════
# #  Creator / Admin CRUD
# # ══════════════════════════════════════════════════════════════════

# @router.post("/", status_code=201, summary="Create assessment (creator/admin)")
# async def create_assessment(
#     payload: LessonAssessmentCreate,
#     user: User = Depends(require_creator_or_admin),
#     db: Session = Depends(get_db),
# ):
#     course = db.query(Course).filter(Course.id == payload.course_id).first()
#     if not course:
#         raise HTTPException(404, "Course not found")
#     if not user.is_admin() and course.creator_id != user.id:
#         raise HTTPException(403, "Access denied")

#     a = LessonAssessment(
#         title=payload.title,
#         instructions=payload.instructions,
#         assessment_type=payload.assessment_type,
#         lesson_id=payload.lesson_id,
#         course_id=payload.course_id,
#         total_marks=payload.total_marks,
#         pass_mark=payload.pass_mark,
#         max_attempts=payload.max_attempts,
#         time_limit_minutes=payload.time_limit_minutes,
#         due_date=payload.due_date,
#         shuffle_questions=payload.shuffle_questions,
#         show_answers_after=payload.show_answers_after,
#         is_auto_graded=payload.is_auto_graded,
#     )
#     db.add(a)
#     db.flush()

#     for i, q in enumerate(payload.questions):
#         opts = (
#             [{"text": o.text, "is_correct": o.is_correct} for o in q.options]
#             if q.options else None
#         )
#         db.add(LessonAssessmentQuestion(
#             assessment_id=a.id,
#             body=q.body,
#             question_type=q.question_type,
#             options=opts,
#             correct_answer=q.correct_answer,
#             explanation=q.explanation,
#             marks=q.marks,
#             partial_credit=q.partial_credit,
#             order_index=q.order_index if q.order_index is not None else i,
#         ))

#     db.commit()
#     db.refresh(a)
#     return _serialize_assessment(a, include_answers=True)


# @router.put("/{assessment_id}", summary="Update assessment (creator/admin)")
# async def update_assessment(
#     assessment_id: int,
#     payload: LessonAssessmentUpdate,
#     user: User = Depends(require_creator_or_admin),
#     db: Session = Depends(get_db),
# ):
#     a = db.query(LessonAssessment).filter(LessonAssessment.id == assessment_id).first()
#     if not a:
#         raise HTTPException(404, "Assessment not found")
#     if not _is_staff(a, user, db):
#         raise HTTPException(403, "Access denied")

#     for k, v in payload.model_dump(exclude_none=True).items():
#         setattr(a, k, v)
#     db.commit()
#     return _serialize_assessment(a, include_answers=True)


# @router.delete("/{assessment_id}", summary="Delete assessment (creator/admin)")
# async def delete_assessment(
#     assessment_id: int,
#     user: User = Depends(require_creator_or_admin),
#     db: Session = Depends(get_db),
# ):
#     a = db.query(LessonAssessment).filter(LessonAssessment.id == assessment_id).first()
#     if not a:
#         raise HTTPException(404, "Assessment not found")
#     if not _is_staff(a, user, db):
#         raise HTTPException(403, "Access denied")
#     a.is_active = False
#     db.commit()
#     return {"message": "Assessment deactivated"}


# @router.post("/{assessment_id}/ai-generate-questions",
#              summary="AI-generate assessment questions (creator/admin)")
# async def ai_generate_questions(
#     assessment_id: int,
#     count: int = Query(10, ge=1, le=30),
#     question_types: str = Query("mcq,short_answer,essay"),
#     user: User = Depends(require_creator_or_admin),
#     db: Session = Depends(get_db),
# ):
#     """Generate draft questions for an assessment. Nothing is persisted here."""
#     a = db.query(LessonAssessment).filter(LessonAssessment.id == assessment_id).first()
#     if not a:
#         raise HTTPException(404, "Assessment not found")

#     lesson = db.query(Lesson).filter(Lesson.id == a.lesson_id).first()
#     lesson_title = lesson.title if lesson else a.title

#     cfg     = get_app_config()
#     api_key = _get_api_key(cfg)

#     questions = generate_assessment_questions(
#         lesson_title=lesson_title,
#         assessment_type=a.assessment_type,
#         count=count,
#         question_types=question_types,
#         api_key=api_key,
#     )
#     if not questions:
#         raise HTTPException(502, "AI generation failed — add questions manually")
#     return {"questions": questions, "count": len(questions)}




# v2
"""
app/api/v1/lesson_assessments.py  v2
=================================
• Assessment read caching (lesson-level & detail) with staff/student variants
• Invalidation on CRUD and submission grading
• Query optimizations via joinedload / subqueryload
"""

from __future__ import annotations

import logging
import os
import random
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, joinedload, subqueryload

from app.api.deps.auth import (
    get_current_user,
    require_tutor_or_admin,
    require_creator_or_admin,
)
from app.core.config import get_app_config
from app.db.database import get_db
from app.enums import SubmissionStatus, QuizQuestionType
from app.models import Course, Enrollment, Lesson, User
from app.models.quizzes import (
    LessonAssessment,
    LessonAssessmentQuestion,
    LessonAssessmentSubmission,
)
from app.schemas.lesson_assessments import (
    LessonAssessmentCreate,
    LessonAssessmentUpdate,
    LessonAssessmentSubmit,
    LessonTutorGradeRequest,
)
from app.services.ai_grading import (
    grade_question_batch,
    generate_assessment_questions,
)
from app.services.quiz_grading import auto_grade_assessment
from app.core.performance.cache_config import cache
from app.utils.helpers import _to_cacheable

router = APIRouter(prefix="/lesson-assessments", tags=["Lesson Assessments"])
logger = logging.getLogger(__name__)


def _serialize_assessment(a: LessonAssessment, include_answers: bool = False) -> dict:
    questions = []
    for q in a.questions:
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
            raw = q.options or []
            qd["options"] = [{"text": o["text"]} for o in raw]
        questions.append(qd)

    return {
        "id":                  a.id,
        "title":               a.title,
        "instructions":        a.instructions,
        "assessment_type":     a.assessment_type,
        "lesson_id":           a.lesson_id,
        "course_id":           a.course_id,
        "total_marks":         a.total_marks,
        "pass_mark":           a.pass_mark,
        "max_attempts":        a.max_attempts,
        "time_limit_minutes":  a.time_limit_minutes,
        "due_date":            a.due_date,
        "shuffle_questions":   a.shuffle_questions,
        "show_answers_after":  a.show_answers_after,
        "is_auto_graded":      a.is_auto_graded,
        "is_active":           a.is_active,
        "questions":           questions,
        "questions_count":     len(questions),
    }


def _serialize_submission(sub: LessonAssessmentSubmission, show_detail: bool = True) -> dict:
    return {
        "id":             sub.id,
        "assessment_id":  sub.assessment_id,
        "user_id":        sub.user_id,
        "score":          sub.score,
        "max_score":      sub.max_score,
        "percentage":     sub.percentage,
        "passed":         sub.passed,
        "status":         sub.status,
        "attempt_number": sub.attempt_number,
        "ai_feedback":    sub.ai_feedback,
        "tutor_feedback": sub.tutor_feedback,
        "submitted_at":   sub.submitted_at,
        "graded_at":      sub.graded_at,
        "result_detail":  sub.result_detail if show_detail else None,
    }


def _is_staff(assessment: LessonAssessment, user: User, db: Session) -> bool:
    if user.is_admin():
        return True
    course = db.query(Course).filter(Course.id == assessment.course_id).first()
    return bool(course and course.creator_id == user.id)


def _get_api_key(cfg) -> str:
    return getattr(cfg.ai_config, "anthropic_api_key", "") or os.environ.get("ANTHROPIC_API_KEY", "")


def _invalidate_assessment_caches(assessment: LessonAssessment):
    cache.invalidate(f"assessments:lesson:{assessment.lesson_id}")
    cache.invalidate(f"assessments:detail:{assessment.id}:student")
    cache.invalidate(f"assessments:detail:{assessment.id}:staff")


# ══════════════════════════════════════════════════════════════════
#  Student Routes
# ══════════════════════════════════════════════════════════════════

@router.get("/lesson/{lesson_id}", summary="List assessments for a lesson (student)")
async def get_lesson_assessments(
    lesson_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    cache_key = f"assessments:lesson:{lesson_id}"
    hit = cache.get(cache_key)
    if hit is not None:
        return hit

    lesson = db.query(Lesson).filter(Lesson.id == lesson_id).first()
    if not lesson:
        raise HTTPException(404, "Lesson not found")

    assessments = (
        db.query(LessonAssessment)
        .options(subqueryload(LessonAssessment.questions))
        .filter(
            LessonAssessment.lesson_id == lesson_id,
            LessonAssessment.is_active == True,
        )
        .all()
    )

    is_privileged = user.is_admin() or user.has_role("tutor")
    result = [_serialize_assessment(a, include_answers=is_privileged) for a in assessments]
    cache.set(cache_key, _to_cacheable(result), ttl=600)
    return result


@router.get("/{assessment_id}", summary="Get assessment detail (student)")
async def get_assessment(
    assessment_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    is_privileged = user.is_admin() or user.has_role("tutor")
    cache_key = f"assessments:detail:{assessment_id}:{'staff' if is_privileged else 'student'}"
    hit = cache.get(cache_key)
    if hit is not None:
        return hit

    a = db.query(LessonAssessment).options(
        subqueryload(LessonAssessment.questions),
    ).filter(LessonAssessment.id == assessment_id).first()

    if not a:
        raise HTTPException(404, "Assessment not found")

    data = _serialize_assessment(a, include_answers=is_privileged)
    if a.shuffle_questions and not is_privileged:
        random.shuffle(data["questions"])
    cache.set(cache_key, _to_cacheable(data), ttl=600)
    return data


@router.post("/{assessment_id}/submit", status_code=201, summary="Submit assessment answers")
async def submit_assessment(
    assessment_id: int,
    payload: LessonAssessmentSubmit,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    a = db.query(LessonAssessment).options(
        subqueryload(LessonAssessment.questions),
    ).filter(
        LessonAssessment.id == assessment_id,
        LessonAssessment.is_active == True,
    ).first()
    if not a:
        raise HTTPException(404, "Assessment not found")

    prev_count = db.query(LessonAssessmentSubmission).filter(
        LessonAssessmentSubmission.assessment_id == assessment_id,
        LessonAssessmentSubmission.user_id == user.id,
    ).count()
    if prev_count >= a.max_attempts:
        raise HTTPException(403, f"Maximum attempts ({a.max_attempts}) reached.")

    if a.due_date and datetime.now(timezone.utc) > a.due_date:
        raise HTTPException(400, "Submission deadline has passed.")

    answer_map = {ans.question_id: ans.response for ans in payload.answers}
    score, max_score, detail = auto_grade_assessment(a, answer_map)

    needs_open = any(row["is_correct"] is None for row in detail)

    if a.show_answers_after:
        q_map = {q.id: q for q in a.questions}
        for row in detail:
            q = q_map.get(row["question_id"])
            if q:
                row["correct_answer"] = q.correct_answer
                row["explanation"]    = q.explanation

    percentage = round(score / max_score * 100, 1) if max_score else 0.0
    passed     = percentage >= a.pass_mark

    if needs_open and a.is_auto_graded:
        cfg     = get_app_config()
        api_key = _get_api_key(cfg)
        q_map   = {q.id: q for q in a.questions}
        items   = [
            {
                "question_id":   row["question_id"],
                "question_type": row["question_type"],
                "body":          row["body"],
                "max_points":    row["max_points"],
                "response":      row["response"],
                "correct_answer": q_map[row["question_id"]].correct_answer
                                  if row["question_id"] in q_map else None,
            }
            for row in detail
            if row["is_correct"] is None
        ]
        ai_results = grade_question_batch(
            items=items,
            quiz_title=a.title,
            pass_score=a.pass_mark / a.total_marks * 100 if a.total_marks else 70,
            api_key=api_key,
        )
        ai_map = {r["question_id"]: r for r in ai_results}
        for row in detail:
            ai = ai_map.get(row["question_id"])
            if ai:
                row["points_earned"] = ai["points_earned"]
                row["is_correct"]    = ai["is_correct"]
                row["ai_feedback"]   = ai.get("feedback", "")
                score               += ai["points_earned"]

        percentage = round(score / max_score * 100, 1) if max_score else 0.0
        passed     = percentage >= a.pass_mark
        status     = SubmissionStatus.ai_graded
    else:
        status = SubmissionStatus.reviewing if needs_open else SubmissionStatus.returned

    sub = LessonAssessmentSubmission(
        assessment_id=assessment_id,
        user_id=user.id,
        answers=answer_map,
        score=score,
        max_score=max_score,
        percentage=percentage,
        passed=passed,
        result_detail=detail,
        status=status,
        attempt_number=prev_count + 1,
        submitted_at=datetime.now(timezone.utc),
        graded_at=datetime.now(timezone.utc) if not needs_open else None,
    )
    db.add(sub)
    db.commit()
    db.refresh(sub)
    return _serialize_submission(sub, show_detail=a.show_answers_after)


@router.get("/submissions/my", summary="My submissions")
async def my_submissions(
    course_id: Optional[int] = None,
    assessment_type: Optional[str] = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    q = db.query(LessonAssessmentSubmission).filter(
        LessonAssessmentSubmission.user_id == user.id
    )
    if course_id:
        q = q.join(LessonAssessmentSubmission.assessment).filter(
            LessonAssessment.course_id == course_id
        )
    if assessment_type:
        q = q.join(LessonAssessmentSubmission.assessment).filter(
            LessonAssessment.assessment_type == assessment_type
        )
    subs = q.order_by(LessonAssessmentSubmission.submitted_at.desc()).all()
    return [_serialize_submission(s, show_detail=False) for s in subs]


@router.get("/submissions/{submission_id}", summary="Get submission detail")
async def get_submission(
    submission_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    sub = db.query(LessonAssessmentSubmission).filter(
        LessonAssessmentSubmission.id == submission_id
    ).first()
    if not sub:
        raise HTTPException(404, "Submission not found")
    a        = db.query(LessonAssessment).options(
        subqueryload(LessonAssessment.questions),
    ).filter(LessonAssessment.id == sub.assessment_id).first()
    is_owner = sub.user_id == user.id
    is_staff = _is_staff(a, user, db)
    if not is_owner and not is_staff:
        raise HTTPException(403, "Access denied")
    show = is_staff or (a.show_answers_after and sub.status in (
        SubmissionStatus.ai_graded, SubmissionStatus.returned
    ))
    return _serialize_submission(sub, show_detail=show)


# ══════════════════════════════════════════════════════════════════
#  AI Grading
# ══════════════════════════════════════════════════════════════════

@router.post("/submissions/{submission_id}/ai-grade", summary="AI-grade open-ended answers")
async def ai_grade_submission(
    submission_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    sub = db.query(LessonAssessmentSubmission).filter(
        LessonAssessmentSubmission.id == submission_id
    ).first()
    if not sub:
        raise HTTPException(404, "Submission not found")
    a = db.query(LessonAssessment).options(
        subqueryload(LessonAssessment.questions),
    ).filter(LessonAssessment.id == sub.assessment_id).first()
    is_owner = sub.user_id == user.id
    if not is_owner and not _is_staff(a, user, db):
        raise HTTPException(403, "Access denied")

    detail = sub.result_detail or []
    q_map  = {q.id: q for q in a.questions}
    pending = [
        row for row in detail
        if row.get("is_correct") is None
    ]
    if not pending:
        return {"message": "No questions require AI grading", "submission": _serialize_submission(sub)}

    cfg     = get_app_config()
    api_key = _get_api_key(cfg)
    items   = [
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

    ai_results = grade_question_batch(
        items=items,
        quiz_title=a.title,
        pass_score=a.pass_mark / a.total_marks * 100 if a.total_marks else 70,
        api_key=api_key,
    )
    if not ai_results:
        raise HTTPException(502, "AI grading unavailable — please grade manually")

    ai_map      = {r["question_id"]: r for r in ai_results}
    extra_score = 0.0
    for row in detail:
        ai = ai_map.get(row["question_id"])
        if ai:
            row["points_earned"] = ai["points_earned"]
            row["is_correct"]    = ai["is_correct"]
            row["ai_feedback"]   = ai.get("feedback", "")
            extra_score         += ai["points_earned"]

    new_score  = (sub.score or 0.0) + extra_score
    new_pct    = round(new_score / (sub.max_score or 1) * 100, 1)
    sub.result_detail = detail
    sub.score         = new_score
    sub.percentage    = new_pct
    sub.passed        = new_pct >= a.pass_mark
    sub.status        = SubmissionStatus.ai_graded
    sub.graded_at     = datetime.now(timezone.utc)
    db.commit()
    db.refresh(sub)
    return _serialize_submission(sub)


# ══════════════════════════════════════════════════════════════════
#  Tutor / Admin Routes
# ══════════════════════════════════════════════════════════════════

@router.post("/submissions/{submission_id}/tutor-grade", summary="Tutor override / review")
async def tutor_grade_submission(
    submission_id: int,
    payload: LessonTutorGradeRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    sub = db.query(LessonAssessmentSubmission).filter(
        LessonAssessmentSubmission.id == submission_id
    ).first()
    if not sub:
        raise HTTPException(404, "Submission not found")
    a = db.query(LessonAssessment).options(
        subqueryload(LessonAssessment.questions),
    ).filter(LessonAssessment.id == sub.assessment_id).first()
    if not _is_staff(a, user, db):
        raise HTTPException(403, "Access denied")

    if payload.answers:
        detail = sub.result_detail or []
        q_override = {item.question_id: item for item in payload.answers}
        for row in detail:
            override = q_override.get(row["question_id"])
            if override:
                row["points_earned"]  = override.score
                row["tutor_feedback"] = override.feedback or ""
                row["is_correct"]     = override.score >= row["max_points"]
        sub.result_detail = detail
        sub.score         = sum(r.get("points_earned", 0.0) for r in detail)
    elif payload.score_override is not None:
        sub.score = payload.score_override

    if sub.score is not None and sub.max_score:
        sub.percentage = round(sub.score / sub.max_score * 100, 1)
        sub.passed     = sub.percentage >= a.pass_mark

    sub.tutor_feedback = payload.overall_feedback
    sub.graded_by_id   = user.id
    sub.status         = SubmissionStatus.returned
    sub.graded_at      = datetime.now(timezone.utc)
    db.commit()
    db.refresh(sub)
    return _serialize_submission(sub)


@router.get("/course/{course_id}/submissions", summary="All submissions for a course (staff)")
async def get_course_submissions(
    course_id: int,
    assessment_type: Optional[str] = None,
    status: Optional[str] = None,
    user: User = Depends(require_tutor_or_admin),
    db: Session = Depends(get_db),
):
    q = db.query(LessonAssessmentSubmission).join(
        LessonAssessment,
        LessonAssessmentSubmission.assessment_id == LessonAssessment.id,
    ).filter(LessonAssessment.course_id == course_id)

    if assessment_type:
        q = q.filter(LessonAssessment.assessment_type == assessment_type)
    if status:
        q = q.filter(LessonAssessmentSubmission.status == status)

    subs = q.order_by(LessonAssessmentSubmission.submitted_at.desc()).all()
    return [_serialize_submission(s) for s in subs]


# ══════════════════════════════════════════════════════════════════
#  Creator / Admin CRUD
# ══════════════════════════════════════════════════════════════════

@router.post("/", status_code=201, summary="Create assessment (creator/admin)")
async def create_assessment(
    payload: LessonAssessmentCreate,
    user: User = Depends(require_creator_or_admin),
    db: Session = Depends(get_db),
):
    course = db.query(Course).filter(Course.id == payload.course_id).first()
    if not course:
        raise HTTPException(404, "Course not found")
    if not user.is_admin() and course.creator_id != user.id:
        raise HTTPException(403, "Access denied")

    a = LessonAssessment(
        title=payload.title,
        instructions=payload.instructions,
        assessment_type=payload.assessment_type,
        lesson_id=payload.lesson_id,
        course_id=payload.course_id,
        total_marks=payload.total_marks,
        pass_mark=payload.pass_mark,
        max_attempts=payload.max_attempts,
        time_limit_minutes=payload.time_limit_minutes,
        due_date=payload.due_date,
        shuffle_questions=payload.shuffle_questions,
        show_answers_after=payload.show_answers_after,
        is_auto_graded=payload.is_auto_graded,
    )
    db.add(a)
    db.flush()

    for i, q in enumerate(payload.questions):
        opts = (
            [{"text": o.text, "is_correct": o.is_correct} for o in q.options]
            if q.options else None
        )
        db.add(LessonAssessmentQuestion(
            assessment_id=a.id,
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
    db.refresh(a)
    _invalidate_assessment_caches(a)
    return _serialize_assessment(a, include_answers=True)


@router.put("/{assessment_id}", summary="Update assessment (creator/admin)")
async def update_assessment(
    assessment_id: int,
    payload: LessonAssessmentUpdate,
    user: User = Depends(require_creator_or_admin),
    db: Session = Depends(get_db),
):
    a = db.query(LessonAssessment).options(
        subqueryload(LessonAssessment.questions),
    ).filter(LessonAssessment.id == assessment_id).first()
    if not a:
        raise HTTPException(404, "Assessment not found")
    if not _is_staff(a, user, db):
        raise HTTPException(403, "Access denied")

    for k, v in payload.model_dump(exclude_none=True).items():
        setattr(a, k, v)
    db.commit()
    _invalidate_assessment_caches(a)
    return _serialize_assessment(a, include_answers=True)


@router.delete("/{assessment_id}", summary="Delete assessment (creator/admin)")
async def delete_assessment(
    assessment_id: int,
    user: User = Depends(require_creator_or_admin),
    db: Session = Depends(get_db),
):
    a = db.query(LessonAssessment).filter(LessonAssessment.id == assessment_id).first()
    if not a:
        raise HTTPException(404, "Assessment not found")
    if not _is_staff(a, user, db):
        raise HTTPException(403, "Access denied")
    a.is_active = False
    db.commit()
    _invalidate_assessment_caches(a)
    return {"message": "Assessment deactivated"}


@router.post("/{assessment_id}/ai-generate-questions",
             summary="AI-generate assessment questions (creator/admin)")
async def ai_generate_questions(
    assessment_id: int,
    count: int = Query(10, ge=1, le=30),
    question_types: str = Query("mcq,short_answer,essay"),
    user: User = Depends(require_creator_or_admin),
    db: Session = Depends(get_db),
):
    a = db.query(LessonAssessment).filter(LessonAssessment.id == assessment_id).first()
    if not a:
        raise HTTPException(404, "Assessment not found")

    lesson = db.query(Lesson).filter(Lesson.id == a.lesson_id).first()
    lesson_title = lesson.title if lesson else a.title

    cfg     = get_app_config()
    api_key = _get_api_key(cfg)

    questions = generate_assessment_questions(
        lesson_title=lesson_title,
        assessment_type=a.assessment_type,
        count=count,
        question_types=question_types,
        api_key=api_key,
    )
    if not questions:
        raise HTTPException(502, "AI generation failed — add questions manually")
    return {"questions": questions, "count": len(questions)}


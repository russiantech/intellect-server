# """
# app/api/v1/projects.py
# ======================
# Course-level project brief and submission routes.

# All routes are prefixed /projects.

# Endpoints
# ---------
# Student
#   GET  /course/{course_id}                    – list active project briefs
#   GET  /{project_id}                          – get brief detail
#   POST /{project_id}/submit                   – submit (multipart file + form fields)
#   GET  /submissions/my                        – student's own submissions
#   GET  /submissions/{submission_id}           – detail view

# AI grading
#   POST /submissions/{submission_id}/ai-grade  – AI grades the submission

# Tutor / Admin
#   POST /submissions/{submission_id}/tutor-review – tutor review / override
#   GET  /course/{course_id}/all-submissions    – all submissions for a course
#   GET  /submissions/{submission_id}/download  – download submitted file

# Creator / Admin CRUD
#   POST /course/{course_id}                    – create project brief
#   PUT  /{project_id}                          – update brief
#   DELETE /{project_id}                        – soft-delete brief
# """

# from __future__ import annotations

# import logging
# import os
# import uuid
# from datetime import datetime, timezone
# from pathlib import Path
# from typing import Optional

# from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
# from fastapi.responses import FileResponse
# from sqlalchemy.orm import Session

# from app.api.deps.auth import (
#     get_current_user,
#     require_tutor_or_admin,
#     require_creator_or_admin,
# )
# from app.core.config import get_app_config
# from app.db.database import get_db
# from app.enums import SubmissionStatus
# from app.models import Course, Enrollment, User
# from app.models.quizzes import Project, ProjectSubmission
# from app.schemas.projects import (
#     ProjectCreate,
#     ProjectUpdate,
#     ProjectTutorReview,
# )
# from app.services.ai_grading import grade_project_submission

# router = APIRouter(prefix="/projects", tags=["Projects"])
# logger = logging.getLogger(__name__)

# ALLOWED_EXTENSIONS = {
#     "pdf", "zip", "docx", "doc", "pptx", "ppt",
#     "txt", "md", "py", "js", "ts", "html", "css", "ipynb",
#     "png", "jpg", "jpeg", "gif", "webp",
#     "mp4", "mov", "xlsx", "csv",
# }


# # ══════════════════════════════════════════════════════════════════
# #  Serialisation helpers
# # ══════════════════════════════════════════════════════════════════

# def _serialize_project(p: Project) -> dict:
#     return {
#         "id":               p.id,
#         "title":            p.title,
#         "description":      p.description,
#         "rubric":           p.rubric,
#         "course_id":        p.course_id,
#         "lesson_id":        p.lesson_id,
#         "due_date":         p.due_date,
#         "max_file_size_mb": p.max_file_size_mb,
#         "allowed_formats":  p.allowed_formats,
#         "is_active":        p.is_active,
#         "created_at":       p.created_at,
#     }


# def _serialize_submission(s: ProjectSubmission, with_file_url: bool = False) -> dict:
#     d = {
#         "id":              s.id,
#         "project_id":      s.project_id,
#         "user_id":         s.user_id,
#         "title":           s.title,
#         "note":            s.note,
#         "external_url":    s.external_url,
#         "file_name":       s.file_name,
#         "has_file":        bool(s.file_path),
#         "score":           s.score,
#         "max_score":       s.max_score,
#         "passed":          s.passed,
#         "status":          s.status,
#         "ai_feedback":     s.ai_feedback,
#         "ai_strengths":    s.ai_strengths,
#         "ai_improvements": s.ai_improvements,
#         "tutor_feedback":  s.tutor_feedback,
#         "graded_at":       s.graded_at,
#         "created_at":      s.created_at,
#     }
#     if with_file_url and s.file_path:
#         cfg  = get_app_config()
#         base = cfg.hosting_config.api_url.rstrip("/")
#         d["file_url"] = f"{base}/projects/submissions/{s.id}/download"
#     return d


# # ══════════════════════════════════════════════════════════════════
# #  Access helpers
# # ══════════════════════════════════════════════════════════════════

# def _is_course_staff(course: Course, user: User) -> bool:
#     return user.is_admin() or course.creator_id == user.id


# def _require_enrolled_or_staff(course: Course, user: User, db: Session) -> None:
#     if _is_course_staff(course, user):
#         return
#     enrolled = db.query(Enrollment).filter(
#         Enrollment.user_id == user.id,
#         Enrollment.course_id == course.id,
#     ).first()
#     if not enrolled:
#         raise HTTPException(403, "Enrollment required to access this project")


# def _get_api_key(cfg) -> str:
#     return (
#         getattr(cfg.ai_config, "anthropic_api_key", "")
#         or os.environ.get("ANTHROPIC_API_KEY", "")
#     )


# # ══════════════════════════════════════════════════════════════════
# #  Student Routes — Briefs
# # ══════════════════════════════════════════════════════════════════

# @router.get("/course/{course_id}", summary="List project briefs for a course")
# async def list_course_projects(
#     course_id: int,
#     user: User  = Depends(get_current_user),
#     db: Session = Depends(get_db),
# ):
#     course = db.query(Course).filter(Course.id == course_id).first()
#     if not course:
#         raise HTTPException(404, "Course not found")
#     _require_enrolled_or_staff(course, user, db)

#     projects = db.query(Project).filter(
#         Project.course_id == course_id,
#         Project.is_active == True,
#     ).all()
#     return [_serialize_project(p) for p in projects]


# @router.get("/{project_id}", summary="Get project brief")
# async def get_project(
#     project_id: int,
#     user: User  = Depends(get_current_user),
#     db: Session = Depends(get_db),
# ):
#     p = db.query(Project).filter(Project.id == project_id, Project.is_active == True).first()
#     if not p:
#         raise HTTPException(404, "Project not found")
#     course = db.query(Course).filter(Course.id == p.course_id).first()
#     _require_enrolled_or_staff(course, user, db)
#     return _serialize_project(p)


# # ══════════════════════════════════════════════════════════════════
# #  Student Routes — Submissions
# # ══════════════════════════════════════════════════════════════════

# @router.post("/{project_id}/submit", status_code=201, summary="Submit a project")
# async def submit_project(
#     project_id: int,
#     title:        Optional[str]        = Form(None),
#     note:         Optional[str]        = Form(None),
#     external_url: Optional[str]        = Form(None),
#     file:         Optional[UploadFile] = File(None),
#     user: User   = Depends(get_current_user),
#     db: Session  = Depends(get_db),
# ):
#     """
#     Submit a project.  At least one of note, external_url, or file is required.
#     File is sent as multipart/form-data.
#     """
#     p = db.query(Project).filter(Project.id == project_id, Project.is_active == True).first()
#     if not p:
#         raise HTTPException(404, "Project not found")
#     course = db.query(Course).filter(Course.id == p.course_id).first()
#     _require_enrolled_or_staff(course, user, db)

#     if p.due_date and datetime.now(timezone.utc) > p.due_date:
#         raise HTTPException(400, "Project submission deadline has passed.")
#     if not note and not external_url and not file:
#         raise HTTPException(400, "Provide at least one of: note, external_url, or a file.")

#     # ── File upload ───────────────────────────────────────────────
#     file_path: Optional[str] = None
#     file_name: Optional[str] = None
#     mime_type: Optional[str] = None
#     file_size: Optional[int] = None

#     if file:
#         ext = Path(file.filename or "").suffix.lstrip(".").lower()
#         allowed = (
#             set(p.allowed_formats.split(",")) if p.allowed_formats else ALLOWED_EXTENSIONS
#         )
#         if ext not in allowed:
#             raise HTTPException(400, f"File type '.{ext}' is not allowed.")

#         cfg        = get_app_config()
#         upload_dir = Path(cfg.hosting_config.content_delivery.filesystem_base_path) / "projects"
#         upload_dir.mkdir(parents=True, exist_ok=True)

#         contents  = await file.read()
#         max_bytes = p.max_file_size_mb * 1024 * 1024
#         if len(contents) > max_bytes:
#             raise HTTPException(400, f"File exceeds the {p.max_file_size_mb} MB limit.")

#         stored_name = f"{uuid.uuid4().hex}.{ext}"
#         dest        = upload_dir / stored_name
#         dest.write_bytes(contents)

#         file_path = str(dest)
#         file_name = file.filename
#         mime_type = file.content_type
#         file_size = len(contents)

#     sub = ProjectSubmission(
#         project_id=project_id,
#         user_id=user.id,
#         title=title,
#         note=note,
#         external_url=external_url,
#         file_path=file_path,
#         file_name=file_name,
#         mime_type=mime_type,
#         file_size_bytes=file_size,
#         status=SubmissionStatus.pending,
#     )
#     db.add(sub)
#     db.commit()
#     db.refresh(sub)
#     return _serialize_submission(sub, with_file_url=True)


# @router.get("/submissions/my", summary="My project submissions")
# async def my_submissions(
#     course_id: Optional[int] = None,
#     user: User  = Depends(get_current_user),
#     db: Session = Depends(get_db),
# ):
#     q = (
#         db.query(ProjectSubmission)
#         .join(Project, ProjectSubmission.project_id == Project.id)
#         .filter(ProjectSubmission.user_id == user.id)
#     )
#     if course_id:
#         q = q.filter(Project.course_id == course_id)
#     subs = q.order_by(ProjectSubmission.created_at.desc()).all()
#     return [_serialize_submission(s) for s in subs]


# @router.get("/submissions/{submission_id}", summary="Get submission detail")
# async def get_submission(
#     submission_id: int,
#     user: User  = Depends(get_current_user),
#     db: Session = Depends(get_db),
# ):
#     sub = db.query(ProjectSubmission).filter(ProjectSubmission.id == submission_id).first()
#     if not sub:
#         raise HTTPException(404, "Submission not found")
#     project  = db.query(Project).filter(Project.id == sub.project_id).first()
#     course   = db.query(Course).filter(Course.id == project.course_id).first()
#     is_owner = sub.user_id == user.id
#     is_staff = _is_course_staff(course, user)
#     if not is_owner and not is_staff:
#         raise HTTPException(403, "Access denied")
#     return _serialize_submission(sub, with_file_url=is_staff)


# # ══════════════════════════════════════════════════════════════════
# #  AI Grading
# # ══════════════════════════════════════════════════════════════════

# @router.post("/submissions/{submission_id}/ai-grade", summary="AI-grade a project submission")
# async def ai_grade_submission(
#     submission_id: int,
#     user: User  = Depends(get_current_user),
#     db: Session = Depends(get_db),
# ):
#     """Only course staff or the submission owner can trigger AI grading."""
#     sub = db.query(ProjectSubmission).filter(ProjectSubmission.id == submission_id).first()
#     if not sub:
#         raise HTTPException(404, "Submission not found")
#     project  = db.query(Project).filter(Project.id == sub.project_id).first()
#     course   = db.query(Course).filter(Course.id == project.course_id).first()
#     is_owner = sub.user_id == user.id
#     if not is_owner and not _is_course_staff(course, user):
#         raise HTTPException(403, "Access denied")

#     cfg     = get_app_config()
#     api_key = _get_api_key(cfg)

#     result = grade_project_submission(
#         project_title=project.title,
#         project_description=project.description,
#         rubric=project.rubric,
#         student_note=sub.note,
#         external_url=sub.external_url,
#         file_name=sub.file_name,
#         max_score=sub.max_score,
#         api_key=api_key,
#     )

#     sub.score           = result["score"]
#     sub.passed          = result["passed"]
#     sub.ai_feedback     = result["feedback"]
#     sub.ai_strengths    = result["strengths"]
#     sub.ai_improvements = result["improvements"]
#     sub.status          = SubmissionStatus.ai_graded
#     sub.graded_at       = datetime.now(timezone.utc)
#     db.commit()
#     db.refresh(sub)
#     return _serialize_submission(sub, with_file_url=True)


# # ══════════════════════════════════════════════════════════════════
# #  Tutor / Admin Routes
# # ══════════════════════════════════════════════════════════════════

# @router.post("/submissions/{submission_id}/tutor-review",
#              summary="Tutor review / override")
# async def tutor_review_submission(
#     submission_id: int,
#     payload: ProjectTutorReview,
#     user: User  = Depends(get_current_user),
#     db: Session = Depends(get_db),
# ):
#     sub = db.query(ProjectSubmission).filter(ProjectSubmission.id == submission_id).first()
#     if not sub:
#         raise HTTPException(404, "Submission not found")
#     project = db.query(Project).filter(Project.id == sub.project_id).first()
#     course  = db.query(Course).filter(Course.id == project.course_id).first()
#     if not _is_course_staff(course, user):
#         raise HTTPException(403, "Access denied")

#     if payload.score is not None:
#         sub.score  = payload.score
#         sub.passed = (
#             payload.passed
#             if payload.passed is not None
#             else payload.score >= sub.max_score * 0.5
#         )
#     sub.tutor_feedback = payload.feedback
#     sub.graded_by_id   = user.id
#     sub.status         = SubmissionStatus.returned
#     sub.graded_at      = datetime.now(timezone.utc)
#     db.commit()
#     db.refresh(sub)
#     return _serialize_submission(sub, with_file_url=True)


# @router.get("/course/{course_id}/all-submissions",
#             summary="All project submissions for a course (staff)")
# async def get_all_course_submissions(
#     course_id: int,
#     project_id: Optional[int] = None,
#     status:     Optional[str] = None,
#     user: User  = Depends(require_tutor_or_admin),
#     db: Session = Depends(get_db),
# ):
#     q = (
#         db.query(ProjectSubmission)
#         .join(Project, ProjectSubmission.project_id == Project.id)
#         .filter(Project.course_id == course_id)
#     )
#     if project_id:
#         q = q.filter(ProjectSubmission.project_id == project_id)
#     if status:
#         q = q.filter(ProjectSubmission.status == status)
#     subs = q.order_by(ProjectSubmission.created_at.desc()).all()
#     return [_serialize_submission(s, with_file_url=True) for s in subs]


# @router.get("/submissions/{submission_id}/download",
#             summary="Download submitted file (owner or staff)")
# async def download_submission_file(
#     submission_id: int,
#     user: User  = Depends(get_current_user),
#     db: Session = Depends(get_db),
# ):
#     sub = db.query(ProjectSubmission).filter(ProjectSubmission.id == submission_id).first()
#     if not sub or not sub.file_path:
#         raise HTTPException(404, "File not found")
#     project  = db.query(Project).filter(Project.id == sub.project_id).first()
#     course   = db.query(Course).filter(Course.id == project.course_id).first()
#     is_owner = sub.user_id == user.id
#     if not is_owner and not _is_course_staff(course, user):
#         raise HTTPException(403, "Access denied")
#     if not Path(sub.file_path).exists():
#         raise HTTPException(404, "File not found on disk")
#     return FileResponse(
#         path=sub.file_path,
#         filename=sub.file_name or "submission",
#         media_type=sub.mime_type or "application/octet-stream",
#     )


# # ══════════════════════════════════════════════════════════════════
# #  Creator / Admin CRUD — Briefs
# # ══════════════════════════════════════════════════════════════════

# @router.post("/course/{course_id}", status_code=201, summary="Create project brief (creator/admin)")
# async def create_project(
#     course_id: int,
#     payload: ProjectCreate,
#     user: User  = Depends(require_creator_or_admin),
#     db: Session = Depends(get_db),
# ):
#     course = db.query(Course).filter(Course.id == course_id).first()
#     if not course:
#         raise HTTPException(404, "Course not found")
#     if not user.is_admin() and course.creator_id != user.id:
#         raise HTTPException(403, "Access denied")

#     p = Project(
#         title=payload.title,
#         description=payload.description,
#         rubric=payload.rubric,
#         course_id=course_id,
#         lesson_id=payload.lesson_id,
#         due_date=payload.due_date,
#         max_file_size_mb=payload.max_file_size_mb,
#         allowed_formats=payload.allowed_formats,
#     )
#     db.add(p)
#     db.commit()
#     db.refresh(p)
#     return _serialize_project(p)


# @router.put("/{project_id}", summary="Update project brief (creator/admin)")
# async def update_project(
#     project_id: int,
#     payload: ProjectUpdate,
#     user: User  = Depends(require_creator_or_admin),
#     db: Session = Depends(get_db),
# ):
#     p = db.query(Project).filter(Project.id == project_id).first()
#     if not p:
#         raise HTTPException(404, "Project not found")
#     course = db.query(Course).filter(Course.id == p.course_id).first()
#     if not user.is_admin() and course.creator_id != user.id:
#         raise HTTPException(403, "Access denied")
#     for k, v in payload.model_dump(exclude_none=True).items():
#         setattr(p, k, v)
#     db.commit()
#     return _serialize_project(p)


# @router.delete("/{project_id}", summary="Delete project brief (creator/admin)")
# async def delete_project(
#     project_id: int,
#     user: User  = Depends(require_creator_or_admin),
#     db: Session = Depends(get_db),
# ):
#     p = db.query(Project).filter(Project.id == project_id).first()
#     if not p:
#         raise HTTPException(404, "Project not found")
#     course = db.query(Course).filter(Course.id == p.course_id).first()
#     if not user.is_admin() and course.creator_id != user.id:
#         raise HTTPException(403, "Access denied")
#     p.is_active = False
#     db.commit()
#     return {"message": "Project brief deactivated"}





# v2
"""
app/api/v1/projects.py  v2
======================
• Project brief read caching (course-level & detail)
• Invalidation on brief CRUD
• Query optimizations via joinedload on submission listings
"""

from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session, joinedload

from app.api.deps.auth import (
    get_current_user,
    require_tutor_or_admin,
    require_creator_or_admin,
)
from app.core.config import get_app_config
from app.db.database import get_db
from app.enums import SubmissionStatus
from app.models import Course, Enrollment, User
from app.models.quizzes import Project, ProjectSubmission
from app.schemas.projects import (
    ProjectCreate,
    ProjectUpdate,
    ProjectTutorReview,
)
from app.services.ai_grading import grade_project_submission
from app.core.performance.cache_config import cache
from app.utils.helpers import _to_cacheable

router = APIRouter(prefix="/projects", tags=["Projects"])
logger = logging.getLogger(__name__)

ALLOWED_EXTENSIONS = {
    "pdf", "zip", "docx", "doc", "pptx", "ppt",
    "txt", "md", "py", "js", "ts", "html", "css", "ipynb",
    "png", "jpg", "jpeg", "gif", "webp",
    "mp4", "mov", "xlsx", "csv",
}


def _serialize_project(p: Project) -> dict:
    return {
        "id":               p.id,
        "title":            p.title,
        "description":      p.description,
        "rubric":           p.rubric,
        "course_id":        p.course_id,
        "lesson_id":        p.lesson_id,
        "due_date":         p.due_date,
        "max_file_size_mb": p.max_file_size_mb,
        "allowed_formats":  p.allowed_formats,
        "is_active":        p.is_active,
        "created_at":       p.created_at,
    }


def _serialize_submission(s: ProjectSubmission, with_file_url: bool = False) -> dict:
    d = {
        "id":              s.id,
        "project_id":      s.project_id,
        "user_id":         s.user_id,
        "title":           s.title,
        "note":            s.note,
        "external_url":    s.external_url,
        "file_name":       s.file_name,
        "has_file":        bool(s.file_path),
        "score":           s.score,
        "max_score":       s.max_score,
        "passed":          s.passed,
        "status":          s.status,
        "ai_feedback":     s.ai_feedback,
        "ai_strengths":    s.ai_strengths,
        "ai_improvements": s.ai_improvements,
        "tutor_feedback":  s.tutor_feedback,
        "graded_at":       s.graded_at,
        "created_at":      s.created_at,
    }
    if with_file_url and s.file_path:
        cfg  = get_app_config()
        base = cfg.hosting_config.api_url.rstrip("/")
        d["file_url"] = f"{base}/projects/submissions/{s.id}/download"
    return d


def _is_course_staff(course: Course, user: User) -> bool:
    return user.is_admin() or course.creator_id == user.id


def _require_enrolled_or_staff(course: Course, user: User, db: Session) -> None:
    if _is_course_staff(course, user):
        return
    enrolled = db.query(Enrollment).filter(
        Enrollment.user_id == user.id,
        Enrollment.course_id == course.id,
    ).first()
    if not enrolled:
        raise HTTPException(403, "Enrollment required to access this project")


def _get_api_key(cfg) -> str:
    return (
        getattr(cfg.ai_config, "anthropic_api_key", "")
        or os.environ.get("ANTHROPIC_API_KEY", "")
    )


def _invalidate_project_caches(project: Project):
    cache.invalidate(f"projects:course:{project.course_id}")
    cache.invalidate(f"projects:detail:{project.id}")


# ══════════════════════════════════════════════════════════════════
#  Student Routes — Briefs
# ══════════════════════════════════════════════════════════════════

@router.get("/course/{course_id}", summary="List project briefs for a course")
async def list_course_projects(
    course_id: int,
    user: User  = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    course = db.query(Course).filter(Course.id == course_id).first()
    if not course:
        raise HTTPException(404, "Course not found")
    _require_enrolled_or_staff(course, user, db)

    cache_key = f"projects:course:{course_id}"
    hit = cache.get(cache_key)
    if hit is not None:
        return hit

    projects = db.query(Project).filter(
        Project.course_id == course_id,
        Project.is_active == True,
    ).all()
    result = [_serialize_project(p) for p in projects]
    cache.set(cache_key, _to_cacheable(result), ttl=600)
    return result


@router.get("/{project_id}", summary="Get project brief")
async def get_project(
    project_id: int,
    user: User  = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    cache_key = f"projects:detail:{project_id}"
    hit = cache.get(cache_key)
    if hit is not None:
        return hit

    p = db.query(Project).filter(Project.id == project_id, Project.is_active == True).first()
    if not p:
        raise HTTPException(404, "Project not found")
    course = db.query(Course).filter(Course.id == p.course_id).first()
    _require_enrolled_or_staff(course, user, db)

    result = _serialize_project(p)
    cache.set(cache_key, _to_cacheable(result), ttl=600)
    return result


# ══════════════════════════════════════════════════════════════════
#  Student Routes — Submissions
# ══════════════════════════════════════════════════════════════════

@router.post("/{project_id}/submit", status_code=201, summary="Submit a project")
async def submit_project(
    project_id: int,
    title:        Optional[str]        = Form(None),
    note:         Optional[str]        = Form(None),
    external_url: Optional[str]        = Form(None),
    file:         Optional[UploadFile] = File(None),
    user: User   = Depends(get_current_user),
    db: Session  = Depends(get_db),
):
    p = db.query(Project).filter(Project.id == project_id, Project.is_active == True).first()
    if not p:
        raise HTTPException(404, "Project not found")
    course = db.query(Course).filter(Course.id == p.course_id).first()
    _require_enrolled_or_staff(course, user, db)

    if p.due_date and datetime.now(timezone.utc) > p.due_date:
        raise HTTPException(400, "Project submission deadline has passed.")
    if not note and not external_url and not file:
        raise HTTPException(400, "Provide at least one of: note, external_url, or a file.")

    file_path: Optional[str] = None
    file_name: Optional[str] = None
    mime_type: Optional[str] = None
    file_size: Optional[int] = None

    if file:
        ext = Path(file.filename or "").suffix.lstrip(".").lower()
        allowed = (
            set(p.allowed_formats.split(",")) if p.allowed_formats else ALLOWED_EXTENSIONS
        )
        if ext not in allowed:
            raise HTTPException(400, f"File type '.{ext}' is not allowed.")

        cfg        = get_app_config()
        upload_dir = Path(cfg.hosting_config.content_delivery.filesystem_base_path) / "projects"
        upload_dir.mkdir(parents=True, exist_ok=True)

        contents  = await file.read()
        max_bytes = p.max_file_size_mb * 1024 * 1024
        if len(contents) > max_bytes:
            raise HTTPException(400, f"File exceeds the {p.max_file_size_mb} MB limit.")

        stored_name = f"{uuid.uuid4().hex}.{ext}"
        dest        = upload_dir / stored_name
        dest.write_bytes(contents)

        file_path = str(dest)
        file_name = file.filename
        mime_type = file.content_type
        file_size = len(contents)

    sub = ProjectSubmission(
        project_id=project_id,
        user_id=user.id,
        title=title,
        note=note,
        external_url=external_url,
        file_path=file_path,
        file_name=file_name,
        mime_type=mime_type,
        file_size_bytes=file_size,
        status=SubmissionStatus.pending,
    )
    db.add(sub)
    db.commit()
    db.refresh(sub)
    return _serialize_submission(sub, with_file_url=True)


@router.get("/submissions/my", summary="My project submissions")
async def my_submissions(
    course_id: Optional[int] = None,
    user: User  = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    q = (
        db.query(ProjectSubmission)
        .join(Project, ProjectSubmission.project_id == Project.id)
        .filter(ProjectSubmission.user_id == user.id)
    )
    if course_id:
        q = q.filter(Project.course_id == course_id)
    subs = q.order_by(ProjectSubmission.created_at.desc()).all()
    return [_serialize_submission(s) for s in subs]


@router.get("/submissions/{submission_id}", summary="Get submission detail")
async def get_submission(
    submission_id: int,
    user: User  = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    sub = db.query(ProjectSubmission).filter(ProjectSubmission.id == submission_id).first()
    if not sub:
        raise HTTPException(404, "Submission not found")
    project  = db.query(Project).filter(Project.id == sub.project_id).first()
    course   = db.query(Course).filter(Course.id == project.course_id).first()
    is_owner = sub.user_id == user.id
    is_staff = _is_course_staff(course, user)
    if not is_owner and not is_staff:
        raise HTTPException(403, "Access denied")
    return _serialize_submission(sub, with_file_url=is_staff)


# ══════════════════════════════════════════════════════════════════
#  AI Grading
# ══════════════════════════════════════════════════════════════════

@router.post("/submissions/{submission_id}/ai-grade", summary="AI-grade a project submission")
async def ai_grade_submission(
    submission_id: int,
    user: User  = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    sub = db.query(ProjectSubmission).filter(ProjectSubmission.id == submission_id).first()
    if not sub:
        raise HTTPException(404, "Submission not found")
    project  = db.query(Project).filter(Project.id == sub.project_id).first()
    course   = db.query(Course).filter(Course.id == project.course_id).first()
    is_owner = sub.user_id == user.id
    if not is_owner and not _is_course_staff(course, user):
        raise HTTPException(403, "Access denied")

    cfg     = get_app_config()
    api_key = _get_api_key(cfg)

    result = grade_project_submission(
        project_title=project.title,
        project_description=project.description,
        rubric=project.rubric,
        student_note=sub.note,
        external_url=sub.external_url,
        file_name=sub.file_name,
        max_score=sub.max_score,
        api_key=api_key,
    )

    sub.score           = result["score"]
    sub.passed          = result["passed"]
    sub.ai_feedback     = result["feedback"]
    sub.ai_strengths    = result["strengths"]
    sub.ai_improvements = result["improvements"]
    sub.status          = SubmissionStatus.ai_graded
    sub.graded_at       = datetime.now(timezone.utc)
    db.commit()
    db.refresh(sub)
    return _serialize_submission(sub, with_file_url=True)


# ══════════════════════════════════════════════════════════════════
#  Tutor / Admin Routes
# ══════════════════════════════════════════════════════════════════

@router.post("/submissions/{submission_id}/tutor-review",
             summary="Tutor review / override")
async def tutor_review_submission(
    submission_id: int,
    payload: ProjectTutorReview,
    user: User  = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    sub = db.query(ProjectSubmission).filter(ProjectSubmission.id == submission_id).first()
    if not sub:
        raise HTTPException(404, "Submission not found")
    project = db.query(Project).filter(Project.id == sub.project_id).first()
    course  = db.query(Course).filter(Course.id == project.course_id).first()
    if not _is_course_staff(course, user):
        raise HTTPException(403, "Access denied")

    if payload.score is not None:
        sub.score  = payload.score
        sub.passed = (
            payload.passed
            if payload.passed is not None
            else payload.score >= sub.max_score * 0.5
        )
    sub.tutor_feedback = payload.feedback
    sub.graded_by_id   = user.id
    sub.status         = SubmissionStatus.returned
    sub.graded_at      = datetime.now(timezone.utc)
    db.commit()
    db.refresh(sub)
    return _serialize_submission(sub, with_file_url=True)


@router.get("/course/{course_id}/all-submissions",
            summary="All project submissions for a course (staff)")
async def get_all_course_submissions(
    course_id: int,
    project_id: Optional[int] = None,
    status:     Optional[str] = None,
    user: User  = Depends(require_tutor_or_admin),
    db: Session = Depends(get_db),
):
    q = (
        db.query(ProjectSubmission)
        .join(Project, ProjectSubmission.project_id == Project.id)
        .filter(Project.course_id == course_id)
    )
    if project_id:
        q = q.filter(ProjectSubmission.project_id == project_id)
    if status:
        q = q.filter(ProjectSubmission.status == status)
    subs = q.order_by(ProjectSubmission.created_at.desc()).all()
    return [_serialize_submission(s, with_file_url=True) for s in subs]


@router.get("/submissions/{submission_id}/download",
            summary="Download submitted file (owner or staff)")
async def download_submission_file(
    submission_id: int,
    user: User  = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    sub = db.query(ProjectSubmission).filter(ProjectSubmission.id == submission_id).first()
    if not sub or not sub.file_path:
        raise HTTPException(404, "File not found")
    project  = db.query(Project).filter(Project.id == sub.project_id).first()
    course   = db.query(Course).filter(Course.id == project.course_id).first()
    is_owner = sub.user_id == user.id
    if not is_owner and not _is_course_staff(course, user):
        raise HTTPException(403, "Access denied")
    if not Path(sub.file_path).exists():
        raise HTTPException(404, "File not found on disk")
    return FileResponse(
        path=sub.file_path,
        filename=sub.file_name or "submission",
        media_type=sub.mime_type or "application/octet-stream",
    )


# ══════════════════════════════════════════════════════════════════
#  Creator / Admin CRUD — Briefs
# ══════════════════════════════════════════════════════════════════

@router.post("/course/{course_id}", status_code=201, summary="Create project brief (creator/admin)")
async def create_project(
    course_id: int,
    payload: ProjectCreate,
    user: User  = Depends(require_creator_or_admin),
    db: Session = Depends(get_db),
):
    course = db.query(Course).filter(Course.id == course_id).first()
    if not course:
        raise HTTPException(404, "Course not found")
    if not user.is_admin() and course.creator_id != user.id:
        raise HTTPException(403, "Access denied")

    p = Project(
        title=payload.title,
        description=payload.description,
        rubric=payload.rubric,
        course_id=course_id,
        lesson_id=payload.lesson_id,
        due_date=payload.due_date,
        max_file_size_mb=payload.max_file_size_mb,
        allowed_formats=payload.allowed_formats,
    )
    db.add(p)
    db.commit()
    db.refresh(p)
    _invalidate_project_caches(p)
    return _serialize_project(p)


@router.put("/{project_id}", summary="Update project brief (creator/admin)")
async def update_project(
    project_id: int,
    payload: ProjectUpdate,
    user: User  = Depends(require_creator_or_admin),
    db: Session = Depends(get_db),
):
    p = db.query(Project).filter(Project.id == project_id).first()
    if not p:
        raise HTTPException(404, "Project not found")
    course = db.query(Course).filter(Course.id == p.course_id).first()
    if not user.is_admin() and course.creator_id != user.id:
        raise HTTPException(403, "Access denied")
    for k, v in payload.model_dump(exclude_none=True).items():
        setattr(p, k, v)
    db.commit()
    _invalidate_project_caches(p)
    return _serialize_project(p)


@router.delete("/{project_id}", summary="Delete project brief (creator/admin)")
async def delete_project(
    project_id: int,
    user: User  = Depends(require_creator_or_admin),
    db: Session = Depends(get_db),
):
    p = db.query(Project).filter(Project.id == project_id).first()
    if not p:
        raise HTTPException(404, "Project not found")
    course = db.query(Course).filter(Course.id == p.course_id).first()
    if not user.is_admin() and course.creator_id != user.id:
        raise HTTPException(403, "Access denied")
    p.is_active = False
    db.commit()
    _invalidate_project_caches(p)
    return {"message": "Project brief deactivated"}


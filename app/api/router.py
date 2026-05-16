"""
app/api/router.py
=================
Main API router — registers all v1 sub-routers under the configured prefix
(default: /api/v1).

Route groups
------------
/auth              – authentication (login, register, tokens)
/users             – user profile management
/courses           – course, lesson, topic CRUD + content upload
/enrollments       – enroll / unenroll / progress
/paths             – learning path enrollments
/quizzes           – topic-level interactive quizzes + AI grading
/lesson-assessments– classwork, homework, exam (new assessment system)
/assessments       – legacy assessment endpoint (backwards compat)
/projects          – course-level project briefs + submissions
/attendance        – schedule management + attendance tracking
/payments          – payment processing + Paystack integration
/admin             – admin-only operations
/creator           – creator dashboard
/partnership       – partner management
/messages          – direct messaging
/notifications     – push/in-app notifications
/ai                – AI assistant chat
/certificates      – certificate download
"""

from fastapi import APIRouter

from app.core.config import get_app_config

from app.api.v1.auth import router as auth_router
from app.api.v1.users import router as users_router
from app.api.v1.courses import router as courses_router
from app.api.v1.enrollments import router as enrollments_router
from app.api.v1.paths import router as  path_router
from app.api.v1.quizzes import router as quiz_router
from app.api.v1.lesson_assessments import router as lesson_assessments_router
# from app.api.v1.assessments import router as assessments_router
from app.api.v1.projects import router as projects_router
from app.api.v1.attendance import router as attendance_router
from app.api.v1.payments import router as payments_router
from app.api.v1.admin import router as admin_router
from app.api.v1.creator import router as creator_router
from app.api.v1.partnership import router as partnership_router
from app.api.v1.messaging import router as messaging_router, notif_router
from app.api.v1.ai_assistant import router as ai_router
from app.api.v1.certificates import router as cert_router

cfg    = get_app_config()
prefix = cfg.general_config.api_prefix   # /api/v1

v1_router = APIRouter(prefix=prefix)

# ── Core ──────────────────────────────────────────────────────────
v1_router.include_router(auth_router)
v1_router.include_router(users_router)
v1_router.include_router(courses_router)
v1_router.include_router(enrollments_router)
v1_router.include_router(path_router)

# ── Assessment layer ──────────────────────────────────────────────
v1_router.include_router(quiz_router)               # /quizzes
v1_router.include_router(lesson_assessments_router) # /lesson-assessments
# v1_router.include_router(assessments_router)        # /assessments (legacy)
v1_router.include_router(projects_router)           # /projects
v1_router.include_router(attendance_router)         # /attendance

# ── Commerce & admin ──────────────────────────────────────────────
v1_router.include_router(payments_router)
v1_router.include_router(admin_router)
v1_router.include_router(creator_router)
v1_router.include_router(partnership_router)

# ── Comms & AI ────────────────────────────────────────────────────
v1_router.include_router(messaging_router)
v1_router.include_router(notif_router)
v1_router.include_router(ai_router)

# ── Certificates ──────────────────────────────────────────────────
v1_router.include_router(cert_router)

"""
app/api/v1/router.py
====================
Assembles all v1 route modules into a single APIRouter.

Mounted in main.py as:
    app.include_router(v1_router, prefix="/api/v1")

Route prefixes (final URL = /api/v1 + prefix)
---------------------------------------------
/auth                  – authentication (login, register, tokens)
/users                 – user management
/courses               – course CRUD
/lessons               – lesson CRUD
/topics                – topic CRUD
/enrollments           – enrollment management
/payments              – payment processing
/categories            – course categories
/certificates          – certificate issuance
/partnerships          – partner management
/teams                 – team management
/notifications         – notifications
/admin                 – admin-only routes

Assessment layer (new)
/quizzes               – topic-level quizzes + AI grading
/lesson-assessments    – classwork / homework / exams
/projects              – course-level project briefs & submissions
/attendance            – schedules + attendance records + OTP check-in
/assessments           – LEGACY assessment routes (original system)
"""

from fastapi import APIRouter

# ── Pre-existing routers ──────────────────────────────────────────
from app.api.v1 import (
    auth,
    users,
    courses,
    lessons,
    topics,
    enrollments,
    payments,
    categories,
    certificates,
    partnerships,
    teams,
    notifications,
    admin,
)

# ── Assessment layer routers ──────────────────────────────────────
from app.api.v1 import (
    quizzes,
    lesson_assessments,
    projects,
    attendance,
    # assessments as legacy_assessments,   # original legacy system
)

v1_router = APIRouter()

# ── Register pre-existing routes ─────────────────────────────────
v1_router.include_router(auth.router)
v1_router.include_router(users.router)
v1_router.include_router(courses.router)
v1_router.include_router(lessons.router)
v1_router.include_router(topics.router)
v1_router.include_router(enrollments.router)
v1_router.include_router(payments.router)
v1_router.include_router(categories.router)
v1_router.include_router(certificates.router)
v1_router.include_router(partnerships.router)
v1_router.include_router(teams.router)
v1_router.include_router(notifications.router)
v1_router.include_router(admin.router)

# ── Register assessment layer routes ─────────────────────────────
v1_router.include_router(quizzes.router)
v1_router.include_router(lesson_assessments.router)
v1_router.include_router(projects.router)
v1_router.include_router(attendance.router)
# v1_router.include_router(legacy_assessments.router)

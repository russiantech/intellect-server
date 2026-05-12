# Intellect LMS — Backend Server

FastAPI backend for the Intellect Learning Management System.

## Stack
- **FastAPI** + **SQLAlchemy 2.0** (ORM)
- **PostgreSQL** (production) / SQLite (dev/test)
- **Alembic** (migrations)
- **Paystack** (payments + subscriptions)
- **Resend** (email)
- **Anthropic/OpenAI** (AI grading assistant)

## Quick Start

```bash
# 1. Create virtual environment
python -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Configure environment
cp .env.example .env
# Edit .env with your database URL, Paystack keys, etc.

# 4. Run migrations
alembic upgrade head
# OR for dev (auto-creates tables):
python main.py  # creates tables on startup

# 5. Seed database
python seed.py

# 6. Start server
python main.py
# OR with uvicorn directly:
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

## API Documentation
Once running, visit:
- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc

## Project Structure
```
server/
├── app/
│   ├── api/v1/           # Route handlers (auth, courses, enrollments, payments, admin...)
│   ├── models/           # SQLAlchemy models split by domain
│   │   ├── base.py       # TimestampMixin (is_active, is_deleted, created_at, updated_at)
│   │   ├── users.py      # User, Role, BrandConfig, EmailToken
│   │   ├── courses.py    # Course, Lesson, Topic, TopicContent, Category, Tag, LearningPath,
│   │   │                 # SubscriptionPlan, user_topic_progress (association table)
│   │   ├── payments.py   # Payment, Enrollment, PathEnrollment, Discount
│   │   └── misc.py       # Assessment, Certificate, Schedule, Messaging, Partnership, Team
│   ├── schemas/          # Pydantic request/response schemas split by domain
│   ├── services/         # Email, PDF certificate generation, AI grading
│   ├── core/             # Config (YAML-based), security (JWT)
│   ├── db/               # SQLAlchemy engine, session, Base
│   └── utils/responses.py# Standardised api_response() helper
├── migrations/           # Alembic migration files
├── uploads/              # Media storage (avatars, certificates, course media)
├── main.py               # FastAPI app entrypoint
├── seed.py               # Database seeder
├── requirements.txt      # Python dependencies
└── .env.example          # Environment variable template
```

## Key Features
- **Authentication**: JWT access + refresh tokens, email verification
- **Courses**: Full CRUD, lessons → topics → content (video/PDF/text/HTML/quiz/link)
- **Subscriptions**: Paystack `PLN_xxx` plan integration, weekly/monthly/yearly intervals
- **Content Throttling**: Admin-configurable weekly/monthly topic limits per enrollment
- **Learning Paths**: Group courses into paths; path-level certificate on 100% completion
- **Certificates**: Auto-issued on course/path completion; PDF generation via ReportLab
- **Assessments**: MCQ, true/false, short-answer, essay; auto-grading + AI feedback
- **Payments**: One-time, pay-as-you-go, subscription; Paystack webhook handler
- **Admin Panel**: Full CRUD on users, courses, paths, enrollments, discounts, broadcasts
- **Partnerships**: B2B org management with student allocation and revenue tracking
- **Messaging**: Direct messages + notifications + admin broadcasts
- **AI Assistant**: Grading assistance via Anthropic Claude / OpenAI

## Paystack Subscription Flow
1. Admin creates `SubscriptionPlan` → system creates Paystack plan (`PLN_xxx`)
2. Student calls `POST /payments/initiate` with `plan_id`
3. Student redirected to Paystack checkout → subscribes to plan
4. `POST /payments/webhook/paystack` handles:
   - `charge.success` → enroll student
   - `subscription.create` → record `subscription_code`
   - `subscription.disable` / `invoice.payment_failed` → suspend enrollment
   - `invoice.update` → update `next_payment_date`

## Content Throttling
Set on Course: `throttle_enabled=true`, `weekly_topic_limit=3`, `monthly_topic_limit=10`
Students hitting `POST /enrollments/progress` get HTTP 429 when limit exceeded,
with message showing when their limit resets.

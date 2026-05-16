# """
# Intellect LMS — Payments API  v3

# Changes vs v2
# ─────────────────────────────────────────────────────────────────────────────
# 1.  access_code RETURNED  — _paystack_init now returns the full Paystack
#     data dict (authorization_url + access_code + reference).  Both the
#     initiate and the subscription branches include access_code in the
#     response so the frontend inline SDK can call PopSetup({ accessCode })
#     instead of redirecting.  Without access_code the SDK has no transaction
#     to open and falls back to window.location — this was the redirect bug.

# 2.  verify endpoint accepts EITHER tx_ref OR reference  — Paystack returns
#     the field as "reference" in the inline callback; the old endpoint only
#     matched Payment.tx_ref == payload.tx_ref.  A PaymentVerify schema with
#     an alias keeps both names working.

# 3.  Email is FIRE-AND-FORGET in both verify and webhook  — send_email() in
#     email_service.py already catches and logs exceptions but the background
#     task runner can still surface them.  The verify endpoint now wraps the
#     background_tasks.add_task call in a try/except and never lets an email
#     error change the HTTP response.

# 4.  _send_resend hardened  — the resend library raises on 4xx (including
#     401 invalid API key).  _send_resend already catches Exception and
#     returns False; send_email propagates that False but never raises, so
#     callers that do `if not send_email(...)` work correctly.  No change
#     needed in email_service.py — the existing try/except is sufficient once
#     the payments endpoint stops letting the background task propagate.

# 5.  Free-enroll path returns consistent shape  — added authorization_url: ""
#     and access_code: "" to the free-enroll response so the frontend does not
#     need a special branch.
# ─────────────────────────────────────────────────────────────────────────────
# """

# import uuid
# import hmac
# import hashlib
# import json
# import logging
# import httpx
# from typing import Optional
# from datetime import datetime, timezone, timedelta
# from fastapi import APIRouter, Depends, HTTPException, Query, Request, BackgroundTasks
# from sqlalchemy.orm import Session

# from app.db.database import get_db
# from app.models import (
#     Payment, Course, LearningPath, Enrollment, PathEnrollment,
#     Discount, User, BrandConfig, Partnership, SubscriptionPlan,
# )
# from app.models.payments import PaymentStatus, EnrollmentStatus
# from app.models.courses import PaymentType, CourseStatus
# from app.schemas import (
#     InitiatePayment, PaymentVerify, DiscountCreate, DiscountValidate,
#     SubscriptionPlanCreate, SuccessResponse,
# )
# from app.api.deps.auth import get_current_user, get_current_verified_user, require_admin
# from app.core.config import get_app_config
# from app.services.email_service import send_enrollment_confirmation
# from app.utils.responses import api_response

# router = APIRouter(prefix="/payments", tags=["Payments"])
# logger = logging.getLogger(__name__)


# # ─────────────────────────────────────────────────────────────────────────────
# #  Internal helpers
# # ─────────────────────────────────────────────────────────────────────────────

# def _paystack_headers():
#     cfg = get_app_config()
#     return {
#         "Authorization": f"Bearer {cfg.payments_config.paystack.secret_key}",
#         "Content-Type":  "application/json",
#     }


# def _get_revenue_split(course, db):
#     brand = db.query(BrandConfig).filter(BrandConfig.id == 1).first()
#     dc = brand.default_creator_pct  if brand else 70.0
#     dp = brand.default_platform_pct if brand else 30.0
#     if course and course.creator_pct is not None:
#         return course.creator_pct, course.platform_pct or (100 - course.creator_pct)
#     return dc, dp


# def _apply_discount(code, course_id, path_id, price, db):
#     d = db.query(Discount).filter(
#         Discount.code == code.upper(),
#         Discount.is_active == True,
#     ).first()
#     if not d:
#         return price, None
#     now = datetime.now(timezone.utc)
#     if d.valid_from  and d.valid_from  > now: return price, None
#     if d.valid_until and d.valid_until < now: return price, None
#     if d.max_uses    and d.used_count >= d.max_uses: return price, None
#     if d.applies_to == "course" and d.course_id != course_id: return price, None
#     if d.applies_to == "path"   and d.path_id   != path_id:   return price, None
#     final = (
#         price * (1 - d.value / 100)
#         if d.discount_type == "percentage"
#         else max(0, price - d.value)
#     )
#     return round(final, 2), d


# async def _paystack_create_plan(name, amount, interval, currency="NGN"):
#     try:
#         async with httpx.AsyncClient(timeout=15) as c:
#             r = await c.post(
#                 "https://api.paystack.co/plan",
#                 headers=_paystack_headers(),
#                 json={
#                     "name":     name,
#                     "interval": interval,
#                     "amount":   int(amount * 100),
#                     "currency": currency,
#                 },
#             )
#             data = r.json()
#             if data.get("status"):
#                 return data["data"]["plan_code"]
#     except Exception as e:
#         logger.error("Paystack create-plan error: %s", e)
#     return None


# async def _paystack_init(
#     email: str,
#     amount: float,
#     tx_ref: str,
#     callback_url: str,
#     plan_code: str | None = None,
#     metadata: dict | None = None,
# ) -> dict | None:
#     """
#     Call Paystack /transaction/initialize and return the full data dict:
#         {
#             "authorization_url": "https://checkout.paystack.com/...",
#             "access_code":       "xxxxxxxxxxxxxxxx",   ← required by inline SDK
#             "reference":         "ILT-XXXX",
#         }
#     Returns None on any error.
#     """
#     payload: dict = {
#         "email":        email,
#         "amount":       int(amount * 100),   # Paystack expects kobo
#         "reference":    tx_ref,
#         "callback_url": callback_url,
#     }
#     if plan_code: payload["plan"]     = plan_code
#     if metadata:  payload["metadata"] = metadata

#     try:
#         async with httpx.AsyncClient(timeout=15) as c:
#             r = await c.post(
#                 "https://api.paystack.co/transaction/initialize",
#                 headers=_paystack_headers(),
#                 json=payload,
#             )
#             data = r.json()
#             if data.get("status"):
#                 # Return the full nested data dict — includes access_code
#                 return data["data"]
#     except Exception as e:
#         logger.error("Paystack init error: %s", e)
#     return None


# def _enroll_after_payment(
#     user_id:           int,
#     course_id:         int | None,
#     path_id:           int | None,
#     db:                Session,
#     payment_type:      str | None = None,
#     access_period_days: int = 30,
# ):
#     """
#     Create or reactivate enrollment records after a successful payment.

#     For pay_as_you_go: valid_until is set to now + access_period_days.
#     If the enrollment already has a future valid_until the window is
#     extended from that date (top-up behaviour).
#     """
#     if course_id:
#         enrollment = db.query(Enrollment).filter(
#             Enrollment.user_id   == user_id,
#             Enrollment.course_id == course_id,
#         ).first()

#         if not enrollment:
#             enrollment = Enrollment(user_id=user_id, course_id=course_id)
#             db.add(enrollment)
#             db.flush()

#         if payment_type in (PaymentType.pay_as_you_go.value, "pay_as_you_go"):
#             now            = datetime.now(timezone.utc)
#             current_expiry = getattr(enrollment, "valid_until", None)
#             base           = (
#                 current_expiry
#                 if (current_expiry and current_expiry > now)
#                 else now
#             )
#             try:
#                 enrollment.valid_until = base + timedelta(days=access_period_days)
#             except Exception:
#                 pass  # column not yet migrated — skip silently

#         if getattr(enrollment, "status", None) == EnrollmentStatus.suspended:
#             enrollment.status = EnrollmentStatus.active

#     if path_id:
#         path = db.query(LearningPath).filter(LearningPath.id == path_id).first()
#         if path:
#             pe = db.query(PathEnrollment).filter(
#                 PathEnrollment.user_id == user_id,
#                 PathEnrollment.path_id == path_id,
#             ).first()
#             if not pe:
#                 pe = PathEnrollment(user_id=user_id, path_id=path_id)
#                 db.add(pe)
#                 db.flush()
#             for c in path.courses:
#                 if not db.query(Enrollment).filter(
#                     Enrollment.user_id   == user_id,
#                     Enrollment.course_id == c.id,
#                 ).first():
#                     db.add(Enrollment(
#                         user_id=user_id,
#                         course_id=c.id,
#                         path_enrollment_id=pe.id,
#                     ))


# def _safe_send_confirmation(
#     background_tasks: BackgroundTasks,
#     user_email: str,
#     user_name: str,
#     course_title: str,
#     course_url: str,
# ) -> None:
#     """
#     Schedule an enrollment confirmation email as a background task.

#     Email failures (Resend 401, SMTP timeout, template error, etc.) must
#     NEVER affect the HTTP response for a payment or enrollment endpoint.
#     We wrap add_task itself in try/except so even a misconfigured background
#     task runner cannot surface as a 500 to the client.
#     """
#     try:
#         background_tasks.add_task(
#             send_enrollment_confirmation,
#             user_email,
#             user_name,
#             course_title,
#             course_url,
#         )
#     except Exception as exc:
#         # Log but swallow — the student is already enrolled.
#         logger.warning(
#             "Could not schedule enrollment confirmation email (non-fatal): %s", exc,
#             exc_info=True,
#         )


# # ─────────────────────────────────────────────────────────────────────────────
# #  Subscription Plans (Admin)
# # ─────────────────────────────────────────────────────────────────────────────

# @router.get("/plans")
# async def list_subscription_plans(
#     course_id: Optional[int] = None,
#     path_id:   Optional[int] = None,
#     db:        Session = Depends(get_db),
# ):
#     q = db.query(SubscriptionPlan).filter(SubscriptionPlan.is_active == True)
#     if course_id: q = q.filter(SubscriptionPlan.course_id == course_id)
#     if path_id:   q = q.filter(SubscriptionPlan.path_id   == path_id)
#     return api_response(True, "Plans fetched", [
#         {
#             "id":                  p.id,
#             "name":                p.name,
#             "paystack_plan_code":  p.paystack_plan_code,
#             "interval":            p.interval,
#             "amount":              p.amount,
#             "currency":            p.currency,
#             "course_id":           p.course_id,
#             "path_id":             p.path_id,
#         }
#         for p in q.all()
#     ])


# @router.post("/plans", dependencies=[Depends(require_admin)], status_code=201)
# async def create_subscription_plan(
#     payload: SubscriptionPlanCreate,
#     db:      Session = Depends(get_db),
# ):
#     plan_code = await _paystack_create_plan(
#         payload.name, payload.amount, payload.interval.value, payload.currency,
#     )
#     plan = SubscriptionPlan(
#         name=payload.name, paystack_plan_code=plan_code,
#         interval=payload.interval, amount=payload.amount, currency=payload.currency,
#         course_id=payload.course_id, path_id=payload.path_id,
#     )
#     db.add(plan)
#     db.commit()
#     db.refresh(plan)
#     return api_response(True, "Plan created", {
#         "id":                 plan.id,
#         "paystack_plan_code": plan.paystack_plan_code,
#         "name":               plan.name,
#         "interval":           plan.interval,
#     }, status_code=201)


# @router.put("/plans/{plan_id}", dependencies=[Depends(require_admin)])
# async def update_subscription_plan(
#     plan_id:   int,
#     name:      Optional[str]  = None,
#     is_active: Optional[bool] = None,
#     db:        Session = Depends(get_db),
# ):
#     plan = db.query(SubscriptionPlan).filter(SubscriptionPlan.id == plan_id).first()
#     if not plan:
#         raise HTTPException(404, "Plan not found")
#     if name      is not None: plan.name      = name
#     if is_active is not None: plan.is_active = is_active
#     db.commit()
#     return api_response(True, "Plan updated")


# @router.delete("/plans/{plan_id}", dependencies=[Depends(require_admin)])
# async def delete_subscription_plan(plan_id: int, db: Session = Depends(get_db)):
#     plan = db.query(SubscriptionPlan).filter(SubscriptionPlan.id == plan_id).first()
#     if not plan:
#         raise HTTPException(404, "Plan not found")
#     plan.is_active = False
#     plan.is_deleted = True
#     db.commit()
#     return api_response(True, "Plan deleted")


# # ─────────────────────────────────────────────────────────────────────────────
# #  Initiate payment
# # ─────────────────────────────────────────────────────────────────────────────

# @router.post("/initiate")
# async def initiate_payment(
#     payload: InitiatePayment,
#     user:    User    = Depends(get_current_verified_user),
#     db:      Session = Depends(get_db),
# ):
#     """
#     Initiate a Paystack transaction for a course or learning path.

#     Response always includes:
#         authorization_url  — Paystack hosted checkout (redirect fallback)
#         access_code        — opaque token for PaystackPop.setup({ accessCode })
#                              THIS is what the inline SDK needs; without it the
#                              frontend has no choice but to redirect.
#         tx_ref             — our internal reference stored in Payment.tx_ref
#         payment_type       — effective billing model
#         amount             — final amount in NGN (after discount + instructor fee)

#     Callback URL:
#         Uses payload.callback_url when it begins with the configured
#         frontend URL (open-redirect guard).  Falls back to /payment/callback.

#     Pay-as-you-go:
#         access_period_days is stored in Paystack metadata so the verify
#         endpoint and webhook can both extend valid_until correctly even if
#         the DB value changes between payment and verification.
#     """
#     cfg            = get_app_config()
#     frontend_base  = cfg.hosting_config.frontend_url.rstrip("/")

#     # ── Safe callback URL ────────────────────────────────────────────────────
#     if payload.callback_url and payload.callback_url.startswith(frontend_base):
#         callback_url = payload.callback_url
#     else:
#         callback_url = f"{frontend_base}/payment/callback"

#     course = path = None
#     price  = 0.0
#     access_period_days = 30

#     if payload.course_id:
#         course = db.query(Course).filter(
#             Course.id == payload.course_id,
#             Course.is_active == True,
#         ).first()
#         if not course:
#             raise HTTPException(404, "Course not found")
#         price              = float(course.fee or 0)
#         access_period_days = int(getattr(course, "access_period_days", None) or 30)

#     if payload.path_id:
#         path = db.query(LearningPath).filter(
#             LearningPath.id == payload.path_id,
#             LearningPath.is_active == True,
#         ).first()
#         if not path:
#             raise HTTPException(404, "Learning path not found")
#         price = float(path.fee or 0)

#     # ── Discount ─────────────────────────────────────────────────────────────
#     if payload.discount_code:
#         price, disc = _apply_discount(
#             payload.discount_code, payload.course_id, payload.path_id, price, db,
#         )
#         if disc:
#             disc.used_count = (disc.used_count or 0) + 1

#     # ── Instructor-led uplift ─────────────────────────────────────────────────
#     instructor_led        = bool(getattr(payload, "instructor_led", False))
#     instructor_led_amount = 0.0
#     if instructor_led and course:
#         instructor_led_amount = float(getattr(course, "instructor_led_fee", 0) or 0)
#         price = round(price + instructor_led_amount, 2)

#     # ── Effective payment type ────────────────────────────────────────────────
#     eff_type = (
#         payload.payment_type
#         or (course.payment_type if course else None)
#         or (path.payment_type   if path   else None)
#         or PaymentType.one_time
#     )

#     # ── Free enroll (price == 0 or type == free) ──────────────────────────────
#     if price == 0 or eff_type == PaymentType.free:
#         _enroll_after_payment(user.id, payload.course_id, payload.path_id, db)
#         db.commit()
#         # Return a consistent shape so the frontend needs no special branch
#         return api_response(True, "Enrolled for free", {
#             "enrolled":          True,
#             "authorization_url": "",
#             "access_code":       "",
#             "tx_ref":            "",
#             "payment_type":      eff_type.value if hasattr(eff_type, "value") else str(eff_type),
#             "amount":            0,
#         })

#     # ── Build metadata stored in Paystack (survives webhook round-trips) ──────
#     metadata = {
#         "course_id":             payload.course_id,
#         "path_id":               payload.path_id,
#         "instructor_led":        instructor_led,
#         "instructor_led_amount": instructor_led_amount,
#         "access_period_days":    access_period_days,
#     }

#     tx_ref   = f"ILT-{uuid.uuid4().hex[:16].upper()}"
#     cp, pp   = _get_revenue_split(course, db)

#     # ── Subscription with explicit plan ───────────────────────────────────────
#     if eff_type == PaymentType.subscription and getattr(payload, "plan_id", None):
#         plan = db.query(SubscriptionPlan).filter(
#             SubscriptionPlan.id       == payload.plan_id,
#             SubscriptionPlan.is_active == True,
#         ).first()
#         if not plan:
#             raise HTTPException(404, "Subscription plan not found")
#         if not plan.paystack_plan_code:
#             raise HTTPException(400, "Plan not yet synced with Paystack")

#         ps = await _paystack_init(
#             user.email, plan.amount, tx_ref, callback_url,
#             plan_code=plan.paystack_plan_code, metadata=metadata,
#         )
#         if not ps:
#             raise HTTPException(502, "Payment gateway error — please try again")

#         payment = Payment(
#             tx_ref=tx_ref, tx_status=PaymentStatus.pending,
#             amount=plan.amount, currency=plan.currency,
#             provider="paystack", payment_type="subscription",
#             paystack_plan_code=plan.paystack_plan_code,
#             creator_amount=round(plan.amount * cp / 100, 2),
#             platform_amount=round(plan.amount * pp / 100, 2),
#             user_id=user.id, course_id=payload.course_id, path_id=payload.path_id,
#         )
#         db.add(payment)
#         db.commit()

#         return api_response(True, "Subscription initiated", {
#             # ✅ Both keys returned so frontend inline SDK can use access_code
#             "authorization_url": ps["authorization_url"],
#             "access_code":       ps.get("access_code", ""),
#             "tx_ref":            tx_ref,
#             "payment_type":      "subscription",
#             "plan_code":         plan.paystack_plan_code,
#             "interval":          plan.interval,
#             "amount":            plan.amount,
#         })

#     # ── One-time / pay-as-you-go ──────────────────────────────────────────────
#     ps = await _paystack_init(user.email, price, tx_ref, callback_url, metadata=metadata)
#     if not ps:
#         raise HTTPException(502, "Payment gateway error — please try again")

#     # Count existing successful PAYG installments for this user + course
#     installment = None
#     if eff_type in (PaymentType.pay_as_you_go, "pay_as_you_go"):
#         installment = (
#             db.query(Payment)
#             .filter(
#                 Payment.user_id      == user.id,
#                 Payment.course_id    == payload.course_id,
#                 Payment.tx_status    == PaymentStatus.successful,
#                 Payment.payment_type == "pay_as_you_go",
#             )
#             .count()
#         ) + 1

#     payment = Payment(
#         tx_ref=tx_ref, tx_status=PaymentStatus.pending,
#         amount=price, currency="NGN",
#         provider="paystack",
#         payment_type=eff_type.value if hasattr(eff_type, "value") else str(eff_type),
#         installment_number=installment,
#         creator_amount=round(price * cp / 100, 2),
#         platform_amount=round(price * pp / 100, 2),
#         user_id=user.id, course_id=payload.course_id, path_id=payload.path_id,
#     )
#     db.add(payment)
#     db.commit()

#     return api_response(True, "Payment initiated", {
#         # access_code is the critical field for the inline SDK
#         "authorization_url":  ps["authorization_url"],
#         "access_code":        ps.get("access_code", ""),
#         "tx_ref":             tx_ref,
#         "payment_type":       eff_type.value if hasattr(eff_type, "value") else str(eff_type),
#         "amount":             price,
#         "access_period_days": access_period_days if str(eff_type) == "pay_as_you_go" else None,
#     })


# # ─────────────────────────────────────────────────────────────────────────────
# #  Verify payment
# # ─────────────────────────────────────────────────────────────────────────────

# @router.post("/verify")
# async def verify_payment(
#     payload:          PaymentVerify,
#     background_tasks: BackgroundTasks,
#     user:             User    = Depends(get_current_user),
#     db:               Session = Depends(get_db),
# ):
#     """
#     Verify a Paystack transaction by reference and enroll the user.

#     Accepts the reference under EITHER field name:
#         payload.tx_ref    — our internal reference (ILT-XXXX…)
#         payload.reference — Paystack's own reference field (same value,
#                             but Paystack's inline SDK callback uses "reference")

#     Email confirmation is scheduled as a background task and is
#     FIRE-AND-FORGET — a Resend 401 or any SMTP error must never change
#     this endpoint's HTTP response.
#     """
#     # Accept both field names — whichever the client sends
#     reference = getattr(payload, "reference", None) or getattr(payload, "tx_ref", None)
#     if not reference:
#         raise HTTPException(400, "reference is required")

#     payment = db.query(Payment).filter(
#         Payment.tx_ref  == reference,
#         Payment.user_id == user.id,
#     ).first()
#     if not payment:
#         raise HTTPException(404, "Transaction not found")
#     if payment.tx_status == PaymentStatus.successful:
#         # Idempotent — already verified, return success
#         return api_response(True, "Already verified", {"paid": True, "status": "success"})

#     # ── Verify with Paystack ──────────────────────────────────────────────────
#     try:
#         async with httpx.AsyncClient(timeout=15) as c:
#             r = await c.get(
#                 f"https://api.paystack.co/transaction/verify/{reference}",
#                 headers=_paystack_headers(),
#             )
#             data = r.json()
#     except Exception as e:
#         logger.error("Paystack verify network error: %s", e)
#         raise HTTPException(502, "Could not reach payment gateway")

#     if not data.get("status") or data["data"]["status"] != "success":
#         payment.tx_status = PaymentStatus.failed
#         db.commit()
#         raise HTTPException(402, "Payment not successful")

#     ps = data["data"]

#     payment.tx_id     = str(ps.get("id", ""))
#     payment.tx_status = PaymentStatus.successful

#     if ps.get("plan"):
#         payment.paystack_plan_code = ps["plan"].get("plan_code")
#     if ps.get("subscription_code"):
#         payment.subscription_code = ps["subscription_code"]

#     # Pull access_period_days from metadata — safe even if key absent
#     meta               = ps.get("metadata") or {}
#     access_period_days = int(meta.get("access_period_days") or 30)

#     _enroll_after_payment(
#         user.id, payment.course_id, payment.path_id, db,
#         payment_type=payment.payment_type,
#         access_period_days=access_period_days,
#     )
#     db.commit()

#     # ── Email — fire and forget ───────────────────────────────────────────────
#     if payment.course_id:
#         c_obj = db.query(Course).filter(Course.id == payment.course_id).first()
#         if c_obj:
#             cfg = get_app_config()
#             _safe_send_confirmation(
#                 background_tasks,
#                 user.email,
#                 user.name or user.username or "",
#                 c_obj.title,
#                 f"{cfg.hosting_config.frontend_url.rstrip('/')}/learn/{c_obj.slug}",
#             )

#     return api_response(True, "Payment verified — enrolled successfully", {
#         "paid":   True,
#         "status": "success",
#     })


# # ─────────────────────────────────────────────────────────────────────────────
# #  Paystack webhook
# # ─────────────────────────────────────────────────────────────────────────────

# @router.post("/webhook/paystack")
# async def paystack_webhook(
#     request:          Request,
#     background_tasks: BackgroundTasks,
#     db:               Session = Depends(get_db),
# ):
#     cfg    = get_app_config()
#     secret = cfg.payments_config.paystack.secret_key
#     body   = await request.body()
#     sig    = request.headers.get("x-paystack-signature", "")

#     if not hmac.compare_digest(
#         sig,
#         hmac.new(secret.encode(), body, hashlib.sha512).hexdigest(),
#     ):
#         raise HTTPException(400, "Invalid signature")

#     try:
#         event = json.loads(body)
#     except Exception:
#         raise HTTPException(400, "Invalid JSON")

#     ev   = event.get("event")
#     data = event.get("data", {})
#     ref  = data.get("reference") or data.get("transaction", {}).get("reference")
#     logger.info("Paystack webhook: %s ref=%s", ev, ref)

#     if ev == "charge.success":
#         p = db.query(Payment).filter(Payment.tx_ref == ref).first()
#         if p and p.tx_status != PaymentStatus.successful:
#             p.tx_id     = str(data.get("id", ""))
#             p.tx_status = PaymentStatus.successful

#             if data.get("plan"):
#                 p.paystack_plan_code = data["plan"].get("plan_code")
#             if data.get("subscription_code"):
#                 p.subscription_code = data["subscription_code"]

#             meta               = data.get("metadata") or {}
#             access_period_days = int(meta.get("access_period_days") or 30)

#             _enroll_after_payment(
#                 p.user_id, p.course_id, p.path_id, db,
#                 payment_type=p.payment_type,
#                 access_period_days=access_period_days,
#             )
#             db.commit()

#             # ── Email — fire and forget in webhook too ────────────────────────
#             if p.course_id:
#                 c_obj = db.query(Course).filter(Course.id == p.course_id).first()
#                 u_obj = db.query(User).filter(User.id == p.user_id).first()
#                 if c_obj and u_obj:
#                     cfg2 = get_app_config()
#                     _safe_send_confirmation(
#                         background_tasks,
#                         u_obj.email,
#                         u_obj.name or u_obj.username or "",
#                         c_obj.title,
#                         f"{cfg2.hosting_config.frontend_url.rstrip('/')}/learn/{c_obj.slug}",
#                     )

#     elif ev == "subscription.create":
#         sub_code  = data.get("subscription_code")
#         email     = data.get("customer", {}).get("email")
#         plan_code = data.get("plan", {}).get("plan_code")
#         if sub_code and email:
#             p = db.query(Payment).filter(Payment.subscription_code == sub_code).first()
#             if not p:
#                 u = db.query(User).filter(User.email == email).first()
#                 if u:
#                     p = (
#                         db.query(Payment)
#                         .filter(
#                             Payment.user_id            == u.id,
#                             Payment.paystack_plan_code == plan_code,
#                         )
#                         .order_by(Payment.created_at.desc())
#                         .first()
#                     )
#             if p:
#                 p.subscription_code  = sub_code
#                 p.subscription_token = data.get("email_token")
#                 nxt = data.get("next_payment_date")
#                 if nxt:
#                     try:
#                         p.next_payment_date = datetime.fromisoformat(
#                             nxt.replace("Z", "+00:00")
#                         )
#                     except Exception:
#                         pass
#                 db.commit()

#     elif ev in ("subscription.disable", "invoice.payment_failed"):
#         sub_code = (
#             data.get("subscription", {}).get("subscription_code")
#             or data.get("subscription_code")
#         )
#         if sub_code:
#             p = db.query(Payment).filter(Payment.subscription_code == sub_code).first()
#             if p and p.course_id:
#                 enr = db.query(Enrollment).filter(
#                     Enrollment.user_id   == p.user_id,
#                     Enrollment.course_id == p.course_id,
#                 ).first()
#                 if enr:
#                     enr.status = EnrollmentStatus.suspended
#                     db.commit()

#     elif ev == "invoice.update":
#         sub_code = data.get("subscription", {}).get("subscription_code")
#         nxt      = data.get("subscription", {}).get("next_payment_date")
#         if sub_code and nxt:
#             p = db.query(Payment).filter(Payment.subscription_code == sub_code).first()
#             if p:
#                 try:
#                     p.next_payment_date = datetime.fromisoformat(
#                         nxt.replace("Z", "+00:00")
#                     )
#                     db.commit()
#                 except Exception:
#                     pass

#     return {"received": True}


# # ─────────────────────────────────────────────────────────────────────────────
# #  Discounts
# # ─────────────────────────────────────────────────────────────────────────────

# @router.post("/discounts", dependencies=[Depends(require_admin)], status_code=201)
# async def create_discount(payload: DiscountCreate, db: Session = Depends(get_db)):
#     if db.query(Discount).filter(Discount.code == payload.code.upper()).first():
#         raise HTTPException(400, "Code already exists")
#     d = Discount(
#         code=payload.code.upper(), description=payload.description,
#         discount_type=payload.discount_type, value=payload.value,
#         max_uses=payload.max_uses, valid_from=payload.valid_from,
#         valid_until=payload.valid_until, applies_to=payload.applies_to,
#         course_id=payload.course_id, path_id=payload.path_id,
#     )
#     db.add(d)
#     db.commit()
#     db.refresh(d)
#     return api_response(True, "Discount created", {"id": d.id, "code": d.code}, status_code=201)


# @router.post("/discounts/validate")
# async def validate_discount(payload: DiscountValidate, db: Session = Depends(get_db)):
#     price = 0.0
#     if payload.course_id:
#         c = db.query(Course).filter(Course.id == payload.course_id).first()
#         if c: price = float(c.fee or 0)
#     elif payload.path_id:
#         p = db.query(LearningPath).filter(LearningPath.id == payload.path_id).first()
#         if p: price = float(p.fee or 0)
#     final, d = _apply_discount(payload.code, payload.course_id, payload.path_id, price, db)
#     if not d:
#         return api_response(True, "Discount info", {
#             "valid":   False,
#             "message": "Invalid, expired, or inapplicable.",
#         })
#     return api_response(True, "Discount valid", {
#         "valid":          True,
#         "discount_type":  d.discount_type,
#         "value":          d.value,
#         "original_price": price,
#         "final_price":    final,
#         "savings":        round(price - final, 2),
#         "message":        f"Save ₦{price - final:,.2f}",
#     })


# @router.get("/discounts", dependencies=[Depends(require_admin)])
# async def list_discounts(
#     page:     int = Query(1, ge=1),
#     per_page: int = Query(20),
#     db:       Session = Depends(get_db),
# ):
#     q     = db.query(Discount).filter(Discount.is_active == True)
#     total = q.count()
#     items = (
#         q.order_by(Discount.created_at.desc())
#         .offset((page - 1) * per_page)
#         .limit(per_page)
#         .all()
#     )
#     return api_response(True, "Discounts fetched", {
#         "items": [
#             {
#                 "id":            d.id,
#                 "code":          d.code,
#                 "discount_type": d.discount_type,
#                 "value":         d.value,
#                 "max_uses":      d.max_uses,
#                 "used_count":    d.used_count,
#                 "valid_from":    d.valid_from,
#                 "valid_until":   d.valid_until,
#                 "applies_to":    d.applies_to,
#             }
#             for d in items
#         ],
#         "total": total,
#         "page":  page,
#         "pages": (total + per_page - 1) // per_page,
#     })


# @router.delete("/discounts/{discount_id}", dependencies=[Depends(require_admin)])
# async def delete_discount(discount_id: int, db: Session = Depends(get_db)):
#     d = db.query(Discount).filter(Discount.id == discount_id).first()
#     if not d:
#         raise HTTPException(404, "Not found")
#     d.is_active  = False
#     d.is_deleted = True
#     db.commit()
#     return api_response(True, "Deleted")


# # ─────────────────────────────────────────────────────────────────────────────
# #  Payment history
# # ─────────────────────────────────────────────────────────────────────────────

# @router.get("/my-payments")
# async def my_payments(
#     page:     int  = Query(1, ge=1),
#     per_page: int  = Query(20),
#     user:     User = Depends(get_current_user),
#     db:       Session = Depends(get_db),
# ):
#     q     = db.query(Payment).filter(Payment.user_id == user.id)
#     total = q.count()
#     items = (
#         q.order_by(Payment.created_at.desc())
#         .offset((page - 1) * per_page)
#         .limit(per_page)
#         .all()
#     )
#     return api_response(True, "Payment history", {
#         "items": [
#             {
#                 "id":                  p.id,
#                 "tx_ref":              p.tx_ref,
#                 "tx_status":           p.tx_status,
#                 "amount":              p.amount,
#                 "currency":            p.currency,
#                 "payment_type":        p.payment_type,
#                 "course_id":           p.course_id,
#                 "path_id":             p.path_id,
#                 "paystack_plan_code":  p.paystack_plan_code,
#                 "next_payment_date":   p.next_payment_date,
#                 "created_at":          p.created_at,
#             }
#             for p in items
#         ],
#         "total": total,
#         "page":  page,
#     })


# @router.get("/admin/all", dependencies=[Depends(require_admin)])
# async def admin_all_payments(
#     page:     int           = Query(1),
#     per_page: int           = Query(50),
#     status:   Optional[str] = None,
#     db:       Session = Depends(get_db),
# ):
#     q = db.query(Payment)
#     if status:
#         q = q.filter(Payment.tx_status == status)
#     total = q.count()
#     items = (
#         q.order_by(Payment.created_at.desc())
#         .offset((page - 1) * per_page)
#         .limit(per_page)
#         .all()
#     )
#     return api_response(True, "All payments", {
#         "items": [
#             {
#                 "id":                p.id,
#                 "tx_ref":            p.tx_ref,
#                 "tx_id":             p.tx_id,
#                 "tx_status":         p.tx_status,
#                 "amount":            p.amount,
#                 "payment_type":      p.payment_type,
#                 "user_id":           p.user_id,
#                 "course_id":         p.course_id,
#                 "path_id":           p.path_id,
#                 "creator_amount":    p.creator_amount,
#                 "platform_amount":   p.platform_amount,
#                 "subscription_code": p.subscription_code,
#                 "next_payment_date": p.next_payment_date,
#                 "created_at":        p.created_at,
#             }
#             for p in items
#         ],
#         "total": total,
#         "pages": (total + per_page - 1) // per_page,
#     })


# v2
"""
Intellect LMS — Payments API  v4

Changes vs v3
─────────────────────────────────────────────────────────────────────────────
1.  PATH-SPECIFIC FEE RESOLUTION  — the initiate endpoint now correctly
    resolves the effective price for paths using subscription/pay_as_you_go
    payment types.

    Previously, `price` was always set from `path.fee` regardless of payment
    type.  Now:
      subscription   → path.subscription_fee ?? path.fee
      pay_as_you_go  → path.pay_as_you_go_fee ?? path.fee
      one_time/free  → path.fee  (unchanged)

2.  ACCESS_PERIOD_DAYS FOR PATHS  — previously only `course.access_period_days`
    was read.  For path payments this was always the default (30 days).  Now
    path.access_period_days is used when the item is a path.

3.  INSTRUCTOR-LED UPLIFT FOR PATHS  — instructor_led_fee was only applied
    when `course` was truthy.  Paths also support instructor-led fees; the
    uplift is now applied from whichever item (course or path) is being paid.

4.  PATH SUBSCRIPTION WITHOUT EXPLICIT plan_id  — when a path's payment_type
    is 'subscription' and no plan_id is supplied in the payload, the endpoint
    now auto-creates a Paystack plan using path.subscription_interval and the
    resolved subscription price, then proceeds with the plan-based flow.
    This ensures proper recurring billing for path subscriptions instead of
    silently falling back to a one-time charge.

5.  SUBSCRIPTION INTERVAL NORMALISATION  — Paystack accepts 'monthly' but
    not 'monthly' with capital; the interval is lower-cased before sending.
    Also normalised: 'quarterly' → 'quarterly' (Paystack uses this directly).
─────────────────────────────────────────────────────────────────────────────
"""

import uuid
import hmac
import hashlib
import json
import logging
import httpx
from typing import Optional
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends, HTTPException, Query, Request, BackgroundTasks
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.models import (
    Payment, Course, LearningPath, Enrollment, PathEnrollment,
    Discount, User, BrandConfig, Partnership, SubscriptionPlan,
)
from app.models.payments import PaymentStatus, EnrollmentStatus
from app.models.courses import PaymentType, CourseStatus
from app.schemas import (
    InitiatePayment, PaymentVerify, DiscountCreate, DiscountValidate,
    SubscriptionPlanCreate, SuccessResponse,
)
from app.api.deps.auth import get_current_user, get_current_verified_user, require_admin
from app.core.config import get_app_config
from app.services.email_service import send_enrollment_confirmation
from app.utils.responses import api_response

router = APIRouter(prefix="/payments", tags=["Payments"])
logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
#  Internal helpers
# ─────────────────────────────────────────────────────────────────────────────

def _paystack_headers():
    cfg = get_app_config()
    return {
        "Authorization": f"Bearer {cfg.payments_config.paystack.secret_key}",
        "Content-Type":  "application/json",
    }


def _get_revenue_split(course, db):
    brand = db.query(BrandConfig).filter(BrandConfig.id == 1).first()
    dc = brand.default_creator_pct  if brand else 70.0
    dp = brand.default_platform_pct if brand else 30.0
    if course and course.creator_pct is not None:
        return course.creator_pct, course.platform_pct or (100 - course.creator_pct)
    return dc, dp


def _apply_discount(code, course_id, path_id, price, db):
    d = db.query(Discount).filter(
        Discount.code == code.upper(),
        Discount.is_active == True,
    ).first()
    if not d:
        return price, None
    now = datetime.now(timezone.utc)
    if d.valid_from  and d.valid_from  > now: return price, None
    if d.valid_until and d.valid_until < now: return price, None
    if d.max_uses    and d.used_count >= d.max_uses: return price, None
    if d.applies_to == "course" and d.course_id != course_id: return price, None
    if d.applies_to == "path"   and d.path_id   != path_id:   return price, None
    final = (
        price * (1 - d.value / 100)
        if d.discount_type == "percentage"
        else max(0, price - d.value)
    )
    return round(final, 2), d


async def _paystack_create_plan(name, amount, interval, currency="NGN"):
    """
    Create a Paystack subscription plan and return the plan_code string,
    or None on any error.  Interval is normalised to lowercase.
    """
    # Paystack accepts: daily, weekly, monthly, biannually, annually, quarterly
    normalised = (interval or "monthly").lower()
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.post(
                "https://api.paystack.co/plan",
                headers=_paystack_headers(),
                json={
                    "name":     name,
                    "interval": normalised,
                    "amount":   int(amount * 100),
                    "currency": currency,
                },
            )
            data = r.json()
            if data.get("status"):
                return data["data"]["plan_code"]
    except Exception as e:
        logger.error("Paystack create-plan error: %s", e)
    return None


async def _paystack_init(
    email: str,
    amount: float,
    tx_ref: str,
    callback_url: str,
    plan_code: str | None = None,
    metadata: dict | None = None,
) -> dict | None:
    """
    Call Paystack /transaction/initialize and return the full data dict:
        {
            "authorization_url": "https://checkout.paystack.com/...",
            "access_code":       "xxxxxxxxxxxxxxxx",   ← required by inline SDK
            "reference":         "ILT-XXXX",
        }
    Returns None on any error.
    """
    payload: dict = {
        "email":        email,
        "amount":       int(amount * 100),   # Paystack expects kobo
        "reference":    tx_ref,
        "callback_url": callback_url,
    }
    if plan_code: payload["plan"]     = plan_code
    if metadata:  payload["metadata"] = metadata

    try:
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.post(
                "https://api.paystack.co/transaction/initialize",
                headers=_paystack_headers(),
                json=payload,
            )
            data = r.json()
            if data.get("status"):
                return data["data"]
    except Exception as e:
        logger.error("Paystack init error: %s", e)
    return None


def _enroll_after_payment(
    user_id:           int,
    course_id:         int | None,
    path_id:           int | None,
    db:                Session,
    payment_type:      str | None = None,
    access_period_days: int = 30,
):
    """
    Create or reactivate enrollment records after a successful payment.

    For pay_as_you_go: valid_until is set to now + access_period_days.
    If the enrollment already has a future valid_until the window is
    extended from that date (top-up behaviour).
    """
    if course_id:
        enrollment = db.query(Enrollment).filter(
            Enrollment.user_id   == user_id,
            Enrollment.course_id == course_id,
        ).first()

        if not enrollment:
            enrollment = Enrollment(user_id=user_id, course_id=course_id)
            db.add(enrollment)
            db.flush()

        if payment_type in (PaymentType.pay_as_you_go.value, "pay_as_you_go"):
            now            = datetime.now(timezone.utc)
            current_expiry = getattr(enrollment, "valid_until", None)
            base           = (
                current_expiry
                if (current_expiry and current_expiry > now)
                else now
            )
            try:
                enrollment.valid_until = base + timedelta(days=access_period_days)
            except Exception:
                pass  # column not yet migrated — skip silently

        if getattr(enrollment, "status", None) == EnrollmentStatus.suspended:
            enrollment.status = EnrollmentStatus.active

    if path_id:
        path = db.query(LearningPath).filter(LearningPath.id == path_id).first()
        if path:
            pe = db.query(PathEnrollment).filter(
                PathEnrollment.user_id == user_id,
                PathEnrollment.path_id == path_id,
            ).first()
            if not pe:
                pe = PathEnrollment(user_id=user_id, path_id=path_id)
                db.add(pe)
                db.flush()

            # For PAYG paths set valid_until on the PathEnrollment if the column exists
            if payment_type in (PaymentType.pay_as_you_go.value, "pay_as_you_go"):
                now            = datetime.now(timezone.utc)
                current_expiry = getattr(pe, "valid_until", None)
                base           = (
                    current_expiry
                    if (current_expiry and current_expiry > now)
                    else now
                )
                try:
                    pe.valid_until = base + timedelta(days=access_period_days)
                except Exception:
                    pass

            for c in path.courses:
                if not db.query(Enrollment).filter(
                    Enrollment.user_id   == user_id,
                    Enrollment.course_id == c.id,
                ).first():
                    db.add(Enrollment(
                        user_id=user_id,
                        course_id=c.id,
                        path_enrollment_id=pe.id,
                    ))


def _safe_send_confirmation(
    background_tasks: BackgroundTasks,
    user_email: str,
    user_name: str,
    course_title: str,
    course_url: str,
) -> None:
    """
    Schedule an enrollment confirmation email as a background task.
    Email failures must NEVER affect the HTTP response.
    """
    try:
        background_tasks.add_task(
            send_enrollment_confirmation,
            user_email,
            user_name,
            course_title,
            course_url,
        )
    except Exception as exc:
        logger.warning(
            "Could not schedule enrollment confirmation email (non-fatal): %s", exc,
            exc_info=True,
        )


# ─────────────────────────────────────────────────────────────────────────────
#  Subscription Plans (Admin)
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/plans")
async def list_subscription_plans(
    course_id: Optional[int] = None,
    path_id:   Optional[int] = None,
    db:        Session = Depends(get_db),
):
    q = db.query(SubscriptionPlan).filter(SubscriptionPlan.is_active == True)
    if course_id: q = q.filter(SubscriptionPlan.course_id == course_id)
    if path_id:   q = q.filter(SubscriptionPlan.path_id   == path_id)
    return api_response(True, "Plans fetched", [
        {
            "id":                  p.id,
            "name":                p.name,
            "paystack_plan_code":  p.paystack_plan_code,
            "interval":            p.interval,
            "amount":              p.amount,
            "currency":            p.currency,
            "course_id":           p.course_id,
            "path_id":             p.path_id,
        }
        for p in q.all()
    ])


@router.post("/plans", dependencies=[Depends(require_admin)], status_code=201)
async def create_subscription_plan(
    payload: SubscriptionPlanCreate,
    db:      Session = Depends(get_db),
):
    plan_code = await _paystack_create_plan(
        payload.name, payload.amount, payload.interval.value, payload.currency,
    )
    plan = SubscriptionPlan(
        name=payload.name, paystack_plan_code=plan_code,
        interval=payload.interval, amount=payload.amount, currency=payload.currency,
        course_id=payload.course_id, path_id=payload.path_id,
    )
    db.add(plan)
    db.commit()
    db.refresh(plan)
    return api_response(True, "Plan created", {
        "id":                 plan.id,
        "paystack_plan_code": plan.paystack_plan_code,
        "name":               plan.name,
        "interval":           plan.interval,
    }, status_code=201)


@router.put("/plans/{plan_id}", dependencies=[Depends(require_admin)])
async def update_subscription_plan(
    plan_id:   int,
    name:      Optional[str]  = None,
    is_active: Optional[bool] = None,
    db:        Session = Depends(get_db),
):
    plan = db.query(SubscriptionPlan).filter(SubscriptionPlan.id == plan_id).first()
    if not plan:
        raise HTTPException(404, "Plan not found")
    if name      is not None: plan.name      = name
    if is_active is not None: plan.is_active = is_active
    db.commit()
    return api_response(True, "Plan updated")


@router.delete("/plans/{plan_id}", dependencies=[Depends(require_admin)])
async def delete_subscription_plan(plan_id: int, db: Session = Depends(get_db)):
    plan = db.query(SubscriptionPlan).filter(SubscriptionPlan.id == plan_id).first()
    if not plan:
        raise HTTPException(404, "Plan not found")
    plan.is_active = False
    plan.is_deleted = True
    db.commit()
    return api_response(True, "Plan deleted")


# ─────────────────────────────────────────────────────────────────────────────
#  Initiate payment
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/initiate")
async def initiate_payment(
    payload: InitiatePayment,
    user:    User    = Depends(get_current_verified_user),
    db:      Session = Depends(get_db),
):
    """
    Initiate a Paystack transaction for a course or learning path.

    Response always includes:
        authorization_url  — Paystack hosted checkout (redirect fallback)
        access_code        — opaque token for PaystackPop inline SDK
        tx_ref             — our internal reference stored in Payment.tx_ref
        payment_type       — effective billing model
        amount             — final amount in NGN (after discount + instructor fee)

    Price resolution (in order of priority):
        course  → course.fee  (always; specific sub/PAYG prices via SubscriptionPlan)
        path    → subscription: path.subscription_fee ?? path.fee
                  pay_as_you_go: path.pay_as_you_go_fee ?? path.fee
                  one_time/free: path.fee
    """
    cfg           = get_app_config()
    frontend_base = cfg.hosting_config.frontend_url.rstrip("/")

    # ── Safe callback URL ────────────────────────────────────────────────────
    if payload.callback_url and payload.callback_url.startswith(frontend_base):
        callback_url = payload.callback_url
    else:
        callback_url = f"{frontend_base}/payment/callback"

    course = path  = None
    price  = 0.0
    access_period_days = 30

    if payload.course_id:
        course = db.query(Course).filter(
            Course.id == payload.course_id,
            Course.is_active == True,
        ).first()
        if not course:
            raise HTTPException(404, "Course not found")
        price              = float(course.fee or 0)
        access_period_days = int(getattr(course, "access_period_days", None) or 30)

    if payload.path_id:
        path = db.query(LearningPath).filter(
            LearningPath.id == payload.path_id,
            LearningPath.is_active == True,
        ).first()
        if not path:
            raise HTTPException(404, "Learning path not found")
        # Base price — will be refined after payment type is resolved below
        price              = float(path.fee or 0)
        access_period_days = int(getattr(path, "access_period_days", None) or 30)

    # ── Effective payment type ────────────────────────────────────────────────
    eff_type = (
        payload.payment_type
        or (course.payment_type if course else None)
        or (path.payment_type   if path   else None)
        or PaymentType.one_time
    )

    # Normalise to string for comparison robustness
    eff_type_str = eff_type.value if hasattr(eff_type, "value") else str(eff_type)

    # ── Path-specific fee resolution ─────────────────────────────────────────
    # Apply model-specific price overrides for paths BEFORE discount/uplift.
    if path and not course:
        if eff_type_str == "subscription":
            sub_fee = getattr(path, "subscription_fee", None)
            if sub_fee is not None:
                price = float(sub_fee)
            # access_period_days not meaningful for subscriptions; keep default
        elif eff_type_str == "pay_as_you_go":
            payg_fee = getattr(path, "pay_as_you_go_fee", None)
            if payg_fee is not None:
                price = float(payg_fee)
            # access_period_days already set from path above

    # ── Discount ─────────────────────────────────────────────────────────────
    if payload.discount_code:
        price, disc = _apply_discount(
            payload.discount_code, payload.course_id, payload.path_id, price, db,
        )
        if disc:
            disc.used_count = (disc.used_count or 0) + 1

    # ── Instructor-led uplift ─────────────────────────────────────────────────
    instructor_led        = bool(getattr(payload, "instructor_led", False))
    instructor_led_amount = 0.0
    if instructor_led:
        # Support both courses and paths
        item = course or path
        if item:
            instructor_led_amount = float(getattr(item, "instructor_led_fee", 0) or 0)
            price = round(price + instructor_led_amount, 2)

    # ── Free enroll (price == 0 or type == free) ──────────────────────────────
    if price == 0 or eff_type_str == "free":
        _enroll_after_payment(user.id, payload.course_id, payload.path_id, db)
        db.commit()
        return api_response(True, "Enrolled for free", {
            "enrolled":          True,
            "authorization_url": "",
            "access_code":       "",
            "tx_ref":            "",
            "payment_type":      eff_type_str,
            "amount":            0,
        })

    # ── Build Paystack metadata ───────────────────────────────────────────────
    metadata = {
        "course_id":             payload.course_id,
        "path_id":               payload.path_id,
        "instructor_led":        instructor_led,
        "instructor_led_amount": instructor_led_amount,
        "access_period_days":    access_period_days,
    }

    tx_ref = f"ILT-{uuid.uuid4().hex[:16].upper()}"
    cp, pp = _get_revenue_split(course, db)

    # ── Subscription with explicit plan_id ────────────────────────────────────
    if eff_type_str == "subscription" and getattr(payload, "plan_id", None):
        plan = db.query(SubscriptionPlan).filter(
            SubscriptionPlan.id        == payload.plan_id,
            SubscriptionPlan.is_active == True,
        ).first()
        if not plan:
            raise HTTPException(404, "Subscription plan not found")
        if not plan.paystack_plan_code:
            raise HTTPException(400, "Plan not yet synced with Paystack")

        ps = await _paystack_init(
            user.email, plan.amount, tx_ref, callback_url,
            plan_code=plan.paystack_plan_code, metadata=metadata,
        )
        if not ps:
            raise HTTPException(502, "Payment gateway error — please try again")

        payment = Payment(
            tx_ref=tx_ref, tx_status=PaymentStatus.pending,
            amount=plan.amount, currency=plan.currency,
            provider="paystack", payment_type="subscription",
            paystack_plan_code=plan.paystack_plan_code,
            creator_amount=round(plan.amount * cp / 100, 2),
            platform_amount=round(plan.amount * pp / 100, 2),
            user_id=user.id, course_id=payload.course_id, path_id=payload.path_id,
        )
        db.add(payment)
        db.commit()

        return api_response(True, "Subscription initiated", {
            "authorization_url": ps["authorization_url"],
            "access_code":       ps.get("access_code", ""),
            "tx_ref":            tx_ref,
            "payment_type":      "subscription",
            "plan_code":         plan.paystack_plan_code,
            "interval":          plan.interval,
            "amount":            plan.amount,
        })

    # ── Subscription WITHOUT explicit plan_id — auto-create plan ─────────────
    # This is the path subscription flow when no SubscriptionPlan record exists.
    # We create the plan on the fly using the path's interval and resolved price.
    if eff_type_str == "subscription" and path and not getattr(payload, "plan_id", None):
        interval = (getattr(path, "subscription_interval", None) or "monthly").lower()
        plan_name = f"Path: {path.title} ({interval})"

        plan_code = await _paystack_create_plan(plan_name, price, interval)
        if not plan_code:
            # Could not create plan — fall through to one-time charge with a warning
            logger.warning(
                "Could not auto-create Paystack plan for path %d (%s). "
                "Falling through to one-time charge.",
                path.id, interval,
            )
        else:
            # Persist the auto-created plan so future charges re-use it
            existing_plan = db.query(SubscriptionPlan).filter(
                SubscriptionPlan.path_id   == path.id,
                SubscriptionPlan.is_active == True,
                SubscriptionPlan.interval  == interval,
            ).first()
            if not existing_plan:
                db.add(SubscriptionPlan(
                    name=plan_name,
                    paystack_plan_code=plan_code,
                    interval=interval,
                    amount=price,
                    currency="NGN",
                    path_id=path.id,
                ))
                db.flush()

            ps = await _paystack_init(
                user.email, price, tx_ref, callback_url,
                plan_code=plan_code, metadata=metadata,
            )
            if not ps:
                raise HTTPException(502, "Payment gateway error — please try again")

            payment = Payment(
                tx_ref=tx_ref, tx_status=PaymentStatus.pending,
                amount=price, currency="NGN",
                provider="paystack", payment_type="subscription",
                paystack_plan_code=plan_code,
                creator_amount=round(price * cp / 100, 2),
                platform_amount=round(price * pp / 100, 2),
                user_id=user.id, course_id=payload.course_id, path_id=payload.path_id,
            )
            db.add(payment)
            db.commit()

            return api_response(True, "Subscription initiated", {
                "authorization_url": ps["authorization_url"],
                "access_code":       ps.get("access_code", ""),
                "tx_ref":            tx_ref,
                "payment_type":      "subscription",
                "plan_code":         plan_code,
                "interval":          interval,
                "amount":            price,
            })

    # ── One-time / pay-as-you-go (or subscription fallback) ──────────────────
    ps = await _paystack_init(user.email, price, tx_ref, callback_url, metadata=metadata)
    if not ps:
        raise HTTPException(502, "Payment gateway error — please try again")

    # Track PAYG installment number for courses
    installment = None
    if eff_type_str == "pay_as_you_go" and payload.course_id:
        installment = (
            db.query(Payment)
            .filter(
                Payment.user_id      == user.id,
                Payment.course_id    == payload.course_id,
                Payment.tx_status    == PaymentStatus.successful,
                Payment.payment_type == "pay_as_you_go",
            )
            .count()
        ) + 1

    payment = Payment(
        tx_ref=tx_ref, tx_status=PaymentStatus.pending,
        amount=price, currency="NGN",
        provider="paystack",
        payment_type=eff_type_str,
        installment_number=installment,
        creator_amount=round(price * cp / 100, 2),
        platform_amount=round(price * pp / 100, 2),
        user_id=user.id, course_id=payload.course_id, path_id=payload.path_id,
    )
    db.add(payment)
    db.commit()

    return api_response(True, "Payment initiated", {
        "authorization_url":  ps["authorization_url"],
        "access_code":        ps.get("access_code", ""),
        "tx_ref":             tx_ref,
        "payment_type":       eff_type_str,
        "amount":             price,
        "access_period_days": access_period_days if eff_type_str == "pay_as_you_go" else None,
    })


# ─────────────────────────────────────────────────────────────────────────────
#  Verify payment
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/verify")
async def verify_payment(
    payload:          PaymentVerify,
    background_tasks: BackgroundTasks,
    user:             User    = Depends(get_current_user),
    db:               Session = Depends(get_db),
):
    """
    Verify a Paystack transaction by reference and enroll the user.

    Accepts the reference under EITHER field name:
        payload.tx_ref    — our internal reference (ILT-XXXX…)
        payload.reference — Paystack's own reference field (same value)

    Email confirmation is FIRE-AND-FORGET — errors never affect response.
    """
    reference = getattr(payload, "reference", None) or getattr(payload, "tx_ref", None)
    if not reference:
        raise HTTPException(400, "reference is required")

    payment = db.query(Payment).filter(
        Payment.tx_ref  == reference,
        Payment.user_id == user.id,
    ).first()
    if not payment:
        raise HTTPException(404, "Transaction not found")
    if payment.tx_status == PaymentStatus.successful:
        return api_response(True, "Already verified", {"paid": True, "status": "success"})

    # ── Verify with Paystack ──────────────────────────────────────────────────
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.get(
                f"https://api.paystack.co/transaction/verify/{reference}",
                headers=_paystack_headers(),
            )
            data = r.json()
    except Exception as e:
        logger.error("Paystack verify network error: %s", e)
        raise HTTPException(502, "Could not reach payment gateway")

    if not data.get("status") or data["data"]["status"] != "success":
        payment.tx_status = PaymentStatus.failed
        db.commit()
        raise HTTPException(402, "Payment not successful")

    ps = data["data"]

    payment.tx_id     = str(ps.get("id", ""))
    payment.tx_status = PaymentStatus.successful

    if ps.get("plan"):
        payment.paystack_plan_code = ps["plan"].get("plan_code")
    if ps.get("subscription_code"):
        payment.subscription_code = ps["subscription_code"]

    meta               = ps.get("metadata") or {}
    access_period_days = int(meta.get("access_period_days") or 30)

    _enroll_after_payment(
        user.id, payment.course_id, payment.path_id, db,
        payment_type=payment.payment_type,
        access_period_days=access_period_days,
    )
    db.commit()

    # ── Email — fire and forget ───────────────────────────────────────────────
    if payment.course_id:
        c_obj = db.query(Course).filter(Course.id == payment.course_id).first()
        if c_obj:
            cfg = get_app_config()
            _safe_send_confirmation(
                background_tasks,
                user.email,
                user.name or user.username or "",
                c_obj.title,
                f"{cfg.hosting_config.frontend_url.rstrip('/')}/learn/{c_obj.slug}",
            )

    return api_response(True, "Payment verified — enrolled successfully", {
        "paid":   True,
        "status": "success",
    })


# ─────────────────────────────────────────────────────────────────────────────
#  Paystack webhook
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/webhook/paystack")
async def paystack_webhook(
    request:          Request,
    background_tasks: BackgroundTasks,
    db:               Session = Depends(get_db),
):
    cfg    = get_app_config()
    secret = cfg.payments_config.paystack.secret_key
    body   = await request.body()
    sig    = request.headers.get("x-paystack-signature", "")

    if not hmac.compare_digest(
        sig,
        hmac.new(secret.encode(), body, hashlib.sha512).hexdigest(),
    ):
        raise HTTPException(400, "Invalid signature")

    try:
        event = json.loads(body)
    except Exception:
        raise HTTPException(400, "Invalid JSON body")

    ev   = event.get("event", "")
    data = event.get("data", {})

    if ev == "charge.success":
        ref = data.get("reference")
        if ref:
            p = db.query(Payment).filter(Payment.tx_ref == ref).first()
            if p and p.tx_status != PaymentStatus.successful:
                p.tx_id     = str(data.get("id", ""))
                p.tx_status = PaymentStatus.successful

                meta               = data.get("metadata") or {}
                access_period_days = int(meta.get("access_period_days") or 30)

                _enroll_after_payment(
                    p.user_id, p.course_id, p.path_id, db,
                    payment_type=p.payment_type,
                    access_period_days=access_period_days,
                )
                db.commit()

    elif ev == "invoice.payment_succeeded":
        sub_code = (
            data.get("subscription", {}).get("subscription_code")
            or data.get("subscription_code")
        )
        ref = data.get("transaction", {}).get("reference")
        if sub_code and ref:
            p = db.query(Payment).filter(Payment.subscription_code == sub_code).first()
            if p:
                new_tx_ref = f"ILT-{uuid.uuid4().hex[:16].upper()}"
                renewal = Payment(
                    tx_ref=new_tx_ref, tx_id=str(data.get("id", "")),
                    tx_status=PaymentStatus.successful,
                    amount=p.amount, currency=p.currency,
                    provider="paystack", payment_type="subscription",
                    paystack_plan_code=p.paystack_plan_code,
                    subscription_code=sub_code,
                    creator_amount=p.creator_amount,
                    platform_amount=p.platform_amount,
                    user_id=p.user_id, course_id=p.course_id, path_id=p.path_id,
                )
                db.add(renewal)

                # Reactivate enrollment if suspended
                if p.course_id:
                    enr = db.query(Enrollment).filter(
                        Enrollment.user_id   == p.user_id,
                        Enrollment.course_id == p.course_id,
                    ).first()
                    if enr and getattr(enr, "status", None) == EnrollmentStatus.suspended:
                        enr.status = EnrollmentStatus.active

                nxt = data.get("subscription", {}).get("next_payment_date")
                if nxt:
                    try:
                        p.next_payment_date = datetime.fromisoformat(
                            nxt.replace("Z", "+00:00")
                        )
                    except Exception:
                        pass
                db.commit()

    elif ev in ("subscription.disable", "invoice.payment_failed"):
        sub_code = (
            data.get("subscription", {}).get("subscription_code")
            or data.get("subscription_code")
        )
        if sub_code:
            p = db.query(Payment).filter(Payment.subscription_code == sub_code).first()
            if p and p.course_id:
                enr = db.query(Enrollment).filter(
                    Enrollment.user_id   == p.user_id,
                    Enrollment.course_id == p.course_id,
                ).first()
                if enr:
                    enr.status = EnrollmentStatus.suspended
                    db.commit()

    elif ev == "invoice.update":
        sub_code = data.get("subscription", {}).get("subscription_code")
        nxt      = data.get("subscription", {}).get("next_payment_date")
        if sub_code and nxt:
            p = db.query(Payment).filter(Payment.subscription_code == sub_code).first()
            if p:
                try:
                    p.next_payment_date = datetime.fromisoformat(
                        nxt.replace("Z", "+00:00")
                    )
                    db.commit()
                except Exception:
                    pass

    return {"received": True}


# ─────────────────────────────────────────────────────────────────────────────
#  Discounts
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/discounts", dependencies=[Depends(require_admin)], status_code=201)
async def create_discount(payload: DiscountCreate, db: Session = Depends(get_db)):
    if db.query(Discount).filter(Discount.code == payload.code.upper()).first():
        raise HTTPException(400, "Code already exists")
    d = Discount(
        code=payload.code.upper(), description=payload.description,
        discount_type=payload.discount_type, value=payload.value,
        max_uses=payload.max_uses, valid_from=payload.valid_from,
        valid_until=payload.valid_until, applies_to=payload.applies_to,
        course_id=payload.course_id, path_id=payload.path_id,
    )
    db.add(d)
    db.commit()
    db.refresh(d)
    return api_response(True, "Discount created", {"id": d.id, "code": d.code}, status_code=201)


@router.post("/discounts/validate")
async def validate_discount(payload: DiscountValidate, db: Session = Depends(get_db)):
    price = 0.0
    if payload.course_id:
        c = db.query(Course).filter(Course.id == payload.course_id).first()
        if c: price = float(c.fee or 0)
    elif payload.path_id:
        p = db.query(LearningPath).filter(LearningPath.id == payload.path_id).first()
        if p: price = float(p.fee or 0)
    final, d = _apply_discount(payload.code, payload.course_id, payload.path_id, price, db)
    if not d:
        return api_response(True, "Discount info", {
            "valid":   False,
            "message": "Invalid, expired, or inapplicable.",
        })
    return api_response(True, "Discount valid", {
        "valid":          True,
        "discount_type":  d.discount_type,
        "value":          d.value,
        "original_price": price,
        "final_price":    final,
        "savings":        round(price - final, 2),
        "message":        f"Save ₦{price - final:,.2f}",
    })


@router.get("/discounts", dependencies=[Depends(require_admin)])
async def list_discounts(
    page:     int = Query(1, ge=1),
    per_page: int = Query(20),
    db:       Session = Depends(get_db),
):
    q     = db.query(Discount).filter(Discount.is_active == True)
    total = q.count()
    items = (
        q.order_by(Discount.created_at.desc())
        .offset((page - 1) * per_page)
        .limit(per_page)
        .all()
    )
    return api_response(True, "Discounts fetched", {
        "items": [
            {
                "id":            d.id,
                "code":          d.code,
                "discount_type": d.discount_type,
                "value":         d.value,
                "max_uses":      d.max_uses,
                "used_count":    d.used_count,
                "valid_from":    d.valid_from,
                "valid_until":   d.valid_until,
                "applies_to":    d.applies_to,
            }
            for d in items
        ],
        "total": total,
        "page":  page,
        "pages": (total + per_page - 1) // per_page,
    })


@router.delete("/discounts/{discount_id}", dependencies=[Depends(require_admin)])
async def delete_discount(discount_id: int, db: Session = Depends(get_db)):
    d = db.query(Discount).filter(Discount.id == discount_id).first()
    if not d:
        raise HTTPException(404, "Not found")
    d.is_active  = False
    d.is_deleted = True
    db.commit()
    return api_response(True, "Deleted")


# ─────────────────────────────────────────────────────────────────────────────
#  Payment history
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/my-payments")
async def my_payments(
    page:     int  = Query(1, ge=1),
    per_page: int  = Query(20),
    user:     User = Depends(get_current_user),
    db:       Session = Depends(get_db),
):
    q     = db.query(Payment).filter(Payment.user_id == user.id)
    total = q.count()
    items = (
        q.order_by(Payment.created_at.desc())
        .offset((page - 1) * per_page)
        .limit(per_page)
        .all()
    )
    return api_response(True, "Payment history", {
        "items": [
            {
                "id":                  p.id,
                "tx_ref":              p.tx_ref,
                "tx_status":           p.tx_status,
                "amount":              p.amount,
                "currency":            p.currency,
                "payment_type":        p.payment_type,
                "course_id":           p.course_id,
                "path_id":             p.path_id,
                "paystack_plan_code":  p.paystack_plan_code,
                "next_payment_date":   p.next_payment_date,
                "created_at":          p.created_at,
            }
            for p in items
        ],
        "total": total,
        "page":  page,
    })


@router.get("/admin/all", dependencies=[Depends(require_admin)])
async def admin_all_payments(
    page:     int           = Query(1),
    per_page: int           = Query(50),
    status:   Optional[str] = None,
    db:       Session = Depends(get_db),
):
    q = db.query(Payment)
    if status:
        q = q.filter(Payment.tx_status == status)
    total = q.count()
    items = (
        q.order_by(Payment.created_at.desc())
        .offset((page - 1) * per_page)
        .limit(per_page)
        .all()
    )
    return api_response(True, "All payments", {
        "items": [
            {
                "id":                p.id,
                "tx_ref":            p.tx_ref,
                "tx_id":             p.tx_id,
                "tx_status":         p.tx_status,
                "amount":            p.amount,
                "payment_type":      p.payment_type,
                "user_id":           p.user_id,
                "course_id":         p.course_id,
                "path_id":           p.path_id,
                "creator_amount":    p.creator_amount,
                "platform_amount":   p.platform_amount,
                "subscription_code": p.subscription_code,
                "next_payment_date": p.next_payment_date,
                "created_at":        p.created_at,
            }
            for p in items
        ],
        "total": total,
        "pages": (total + per_page - 1) // per_page,
    })


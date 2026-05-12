"""Payment schemas"""
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field

from app.enums import PaymentType

class InitiatePayment(BaseModel):
    course_id: Optional[int] = None
    path_id: Optional[int] = None
    payment_type: Optional[PaymentType] = None
    plan_id: Optional[int] = None          # SubscriptionPlan.id → creates Paystack sub
    discount_code: Optional[str] = None
    instructor_led: bool        = Field(False, description="Opt into instructor-led mode (adds instructor_led_fee)")
    callback_url:   Optional[str] = Field(None,  description="Paystack return URL; defaults to server config if not set")


class PaymentVerify(BaseModel):
    tx_ref: str


class DiscountCreate(BaseModel):
    code: str
    description: Optional[str] = None
    discount_type: str = "percentage"  # percentage | fixed
    value: float
    max_uses: Optional[int] = None
    valid_from: Optional[datetime] = None
    valid_until: Optional[datetime] = None
    applies_to: str = "all"  # all | course | path
    course_id: Optional[int] = None
    path_id: Optional[int] = None


class DiscountValidate(BaseModel):
    code: str
    course_id: Optional[int] = None
    path_id: Optional[int] = None


class DiscountValidateResponse(BaseModel):
    valid: bool
    discount_type: Optional[str] = None
    value: Optional[float] = None
    original_price: Optional[float] = None
    final_price: Optional[float] = None
    savings: Optional[float] = None
    message: str

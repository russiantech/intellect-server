"""Social schemas - messaging, notifications, broadcasts"""
from typing import Optional, List
from pydantic import BaseModel, Field
from app.enums import BroadcastType

class MessageCreate(BaseModel):
    recipient_id: int
    body: str = Field(..., min_length=1, max_length=5000)


class BroadcastCreate(BaseModel):
    subject: str
    body: str
    broadcast_type: BroadcastType = BroadcastType.all
    sent_via_email: bool = True
    sent_via_notification: bool = True
    recipient_ids: Optional[List[int]] = None

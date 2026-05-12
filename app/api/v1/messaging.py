from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.models import Message, Notification, User
from app.schemas import MessageCreate, SuccessResponse
from app.api.deps.auth import get_current_user

router = APIRouter(prefix="/messages", tags=["Messaging"])
notif_router = APIRouter(prefix="/notifications", tags=["Notifications"])


@router.post("/", status_code=201)
async def send_message(
    payload: MessageCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if payload.recipient_id == user.id:
        raise HTTPException(status_code=400, detail="Cannot message yourself")
    recipient = db.query(User).filter(User.id == payload.recipient_id, User.is_active == True).first()
    if not recipient:
        raise HTTPException(status_code=404, detail="Recipient not found")
    msg = Message(body=payload.body, sender_id=user.id, recipient_id=payload.recipient_id)
    db.add(msg)
    db.commit()
    db.refresh(msg)
    return {
        "id": msg.id, "body": msg.body, "is_seen": msg.is_seen,
        "sender_id": msg.sender_id, "recipient_id": msg.recipient_id,
        "created_at": msg.created_at,
    }


@router.get("/conversations")
async def get_conversations(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Get list of unique conversation partners."""
    from sqlalchemy import or_, func
    msgs = db.query(Message).filter(
        or_(Message.sender_id == user.id, Message.recipient_id == user.id),
        Message.is_active == True,
    ).all()

    # Unique users
    partner_ids = set()
    for m in msgs:
        other = m.recipient_id if m.sender_id == user.id else m.sender_id
        partner_ids.add(other)

    conversations = []
    for pid in partner_ids:
        partner = db.query(User).filter(User.id == pid).first()
        if not partner:
            continue
        last_msg = db.query(Message).filter(
            or_(
                (Message.sender_id == user.id) & (Message.recipient_id == pid),
                (Message.sender_id == pid) & (Message.recipient_id == user.id),
            )
        ).order_by(Message.created_at.desc()).first()
        unread = db.query(Message).filter(
            Message.sender_id == pid, Message.recipient_id == user.id, Message.is_seen == False,
        ).count()
        conversations.append({
            "partner": {
                "id": partner.id, "name": partner.name,
                "username": partner.username, "image": partner.image,
            },
            "last_message": {"body": last_msg.body, "created_at": last_msg.created_at} if last_msg else None,
            "unread_count": unread,
        })

    conversations.sort(key=lambda x: x["last_message"]["created_at"] if x["last_message"] else "", reverse=True)
    return conversations


@router.get("/{partner_id}")
async def get_conversation(
    partner_id: int,
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from sqlalchemy import or_
    msgs = db.query(Message).filter(
        or_(
            (Message.sender_id == user.id) & (Message.recipient_id == partner_id),
            (Message.sender_id == partner_id) & (Message.recipient_id == user.id),
        ),
        Message.is_active == True,
    ).order_by(Message.created_at.asc()).all()

    # Mark as seen
    for m in msgs:
        if m.recipient_id == user.id and not m.is_seen:
            m.is_seen = True
    db.commit()

    return [
        {
            "id": m.id, "body": m.body, "is_seen": m.is_seen,
            "sender_id": m.sender_id, "recipient_id": m.recipient_id,
            "mine": m.sender_id == user.id,
            "created_at": m.created_at,
        }
        for m in msgs
    ]


@router.delete("/{message_id}")
async def delete_message(
    message_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    msg = db.query(Message).filter(Message.id == message_id, Message.sender_id == user.id).first()
    if not msg:
        raise HTTPException(status_code=404, detail="Message not found")
    msg.is_active = False
    db.commit()
    return SuccessResponse(message="Message deleted")


# ─── NOTIFICATIONS ─────────────────────────────────

@notif_router.get("/")
async def get_notifications(
    unread_only: bool = False,
    page: int = Query(1, ge=1),
    per_page: int = Query(20),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    q = db.query(Notification).filter(Notification.user_id == user.id, Notification.is_active == True)
    if unread_only:
        q = q.filter(Notification.is_read == False)
    total = q.count()
    notifs = q.order_by(Notification.created_at.desc()).offset((page - 1) * per_page).limit(per_page).all()
    return {
        "items": [
            {
                "id": n.id, "title": n.title, "body": n.body,
                "notification_type": n.notification_type,
                "is_read": n.is_read, "link": n.link,
                "created_at": n.created_at,
            }
            for n in notifs
        ],
        "total": total,
        "unread_count": db.query(Notification).filter(
            Notification.user_id == user.id, Notification.is_read == False,
        ).count(),
    }


@notif_router.post("/{notif_id}/read")
async def mark_read(
    notif_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    n = db.query(Notification).filter(Notification.id == notif_id, Notification.user_id == user.id).first()
    if n:
        n.is_read = True
        db.commit()
    return SuccessResponse(message="Marked as read")


@notif_router.post("/read-all")
async def mark_all_read(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    db.query(Notification).filter(
        Notification.user_id == user.id, Notification.is_read == False,
    ).update({"is_read": True})
    db.commit()
    return SuccessResponse(message="All notifications marked as read")

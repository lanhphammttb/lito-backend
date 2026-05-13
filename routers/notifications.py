"""Notification and push subscription routes."""

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from config.database import engine
from legacy_state import NotificationLog, sent_notifications
from models import FcmTokenTable, PushSubscriptionTable
from models.user import User
from services import fcm as fcm_service
from services.auth import get_current_user
from services.notification import ws_manager
from utils.datetime import utcnow

router = APIRouter()


@router.post("/subscribe")
async def subscribe_push(payload: dict, user: User = Depends(get_current_user)):
    """Register push notification subscription."""
    endpoint = payload.get("endpoint", "")
    keys = payload.get("keys", {})
    with Session(engine) as session:
        existing = session.exec(
            select(PushSubscriptionTable).where(PushSubscriptionTable.endpoint == endpoint)
        ).first()
        if existing:
            existing.user_id = user.id
            session.add(existing)
        else:
            session.add(PushSubscriptionTable(
                user_id=user.id,
                endpoint=endpoint,
                p256dh=keys.get("p256dh", ""),
                auth=keys.get("auth", "")
            ))
        session.commit()
    return {"message": "Subscription registered"}


@router.delete("/unsubscribe")
async def unsubscribe_push(endpoint: str, user: User = Depends(get_current_user)):
    """Unsubscribe from push notifications."""
    with Session(engine) as session:
        sub = session.exec(
            select(PushSubscriptionTable).where(
                PushSubscriptionTable.endpoint == endpoint,
                PushSubscriptionTable.user_id == user.id
            )
        ).first()
        if sub:
            session.delete(sub)
            session.commit()
    return {"message": "Unsubscribed"}


@router.post("/fcm-token")
async def register_fcm_token(payload: dict, user: User = Depends(get_current_user)):
    """Register FCM device token for push notifications when app is closed."""
    token = payload.get("token", "").strip()
    if not token:
        raise HTTPException(status_code=400, detail="FCM token required")
    with Session(engine) as session:
        existing = session.exec(
            select(FcmTokenTable).where(FcmTokenTable.token == token)
        ).first()
        if existing:
            existing.user_id = user.id
            existing.updated_at = utcnow()
            session.add(existing)
        else:
            session.add(FcmTokenTable(
                user_id=user.id,
                token=token,
                device_info=payload.get("device_info", "")
            ))
        session.commit()
    return {"message": "FCM token registered"}


@router.delete("/fcm-token")
async def remove_fcm_token(payload: dict, user: User = Depends(get_current_user)):
    """Remove FCM token (on logout)."""
    token = payload.get("token", "")
    with Session(engine) as session:
        row = session.exec(
            select(FcmTokenTable).where(
                FcmTokenTable.token == token,
                FcmTokenTable.user_id == user.id
            )
        ).first()
        if row:
            session.delete(row)
            session.commit()
    return {"message": "FCM token removed"}


@router.get("")
async def list_notifications(limit: int = 50, user: User = Depends(get_current_user)):
    """Get sent notification history from DB."""
    try:
        with Session(engine) as session:
            rows = session.exec(
                select(NotificationLog).order_by(NotificationLog.timestamp.desc()).limit(limit)
            ).all()
            return [{"id": r.id, "title": r.title, "body": r.body, "sent_by": r.sent_by,
                     "sent_count": r.sent_count, "timestamp": r.timestamp.isoformat()} for r in rows]
    except Exception:
        return sent_notifications[:limit]


@router.post("/send")
async def send_notification(payload: dict, user: User = Depends(get_current_user)):
    """Send notification via WebSocket (online) + FCM (offline/background)."""
    ts = utcnow()
    title = payload.get("title", "")
    body = payload.get("body", "")
    notification_data = {
        "type": "notification",
        "title": title,
        "body": body,
        "data": payload.get("data", {}),
        "timestamp": ts.isoformat(),
    }
    user_ids = payload.get("user_ids")
    # 1. WebSocket for online users
    if user_ids:
        for uid in user_ids:
            await ws_manager.send_personal_message(notification_data, uid)
    else:
        await ws_manager.broadcast(notification_data)

    # 2. FCM for offline/background users
    with Session(engine) as session:
        if user_ids:
            tokens_rows = session.exec(
                select(FcmTokenTable).where(FcmTokenTable.user_id.in_(user_ids))
            ).all()
        else:
            tokens_rows = session.exec(select(FcmTokenTable)).all()
        tokens = [r.token for r in tokens_rows]
    fcm_sent = fcm_service.send_many(tokens, title, body, payload.get("data", {})) if tokens else 0

    sent_count = len(user_ids) if user_ids else 1
    record = {
        "title": notification_data["title"],
        "body": notification_data["body"],
        "sent_by": user.name or user.email,
        "sent_count": sent_count,
        "timestamp": ts.isoformat(),
    }
    # Persist to DB
    try:
        with Session(engine) as session:
            row = NotificationLog(
                title=record["title"], body=record["body"],
                sent_by=record["sent_by"], sent_count=sent_count, timestamp=ts,
            )
            session.add(row)
            session.commit()
            session.refresh(row)
            record["id"] = row.id
    except Exception:
        record["id"] = len(sent_notifications) + 1
    sent_notifications.insert(0, record)
    return {"success": True, "message": "Notification sent", "sent_count": sent_count, "fcm_sent": fcm_sent}


@router.post("/test")
async def test_notification(user: User = Depends(get_current_user)):
    """Test notification."""
    await ws_manager.broadcast({"type": "notification", "title": "Test", "body": "Test notification", "timestamp": utcnow().isoformat()})
    return {"success": True, "message": "Test notification sent"}

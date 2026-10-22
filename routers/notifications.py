"""Notification and push subscription routes."""

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select
from starlette.concurrency import run_in_threadpool

from config.database import engine
from legacy_state import NotificationLog, sent_notifications
from models import FcmTokenTable, PushSubscriptionTable
from models.user import User
from services import fcm as fcm_service
from services.auth import get_current_user, require_admin
from services.notification import ws_manager, send_notifications
from config.settings import settings as app_settings
from utils.datetime import utcnow

router = APIRouter()


@router.get("/status")
async def notification_status(user: User = Depends(get_current_user)):
    with Session(engine) as session:
        devices = session.exec(select(FcmTokenTable).where(FcmTokenTable.user_id == user.id)).all()
    return {**fcm_service.delivery_status(), "registered_devices": len(devices)}


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
    return await _deliver_notification(payload, user)


async def _deliver_notification(payload: dict, user: User):
    ts = utcnow()
    title = payload.get("title")
    body = payload.get("body")
    if not isinstance(title, str) or not title.strip() or len(title) > 200:
        raise HTTPException(422, "Nhập tiêu đề thông báo, tối đa 200 ký tự")
    if not isinstance(body, str) or not body.strip() or len(body) > 2000:
        raise HTTPException(422, "Nhập nội dung thông báo, tối đa 2000 ký tự")
    title, body = title.strip(), body.strip()
    data = payload.get("data")
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise HTTPException(422, "Dữ liệu đính kèm phải là đối tượng JSON")
    user_ids = payload.get("user_ids")
    if user_ids is not None:
        if not isinstance(user_ids, list) or not user_ids or any(type(uid) is not int or uid <= 0 for uid in user_ids):
            raise HTTPException(422, "Danh sách người nhận không hợp lệ")
        user_ids = list(dict.fromkeys(user_ids))
    notification_data = {
        "type": "notification",
        "title": title,
        "body": body,
        "data": data,
        "timestamp": ts.isoformat(),
    }
    # 1. WebSocket for online users
    online_connections = 0
    if user_ids:
        for uid in user_ids:
            online_connections += await ws_manager.send_personal_message(notification_data, uid)
    else:
        online_connections = await ws_manager.broadcast(notification_data)

    # 2. FCM for offline/background users
    with Session(engine) as session:
        if user_ids:
            tokens_rows = session.exec(
                select(FcmTokenTable).where(FcmTokenTable.user_id.in_(user_ids))
            ).all()
        else:
            tokens_rows = session.exec(select(FcmTokenTable)).all()
        tokens = [r.token for r in tokens_rows]
    result = await run_in_threadpool(fcm_service.send_many_result, tokens, title, body, data)
    if result["invalid_tokens"]:
        with Session(engine) as session:
            for row in session.exec(select(FcmTokenTable).where(FcmTokenTable.token.in_(result["invalid_tokens"]))):
                session.delete(row)
            session.commit()

    fcm_sent = result["accepted"]
    sent_count = fcm_sent
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
    success = bool(fcm_sent or online_connections)
    if not tokens and not online_connections:
        status, message = "no_recipients", "Chưa có thiết bị nhận. Người nhận cần bật thông báo trình duyệt và đăng ký thiết bị."
    elif not success:
        status, message = "failed", "Không gửi được thông báo. Kiểm tra cấu hình Firebase phía máy chủ và đăng ký thiết bị."
    elif result["failed"]:
        status, message = "partial", "Một số thiết bị chưa nhận được thông báo."
    else:
        status, message = "sent", "Đã chuyển thông báo tới kênh nhận."
    return {"success": success, "status": status, "message": message,
            "sent_count": sent_count, "fcm_sent": fcm_sent,
            "attempted_devices": result["attempted"], "failed_devices": result["failed"],
            "online_connections": online_connections, "error_codes": result["error_codes"]}


@router.post("/test")
async def test_notification(user: User = Depends(get_current_user)):
    """Test delivery only to the current user's registered devices."""
    return await _deliver_notification({"title": "LITO Handmade", "body": "Thông báo thử từ LITO Handmade.",
                                        "user_ids": [user.id]}, user)


@router.post("/test-email")
async def test_email(user: User = Depends(get_current_user)):
    """The SMTP test button must test email, not broadcast a browser push."""
    require_admin(user)
    if not app_settings.smtp_host or not (app_settings.notification_emails or app_settings.backup_email):
        raise HTTPException(400, "Lưu cấu hình SMTP và email nhận thông báo hoặc email nhận bản sao lưu trước khi gửi thử")
    sent = await run_in_threadpool(send_notifications, {"title": "Email thử từ LITO Handmade",
                                                       "message": "Kiểm tra cấu hình gửi email của hệ thống."})
    if not sent:
        raise HTTPException(503, "Không gửi được email thử. Kiểm tra địa chỉ máy chủ, cổng và thông tin đăng nhập SMTP")
    return {"success": True}

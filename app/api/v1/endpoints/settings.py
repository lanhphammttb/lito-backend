from app.shared import *
from fastapi import APIRouter

router = APIRouter()

@router.get("/settings")
async def get_settings():
    import app.shared as shared
    return shared.settings

@router.patch("/settings")
async def update_settings(updated: Settings, current_user: User = Depends(get_current_user)):
    require_admin(current_user)
    import app.shared as shared
    merged = Settings.model_validate({**shared.settings.model_dump(), **updated.model_dump()})
    shared.settings = merged
    upsert_document("settings", merged)
    log_activity(current_user.id, "settings", None, "update", changes=merged.model_dump())
    return shared.settings

@router.get("/alerts")
async def get_alerts(current_user: User = Depends(get_current_user)):
    return {"low_stock": [], "overdue_orders": [], "forecast_low": [], "tasks_overdue": []}

@router.post("/notifications/test")
async def test_notification(current_user: User = Depends(get_current_user)):
    require_admin(current_user)
    payload = {"message": "Test notification", "timestamp": datetime.utcnow().isoformat()}
    send_notifications(payload)
    return {"ok": True, "sent": True}




# --- Push Notification Endpoints ---------------------------------------------
@router.post("/notifications/subscribe")
async def subscribe_push(subscription: PushSubscription, current_user: User = Depends(get_current_user)):
    """Register push notification subscription"""
    try:
        with Session(engine) as session:
            # Check if endpoint already exists
            existing = session.exec(
                select(PushSubscriptionTable).where(PushSubscriptionTable.endpoint == subscription.endpoint)
            ).first()

            if existing:
                # Update user_id if changed
                if existing.user_id != current_user.id:
                    existing.user_id = current_user.id
                    session.add(existing)
                    session.commit()
                return {"message": "Subscription updated"}

            # Create new subscription
            new_sub = PushSubscriptionTable(
                user_id=current_user.id,
                endpoint=subscription.endpoint,
                p256dh=subscription.keys.get("p256dh", ""),
                auth=subscription.keys.get("auth", "")
            )
            session.add(new_sub)
            session.commit()

            return {"message": "Subscription registered successfully"}
    except Exception as e:
        print(f"Error subscribing to push: {e}")
        raise HTTPException(status_code=500, detail="Failed to register subscription")




@router.post("/notifications/send")
async def send_push_notification(payload: NotificationPayload, current_user: User = Depends(get_current_user)):
    """Send push notification (admin only)"""
    require_admin(current_user)

    try:
        with Session(engine) as session:
            # Get target subscriptions
            query = select(PushSubscriptionTable)
            if payload.user_ids:
                query = query.where(PushSubscriptionTable.user_id.in_(payload.user_ids))

            subscriptions = session.exec(query).all()

            sent_count = 0

            # Send via WebSocket (real-time)
            notification_data = {
                "type": "notification",
                "title": payload.title,
                "body": payload.body,
                "icon": payload.icon,
                "data": payload.data,
                "timestamp": datetime.now().isoformat()
            }

            if payload.user_ids:
                for user_id in payload.user_ids:
                    try:
                        await ws_manager.send_personal_message(notification_data, user_id)
                        sent_count += 1
                    except:
                        pass
            else:
                await ws_manager.broadcast(notification_data)
                sent_count = len(ws_manager.active_connections)

            return {
                "message": "Notification sent",
                "sent_count": sent_count,
                "subscriptions_found": len(subscriptions)
            }
    except Exception as e:
        print(f"Error sending notification: {e}")
        raise HTTPException(status_code=500, detail=str(e))




@router.delete("/notifications/unsubscribe")
async def unsubscribe_push(endpoint: str, current_user: User = Depends(get_current_user)):
    """Unsubscribe from push notifications"""
    try:
        with Session(engine) as session:
            sub = session.exec(
                select(PushSubscriptionTable).where(
                    PushSubscriptionTable.endpoint == endpoint,
                    PushSubscriptionTable.user_id == current_user.id
                )
            ).first()

            if sub:
                session.delete(sub)
                session.commit()
                return {"message": "Unsubscribed successfully"}

            return {"message": "Subscription not found"}
    except Exception as e:
        print(f"Error unsubscribing: {e}")
        raise HTTPException(status_code=500, detail="Failed to unsubscribe")




@router.get("/audit-logs/stats")
async def get_audit_log_stats(current_user: User = Depends(get_current_user)):
    from collections import Counter
    with Session(engine) as session:
        logs = session.exec(select(AuditLogTable)).all()
        total_actions = len(logs)
        by_action = Counter(log.action for log in logs)
        period_days = 30  # or calculate from logs if needed
        return {
            "total_actions": total_actions,
            "by_action": dict(by_action),
            "period_days": period_days
        }




@router.get("/audit-logs")
async def get_audit_logs(
    page: int = 1,
    page_size: int = 50,
    current_user: User = Depends(get_current_user)
):
    """Get audit logs with pagination"""
    try:
        with Session(engine) as session:
            query = select(AuditLogTable).order_by(AuditLogTable.timestamp.desc())
            result = session.exec(select(AuditLogTable)).all()
            total = len(result)
            query = query.offset((page - 1) * page_size).limit(page_size)
            logs = session.exec(query).all()
            items = [
                {
                    "id": log.id,
                    "user_id": log.user_id,
                    "user_name": log.user_name,
                    "action": log.action,
                    "table_name": log.table_name,
                    "record_id": log.record_id,
                    "before_data": log.before_data,
                    "after_data": log.after_data,
                    "ip_address": log.ip_address,
                    "user_agent": log.user_agent,
                    "timestamp": log.timestamp.isoformat() if log.timestamp else None
                }
                for log in logs
            ]
            total_pages = (total + page_size - 1) // page_size
            return JSONResponse({
                "items": items,
                "total": total,
                "page": page,
                "page_size": page_size,
                "total_pages": total_pages
            })
            with Session(engine) as session:
                query = select(AuditLogTable).order_by(AuditLogTable.timestamp.desc())
                total = session.exec(select(AuditLogTable)).count()
                query = query.offset((page - 1) * page_size).limit(page_size)
                logs = session.exec(query).all()
                items = [
                    {
                        "id": log.id,
                        "user_id": log.user_id,
                        "user_name": log.user_name,
                        "action": log.action,
                        "table_name": log.table_name,
                        "record_id": log.record_id,
                        "before_data": log.before_data,
                        "after_data": log.after_data,
                        "ip_address": log.ip_address,
                        "user_agent": log.user_agent,
                        "timestamp": log.timestamp.isoformat() if log.timestamp else None
                    }
                    for log in logs
                ]
                total_pages = (total + page_size - 1) // page_size
                return JSONResponse({
                    "items": items,
                    "total": total,
                    "page": page,
                    "page_size": page_size,
                    "total_pages": total_pages
                })
    except jwt.PyJWTError:
        raise credentials_exception
    # Check SQL DB first
    with Session(engine) as session:
        row = session.get(UserTable, user_id)
        if row:
            return User(
                id=row.id,
                name=row.name,
                email=row.email,
                password_hash=row.password_hash,
                role=row.role,
                is_owner=row.is_owner,
                created_at=row.created_at,
                last_login_at=row.last_login_at,
            )
    for user in users:
        if user.id == user_id:
            return user
    raise credentials_exception

"""Activity logging services."""
from typing import Optional, Dict, Any
import json
from fastapi import Request
from sqlmodel import Session

from config.database import engine
from config.settings import USE_MONGO
from models.activity import ActivityLog, ActivityLogTable, AuditLogTable
from utils.datetime import utcnow

# In-memory data stores
activity_logs = []
_audit_logs = []


def set_data_stores(a, audit=None):
    """Set data stores."""
    global activity_logs, _audit_logs
    activity_logs = a
    if audit is not None:
        _audit_logs = audit


def log_activity(
    user_id: int,
    entity_type: str,
    entity_id: Optional[int],
    action: str,
    changes: Optional[dict] = None
):
    """Log activity to database."""
    log = ActivityLog(
        id=len(activity_logs) + 1,
        user_id=user_id,
        entity_type=entity_type,
        entity_id=entity_id,
        action=action,
        changes=changes,
        created_at=utcnow(),
    )
    activity_logs.insert(0, log)
    
    # Save to SQL
    with Session(engine) as session:
        try:
            session.add(
                ActivityLogTable(
                    user_id=user_id,
                    entity_type=entity_type,
                    entity_id=entity_id,
                    action=action,
                    changes=str(changes) if changes else None,
                    created_at=log.created_at,
                )
            )
            session.commit()
        except Exception:
            session.rollback()


async def create_audit_log(
    user,
    action: str,
    table_name: str,
    record_id: int,
    before_data: Optional[dict],
    after_data: Optional[dict],
    request: Request
):
    """Create audit log entry for compliance tracking."""
    now = utcnow()
    ip = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent", None)
    user_name = getattr(user, "name", None) or getattr(user, "email", "unknown")

    # Always insert into memory first so UI reflects immediately
    entry = {
        "id": len(_audit_logs) + 1,
        "user_id": user.id,
        "user_name": user_name,
        "action": action,
        "table_name": table_name,
        "record_id": record_id,
        "before_data": before_data,
        "after_data": after_data,
        "ip_address": ip,
        "timestamp": now.isoformat(),
    }
    _audit_logs.insert(0, entry)

    # Persist to SQL independently
    try:
        audit_entry = AuditLogTable(
            user_id=user.id,
            user_name=user_name,
            action=action,
            table_name=table_name,
            record_id=record_id,
            before_data=json.dumps(before_data, default=str) if before_data else None,
            after_data=json.dumps(after_data, default=str) if after_data else None,
            ip_address=ip,
            user_agent=user_agent,
            timestamp=now
        )
        with Session(engine) as session:
            session.add(audit_entry)
            session.commit()
            # Update in-memory entry with real DB id
            entry["id"] = audit_entry.id or entry["id"]
    except Exception as e:
        print(f"[AUDIT ERROR] SQL persist failed: {e}")

    print(f"[AUDIT] {action} {table_name} #{record_id} by {user_name}")

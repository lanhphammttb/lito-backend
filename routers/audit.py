"""Audit log routes."""

import json
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends
from sqlmodel import Session, select

from config.database import engine
from models.activity import AuditLogTable
from models.user import User
from services.auth import get_current_user

router = APIRouter()


def _audit_payload(row: AuditLogTable) -> dict:
    def parse_json(value):
        if not value:
            return None
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value

    return {
        "id": row.id,
        "user_id": row.user_id,
        "user_name": row.user_name,
        "action": row.action,
        "table_name": row.table_name,
        "record_id": row.record_id,
        "before_data": parse_json(row.before_data),
        "after_data": parse_json(row.after_data),
        "ip_address": row.ip_address,
        "user_agent": row.user_agent,
        "timestamp": row.timestamp.isoformat() if row.timestamp else None,
    }


@router.get("/logs")
async def list_audit_logs(
    skip: int = 0, limit: int = 100,
    page: int = 1, page_size: int = 50,
    action: Optional[str] = None,
    user_id: Optional[int] = None,
    table_name: Optional[str] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    user: User = Depends(get_current_user)
):
    """List audit logs with page/skip pagination support."""
    stmt = select(AuditLogTable)
    if action:
        stmt = stmt.where(AuditLogTable.action == action)
    if user_id:
        stmt = stmt.where(AuditLogTable.user_id == user_id)
    if table_name:
        stmt = stmt.where(AuditLogTable.table_name == table_name)
    if start_date:
        stmt = stmt.where(AuditLogTable.timestamp >= start_date)
    if end_date:
        stmt = stmt.where(AuditLogTable.timestamp <= end_date)

    if skip > 0:
        offset, per_page = skip, limit
    else:
        offset = (page - 1) * page_size
        per_page = page_size

    with Session(engine) as session:
        all_rows = session.exec(stmt.order_by(AuditLogTable.timestamp.desc())).all()
        total = len(all_rows)
        rows = all_rows[offset:offset + per_page]
    return {"items": [_audit_payload(row) for row in rows], "total": total}


@router.get("/stats")
async def get_audit_stats(user: User = Depends(get_current_user)):
    """Get audit log statistics."""
    by_action: dict = {}
    by_user: dict = {}
    with Session(engine) as session:
        rows = session.exec(select(AuditLogTable)).all()
    for row in rows:
        a = row.action or "unknown"
        by_action[a] = by_action.get(a, 0) + 1
        u = str(row.user_id or "?")
        by_user[u] = by_user.get(u, 0) + 1
    return {"total": len(rows), "total_actions": len(rows), "by_action": by_action, "by_user": by_user}

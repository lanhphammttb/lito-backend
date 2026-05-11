"""Activity and audit log routes."""
from typing import List, Optional
from datetime import date
from fastapi import APIRouter, Depends, Query
from sqlmodel import Session, select

from config.database import engine
from models.user import User
from models.activity import ActivityLog, AuditLogTable
from services.auth import get_current_user, require_admin

router = APIRouter()

from models.activity import ActivityLogTable

activity_logs: List[ActivityLog] = []


@router.get("")
async def list_activity(
    skip: int = 0,
    limit: int = 100,
    entity_type: Optional[str] = None,
    user_id: Optional[int] = None,
    action: Optional[str] = None,
    user: User = Depends(get_current_user)
):
    """List activity logs from DB."""
    import json
    with Session(engine) as session:
        statement = select(ActivityLogTable)
        if entity_type:
            statement = statement.where(ActivityLogTable.entity_type == entity_type)
        if user_id:
            statement = statement.where(ActivityLogTable.user_id == user_id)
        if action:
            statement = statement.where(ActivityLogTable.action == action)
            
        statement = statement.order_by(ActivityLogTable.created_at.desc()).offset(skip).limit(limit)
        results = session.exec(statement).all()
        
        output = []
        for r in results:
            d = r.model_dump()
            try:
                d['changes'] = json.loads(d['changes']) if d['changes'] else None
            except:
                pass
            output.append(d)
        return output


@router.get("/audit")
async def list_audit_logs(
    skip: int = 0,
    limit: int = 100,
    table_name: Optional[str] = None,
    user_id: Optional[int] = None,
    action: Optional[str] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    user: User = Depends(get_current_user)
):
    """List audit logs (admin only)."""
    require_admin(user)
    
    with Session(engine) as session:
        stmt = select(AuditLogTable).order_by(AuditLogTable.timestamp.desc())
        
        results = session.exec(stmt).all()
        
        # Filter in Python (could optimize with SQL WHERE clauses)
        if table_name:
            results = [r for r in results if r.table_name == table_name]
        if user_id:
            results = [r for r in results if r.user_id == user_id]
        if action:
            results = [r for r in results if r.action == action]
        if start_date:
            results = [r for r in results if r.timestamp.date() >= start_date]
        if end_date:
            results = [r for r in results if r.timestamp.date() <= end_date]
        
        return results[skip:skip + limit]


@router.get("/audit/{log_id}")
async def get_audit_log(
    log_id: int,
    user: User = Depends(get_current_user)
):
    """Get single audit log entry."""
    require_admin(user)
    
    with Session(engine) as session:
        log = session.get(AuditLogTable, log_id)
        if not log:
            from fastapi import HTTPException
            raise HTTPException(status_code=404, detail="Audit log không tồn tại")
        return log


@router.get("/summary")
async def activity_summary(
    days: int = 7,
    user: User = Depends(get_current_user)
):
    """Get activity summary from DB."""
    from datetime import datetime, timedelta
    
    cutoff = datetime.utcnow() - timedelta(days=days)
    
    with Session(engine) as session:
        statement = select(ActivityLogTable).where(ActivityLogTable.created_at >= cutoff)
        recent = session.exec(statement).all()
        
        # Group by entity type
        by_entity = {}
        for a in recent:
            entity = a.entity_type
            if entity not in by_entity:
                by_entity[entity] = {"create": 0, "update": 0, "delete": 0, "other": 0}
            action_group = a.action if a.action in ("create", "update", "delete") else "other"
            by_entity[entity][action_group] += 1
        
        # Group by day
        by_day = {}
        for a in recent:
            day = a.created_at.date().isoformat()
            if day not in by_day:
                by_day[day] = 0
            by_day[day] += 1
        
        return {
            "total": len(recent),
            "by_entity_type": by_entity,
            "by_day": by_day,
        }

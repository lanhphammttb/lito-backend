"""Task routes."""
import json
from typing import List, Optional
from datetime import datetime, date
from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session

from config.database import engine
from models.user import User
from models.task import Task, TaskTable
from schemas.task import TaskCreate, TaskUpdate
from services.auth import get_current_user
from services.activity import log_activity

router = APIRouter()

from sqlmodel import select

tasks: List[Task] = []


@router.get("")
async def list_tasks(
    skip: int = 0,
    limit: int = 100,
    status: Optional[str] = None,
    priority: Optional[int] = None,
    assignee_id: Optional[int] = None,
    user: User = Depends(get_current_user)
):
    with Session(engine) as session:
        statement = select(TaskTable)
        if status:
            statement = statement.where(TaskTable.status == status)
        if priority is not None:
            statement = statement.where(TaskTable.priority == priority)
        if assignee_id:
            statement = statement.where(TaskTable.assignee_id == assignee_id)
            
        statement = statement.order_by(TaskTable.priority.asc(), TaskTable.due_date.asc())
        results = session.exec(statement.offset(skip).limit(limit)).all()
        
        output = []
        for r in results:
            d = r.model_dump()
            try:
                d['tags'] = json.loads(d.get('tags_json', '[]') or '[]')
            except:
                d['tags'] = []
            output.append(d)
        return output


@router.get("/my")
async def my_tasks(
    status: Optional[str] = None,
    user: User = Depends(get_current_user)
):
    with Session(engine) as session:
        statement = select(TaskTable).where(TaskTable.assignee_id == user.id)
        if status:
            statement = statement.where(TaskTable.status == status)
            
        results = session.exec(statement).all()
        
        output = []
        for r in results:
            d = r.model_dump()
            try:
                d['tags'] = json.loads(d.get('tags_json', '[]') or '[]')
            except:
                d['tags'] = []
            output.append(d)
        return output


@router.get("/{task_id}")
async def get_task(task_id: int, user: User = Depends(get_current_user)):
    with Session(engine) as session:
        row = session.get(TaskTable, task_id)
        if not row:
            raise HTTPException(status_code=404, detail="Task không tồn tại")
        d = row.model_dump()
        try:
            d['tags'] = json.loads(d.get('tags_json', '[]') or '[]')
        except:
            d['tags'] = []
        return d


@router.post("")
async def create_task(payload: TaskCreate, user: User = Depends(get_current_user)):
    now = datetime.utcnow()

    tags = payload.tags or []
    with Session(engine) as session:
        row = TaskTable(
            title=payload.title,
            description=payload.description,
            status=payload.status or "todo",
            priority=payload.priority or 1,
            assignee_id=payload.assignee_id,
            due_date=payload.due_date,
            tags_json=json.dumps(tags),
            created_by=user.id,
            created_at=now,
        )
        session.add(row)
        session.commit()
        session.refresh(row)
    log_activity(user.id, "task", row.id, "create", {"title": row.title})
    d = row.model_dump()
    d['tags'] = tags
    return d


@router.put("/{task_id}")
async def update_task(task_id: int, payload: TaskUpdate, user: User = Depends(get_current_user)):
    with Session(engine) as session:
        row = session.get(TaskTable, task_id)
        if not row:
            raise HTTPException(status_code=404, detail="Task không tồn tại")
            
        if payload.title is not None:
            row.title = payload.title
        if payload.description is not None:
            row.description = payload.description
        if payload.status is not None:
            row.status = payload.status
        if payload.priority is not None:
            row.priority = payload.priority
        if payload.assignee_id is not None:
            row.assignee_id = payload.assignee_id
        if payload.due_date is not None:
            row.due_date = payload.due_date
        if payload.tags is not None:
            row.tags_json = json.dumps(payload.tags)
            
        if row.status == "done" and not row.completed_at:
            row.completed_at = datetime.utcnow()
            
        session.add(row)
        session.commit()
        session.refresh(row)
        
        log_activity(user.id, "task", task_id, "update", {"title": row.title, "status": row.status})
        
        d = row.model_dump()
        try:
            d['tags'] = json.loads(d.get('tags_json', '[]') or '[]')
        except:
            d['tags'] = []
        return d


@router.patch("/{task_id}/status")
async def update_task_status(task_id: int, payload: dict, user: User = Depends(get_current_user)):
    with Session(engine) as session:
        row = session.get(TaskTable, task_id)
        if not row:
            raise HTTPException(status_code=404, detail="Task không tồn tại")

        new_status = payload.get("status")
        if not new_status:
            raise HTTPException(status_code=400, detail="Thiếu status")

        old_status = row.status
        row.status = new_status
        if new_status == "done" and not row.completed_at:
            row.completed_at = datetime.utcnow()

        session.add(row)
        session.commit()

    log_activity(user.id, "task", task_id, "status_change", {"from": old_status, "to": new_status})
    return {"message": "Đã cập nhật trạng thái", "status": new_status}


@router.delete("/{task_id}")
async def delete_task(task_id: int, user: User = Depends(get_current_user)):
    with Session(engine) as session:
        row = session.get(TaskTable, task_id)
        if not row:
            raise HTTPException(status_code=404, detail="Task không tồn tại")

        session.delete(row)
        session.commit()

    log_activity(user.id, "task", task_id, "delete", {})
    return {"message": "Đã xóa task"}

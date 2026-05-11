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

# In-memory data store
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
    result = tasks[:]
    if status:
        result = [t for t in result if t.status == status]
    if priority is not None:
        result = [t for t in result if t.priority == priority]
    if assignee_id:
        result = [t for t in result if t.assignee_id == assignee_id]
    result.sort(key=lambda x: (x.priority or 99, x.due_date or date.max))
    return result[skip:skip + limit]


@router.get("/my")
async def my_tasks(
    status: Optional[str] = None,
    user: User = Depends(get_current_user)
):
    result = [t for t in tasks if t.assignee_id == user.id]
    if status:
        result = [t for t in result if t.status == status]
    return result


@router.get("/{task_id}")
async def get_task(task_id: int, user: User = Depends(get_current_user)):
    task = next((t for t in tasks if t.id == task_id), None)
    if not task:
        raise HTTPException(status_code=404, detail="Task không tồn tại")
    return task


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
        new_id = row.id

    task = Task(
        id=new_id,
        title=payload.title,
        description=payload.description,
        status=payload.status or "todo",
        priority=payload.priority or 1,
        assignee_id=payload.assignee_id,
        due_date=payload.due_date,
        tags=tags,
        created_by=user.id,
        created_at=now,
    )
    tasks.append(task)
    log_activity(user.id, "task", new_id, "create", {"title": task.title})
    return task


@router.put("/{task_id}")
async def update_task(task_id: int, payload: TaskUpdate, user: User = Depends(get_current_user)):
    task = next((t for t in tasks if t.id == task_id), None)
    if not task:
        raise HTTPException(status_code=404, detail="Task không tồn tại")

    if payload.title is not None:
        task.title = payload.title
    if payload.description is not None:
        task.description = payload.description
    if payload.status is not None:
        task.status = payload.status
    if payload.priority is not None:
        task.priority = payload.priority
    if payload.assignee_id is not None:
        task.assignee_id = payload.assignee_id
    if payload.due_date is not None:
        task.due_date = payload.due_date
    if payload.tags is not None:
        task.tags = payload.tags
    if task.status == "done" and not task.completed_at:
        task.completed_at = datetime.utcnow()

    with Session(engine) as session:
        row = session.get(TaskTable, task_id)
        if row:
            row.title = task.title
            row.description = task.description
            row.status = task.status
            row.priority = task.priority
            row.assignee_id = task.assignee_id
            row.due_date = task.due_date
            row.completed_at = task.completed_at
            row.tags_json = json.dumps(task.tags or [])
            session.add(row)
            session.commit()

    log_activity(user.id, "task", task_id, "update", {"title": task.title, "status": task.status})
    return task


@router.patch("/{task_id}/status")
async def update_task_status(task_id: int, payload: dict, user: User = Depends(get_current_user)):
    task = next((t for t in tasks if t.id == task_id), None)
    if not task:
        raise HTTPException(status_code=404, detail="Task không tồn tại")

    new_status = payload.get("status")
    if not new_status:
        raise HTTPException(status_code=400, detail="Thiếu status")

    old_status = task.status
    task.status = new_status
    if new_status == "done" and not task.completed_at:
        task.completed_at = datetime.utcnow()

    with Session(engine) as session:
        row = session.get(TaskTable, task_id)
        if row:
            row.status = new_status
            row.completed_at = task.completed_at
            session.add(row)
            session.commit()

    log_activity(user.id, "task", task_id, "status_change", {"from": old_status, "to": new_status})
    return {"message": "Đã cập nhật trạng thái", "status": new_status}


@router.delete("/{task_id}")
async def delete_task(task_id: int, user: User = Depends(get_current_user)):
    task = next((t for t in tasks if t.id == task_id), None)
    if not task:
        raise HTTPException(status_code=404, detail="Task không tồn tại")

    tasks.remove(task)
    with Session(engine) as session:
        row = session.get(TaskTable, task_id)
        if row:
            session.delete(row)
            session.commit()

    log_activity(user.id, "task", task_id, "delete", {})
    return {"message": "Đã xóa task"}

"""Task model."""
from typing import Optional, List
from datetime import datetime, date
from pydantic import BaseModel, Field
from sqlmodel import SQLModel, Field as SQLField


class Task(BaseModel):
    """Task model."""
    id: int
    title: str
    description: Optional[str] = None
    assignee_id: Optional[int] = None
    due_date: Optional[date] = None
    priority: int = 1
    status: str = "todo"  # todo, in_progress, done
    tags: List[str] = []
    created_by: Optional[int] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None


class TaskTable(SQLModel, table=True):
    """Task database table."""
    __tablename__ = "tasks"
    
    id: Optional[int] = SQLField(default=None, primary_key=True)
    title: str
    description: Optional[str] = None
    assignee_id: Optional[int] = None
    due_date: Optional[date] = None
    priority: int = 1
    status: str = "todo"
    tags_json: str = "[]"
    created_by: Optional[int] = None
    created_at: datetime = SQLField(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None

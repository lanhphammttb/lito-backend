"""Task schemas."""
from typing import Optional, List
from datetime import date
from pydantic import BaseModel


class TaskCreate(BaseModel):
    """Task create schema."""
    title: str
    description: Optional[str] = None
    assignee_id: Optional[int] = None
    due_date: Optional[date] = None
    priority: int = 1
    status: str = "todo"
    tags: List[str] = []


class TaskUpdate(BaseModel):
    """Task update schema - all fields optional."""
    title: Optional[str] = None
    description: Optional[str] = None
    assignee_id: Optional[int] = None
    due_date: Optional[date] = None
    priority: Optional[int] = None
    status: Optional[str] = None
    tags: Optional[List[str]] = None

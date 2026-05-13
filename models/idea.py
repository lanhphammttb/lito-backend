"""Idea model."""
from typing import Optional
from datetime import datetime
from sqlmodel import SQLModel, Field as SQLField


class IdeaTable(SQLModel, table=True):
    __tablename__ = "ideas"

    id: Optional[int] = SQLField(default=None, primary_key=True)
    name: str
    description: Optional[str] = None
    source: Optional[str] = None
    status: str = "Chưa thử"
    priority: int = 1
    estimated_time: Optional[int] = None
    estimated_price: Optional[float] = None
    created_by: Optional[int] = None
    updated_by: Optional[int] = None
    created_at: datetime = SQLField(default_factory=datetime.utcnow)

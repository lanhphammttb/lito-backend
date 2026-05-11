"""Idea model."""
from typing import Optional
from datetime import datetime
from pydantic import BaseModel, Field
from sqlmodel import SQLModel, Field as SQLField


class Idea(BaseModel):
    """Idea model."""
    id: int
    title: str
    name: Optional[str] = None         # alias for title, used by frontend
    description: Optional[str] = None
    source: Optional[str] = None
    status: str = "Chưa thử"
    priority: int = 1
    estimated_time: Optional[int] = None    # minutes
    estimated_price: Optional[float] = None
    created_by: Optional[int] = None
    updated_by: Optional[int] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)

    def model_post_init(self, __context):
        if self.name is None:
            self.name = self.title


class IdeaTable(SQLModel, table=True):
    """Idea database table."""
    __tablename__ = "ideas"
    
    id: Optional[int] = SQLField(default=None, primary_key=True)
    title: str
    description: Optional[str] = None
    source: Optional[str] = None
    status: str = "Chưa thử"
    priority: int = 1
    estimated_time: Optional[int] = None
    estimated_price: Optional[float] = None
    created_by: Optional[int] = None
    updated_by: Optional[int] = None
    created_at: datetime = SQLField(default_factory=datetime.utcnow)

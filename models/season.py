"""Season model."""
from typing import Optional
from datetime import datetime, date
from pydantic import BaseModel, Field
from sqlmodel import SQLModel, Field as SQLField


class Season(BaseModel):
    """Season model."""
    id: int
    name: str
    from_date: date
    to_date: date
    description: Optional[str] = None
    created_by: Optional[int] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class SeasonTable(SQLModel, table=True):
    """Season database table."""
    __tablename__ = "seasons"
    
    id: Optional[int] = SQLField(default=None, primary_key=True)
    name: str
    from_date: date
    to_date: date
    description: Optional[str] = None
    created_by: Optional[int] = None
    created_at: datetime = SQLField(default_factory=datetime.utcnow)

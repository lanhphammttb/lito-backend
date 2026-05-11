"""Goal model."""
from typing import Optional
from datetime import datetime, date
from pydantic import BaseModel, Field
from sqlmodel import SQLModel, Field as SQLField


class Goal(BaseModel):
    """Business goal model."""
    id: int
    title: str
    description: Optional[str] = None
    target_type: str = "revenue"  # revenue, profit, orders, customers
    target_value: float = 0
    current_value: float = 0
    start_date: date
    end_date: date
    status: str = "active"  # active, achieved, missed
    achieved_at: Optional[datetime] = None
    created_by: Optional[int] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class GoalTable(SQLModel, table=True):
    """Goal database table."""
    __tablename__ = "goals"
    
    id: Optional[int] = SQLField(default=None, primary_key=True)
    title: str
    description: Optional[str] = None
    target_type: str = "revenue"
    target_value: float = 0
    current_value: float = 0
    start_date: date
    end_date: date
    status: str = "active"
    achieved_at: Optional[datetime] = None
    created_by: Optional[int] = None
    created_at: datetime = SQLField(default_factory=datetime.utcnow)

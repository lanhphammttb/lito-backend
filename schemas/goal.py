"""Goal schemas."""
from typing import Optional
from datetime import date
from pydantic import BaseModel


class GoalCreate(BaseModel):
    """Goal create schema."""
    title: str
    description: Optional[str] = None
    target_type: str = "revenue"
    target_value: float = 0
    start_date: date
    end_date: date

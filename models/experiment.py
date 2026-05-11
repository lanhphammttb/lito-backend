"""Experiment model."""
from typing import Optional
from datetime import datetime, date
from pydantic import BaseModel, Field
from sqlmodel import SQLModel, Field as SQLField


class Experiment(BaseModel):
    """A/B testing experiment model."""
    id: int
    name: str
    description: Optional[str] = None
    hypothesis: Optional[str] = None
    status: str = "draft"  # draft, running, completed, cancelled
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    variant_a: Optional[str] = None
    variant_b: Optional[str] = None
    metric: Optional[str] = None
    result_a: Optional[float] = None
    result_b: Optional[float] = None
    winner: Optional[str] = None
    conclusion: Optional[str] = None
    created_by: Optional[int] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class ExperimentTable(SQLModel, table=True):
    """Experiment database table."""
    __tablename__ = "experiments"
    
    id: Optional[int] = SQLField(default=None, primary_key=True)
    name: str
    description: Optional[str] = None
    hypothesis: Optional[str] = None
    status: str = "draft"
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    variant_a: Optional[str] = None
    variant_b: Optional[str] = None
    metric: Optional[str] = None
    result_a: Optional[float] = None
    result_b: Optional[float] = None
    winner: Optional[str] = None
    conclusion: Optional[str] = None
    created_by: Optional[int] = None
    created_at: datetime = SQLField(default_factory=datetime.utcnow)

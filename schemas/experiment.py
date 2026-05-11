"""Experiment schemas."""
from typing import Optional
from datetime import date
from pydantic import BaseModel


class ExperimentCreate(BaseModel):
    """Experiment create schema."""
    name: str
    description: Optional[str] = None
    hypothesis: Optional[str] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    variant_a: Optional[str] = None
    variant_b: Optional[str] = None
    metric: Optional[str] = None


class ExperimentUpdate(BaseModel):
    """Experiment update schema."""
    status: Optional[str] = None
    result_a: Optional[float] = None
    result_b: Optional[float] = None
    winner: Optional[str] = None
    conclusion: Optional[str] = None

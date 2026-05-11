"""Forecast schemas."""
from typing import List, Dict
from pydantic import BaseModel, Field


class ForecastRequest(BaseModel):
    """Forecast request parameters."""
    periods: int = Field(default=6, ge=1, le=24, description="Number of periods to forecast")
    period_type: str = Field(default="month", pattern="^(day|week|month)$")


class ForecastResponse(BaseModel):
    """Forecast response."""
    historical: List[Dict]
    forecast: List[Dict]
    metrics: Dict
    trend: str
    confidence: float

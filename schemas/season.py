"""Season schemas."""
from typing import Optional
from datetime import date
from pydantic import BaseModel


class SeasonCreate(BaseModel):
    """Season create schema."""
    name: str
    from_date: date
    to_date: date
    description: Optional[str] = None

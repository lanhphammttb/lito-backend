"""Category schemas."""
from typing import Optional
from pydantic import BaseModel


class CategoryCreate(BaseModel):
    """Category create schema."""
    name: str
    parent_id: Optional[int] = None
    description: Optional[str] = None
    display_order: int = 0

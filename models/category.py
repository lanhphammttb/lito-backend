"""Category model."""
from typing import Optional
from datetime import datetime
from pydantic import BaseModel, Field
from sqlmodel import SQLModel, Field as SQLField


class Category(BaseModel):
    """Category model."""
    id: int
    name: str
    parent_id: Optional[int] = None
    description: Optional[str] = None
    display_order: int = 0
    created_at: datetime = Field(default_factory=datetime.utcnow)


class CategoryTable(SQLModel, table=True):
    """Category database table."""
    __tablename__ = "categories"
    
    id: Optional[int] = SQLField(default=None, primary_key=True)
    name: str
    parent_id: Optional[int] = None
    description: Optional[str] = None
    display_order: int = 0
    created_at: datetime = SQLField(default_factory=datetime.utcnow)

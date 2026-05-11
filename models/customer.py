"""Customer models."""
from typing import Optional, List
from datetime import datetime, date
from pydantic import BaseModel, Field
from sqlmodel import SQLModel, Field as SQLField


class Customer(BaseModel):
    """Customer domain model."""
    id: int
    name: str
    phone: Optional[str] = None
    email: Optional[str] = None
    address: Optional[str] = None
    source: Optional[str] = None
    tags: List[str] = []
    notes: Optional[str] = None
    total_orders: int = 0
    total_spent: float = 0
    last_order_date: Optional[date] = None
    first_order_date: Optional[date] = None
    created_by: Optional[int] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class CustomerTable(SQLModel, table=True):
    """Customer database table."""
    __tablename__ = "customers"
    
    id: Optional[int] = SQLField(default=None, primary_key=True)
    name: str = SQLField(index=True)
    phone: Optional[str] = None
    email: Optional[str] = None
    address: Optional[str] = None
    source: Optional[str] = None
    tags_json: str = "[]"
    notes: Optional[str] = None
    total_orders: int = 0
    total_spent: float = 0
    last_order_date: Optional[date] = None
    first_order_date: Optional[date] = None
    created_by: Optional[int] = None
    created_at: datetime = SQLField(default_factory=datetime.utcnow)

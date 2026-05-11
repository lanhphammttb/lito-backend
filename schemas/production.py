"""Production job schemas."""
from typing import Optional, List
from datetime import datetime
from pydantic import BaseModel, field_validator


class ProductionJobCreate(BaseModel):
    order_id: Optional[int] = None  # None = make-to-stock
    product_id: int
    quantity: int = 1
    assigned_to: Optional[int] = None
    notes: Optional[str] = None
    due_at: Optional[datetime] = None

    @field_validator("quantity")
    @classmethod
    def quantity_positive(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("Số lượng phải lớn hơn 0")
        return v


class ProductionJobStatusUpdate(BaseModel):
    status: str
    notes: Optional[str] = None

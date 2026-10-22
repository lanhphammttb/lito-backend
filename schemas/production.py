"""Production job schemas."""
from typing import Optional, List
from datetime import datetime
from pydantic import BaseModel, Field, field_validator
from models.product import MaterialUsage


class JobMaterialSelection(MaterialUsage):
    quantity: float = Field(gt=0, allow_inf_nan=False)
    wastage_percent: float = Field(default=0, ge=0, le=100, allow_inf_nan=False)
    product_wastage_percent: Optional[float] = Field(default=None, ge=0, le=100, allow_inf_nan=False)


class ProductionJobCreate(BaseModel):
    order_id: Optional[int] = None  # None = make-to-stock
    product_id: int
    quantity: int = 1
    assigned_to: Optional[int] = None
    notes: Optional[str] = None
    due_at: Optional[datetime] = None
    materials: Optional[List[JobMaterialSelection]] = None

    @field_validator("quantity")
    @classmethod
    def quantity_positive(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("Số lượng phải lớn hơn 0")
        return v


class ProductionJobStatusUpdate(BaseModel):
    status: str
    notes: Optional[str] = None


class ProductionJobUpdate(BaseModel):
    quantity: Optional[int] = Field(default=None, gt=0)
    assigned_to: Optional[int] = None
    notes: Optional[str] = None
    due_at: Optional[datetime] = None
    materials: Optional[List[JobMaterialSelection]] = None

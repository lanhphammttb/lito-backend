"""Inventory schemas."""
from typing import Optional, List, Any
from datetime import date
from pydantic import BaseModel, field_validator
from models.inventory import PurchaseOrderLine


class SupplierCreate(BaseModel):
    """Supplier create schema."""
    name: str
    contact_name: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    address: Optional[str] = None
    note: Optional[str] = None
    rating: Optional[float] = None
    lead_time_days: Optional[int] = None


class PurchaseOrderCreate(BaseModel):
    """Purchase order create schema."""
    supplier_id: Optional[int] = None
    status: str = "draft"
    expected_date: Optional[date] = None
    note: Optional[str] = None
    lines: List[PurchaseOrderLine] = []

    @field_validator('expected_date', mode='before')
    @classmethod
    def coerce_date(cls, v: Any) -> Any:
        if isinstance(v, str) and 'T' in v:
            return v.split('T')[0]
        return v

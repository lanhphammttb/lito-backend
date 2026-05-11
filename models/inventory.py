"""Inventory models - Suppliers and Purchase Orders."""
from typing import Optional, List
from datetime import datetime, date
from pydantic import BaseModel, Field
from sqlmodel import SQLModel, Field as SQLField


class Supplier(BaseModel):
    """Supplier model."""
    id: int
    name: str
    contact_name: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    address: Optional[str] = None
    notes: Optional[str] = None  # legacy field
    note: Optional[str] = None
    rating: Optional[float] = None
    lead_time_days: Optional[int] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class SupplierTable(SQLModel, table=True):
    """Supplier database table."""
    __tablename__ = "suppliers"

    id: Optional[int] = SQLField(default=None, primary_key=True)
    name: str
    contact_name: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    address: Optional[str] = None
    notes: Optional[str] = None  # legacy column
    note: Optional[str] = None
    rating: Optional[float] = None
    lead_time_days: Optional[int] = None
    created_at: datetime = SQLField(default_factory=datetime.utcnow)


class PurchaseOrderLine(BaseModel):
    """Purchase order line item."""
    material_id: int
    quantity: float
    unit_price: float
    batch_id: Optional[str] = None
    expiry_date: Optional[date] = None


class PurchaseOrder(BaseModel):
    """Purchase order model."""
    id: int
    supplier_id: Optional[int] = None
    status: str = "draft"  # draft, ordered, received, cancelled
    payment_status: str = "unpaid"  # unpaid, partial, paid
    expected_date: Optional[date] = None
    received_at: Optional[datetime] = None
    note: Optional[str] = None
    lines: List[PurchaseOrderLine] = []
    total_amount: float = 0
    paid_amount: float = 0
    created_by: Optional[int] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class PurchaseOrderTable(SQLModel, table=True):
    """Purchase order database table."""
    __tablename__ = "purchase_orders"

    id: Optional[int] = SQLField(default=None, primary_key=True)
    supplier_id: Optional[int] = SQLField(default=None, index=True)
    status: str = "draft"
    payment_status: str = "unpaid"
    expected_date: Optional[date] = None
    received_at: Optional[datetime] = None
    note: Optional[str] = None
    lines_json: str = "[]"
    total_amount: float = 0
    paid_amount: float = 0
    created_by: Optional[int] = None
    created_at: datetime = SQLField(default_factory=datetime.utcnow)

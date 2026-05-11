from sqlmodel import SQLModel, Field
from typing import Optional
from datetime import datetime

class MaterialTable(SQLModel, table=True):
    __tablename__ = "materialtable"
    id: Optional[int] = Field(default=None, primary_key=True)
    code: str = Field(index=True, unique=True)
    name: str
    type: str
    unit: str
    unit_price: float
    stock_quantity: float
    low_threshold: float = 1.0
    note: Optional[str] = None
    created_by: Optional[int] = None
    updated_by: Optional[int] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)

class StockMovementTable(SQLModel, table=True):
    __tablename__ = "stockmovementtable"
    id: Optional[int] = Field(default=None, primary_key=True)
    material_id: int = Field(index=True)
    quantity_change: float
    type: str
    reference_id: Optional[int] = None
    user_id: Optional[int] = None
    note: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)

class SupplierTable(SQLModel, table=True):
    __tablename__ = "suppliertable"
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    contact_name: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    address: Optional[str] = None
    notes: Optional[str] = None
    created_by: Optional[int] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)

class PurchaseOrderTable(SQLModel, table=True):
    __tablename__ = "purchaseordertable"
    id: Optional[int] = Field(default=None, primary_key=True)
    supplier_id: int = Field(index=True)
    status: str = Field(default="draft")
    total_amount: float = 0.0
    expected_date: Optional[datetime] = None
    received_date: Optional[datetime] = None
    notes: Optional[str] = None
    items_str: str = "[]"
    created_by: Optional[int] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)

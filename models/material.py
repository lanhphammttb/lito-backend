"""Material models."""
from typing import Optional
from datetime import datetime, date
from pydantic import BaseModel, Field
from sqlmodel import SQLModel, Field as SQLField


class Material(BaseModel):
    """Material domain model."""
    id: int
    code: str
    name: str
    type: str = "fabric"
    unit: str = "m"
    # "continuous" = gram/m/ml (có thể chia nhỏ), "piece" = cái/cặp/bộ (làm tròn lên khi tính BOM)
    unit_type: str = "continuous"
    base_unit: Optional[str] = None
    unit_price: float = 0
    stock_quantity: float = 0
    on_hand_qty: float = 0
    reserved_qty: float = 0
    available_qty: float = 0
    low_threshold: float = 1.0
    supplier_id: Optional[int] = None
    note: Optional[str] = None
    batch_id: Optional[str] = None
    expiry_date: Optional[date] = None
    created_by: Optional[int] = None
    updated_by: Optional[int] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class MaterialTable(SQLModel, table=True):
    """Material database table."""
    __tablename__ = "materials"

    id: Optional[int] = SQLField(default=None, primary_key=True)
    code: str = SQLField(unique=True, index=True)
    name: str
    type: str = "fabric"
    unit: str = "m"
    unit_type: str = "continuous"
    base_unit: Optional[str] = None
    unit_price: float = 0
    stock_quantity: float = 0
    on_hand_qty: float = 0
    reserved_qty: float = 0
    available_qty: float = 0
    low_threshold: float = 1.0
    supplier_id: Optional[int] = SQLField(default=None, index=True)
    note: Optional[str] = None
    batch_id: Optional[str] = None
    expiry_date: Optional[date] = None
    created_by: Optional[int] = None
    updated_by: Optional[int] = None
    created_at: datetime = SQLField(default_factory=datetime.utcnow)


class MaterialBatch(BaseModel):
    """A received lot/batch of a specific material."""
    id: int
    material_id: int
    batch_code: str
    purchase_order_id: Optional[int] = None
    supplier_id: Optional[int] = None
    quantity_received: float
    quantity_remaining: float
    unit_cost: float = 0
    received_date: date
    note: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class MaterialBatchTable(SQLModel, table=True):
    """Material batch/lot table — one row per received shipment."""
    __tablename__ = "material_batches"

    id: Optional[int] = SQLField(default=None, primary_key=True)
    material_id: int = SQLField(index=True)
    batch_code: str
    purchase_order_id: Optional[int] = SQLField(default=None, index=True)
    supplier_id: Optional[int] = None
    quantity_received: float
    quantity_remaining: float
    unit_cost: float = 0
    received_date: date
    note: Optional[str] = None
    created_at: datetime = SQLField(default_factory=datetime.utcnow)


class StockMovement(BaseModel):
    """Stock movement record."""
    id: int
    material_id: int
    quantity_change: float
    movement_type: str = "adjustment"  # purchase, reserve, release, consume, adjustment, return
    reference_type: Optional[str] = None  # order, purchase_order
    reference_id: Optional[int] = None
    batch_id: Optional[str] = None
    expiry_date: Optional[date] = None
    unit_price: Optional[float] = None
    new_price: Optional[float] = None
    user_id: Optional[int] = None
    note: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class StockMovementTable(SQLModel, table=True):
    """Stock movement database table."""
    __tablename__ = "stock_movements"

    id: Optional[int] = SQLField(default=None, primary_key=True)
    material_id: int = SQLField(index=True)
    quantity_change: float
    movement_type: str = "adjustment"
    reference_type: Optional[str] = None
    reference_id: Optional[int] = None
    batch_id: Optional[str] = None
    expiry_date: Optional[date] = None
    unit_price: Optional[float] = None
    new_price: Optional[float] = None
    user_id: Optional[int] = None
    note: Optional[str] = None
    created_at: datetime = SQLField(default_factory=datetime.utcnow)


class MaterialPriceEntry(BaseModel):
    """A price record for a material from a specific supplier at a point in time."""
    id: int
    material_id: int
    supplier_id: Optional[int] = None
    supplier_name: Optional[str] = None
    unit_price: float
    total_quantity: Optional[float] = None
    total_amount: Optional[float] = None
    purchase_date: date
    quality_rating: Optional[int] = None  # 1-5
    note: Optional[str] = None
    created_by: Optional[int] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class MaterialPriceEntryTable(SQLModel, table=True):
    """Material price history — one row per supplier price quote or purchase."""
    __tablename__ = "material_price_history"

    id: Optional[int] = SQLField(default=None, primary_key=True)
    material_id: int = SQLField(index=True)
    supplier_id: Optional[int] = SQLField(default=None, index=True)
    supplier_name: Optional[str] = None
    unit_price: float
    total_quantity: Optional[float] = None
    total_amount: Optional[float] = None
    purchase_date: date
    quality_rating: Optional[int] = None
    note: Optional[str] = None
    created_by: Optional[int] = None
    created_at: datetime = SQLField(default_factory=datetime.utcnow)

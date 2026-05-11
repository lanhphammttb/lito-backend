from sqlmodel import SQLModel, Field
from typing import Optional
from datetime import datetime

class ProductTable(SQLModel, table=True):
    __tablename__ = "producttable"
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    difficulty: int
    time_minutes: int
    base_price: float
    priority: int = 1
    notes: Optional[str] = None
    role: str = Field(default="core")
    lifecycle_status: str = Field(default="idea")
    packaging_cost: float = Field(default=0.0)
    marketing_cost: float = Field(default=0.0)
    platform_fee_percent: float = Field(default=0.0)
    tags_str: str = ""
    materials_str: str = "[]"
    seasons_str: str = "[]"
    categories_str: str = "[]"
    demand_score: Optional[float] = 0.0
    feasibility_score: Optional[float] = 0.0
    created_by: Optional[int] = None
    updated_by: Optional[int] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)

class ProductVariantTable(SQLModel, table=True):
    __tablename__ = "productvarianttable"
    id: Optional[int] = Field(default=None, primary_key=True)
    product_id: int = Field(index=True)
    name: str
    sku: Optional[str] = None
    price_modifier: float = 0.0
    stock_quantity: float = 0.0
    is_active: bool = True
    created_at: datetime = Field(default_factory=datetime.utcnow)

class PriceChangeTable(SQLModel, table=True):
    __tablename__ = "pricechangetable"
    id: Optional[int] = Field(default=None, primary_key=True)
    product_id: int = Field(index=True)
    old_price: float
    new_price: float
    changed_by: Optional[int] = None
    changed_at: datetime = Field(default_factory=datetime.utcnow)

class LifecycleEventTable(SQLModel, table=True):
    __tablename__ = "lifecycleeventtable"
    id: Optional[int] = Field(default=None, primary_key=True)
    product_id: int = Field(index=True)
    status: str
    note: Optional[str] = None
    changed_by: Optional[int] = None
    changed_at: datetime = Field(default_factory=datetime.utcnow)

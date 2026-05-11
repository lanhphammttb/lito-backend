"""Product models."""
from typing import Optional, List, Dict, Any
from datetime import datetime
from pydantic import BaseModel, Field
from sqlmodel import SQLModel, Field as SQLField
import json


class MaterialUsage(BaseModel):
    """Material usage in a product."""
    material_id: int
    quantity: float
    wastage_percent: float = 0
    usage_unit: Optional[str] = None


class Product(BaseModel):
    """Product domain model."""
    id: int
    name: str
    base_price: float = 0
    price: float = 0  # alias for base_price for compatibility
    difficulty: int = 3
    time_minutes: int = 60
    wastage_percent: float = 0
    notes: Optional[str] = None
    tags: List[str] = []
    materials: List[MaterialUsage] = []
    categories: List[int] = []
    seasons: List[int] = []
    priority: int = 1
    role: str = "core"
    lifecycle_status: str = "idea"
    packaging_cost: float = 0
    marketing_cost: float = 0
    platform_fee_percent: float = 0
    cost_breakdown: Optional[Dict[str, float]] = None
    demand_score: float = 0
    feasibility_score: float = 0
    finished_qty: int = 0
    created_by: Optional[int] = None
    updated_by: Optional[int] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: Optional[datetime] = None


class ProductTable(SQLModel, table=True):
    """Product database table."""
    __tablename__ = "products"

    id: Optional[int] = SQLField(default=None, primary_key=True)
    name: str = SQLField(index=True)
    base_price: float = 0
    difficulty: int = 3
    time_minutes: int = 60
    wastage_percent: float = 0
    notes: Optional[str] = None
    tags_json: str = "[]"
    materials_json: str = "[]"
    categories_json: str = "[]"
    seasons_json: str = "[]"
    priority: int = 1
    role: str = "core"
    lifecycle_status: str = "idea"
    packaging_cost: float = 0
    marketing_cost: float = 0
    platform_fee_percent: float = 0
    cost_breakdown_json: Optional[str] = None
    demand_score: float = 0
    feasibility_score: float = 0
    finished_qty: int = 0
    created_by: Optional[int] = None
    updated_by: Optional[int] = None
    created_at: datetime = SQLField(default_factory=datetime.utcnow)
    updated_at: Optional[datetime] = None


class ProductComputed(Product):
    """Product with computed metrics."""
    material_cost: float = 0
    labor_cost: float = 0
    profit_per_unit: float = 0
    profit_margin: float = 0
    profit_per_hour: float = 0
    max_units_from_stock: Optional[int] = None
    shortage_materials: List[dict] = []
    feasibility_breakdown: Optional[Dict[str, float]] = None


class ProductVariant(BaseModel):
    """Product variant model."""
    id: int
    product_id: int
    name: str
    sku: Optional[str] = None
    price_modifier: float = 0
    stock_quantity: int = 0
    is_active: bool = True
    created_at: datetime = Field(default_factory=datetime.utcnow)


class ProductVariantTable(SQLModel, table=True):
    """Product variant database table."""
    __tablename__ = "product_variants"

    id: Optional[int] = SQLField(default=None, primary_key=True)
    product_id: int = SQLField(index=True)
    name: str
    sku: Optional[str] = None
    price_modifier: float = 0
    stock_quantity: int = 0
    is_active: bool = True
    created_at: datetime = SQLField(default_factory=datetime.utcnow)


class ProductBundle(BaseModel):
    """Product bundle model."""
    id: int
    parent_product_id: int
    child_product_id: int
    quantity: int = 1
    discount_percent: float = 0
    created_at: datetime = Field(default_factory=datetime.utcnow)


class ProductBundleTable(SQLModel, table=True):
    """Product bundle database table."""
    __tablename__ = "product_bundles"

    id: Optional[int] = SQLField(default=None, primary_key=True)
    parent_product_id: int = SQLField(index=True)
    child_product_id: int
    quantity: int = 1
    discount_percent: float = 0
    created_at: datetime = SQLField(default_factory=datetime.utcnow)


class ProductImage(BaseModel):
    """Product image model."""
    id: int
    product_id: int
    url: str
    type: str = "image"  # image, video
    display_order: int = 0
    is_primary: bool = False
    is_public: bool = True
    created_at: datetime = Field(default_factory=datetime.utcnow)


class ProductImageTable(SQLModel, table=True):
    """Product image database table."""
    __tablename__ = "product_images"

    id: Optional[int] = SQLField(default=None, primary_key=True)
    product_id: int = SQLField(index=True)
    url: str
    type: str = "image"
    display_order: int = 0
    is_primary: bool = False
    is_public: bool = True
    created_at: datetime = SQLField(default_factory=datetime.utcnow)


class ProductReview(BaseModel):
    """Product review model."""
    id: int
    product_id: int
    customer_id: Optional[int] = None
    customer_name: Optional[str] = None
    rating: int = 5
    content: Optional[str] = None
    has_image: bool = False
    images: List[str] = []
    created_at: datetime = Field(default_factory=datetime.utcnow)


class ProductReviewTable(SQLModel, table=True):
    """Product review database table."""
    __tablename__ = "product_reviews"

    id: Optional[int] = SQLField(default=None, primary_key=True)
    product_id: int = SQLField(index=True)
    customer_id: Optional[int] = None
    customer_name: Optional[str] = None
    rating: int = 5
    content: Optional[str] = None
    has_image: bool = False
    images_json: str = "[]"
    created_at: datetime = SQLField(default_factory=datetime.utcnow)


class PriceChange(BaseModel):
    """Price change history."""
    id: int
    product_id: int
    old_price: float
    new_price: float
    changed_by: Optional[int] = None
    changed_at: datetime = Field(default_factory=datetime.utcnow)


class PriceChangeTable(SQLModel, table=True):
    """Price change database table."""
    __tablename__ = "price_changes"

    id: Optional[int] = SQLField(default=None, primary_key=True)
    product_id: int = SQLField(index=True)
    old_price: float
    new_price: float
    changed_by: Optional[int] = None
    changed_at: datetime = SQLField(default_factory=datetime.utcnow)


class LifecycleEvent(BaseModel):
    """Product lifecycle event."""
    id: int
    product_id: int
    status: str
    note: Optional[str] = None
    changed_by: Optional[int] = None
    changed_at: datetime = Field(default_factory=datetime.utcnow)


class LifecycleEventTable(SQLModel, table=True):
    """Lifecycle event database table."""
    __tablename__ = "lifecycle_events"

    id: Optional[int] = SQLField(default=None, primary_key=True)
    product_id: int = SQLField(index=True)
    status: str
    note: Optional[str] = None
    changed_by: Optional[int] = None
    changed_at: datetime = SQLField(default_factory=datetime.utcnow)

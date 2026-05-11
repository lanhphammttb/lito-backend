"""Product schemas."""
from typing import Optional, List, Dict
from pydantic import BaseModel
from models.product import MaterialUsage


class ProductBase(BaseModel):
    """Base product schema for create/update."""
    name: str
    base_price: float = 0
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


class ProductCreate(ProductBase):
    """Product create schema."""
    pass


class ProductVariantCreate(BaseModel):
    """Product variant create schema."""
    product_id: int
    name: str
    sku: Optional[str] = None
    price_modifier: float = 0
    stock_quantity: int = 0
    is_active: bool = True


class ProductBundleCreate(BaseModel):
    """Product bundle create schema."""
    parent_product_id: int
    child_product_id: int
    quantity: int = 1
    discount_percent: float = 0


class ProductImageCreate(BaseModel):
    """Product image create schema."""
    product_id: int
    url: str
    type: str = "image"
    display_order: int = 0
    is_primary: bool = False


class ProductReviewCreate(BaseModel):
    """Product review create schema."""
    product_id: int
    customer_id: Optional[int] = None
    customer_name: Optional[str] = None
    rating: int = 5
    content: Optional[str] = None
    has_image: bool = False
    images: List[str] = []

from pydantic import BaseModel, Field, field_validator
from typing import Optional, List, Dict
from datetime import datetime
import re

# We can duplicate the small validators here or import from core
def validate_positive_number(value: float, field_name: str) -> float:
    if value < 0: raise ValueError(f'{field_name} phải >= 0')
    return value

PRODUCT_ROLE_ALLOWED = {"core", "experiment", "seasonal"}
PRODUCT_LIFECYCLE_ALLOWED = {"idea", "prototype", "experiment", "live", "failed"}

class MaterialUsage(BaseModel):
    material_id: int
    quantity: float

class ProductBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    difficulty: int = Field(ge=1, le=5)
    time_minutes: int = Field(..., gt=0, le=10080)
    materials: List[MaterialUsage] = Field(default_factory=list)
    base_price: float = Field(..., ge=0)
    priority: int = Field(1, ge=1, le=5)
    notes: Optional[str] = Field(None, max_length=2000)
    tags: List[str] = Field(default_factory=list, max_length=20)
    seasons: List[int] = Field(default_factory=list)
    categories: List[int] = Field(default_factory=list)
    role: str = Field("core", pattern="^(core|experiment|seasonal)$")
    lifecycle_status: str = Field("idea", pattern="^(idea|prototype|experiment|live|failed)$")
    packaging_cost: float = Field(0.0, ge=0)
    marketing_cost: float = Field(0.0, ge=0)
    platform_fee_percent: float = Field(0.0, ge=0, le=100)

    @field_validator('name')
    @classmethod
    def check_product_name(cls, v):
        if not v or not v.strip(): raise ValueError('Tên sản phẩm không được để trống')
        return v.strip()

    @field_validator('base_price', 'packaging_cost', 'marketing_cost')
    @classmethod
    def check_positive_prices(cls, v, info):
        return validate_positive_number(v, info.field_name)

class Product(ProductBase):
    id: int
    created_by: Optional[int] = None
    updated_by: Optional[int] = None
    demand_score: float | None = 0
    feasibility_score: float | None = 0

class ProductComputed(Product):
    material_cost: float
    labor_cost: float
    packaging_cost: float
    marketing_cost: float
    platform_fee_amount: float
    profit_per_unit: float
    profit_margin: float
    profit_per_hour: float
    feasibility_score: float
    feasibility_breakdown: Dict[str, float]
    max_units_from_stock: Optional[int]

class MaterialCreate(BaseModel):
    code: str = Field(..., min_length=1, max_length=50)
    name: str = Field(..., min_length=1, max_length=200)
    type: str = Field(..., min_length=1, max_length=50)
    unit: str = Field(..., min_length=1, max_length=20)
    unit_price: float = Field(..., ge=0)
    stock_quantity: float = Field(..., ge=0)
    low_threshold: float = Field(1.0, ge=0)
    note: Optional[str] = Field(None, max_length=500)

class Material(MaterialCreate):
    id: int
    created_by: Optional[int] = None
    updated_by: Optional[int] = None

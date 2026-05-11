"""Promo code model."""
from typing import Optional, List
from datetime import datetime, date
from pydantic import BaseModel, Field
from sqlmodel import SQLModel, Field as SQLField


class PromoCode(BaseModel):
    """Promo code model."""
    id: int
    code: str
    description: Optional[str] = None
    discount_type: str = "percent"  # percent, fixed
    discount_value: float = 0
    min_order_value: float = 0
    max_discount: Optional[float] = None
    applicable_product_ids: List[int] = []
    valid_from: Optional[date] = None
    valid_to: Optional[date] = None
    usage_limit: Optional[int] = None
    usage_count: int = 0
    is_active: bool = True
    created_at: datetime = Field(default_factory=datetime.utcnow)


class PromoCodeTable(SQLModel, table=True):
    """Promo code database table."""
    __tablename__ = "promo_codes"
    
    id: Optional[int] = SQLField(default=None, primary_key=True)
    code: str = SQLField(unique=True, index=True)
    description: Optional[str] = None
    discount_type: str = "percent"
    discount_value: float = 0
    min_order_value: float = 0
    max_discount: Optional[float] = None
    applicable_product_ids_json: str = "[]"
    valid_from: Optional[date] = None
    valid_to: Optional[date] = None
    usage_limit: Optional[int] = None
    usage_count: int = 0
    is_active: bool = True
    created_at: datetime = SQLField(default_factory=datetime.utcnow)

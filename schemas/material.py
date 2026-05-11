"""Material schemas."""
from typing import Optional
from datetime import date
from pydantic import BaseModel, field_validator


class MaterialCreate(BaseModel):
    """Material create schema."""
    code: str
    name: str
    type: str = "fabric"
    unit: str = "m"
    unit_type: str = "continuous"  # "continuous" (gram/m) or "piece" (cái/cặp — rounded up in BOM)
    unit_price: Optional[float] = None
    stock_quantity: float = 0
    on_hand_qty: Optional[float] = None
    reserved_qty: float = 0
    available_qty: Optional[float] = None
    low_threshold: float = 1.0
    supplier_id: Optional[int] = None
    base_unit: Optional[str] = None
    note: Optional[str] = None
    batch_id: Optional[str] = None
    expiry_date: Optional[date] = None

    @field_validator('unit_price')
    @classmethod
    def price_non_negative(cls, v: Optional[float]) -> Optional[float]:
        if v is None:
            return v
        if v < 0:
            raise ValueError('Đơn giá không được âm')
        return v

    @field_validator('stock_quantity')
    @classmethod
    def stock_non_negative(cls, v: float) -> float:
        if v < 0:
            raise ValueError('Số lượng tồn kho không được âm')
        return v

    @field_validator('low_threshold')
    @classmethod
    def threshold_non_negative(cls, v: float) -> float:
        if v < 0:
            raise ValueError('Ngưỡng cảnh báo tồn kho không được âm')
        return v

    @field_validator('code', 'name')
    @classmethod
    def not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError('Trường này không được để trống')
        return v.strip()


class StockMovementCreate(BaseModel):
    """Stock movement create schema."""
    material_id: int
    quantity_change: float
    movement_type: str = "adjustment"
    reference_type: Optional[str] = None
    reference_id: Optional[int] = None
    batch_id: Optional[str] = None
    expiry_date: Optional[date] = None
    note: Optional[str] = None

    @field_validator('quantity_change')
    @classmethod
    def quantity_not_zero(cls, v: float) -> float:
        if v == 0:
            raise ValueError('Số lượng thay đổi không được bằng 0')
        return v

"""Production job schemas."""
from typing import Optional, List
from datetime import datetime
from pydantic import BaseModel, Field, field_validator, model_validator
from models.product import MaterialUsage


class JobMaterialSelection(MaterialUsage):
    bom_line_index: Optional[int] = Field(default=None, ge=0)
    bom_material_id: Optional[int] = None
    quantity: float = Field(gt=0, allow_inf_nan=False)
    wastage_percent: float = Field(default=0, ge=0, le=100, allow_inf_nan=False)
    product_wastage_percent: Optional[float] = Field(default=None, ge=0, le=100, allow_inf_nan=False)


class ProductionJobCreate(BaseModel):
    order_id: Optional[int] = None  # None = make-to-stock
    product_id: int
    quantity: int = 1
    assigned_to: Optional[int] = None
    notes: Optional[str] = None
    due_at: Optional[datetime] = None
    materials: Optional[List[JobMaterialSelection]] = None

    @field_validator("quantity")
    @classmethod
    def quantity_positive(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("Số lượng phải lớn hơn 0")
        return v


class ProductionJobStatusUpdate(BaseModel):
    status: str
    notes: Optional[str] = None


class ProductionJobUpdate(BaseModel):
    quantity: Optional[int] = Field(default=None, gt=0)
    assigned_to: Optional[int] = None
    notes: Optional[str] = None
    due_at: Optional[datetime] = None
    materials: Optional[List[JobMaterialSelection]] = None


class ConsumptionLineUpdate(BaseModel):
    material_index: int = Field(ge=0)
    material_id: int
    replacement_material_id: Optional[int] = Field(default=None, gt=0)
    actual_quantity: float = Field(ge=0, allow_inf_nan=False)

    @field_validator('actual_quantity')
    @classmethod
    def supported_precision(cls, value):
        if abs(value - round(value, 4)) > 1e-8:
            raise ValueError('Lượng tiêu hao chỉ hỗ trợ tối đa 4 chữ số thập phân')
        return round(value, 4)


class ConsumptionAdjustment(BaseModel):
    revision: str = Field(min_length=64, max_length=64)
    reason: str = Field(min_length=1, max_length=1000)
    materials: List[ConsumptionLineUpdate] = Field(min_length=1)

    @field_validator('reason')
    @classmethod
    def nonblank_reason(cls, value):
        if not value.strip():
            raise ValueError('Nhập lý do điều chỉnh')
        return value.strip()

    @model_validator(mode='after')
    def unique_rows(self):
        if len({row.material_index for row in self.materials}) != len(self.materials):
            raise ValueError('Mỗi dòng nguyên liệu chỉ được gửi một lần')
        return self

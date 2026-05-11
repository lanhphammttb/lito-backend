"""Production job models for handmade workflow."""
from typing import Optional, List
from datetime import datetime
from pydantic import BaseModel, Field
from sqlmodel import SQLModel, Field as SQLField


class ProductionMaterial(BaseModel):
    """Material plan or actual usage for a production job."""
    material_id: int
    planned_quantity: float = 0
    reserved_quantity: float = 0
    actual_quantity: float = 0
    wastage_percent: float = 0


class ProductionJob(BaseModel):
    """Track progress of handmade production."""
    id: int
    order_id: Optional[int] = None  # None = make-to-stock (no order)
    product_id: int
    product_name: Optional[str] = None
    quantity: int = 1
    status: str = "planned"  # planned, reserved, in_progress, paused, completed, cancelled
    assigned_to: Optional[int] = None
    notes: Optional[str] = None
    planned_minutes: int = 0
    started_at: Optional[datetime] = None
    due_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    materials: List[ProductionMaterial] = []
    created_by: Optional[int] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: Optional[datetime] = None


class ProductionJobTable(SQLModel, table=True):
    """Persist production jobs in Postgres."""
    __tablename__ = "production_jobs"

    id: Optional[int] = SQLField(default=None, primary_key=True)
    order_id: Optional[int] = SQLField(default=None, index=True)
    product_id: int = SQLField(index=True)
    product_name: Optional[str] = None
    quantity: int = 1
    status: str = "planned"
    assigned_to: Optional[int] = SQLField(default=None, index=True)
    notes: Optional[str] = None
    planned_minutes: int = 0
    started_at: Optional[datetime] = None
    due_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    materials_json: str = "[]"
    created_by: Optional[int] = None
    created_at: datetime = SQLField(default_factory=datetime.utcnow)
    updated_at: Optional[datetime] = None

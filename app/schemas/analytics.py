from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import date, datetime

class SeasonCreate(BaseModel):
    name: str
    from_date: date
    to_date: date

class Season(SeasonCreate):
    id: int
    created_by: Optional[int] = None
    updated_by: Optional[int] = None

class IdeaCreate(BaseModel):
    name: str
    description: Optional[str] = None
    estimated_time: int
    estimated_price: float
    status: str = "Chưa thử"

class Idea(IdeaCreate):
    id: int
    created_by: Optional[int] = None
    updated_by: Optional[int] = None

class ContentPlanCreate(BaseModel):
    date: date
    platform: str
    title: str
    related_product_id: Optional[int] = None
    status: str = "Ý tưởng"
    estimate_views: Optional[int] = 0
    estimate_inquiries: Optional[int] = 0
    estimate_saves: Optional[int] = 0

class ContentPlan(ContentPlanCreate):
    id: int
    actual_views: Optional[int] = 0
    actual_inquiries: Optional[int] = 0
    actual_saves: Optional[int] = 0
    actual_orders: Optional[int] = 0
    actual_revenue: Optional[float] = 0.0
    created_by: Optional[int] = None
    updated_by: Optional[int] = None

class DemandSignalCreate(BaseModel):
    product_id: int
    views: int = 0
    inquiries: int = 0
    saves: int = 0
    platform: Optional[str] = None
    week_of: date

class DemandSignal(DemandSignalCreate):
    id: int
    created_by: Optional[int] = None

class IssueCreate(BaseModel):
    product_id: int
    type: str
    description: str
    evidence: Optional[str] = None
    hypothesis: Optional[str] = None
    next_action: Optional[str] = None
    priority: int = 2
    status: str = "open"
    impact_revenue: Optional[float] = 0.0
    is_template: bool = False
    assigned_to: Optional[int] = None
    resolved_at: Optional[datetime] = None
    resolution_hours: Optional[float] = None

class Issue(IssueCreate):
    id: int
    created_by: Optional[int] = None
    created_at: datetime
    comments_count: int = 0

class TaskCreate(BaseModel):
    title: str
    description: Optional[str] = None
    assignee_id: Optional[int] = None
    due_date: Optional[date] = None
    priority: int = 2
    status: str = "open"
    tags: List[str] = []

class Task(TaskCreate):
    id: int
    created_by: Optional[int] = None
    created_at: datetime
    completed_at: Optional[datetime] = None

class MarketplaceSyncRequest(BaseModel):
    marketplace: str = Field(..., pattern="^(shopee|lazada)$")
    sync_type: str = Field(..., pattern="^(orders|products|inventory)$")
    date_from: Optional[date] = None
    date_to: Optional[date] = None

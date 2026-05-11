"""Content and demand signal models."""
from typing import Optional
from datetime import datetime, date
from pydantic import BaseModel, Field
from sqlmodel import SQLModel, Field as SQLField


class ContentPlan(BaseModel):
    """Content plan model."""
    id: int
    title: str
    platform: Optional[str] = None  # facebook, instagram, tiktok, shopee
    channel: Optional[str] = None
    format: Optional[str] = None  # post, reel, story, video
    status: str = "draft"  # draft, scheduled, published, archived
    scheduled_date: Optional[date] = None
    published_date: Optional[date] = None
    related_product_id: Optional[int] = None
    caption: Optional[str] = None
    hashtags: Optional[str] = None
    estimate_views: Optional[int] = None
    estimate_inquiries: Optional[int] = None
    estimate_saves: Optional[int] = None
    actual_views: Optional[int] = None
    actual_inquiries: Optional[int] = None
    actual_saves: Optional[int] = None
    actual_orders: Optional[int] = None
    actual_revenue: Optional[float] = None
    created_by: Optional[int] = None
    updated_by: Optional[int] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class ContentPlanTable(SQLModel, table=True):
    """Content plan database table."""
    __tablename__ = "content_plans"
    
    id: Optional[int] = SQLField(default=None, primary_key=True)
    title: str
    platform: Optional[str] = None
    channel: Optional[str] = None
    format: Optional[str] = None
    status: str = "draft"
    scheduled_date: Optional[date] = None
    published_date: Optional[date] = None
    related_product_id: Optional[int] = None
    caption: Optional[str] = None
    hashtags: Optional[str] = None
    estimate_views: Optional[int] = None
    estimate_inquiries: Optional[int] = None
    estimate_saves: Optional[int] = None
    actual_views: Optional[int] = None
    actual_inquiries: Optional[int] = None
    actual_saves: Optional[int] = None
    actual_orders: Optional[int] = None
    actual_revenue: Optional[float] = None
    created_by: Optional[int] = None
    updated_by: Optional[int] = None
    created_at: datetime = SQLField(default_factory=datetime.utcnow)


class DemandSignal(BaseModel):
    """Demand signal for tracking product interest."""
    id: int
    product_id: int
    views: int = 0
    inquiries: int = 0
    saves: int = 0
    week_of: date
    created_by: Optional[int] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class DemandSignalTable(SQLModel, table=True):
    """Demand signal database table."""
    __tablename__ = "demand_signals"
    
    id: Optional[int] = SQLField(default=None, primary_key=True)
    product_id: int = SQLField(index=True)
    views: int = 0
    inquiries: int = 0
    saves: int = 0
    week_of: date
    created_by: Optional[int] = None
    created_at: datetime = SQLField(default_factory=datetime.utcnow)

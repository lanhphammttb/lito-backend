"""Content schemas."""
from typing import Optional
from datetime import date
from pydantic import BaseModel


class ContentPlanCreate(BaseModel):
    """Content plan create schema."""
    title: str
    platform: Optional[str] = None
    channel: Optional[str] = None
    format: Optional[str] = None
    status: str = "draft"
    scheduled_date: Optional[date] = None
    related_product_id: Optional[int] = None
    caption: Optional[str] = None
    hashtags: Optional[str] = None
    estimate_views: Optional[int] = None
    estimate_inquiries: Optional[int] = None
    estimate_saves: Optional[int] = None


class ContentPerformanceUpdate(BaseModel):
    """Content performance update schema."""
    actual_views: Optional[int] = None
    actual_inquiries: Optional[int] = None
    actual_saves: Optional[int] = None
    actual_orders: Optional[int] = None
    actual_revenue: Optional[float] = None


class DemandSignalCreate(BaseModel):
    """Demand signal create schema."""
    product_id: int
    views: int = 0
    inquiries: int = 0
    saves: int = 0
    week_of: date

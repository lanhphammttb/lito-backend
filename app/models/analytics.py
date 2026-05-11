from sqlmodel import SQLModel, Field
from typing import Optional
from datetime import date, datetime

class IssueTable(SQLModel, table=True):
    __tablename__ = "issuetable"
    id: Optional[int] = Field(default=None, primary_key=True)
    product_id: int = Field(index=True)
    type: str = Field(index=True)
    description: str
    evidence: Optional[str] = None
    hypothesis: Optional[str] = None
    next_action: Optional[str] = None
    priority: int = 2
    status: str = Field(default="open", index=True)
    impact_revenue: Optional[float] = 0.0
    is_template: bool = False
    assigned_to: Optional[int] = None
    created_by: Optional[int] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    resolved_at: Optional[datetime] = None
    resolution_hours: Optional[float] = None

class TaskTable(SQLModel, table=True):
    __tablename__ = "tasktable"
    id: Optional[int] = Field(default=None, primary_key=True)
    title: str
    description: Optional[str] = None
    assignee_id: Optional[int] = None
    due_date: Optional[date] = None
    priority: int = 2
    status: str = Field(default="open")
    tags_str: str = "[]"
    created_by: Optional[int] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None

class DemandSignalTable(SQLModel, table=True):
    __tablename__ = "demandsignaltable"
    id: Optional[int] = Field(default=None, primary_key=True)
    product_id: int = Field(index=True)
    views: int = 0
    inquiries: int = 0
    saves: int = 0
    platform: Optional[str] = None
    week_of: date = Field(index=True)
    created_by: Optional[int] = None

class MarketplaceSyncLogTable(SQLModel, table=True):
    __tablename__ = "marketplace_sync_logs"
    id: Optional[int] = Field(default=None, primary_key=True)
    marketplace: str = Field(index=True)
    sync_type: str
    status: str
    orders_synced: int = 0
    orders_failed: int = 0
    error_message: Optional[str] = None
    synced_at: datetime = Field(default_factory=datetime.utcnow, index=True)

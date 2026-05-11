"""Activity and Audit log models."""
from typing import Optional, Dict, Any
from datetime import datetime
from pydantic import BaseModel, Field
from sqlmodel import SQLModel, Field as SQLField
from utils.datetime import utcnow


class ActivityLog(BaseModel):
    """Activity log model."""
    id: int
    user_id: int
    entity_type: str
    entity_id: Optional[int] = None
    action: str
    changes: Optional[Dict[str, Any]] = None
    created_at: datetime = Field(default_factory=utcnow)


class ActivityLogTable(SQLModel, table=True):
    """Activity log database table."""
    __tablename__ = "activity_logs"
    
    id: Optional[int] = SQLField(default=None, primary_key=True)
    user_id: int = SQLField(index=True)
    entity_type: str
    entity_id: Optional[int] = None
    action: str
    changes: Optional[str] = None  # JSON string
    created_at: datetime = SQLField(default_factory=utcnow)


class AuditLogTable(SQLModel, table=True):
    """Audit log database table for compliance tracking."""
    __tablename__ = "audit_logs"
    
    id: Optional[int] = SQLField(default=None, primary_key=True)
    user_id: int
    user_name: Optional[str] = None
    action: str
    table_name: Optional[str] = None
    record_id: Optional[int] = None
    before_data: Optional[str] = None  # JSON string
    after_data: Optional[str] = None  # JSON string
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    timestamp: datetime = SQLField(default_factory=utcnow)

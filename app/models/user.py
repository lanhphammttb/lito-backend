from sqlmodel import SQLModel, Field
from typing import Optional
from datetime import datetime

class UserTable(SQLModel, table=True):
    __tablename__ = "usertable"
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    email: str = Field(index=True, unique=True)
    password_hash: str
    role: str = Field(default="ADMIN")
    is_owner: bool = Field(default=False)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    last_login_at: Optional[datetime] = None

class ActivityLogTable(SQLModel, table=True):
    __tablename__ = "activitylogtable"
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int
    entity_type: str
    entity_id: Optional[int] = None
    action: str
    changes: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)

class PushSubscriptionTable(SQLModel, table=True):
    __tablename__ = "push_subscriptions"
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(index=True)
    endpoint: str = Field(unique=True)
    p256dh: str
    auth: str
    created_at: datetime = Field(default_factory=datetime.utcnow)

class AuditLogTable(SQLModel, table=True):
    __tablename__ = "auditlogtable"
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int
    user_name: Optional[str] = None
    user_email: Optional[str] = None
    action: str
    endpoint: str
    method: str
    ip_address: Optional[str] = None
    status_code: Optional[int] = None
    response_time_ms: Optional[float] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)

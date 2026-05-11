"""Notification and marketplace sync models."""
from typing import Optional
from datetime import datetime
from sqlmodel import SQLModel, Field as SQLField


class PushSubscriptionTable(SQLModel, table=True):
    """Push notification subscription database table."""
    __tablename__ = "push_subscriptions"
    
    id: Optional[int] = SQLField(default=None, primary_key=True)
    user_id: int = SQLField(index=True)
    endpoint: str
    p256dh: str
    auth: str
    created_at: datetime = SQLField(default_factory=datetime.utcnow)


class FcmTokenTable(SQLModel, table=True):
    """FCM device token for push notifications."""
    __tablename__ = "fcm_tokens"

    id: Optional[int] = SQLField(default=None, primary_key=True)
    user_id: int = SQLField(index=True)
    token: str = SQLField(unique=True)
    device_info: Optional[str] = None
    created_at: datetime = SQLField(default_factory=datetime.utcnow)
    updated_at: datetime = SQLField(default_factory=datetime.utcnow)


class MarketplaceSyncLogTable(SQLModel, table=True):
    """Marketplace sync log database table."""
    __tablename__ = "marketplace_sync_logs"
    
    id: Optional[int] = SQLField(default=None, primary_key=True)
    marketplace: str  # shopee, lazada
    sync_type: str = "orders"  # orders, products
    status: str = "pending"  # pending, success, failed
    orders_synced: int = 0
    orders_failed: int = 0
    error_message: Optional[str] = None
    synced_at: datetime = SQLField(default_factory=datetime.utcnow)

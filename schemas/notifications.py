"""Notification schemas."""
from typing import Optional, List, Dict, Any
from pydantic import BaseModel


class PushSubscription(BaseModel):
    """Push notification subscription."""
    endpoint: str
    keys: Dict[str, str]


class NotificationPayload(BaseModel):
    """Notification send payload."""
    title: str
    body: str
    icon: Optional[str] = None
    data: Optional[Dict[str, Any]] = None
    user_ids: Optional[List[int]] = None  # If None, broadcast to all

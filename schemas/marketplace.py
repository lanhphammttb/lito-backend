"""Marketplace sync schemas."""
from typing import Optional, List, Dict, Any
from datetime import date
from pydantic import BaseModel


class MarketplaceSyncRequest(BaseModel):
    """Marketplace sync request."""
    marketplace: str  # shopee, lazada
    sync_type: str = "orders"  # orders, products
    date_from: Optional[date] = None
    date_to: Optional[date] = None


class MarketplaceOrder(BaseModel):
    """Marketplace order from external platform."""
    order_sn: str
    marketplace: str
    order_status: str
    create_time: int  # Unix timestamp
    shipping_carrier: Optional[str] = None
    tracking_number: Optional[str] = None
    items: List[Dict[str, Any]] = []

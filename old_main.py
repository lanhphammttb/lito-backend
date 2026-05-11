
from fastapi import FastAPI, Depends
app = FastAPI(title="Handmade Business OS", version="0.1.0")

# --- Models needed for API ---
from pydantic import BaseModel
from typing import Optional
class User(BaseModel):
    id: int
    name: str
    email: str
    password_hash: str
    role: str
    is_owner: bool
    created_at: Optional[str] = None
    last_login_at: Optional[str] = None

# --- get_current_user dependency ---
from sqlmodel import Session, select
from fastapi import HTTPException
from jwt import decode, PyJWTError
from sqlmodel import select
from fastapi.security import OAuth2PasswordBearer
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/token")
def get_current_user(token: str = Depends(oauth2_scheme)) -> User:
    if not token:
        raise HTTPException(status_code=401, detail="Missing token")
    try:
        payload = decode(token, JWT_SECRET, algorithms=[JWT_ALGO])
        user_id = payload.get("sub")
        if not user_id:
            raise HTTPException(status_code=401, detail="Invalid token")
        with Session(engine) as session:
            stmt = select(UserTable).where(UserTable.id == int(user_id))
            row = session.exec(stmt).first()
            if row:
                return User(
                    id=row.id,
                    name=row.name,
                    email=row.email,
                    password_hash=row.password_hash,
                    role=row.role,
                    is_owner=row.is_owner,
                    created_at=row.created_at,
                    last_login_at=row.last_login_at,
                )
        raise HTTPException(status_code=401, detail="User not found")
    except PyJWTError:
        raise HTTPException(status_code=401, detail="Invalid token")

# --- Audit Log Statistics API ---
@app.get("/audit-logs/stats")
async def get_audit_log_stats(current_user: User = Depends(get_current_user)):
    from collections import Counter
    with Session(engine) as session:
        logs = session.exec(select(AuditLogTable)).all()
        total_actions = len(logs)
        by_action = Counter(log.action for log in logs)
        period_days = 30  # or calculate from logs if needed
        return {
            "total_actions": total_actions,
            "by_action": dict(by_action),
            "period_days": period_days
        }

# --- Audit Log API --------------------------------------------------------
from fastapi.responses import JSONResponse
from fastapi import Depends

# --- Models needed for API ---
from pydantic import BaseModel
from typing import Optional
class User(BaseModel):
    id: int
    name: str
    email: str
    password_hash: str
    role: str
    is_owner: bool
    created_at: Optional[str] = None
    last_login_at: Optional[str] = None

from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from fastapi.middleware.cors import CORSMiddleware

# CORS setup for frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow all origins for development
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)

## ...existing code...
import copy
import os
import json
import re
import secrets
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional, Generic, TypeVar
from functools import lru_cache
from contextlib import asynccontextmanager

import jwt
import csv
import io
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Header, Request, Response, status, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordBearer
from fastapi.security.utils import get_authorization_scheme_param
from passlib.context import CryptContext
from pydantic import BaseModel, Field, field_validator, EmailStr
from email.message import EmailMessage
import smtplib
from pymongo import MongoClient
from sqlmodel import Field as SQLField, Session, SQLModel, create_engine, select, delete
from sqlalchemy.exc import OperationalError
from sqlalchemy import inspect as sa_inspect, text as sa_text
from sqlalchemy.pool import StaticPool
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

# --- Input Validators -------------------------------------------------------
def validate_phone_number(phone: str) -> str:
    """Validate Vietnamese phone number format"""
    if not phone:
        return phone
    # Remove spaces and dashes
    cleaned = re.sub(r'[\s\-]', '', phone)
    # Accept Vietnamese phone formats: 0xxx, +84xxx, 84xxx
    pattern = r'^(\+84|84|0)[1-9][0-9]{8}$'
    if not re.match(pattern, cleaned):
        raise ValueError('Số điện thoại không hợp lệ. Định dạng: 0xxxxxxxxx hoặc +84xxxxxxxxx')
    return cleaned


def validate_positive_number(value: float, field_name: str) -> float:
    """Ensure number is positive"""
    if value < 0:
        raise ValueError(f'{field_name} phải >= 0')
    return value


# --- Allowed Enum Values ----------------------------------------------------
ORDER_STATUS_ALLOWED = {"pending", "confirmed", "processing", "completed", "shipped", "delivered", "cancelled"}
PAYMENT_STATUS_ALLOWED = {"unpaid", "partial", "paid", "refunded"}
PRODUCT_ROLE_ALLOWED = {"core", "experiment", "seasonal"}
PRODUCT_LIFECYCLE_ALLOWED = {"idea", "prototype", "experiment", "live", "failed"}


# --- Pagination Models ------------------------------------------------------
T = TypeVar('T')

class PaginatedResponse(BaseModel, Generic[T]):
    items: List[T]
    total: int
    page: int
    page_size: int
    total_pages: int


# --- Models -----------------------------------------------------------------
class Settings(BaseModel):
    hourly_rate: float = Field(80000, description="Wage per hour used to price labor")
    default_profit_margin: float = Field(0.2, description="Fallback margin suggestion")
    low_stock_threshold: float = Field(1.0, description="Low stock threshold in base units")
    profit_share_mode: str | None = "mixed"
    share_user_a: float | None = 0.5
    share_user_b: float | None = 0.5
    business_name: Optional[str] = None
    business_address: Optional[str] = None
    business_logo: Optional[str] = None
    capacity_hours_per_month: Optional[float] = None
    tax_rate: Optional[float] = 0.0
    notification_emails: List[str] = Field(default_factory=list)
    notify_low_stock: bool = True
    notify_forecast_low: bool = True
    backup_email: Optional[str] = None
    smtp_host: Optional[str] = None
    smtp_port: Optional[int] = 587
    smtp_user: Optional[str] = None
    smtp_password: Optional[str] = None
    smtp_use_tls: bool = True
    # Marketplace API credentials
    shopee_partner_id: Optional[int] = None
    shopee_partner_key: Optional[str] = None
    shopee_shop_id: Optional[int] = None
    lazada_app_key: Optional[str] = None
    lazada_app_secret: Optional[str] = None
    lazada_access_token: Optional[str] = None


class Material(BaseModel):
    id: int
    code: str
    name: str
    type: str
    unit: str
    unit_price: float
    stock_quantity: float
    low_threshold: float = 1.0
    note: Optional[str] = None
    created_by: Optional[int] = None
    updated_by: Optional[int] = None


class MaterialCreate(BaseModel):
    code: str = Field(..., min_length=1, max_length=50, description="Mã nguyên liệu")
    name: str = Field(..., min_length=1, max_length=200, description="Tên nguyên liệu")
    type: str = Field(..., min_length=1, max_length=50)
    unit: str = Field(..., min_length=1, max_length=20)
    unit_price: float = Field(..., ge=0, description="Đơn giá")
    stock_quantity: float = Field(..., ge=0, description="Số lượng tồn")
    low_threshold: float = Field(1.0, ge=0, description="Ngưỡng cảnh báo thấp")
    note: Optional[str] = Field(None, max_length=500)

    @field_validator('code', 'name')
    @classmethod
    def check_not_empty(cls, v, info):
        if not v or not v.strip():
            raise ValueError(f'{info.field_name} không được để trống')
        return v.strip()

    @field_validator('unit_price', 'stock_quantity', 'low_threshold')
    @classmethod
    def check_positive_values(cls, v, info):
        return validate_positive_number(v, info.field_name)


class MaterialUsage(BaseModel):
    material_id: int
    quantity: float


class ProductBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=200, description="Tên sản phẩm")
    difficulty: int = Field(ge=1, le=5, description="Độ khó 1-5")
    time_minutes: int = Field(..., gt=0, le=10080, description="Thời gian làm (phút, tối đa 7 ngày)")
    materials: List[MaterialUsage] = Field(default_factory=list)
    base_price: float = Field(..., ge=0, description="Giá cơ bản")
    priority: int = Field(1, ge=1, le=5, description="Ưu tiên đẩy theo mùa")
    notes: Optional[str] = Field(None, max_length=2000)
    tags: List[str] = Field(default_factory=list, max_length=20)
    seasons: List[int] = Field(default_factory=list)
    categories: List[int] = Field(default_factory=list)
    role: str = Field("core", pattern="^(core|experiment|seasonal)$", description="core|experiment|seasonal")
    lifecycle_status: str = Field("idea", pattern="^(idea|prototype|experiment|live|failed)$", description="idea|prototype|experiment|live|failed")
    packaging_cost: float = Field(0.0, ge=0)
    marketing_cost: float = Field(0.0, ge=0)
    platform_fee_percent: float = Field(0.0, ge=0, le=100)

    @field_validator('name')
    @classmethod
    def check_product_name(cls, v):
        if not v or not v.strip():
            raise ValueError('Tên sản phẩm không được để trống')
        return v.strip()

    @field_validator('base_price', 'packaging_cost', 'marketing_cost')
    @classmethod
    def check_positive_prices(cls, v, info):
        return validate_positive_number(v, info.field_name)

    @field_validator('role')
    @classmethod
    def check_role(cls, v):
        if v not in PRODUCT_ROLE_ALLOWED:
            raise ValueError(f'Role phải là một trong: {", ".join(PRODUCT_ROLE_ALLOWED)}')
        return v

    @field_validator('lifecycle_status')
    @classmethod
    def check_lifecycle(cls, v):
        if v not in PRODUCT_LIFECYCLE_ALLOWED:
            raise ValueError(f'Lifecycle status phải là một trong: {", ".join(PRODUCT_LIFECYCLE_ALLOWED)}')
        return v


class Product(ProductBase):
    id: int
    created_by: Optional[int] = None
    updated_by: Optional[int] = None
    demand_score: float | None = 0
    feasibility_score: float | None = 0


class ProductComputed(Product):
    material_cost: float
    labor_cost: float
    packaging_cost: float
    marketing_cost: float
    platform_fee_amount: float
    profit_per_unit: float
    profit_margin: float
    profit_per_hour: float
    feasibility_score: float
    feasibility_breakdown: Dict[str, float]
    max_units_from_stock: Optional[int]


class OrderLine(BaseModel):
    product_id: int = Field(..., gt=0, description="ID sản phẩm")
    quantity: int = Field(..., gt=0, le=10000, description="Số lượng đặt (1-10000)")
    unit_price: float = Field(..., ge=0, description="Đơn giá")


class ShippingUpdate(BaseModel):
    status: Optional[str] = Field(None, max_length=50)
    note: Optional[str] = Field(None, max_length=500)
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class OrderCreate(BaseModel):
    date: date
    channel: str = Field(..., min_length=1, max_length=50)
    order_lines: List[OrderLine] = Field(..., min_length=1, description="Ít nhất 1 sản phẩm")
    customer_id: Optional[int] = None
    shipping_fee: float = 0.0
    discount: float = 0.0
    promo_code: Optional[str] = None
    note: Optional[str] = None
    maker_user_id: Optional[int] = None
    status: str = "pending"  # pending, confirmed, processing, completed, shipped, delivered, cancelled
    payment_status: str = "unpaid"  # unpaid, partial, paid, refunded
    shipping_carrier: Optional[str] = None  # GHN, GHTK, Viettel Post
    tracking_number: Optional[str] = None
    estimated_delivery_date: Optional[date] = None
    shipping_updates: List[ShippingUpdate] = Field(default_factory=list)
    source_content_id: Optional[int] = None

    @field_validator('shipping_fee', 'discount')
    @classmethod
    def check_positive_fees(cls, v, info):
        return validate_positive_number(v, info.field_name)

    @field_validator('status')
    @classmethod
    def check_status(cls, v):
        if v not in ORDER_STATUS_ALLOWED:
            raise ValueError(f'Trạng thái đơn hàng phải là một trong: {", ".join(ORDER_STATUS_ALLOWED)}')
        return v

    @field_validator('payment_status')
    @classmethod
    def check_payment_status(cls, v):
        if v not in PAYMENT_STATUS_ALLOWED:
            raise ValueError(f'Trạng thái thanh toán phải là một trong: {", ".join(PAYMENT_STATUS_ALLOWED)}')
        return v


class Order(BaseModel):
    id: int
    date: date
    channel: str
    order_lines: List[OrderLine]
    customer_id: Optional[int] = None
    shipping_fee: float = 0.0
    discount: float = 0.0
    promo_code: Optional[str] = None
    note: Optional[str] = None
    maker_user_id: Optional[int] = None
    status: str = "pending"
    payment_status: str = "unpaid"
    shipping_carrier: Optional[str] = None
    tracking_number: Optional[str] = None
    estimated_delivery_date: Optional[date] = None
    shipping_updates: List[ShippingUpdate] = Field(default_factory=list)
    created_by: Optional[int] = None
    updated_by: Optional[int] = None
    source_content_id: Optional[int] = None


class OrderComputed(Order):
    revenue: float
    cost: float
    profit: float
    computed_discount: Optional[float] = 0.0


class Season(BaseModel):
    id: int
    name: str
    from_date: date
    to_date: date
    created_by: Optional[int] = None
    updated_by: Optional[int] = None


class SeasonCreate(BaseModel):
    name: str
    from_date: date
    to_date: date

    @field_validator('to_date')
    @classmethod
    def check_date_range(cls, v, info):
        from_date = info.data.get('from_date')
        if from_date and v < from_date:
            raise ValueError('to_date phải sau from_date')
        return v


class Idea(BaseModel):
    id: int
    name: str
    description: Optional[str] = None
    estimated_time: int
    estimated_price: float
    status: str = "Chưa thử"
    created_by: Optional[int] = None
    updated_by: Optional[int] = None


class IdeaCreate(BaseModel):
    name: str
    description: Optional[str] = None
    estimated_time: int
    estimated_price: float
    status: str = "Chưa thử"


class ContentPlan(BaseModel):
    id: int
    date: date
    platform: str
    title: str
    related_product_id: Optional[int] = None
    status: str = "Ý tưởng"
    estimate_views: Optional[int] = 0
    estimate_inquiries: Optional[int] = 0
    estimate_saves: Optional[int] = 0
    actual_views: Optional[int] = 0
    actual_inquiries: Optional[int] = 0
    actual_saves: Optional[int] = 0
    actual_orders: Optional[int] = 0
    actual_revenue: Optional[float] = 0.0
    created_by: Optional[int] = None
    updated_by: Optional[int] = None


class DemandSignal(BaseModel):
    id: int
    product_id: int
    views: int = 0
    inquiries: int = 0
    saves: int = 0
    platform: Optional[str] = None
    week_of: date
    created_by: Optional[int] = None


class DemandSignalCreate(BaseModel):
    product_id: int
    views: int = 0
    inquiries: int = 0
    saves: int = 0
    platform: Optional[str] = None
    week_of: date


class Issue(BaseModel):
    id: int
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
    created_by: Optional[int] = None
    created_at: datetime
    resolved_at: Optional[datetime] = None
    comments_count: int = 0
    resolution_hours: Optional[float] = None


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


class IssueComment(BaseModel):
    id: int
    issue_id: int
    user_id: int
    content: str
    created_at: datetime = Field(default_factory=datetime.utcnow)


class Task(BaseModel):
    id: int
    title: str
    description: Optional[str] = None
    assignee_id: Optional[int] = None
    due_date: Optional[date] = None
    priority: int = 2  # 1-low 2-med 3-high
    status: str = "open"  # open|in_progress|done|blocked
    tags: List[str] = []
    created_by: Optional[int] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None


class TaskCreate(BaseModel):
    title: str
    description: Optional[str] = None
    assignee_id: Optional[int] = None
    due_date: Optional[date] = None
    priority: int = 2
    status: str = "open"
    tags: List[str] = []


class Experiment(BaseModel):
    id: int
    name: str
    hypothesis: str
    metric: str  # views, inbox, orders, revenue
    target_value: float
    start_date: date
    end_date: Optional[date] = None
    status: str = "running"  # running|paused|completed|failed
    variant_a: str = "control"
    variant_b: str = "variant"
    notes: Optional[str] = None
    created_by: Optional[int] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class ExperimentCreate(BaseModel):
    name: str
    hypothesis: str
    metric: str
    target_value: float
    start_date: date
    end_date: Optional[date] = None
    status: str = "running"
    variant_a: str = "control"
    variant_b: str = "variant"
    notes: Optional[str] = None


class ExperimentUpdate(BaseModel):
    name: Optional[str] = None
    hypothesis: Optional[str] = None
    metric: Optional[str] = None
    target_value: Optional[float] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    status: Optional[str] = None
    variant_a: Optional[str] = None
    variant_b: Optional[str] = None
    notes: Optional[str] = None


class Goal(BaseModel):
    id: int
    title: str
    description: Optional[str] = None
    target_type: str = "revenue"  # revenue, orders, products, customers
    target_value: float
    current_value: float = 0.0
    start_date: date
    end_date: date
    status: str = "active"  # active, achieved, failed, cancelled
    created_by: Optional[int] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    achieved_at: Optional[datetime] = None


class GoalCreate(BaseModel):
    title: str
    description: Optional[str] = None
    target_type: str = "revenue"
    target_value: float
    current_value: float = 0.0
    start_date: date
    end_date: date
    status: str = "active"


class PriceChange(BaseModel):
    id: int
    product_id: int
    old_price: float
    new_price: float
    changed_by: Optional[int] = None
    changed_at: datetime


class LifecycleEvent(BaseModel):
    id: int
    product_id: int
    status: str
    note: Optional[str] = None
    changed_by: Optional[int] = None
    changed_at: datetime


class User(BaseModel):
    id: int
    name: str
    email: str
    password_hash: str
    role: str = "ADMIN"
    is_owner: bool = False
    created_at: datetime
    last_login_at: Optional[datetime] = None


class UserTable(SQLModel, table=True):
    id: Optional[int] = SQLField(default=None, primary_key=True)
    name: str
    email: str = SQLField(index=True, unique=True)
    password_hash: str
    role: str = SQLField(default="ADMIN")
    is_owner: bool = SQLField(default=False)
    created_at: datetime = SQLField(default_factory=datetime.utcnow)
    last_login_at: Optional[datetime] = None


class UserPublic(BaseModel):
    id: int
    name: str
    email: str
    role: str
    is_owner: bool
    created_at: datetime
    last_login_at: Optional[datetime] = None


class LoginRequest(BaseModel):
    email: EmailStr = Field(..., description="Email đăng nhập")
    password: str = Field(..., min_length=6, max_length=128, description="Mật khẩu (6-128 ký tự)")


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class ActivityLog(BaseModel):
    id: int
    user_id: int
    entity_type: str
    entity_id: Optional[int]
    action: str
    changes: Optional[dict] = None
    created_at: datetime


class ActivityLogTable(SQLModel, table=True):
    id: Optional[int] = SQLField(default=None, primary_key=True)
    user_id: int
    entity_type: str
    entity_id: Optional[int] = None
    action: str
    changes: Optional[str] = None
    created_at: datetime = SQLField(default_factory=datetime.utcnow)


# Push Notification Models
class PushSubscription(BaseModel):
    endpoint: str
    keys: dict  # { "p256dh": "...", "auth": "..." }


class PushSubscriptionTable(SQLModel, table=True):
    __tablename__ = "push_subscriptions"
    id: Optional[int] = SQLField(default=None, primary_key=True)
    user_id: int = SQLField(index=True)
    endpoint: str = SQLField(unique=True)
    p256dh: str
    auth: str
    created_at: datetime = SQLField(default_factory=datetime.utcnow)


class MarketplaceSyncLogTable(SQLModel, table=True):
    __tablename__ = "marketplace_sync_logs"
    id: Optional[int] = SQLField(default=None, primary_key=True)
    marketplace: str = SQLField(index=True)
    sync_type: str
    status: str
    orders_synced: int = 0
    orders_failed: int = 0
    error_message: Optional[str] = None
    synced_at: datetime = SQLField(default_factory=datetime.utcnow, index=True)


class NotificationPayload(BaseModel):
    title: str
    body: str
    icon: Optional[str] = "/icon-192.png"
    badge: Optional[str] = "/icon-72.png"
    data: Optional[dict] = None
    user_ids: Optional[List[int]] = None  # If None, broadcast to all


# --- Marketplace Integration Models -----------------------------------------
class MarketplaceOrder(BaseModel):
    """Order from marketplace (Shopee/Lazada)"""
    marketplace: str  # shopee, lazada
    marketplace_order_id: str
    order_sn: str  # Order serial number
    create_time: int  # Unix timestamp
    update_time: int  # Unix timestamp
    order_status: str  # UNPAID, READY_TO_SHIP, PROCESSED, SHIPPED, COMPLETED, CANCELLED
    customer_name: str
    customer_phone: Optional[str] = None
    shipping_address: Optional[str] = None
    total_amount: float
    items: List[dict]  # Product items with SKU, name, quantity, price
    shipping_carrier: Optional[str] = None
    tracking_number: Optional[str] = None


class MarketplaceSyncLog(BaseModel):
    """Log of marketplace sync operations"""
    id: int
    marketplace: str
    sync_type: str  # orders, products, inventory
    status: str  # success, failed, partial
    orders_synced: int = 0
    orders_failed: int = 0
    error_message: Optional[str] = None
    synced_at: datetime = Field(default_factory=datetime.utcnow)


class MarketplaceSyncRequest(BaseModel):
    """Request to sync from marketplace"""
    marketplace: str = Field(..., pattern="^(shopee|lazada)$")
    sync_type: str = Field(..., pattern="^(orders|products|inventory)$")
    date_from: Optional[date] = None
    date_to: Optional[date] = None


class ContentPlanCreate(BaseModel):
    date: date
    platform: str
    title: str
    related_product_id: Optional[int] = None
    status: str = "Ý tưởng"
    estimate_views: Optional[int] = 0
    estimate_inquiries: Optional[int] = 0
    estimate_saves: Optional[int] = 0


class Customer(BaseModel):
    id: int
    name: str
    phone: Optional[str] = None
    email: Optional[str] = None
    address: Optional[str] = None
    source: Optional[str] = None  # TikTok, Shopee, Facebook, etc.
    tags: List[str] = Field(default_factory=list)  # VIP, repeater, new, etc.
    total_orders: int = 0
    total_spent: float = 0
    last_order_date: Optional[date] = None
    first_order_date: Optional[date] = None
    notes: Optional[str] = None
    created_by: Optional[int] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class CustomerCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200, description="Tên khách hàng")
    phone: Optional[str] = Field(None, max_length=20)
    email: Optional[EmailStr] = None
    address: Optional[str] = Field(None, max_length=500)
    source: Optional[str] = Field(None, max_length=50)
    tags: List[str] = Field(default_factory=list, max_length=20)
    notes: Optional[str] = Field(None, max_length=1000)

    @field_validator('phone')
    @classmethod
    def check_phone(cls, v):
        if v:
            return validate_phone_number(v)
        return v

    @field_validator('name')
    @classmethod
    def check_name(cls, v):
        if not v or not v.strip():
            raise ValueError('Tên khách hàng không được để trống')
        return v.strip()


class StockMovement(BaseModel):
    id: int
    material_id: int
    quantity_change: float  # positive = in, negative = out
    movement_type: str  # purchase, production, adjustment, damaged
    reference_type: Optional[str] = None  # order, purchase_order
    reference_id: Optional[int] = None
    batch_id: Optional[str] = None
    expiry_date: Optional[date] = None
    user_id: Optional[int] = None
    note: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class StockMovementCreate(BaseModel):
    material_id: int
    quantity_change: float
    movement_type: str
    reference_type: Optional[str] = None
    reference_id: Optional[int] = None
    batch_id: Optional[str] = None
    expiry_date: Optional[date] = None
    note: Optional[str] = None


class ProductVariant(BaseModel):
    id: int
    product_id: int
    name: str  # "Size S", "Màu đỏ", etc.
    sku: Optional[str] = None
    price_modifier: float = 0  # +/- từ base_price
    stock_quantity: int = 0
    is_active: bool = True
    created_at: datetime = Field(default_factory=datetime.utcnow)


class ProductVariantCreate(BaseModel):
    product_id: int
    name: str
    sku: Optional[str] = None
    price_modifier: float = 0
    stock_quantity: int = 0


class ProductBundle(BaseModel):
    id: int
    parent_product_id: int
    child_product_id: int
    quantity: int = 1
    created_at: datetime = Field(default_factory=datetime.utcnow)


class ProductBundleCreate(BaseModel):
    parent_product_id: int
    child_product_id: int
    quantity: int = 1


class ProductImage(BaseModel):
    id: int
    product_id: int
    url: str
    is_primary: bool = False
    display_order: int = 0
    created_at: datetime = Field(default_factory=datetime.utcnow)


class ProductImageCreate(BaseModel):
    product_id: int
    url: str
    is_primary: bool = False
    display_order: int = 0


class ProductReview(BaseModel):
    id: int
    product_id: int
    customer_name: str
    rating: int = Field(ge=1, le=5)
    comment: Optional[str] = None
    order_id: Optional[int] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class ProductReviewCreate(BaseModel):
    product_id: int
    customer_name: str
    rating: int = Field(ge=1, le=5)
    comment: Optional[str] = None
    order_id: Optional[int] = None


class Category(BaseModel):
    id: int
    name: str
    parent_id: Optional[int] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class CategoryCreate(BaseModel):
    name: str
    parent_id: Optional[int] = None


class OrderReturn(BaseModel):
    id: int
    order_id: int
    reason: str
    amount: float
    status: str = "pending"  # pending|approved|rejected|processed
    refund_method: Optional[str] = None  # cash|bank_transfer|wallet
    refund_amount: Optional[float] = None
    note: Optional[str] = None
    created_by: Optional[int] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class OrderReturnCreate(BaseModel):
    order_id: int
    reason: str
    amount: float
    refund_method: Optional[str] = None
    refund_amount: Optional[float] = None
    note: Optional[str] = None


class ShippingUpdatePayload(BaseModel):
    status: Optional[str] = None
    note: Optional[str] = None
    tracking_number: Optional[str] = None
    shipping_carrier: Optional[str] = None
    estimated_delivery_date: Optional[date] = None


class PromoCode(BaseModel):
    id: int
    code: str
    type: str  # percent|fixed
    value: float
    is_active: bool = True
    expires_at: Optional[datetime] = None
    min_order_amount: float = 0.0
    max_discount: Optional[float] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class PromoCodeCreate(BaseModel):
    code: str
    type: str
    value: float
    is_active: bool = True
    expires_at: Optional[datetime] = None
    min_order_amount: float = 0.0
    max_discount: Optional[float] = None

class Supplier(BaseModel):
    id: int
    name: str
    contact_name: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    address: Optional[str] = None
    note: Optional[str] = None
    rating: Optional[int] = Field(default=None, ge=1, le=5)
    lead_time_days: Optional[int] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class SupplierCreate(BaseModel):
    name: str
    contact_name: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    address: Optional[str] = None
    note: Optional[str] = None
    rating: Optional[int] = Field(default=None, ge=1, le=5)
    lead_time_days: Optional[int] = None


class PurchaseOrderLine(BaseModel):
    material_id: int
    quantity: float
    unit_price: float
    batch_id: Optional[str] = None
    expiry_date: Optional[date] = None


class PurchaseOrder(BaseModel):
    id: int
    supplier_id: int
    status: str = "draft"  # draft|ordered|received|cancelled
    expected_date: Optional[date] = None
    note: Optional[str] = None
    lines: List[PurchaseOrderLine]
    total_amount: float
    created_by: Optional[int] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    received_at: Optional[datetime] = None


class PurchaseOrderCreate(BaseModel):
    supplier_id: int
    status: str = "draft"
    expected_date: Optional[date] = None
    note: Optional[str] = None
    lines: List[PurchaseOrderLine]


class Payment(BaseModel):
    id: int
    order_id: int
    amount: float
    method: str  # cash, bank_transfer, momo, zalopay, cod
    status: str  # pending, paid, failed, refunded
    transaction_id: Optional[str] = None
    paid_date: Optional[datetime] = None
    notes: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class PaymentCreate(BaseModel):
    order_id: int = Field(..., gt=0, description="ID đơn hàng")
    amount: float = Field(..., gt=0, description="Số tiền thanh toán")
    method: str = Field(..., pattern="^(cash|bank_transfer|momo|zalopay|cod)$", description="Phương thức: cash|bank_transfer|momo|zalopay|cod")
    status: str = Field("pending", pattern="^(pending|paid|failed|refunded)$")
    transaction_id: Optional[str] = Field(None, max_length=100)
    notes: Optional[str] = Field(None, max_length=500)


# --- Strategic Planning Models ----------------------------------------------
class OKR(BaseModel):
    id: int
    title: str
    description: Optional[str] = None
    owner_id: Optional[int] = None
    quarter: str  # Q1-2024, Q2-2024
    status: str = "active"  # active, achieved, at_risk, failed
    key_results: List[dict]  # [{title, target, current, unit}]
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class OKRCreate(BaseModel):
    title: str
    description: Optional[str] = None
    owner_id: Optional[int] = None
    quarter: str
    key_results: List[dict]


class SWOTAnalysis(BaseModel):
    id: int
    category: str  # product, market, operations, financial
    type: str  # strength, weakness, opportunity, threat
    description: str
    impact: str  # high, medium, low
    action_items: List[str] = []
    created_by: int
    created_at: datetime = Field(default_factory=datetime.utcnow)


class SWOTCreate(BaseModel):
    category: str
    type: str
    description: str
    impact: str = "medium"
    action_items: List[str] = []


class MarketInsight(BaseModel):
    id: int
    type: str  # competitor, trend, customer_feedback, market_size
    title: str
    description: str
    source: Optional[str] = None
    priority: str = "medium"  # high, medium, low
    created_at: datetime = Field(default_factory=datetime.utcnow)


class MarketInsightCreate(BaseModel):
    type: str
    title: str
    description: str
    source: Optional[str] = None
    priority: str = "medium"


# --- SQLModel tables --------------------------------------------------------
class ProductTable(SQLModel, table=True):
    __tablename__ = "producttable"
    __table_args__ = {"sqlite_autoincrement": True}
    id: Optional[int] = SQLField(default=None, primary_key=True)
    name: str
    difficulty: int
    time_minutes: int
    materials_json: str
    base_price: float
    priority: int
    notes: Optional[str] = None
    tags_json: str = "[]"
    seasons_json: str = "[]"
    categories_json: str = "[]"
    role: str = "core"
    lifecycle_status: str = "idea"
    demand_score: float = 0
    feasibility_score: float = 0
    packaging_cost: float = 0
    marketing_cost: float = 0
    platform_fee_percent: float = 0
    created_by: Optional[int] = None
    updated_by: Optional[int] = None
    created_at: datetime = SQLField(default_factory=datetime.utcnow)
    updated_at: Optional[datetime] = None


class MaterialTable(SQLModel, table=True):
    __tablename__ = "materialtable"
    __table_args__ = {"sqlite_autoincrement": True}
    id: Optional[int] = SQLField(default=None, primary_key=True)
    code: str = SQLField(index=True)
    name: str
    type: str
    unit: str
    unit_price: float
    stock_quantity: float
    low_threshold: float = 1.0
    note: Optional[str] = None
    created_by: Optional[int] = None
    updated_by: Optional[int] = None


class OrderTable(SQLModel, table=True):
    __tablename__ = "ordertable"
    __table_args__ = {"sqlite_autoincrement": True}
    id: Optional[int] = SQLField(default=None, primary_key=True)
    date: date
    channel: str
    order_json: str  # full order model json to keep it simple
    status: str = "pending"
    payment_status: str = "unpaid"
    customer_id: Optional[int] = None
    source_content_id: Optional[int] = None
    shipping_carrier: Optional[str] = None
    tracking_number: Optional[str] = None
    estimated_delivery_date: Optional[date] = None
    created_by: Optional[int] = None
    updated_by: Optional[int] = None


class IssueTable(SQLModel, table=True):
    __tablename__ = "issuetable"
    __table_args__ = {"sqlite_autoincrement": True}
    id: Optional[int] = SQLField(default=None, primary_key=True)
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
    created_by: Optional[int] = None
    created_at: datetime = SQLField(default_factory=datetime.utcnow)
    resolved_at: Optional[datetime] = None
    resolution_hours: Optional[float] = None
    history_json: Optional[str] = None


class TaskTable(SQLModel, table=True):
    __tablename__ = "tasktable"
    __table_args__ = {"sqlite_autoincrement": True}
    id: Optional[int] = SQLField(default=None, primary_key=True)
    title: str
    description: Optional[str] = None
    assignee_id: Optional[int] = None
    due_date: Optional[date] = None
    priority: int = 2
    status: str = "open"
    tags_json: Optional[str] = None
    created_by: Optional[int] = None
    created_at: datetime = SQLField(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None


class DemandSignalTable(SQLModel, table=True):
    __tablename__ = "demandsignaltable"
    __table_args__ = {"sqlite_autoincrement": True}
    id: Optional[int] = SQLField(default=None, primary_key=True)
    product_id: int
    views: int = 0
    inquiries: int = 0
    saves: int = 0
    week_of: date
    created_by: Optional[int] = None


class PriceChangeTable(SQLModel, table=True):
    id: Optional[int] = SQLField(default=None, primary_key=True)
    product_id: int
    old_price: float
    new_price: float
    changed_by: Optional[int] = None
    changed_at: datetime = SQLField(default_factory=datetime.utcnow)


class LifecycleEventTable(SQLModel, table=True):
    id: Optional[int] = SQLField(default=None, primary_key=True)
    product_id: int
    status: str
    note: Optional[str] = None
    changed_by: Optional[int] = None
    changed_at: datetime = SQLField(default_factory=datetime.utcnow)


class CustomerTable(SQLModel, table=True):
    id: Optional[int] = SQLField(default=None, primary_key=True)
    name: str
    phone: Optional[str] = None
    email: Optional[str] = None
    address: Optional[str] = None
    source: Optional[str] = None
    tags_json: str = "[]"
    total_orders: int = 0
    total_spent: float = 0
    last_order_date: Optional[date] = None
    first_order_date: Optional[date] = None
    notes: Optional[str] = None
    created_by: Optional[int] = None
    created_at: datetime = SQLField(default_factory=datetime.utcnow)


class StockMovementTable(SQLModel, table=True):
    id: Optional[int] = SQLField(default=None, primary_key=True)
    material_id: int
    quantity_change: float
    movement_type: str
    reference_type: Optional[str] = None
    reference_id: Optional[int] = None
    batch_id: Optional[str] = None
    expiry_date: Optional[date] = None
    user_id: Optional[int] = None
    note: Optional[str] = None
    created_at: datetime = SQLField(default_factory=datetime.utcnow)


class ProductVariantTable(SQLModel, table=True):
    id: Optional[int] = SQLField(default=None, primary_key=True)
    product_id: int
    name: str
    sku: Optional[str] = None
    price_modifier: float = 0
    stock_quantity: int = 0
    is_active: bool = True
    created_at: datetime = SQLField(default_factory=datetime.utcnow)


class PaymentTable(SQLModel, table=True):
    id: Optional[int] = SQLField(default=None, primary_key=True)
    order_id: int
    amount: float
    method: str
    status: str
    transaction_id: Optional[str] = None
    paid_date: Optional[datetime] = None
    notes: Optional[str] = None
    created_at: datetime = SQLField(default_factory=datetime.utcnow)


class PurchaseOrderTable(SQLModel, table=True):
    __tablename__ = "purchaseordertable"
    __table_args__ = {"sqlite_autoincrement": True}
    id: Optional[int] = SQLField(default=None, primary_key=True)
    supplier_id: int
    status: str = "draft"
    expected_date: Optional[date] = None
    note: Optional[str] = None
    lines_json: str
    total_amount: float
    created_by: Optional[int] = None
    created_at: datetime = SQLField(default_factory=datetime.utcnow)
    received_at: Optional[datetime] = None


class OrderReturnTable(SQLModel, table=True):
    __tablename__ = "orderreturntable"
    __table_args__ = {"sqlite_autoincrement": True}
    id: Optional[int] = SQLField(default=None, primary_key=True)
    order_id: int
    reason: str
    amount: float
    status: str = "pending"
    refund_method: Optional[str] = None
    refund_amount: Optional[float] = None
    note: Optional[str] = None
    created_by: Optional[int] = None
    created_at: datetime = SQLField(default_factory=datetime.utcnow)


class SupplierTable(SQLModel, table=True):
    __tablename__ = "suppliertable"
    __table_args__ = {"sqlite_autoincrement": True}
    id: Optional[int] = SQLField(default=None, primary_key=True)
    name: str
    contact_name: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    address: Optional[str] = None
    note: Optional[str] = None
    rating: Optional[int] = None
    lead_time_days: Optional[int] = None
    created_at: datetime = SQLField(default_factory=datetime.utcnow)


# --- Lifespan handler -------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Initialize database connection
    initialize_database()
    yield
    # Shutdown: cleanup if needed
    pass

# --- App setup --------------------------------------------------------------
# Rate limiter setup
limiter = Limiter(
    key_func=get_remote_address,
    default_limits=["200/minute"],  # Global limit: 200 req/phút mỗi IP
)
app = FastAPI(title="Handmade Business OS", version="0.1.0", lifespan=lifespan)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Ensure all tables are created on startup ---
@app.on_event("startup")
def create_all_tables():
    if engine:
        SQLModel.metadata.create_all(engine)

# Load environment variables from .env if present
load_dotenv()
env_secret = os.getenv("JWT_SECRET", "").strip()
if not env_secret:
    raise RuntimeError("JWT_SECRET phải được cấu hình trong .env/môi trường. Không tự tạo tạm để tránh token yếu.")
if env_secret.lower() in {"devsecret", "changeme"} or len(env_secret) < 32:
    raise RuntimeError("JWT_SECRET quá yếu hoặc đang dùng placeholder (devsecret/changeme). Hãy đặt chuỗi >=32 ký tự.")
JWT_SECRET = env_secret
JWT_ALGO = "HS256"
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")
pwd_context = CryptContext(
    # Allow verifying legacy pbkdf2 hashes while hashing mới dùng bcrypt
    schemes=["bcrypt", "pbkdf2_sha256"],
    deprecated="auto",
)

ADMIN_DEFAULT_PASSWORD = os.getenv("ADMIN_DEFAULT_PASSWORD", "").strip()
OWNER_A_PASSWORD = os.getenv("OWNER_A_PASSWORD", "").strip()
OWNER_B_PASSWORD = os.getenv("OWNER_B_PASSWORD", "").strip()
generated_admin_password = None
if not ADMIN_DEFAULT_PASSWORD:
    generated_admin_password = secrets.token_urlsafe(16)
    ADMIN_DEFAULT_PASSWORD = generated_admin_password
    print(f"[WARN] ADMIN_DEFAULT_PASSWORD không được thiết lập, sinh tạm: {ADMIN_DEFAULT_PASSWORD}")
elif len(ADMIN_DEFAULT_PASSWORD) < 12:
    raise RuntimeError("ADMIN_DEFAULT_PASSWORD quá ngắn, cần tối thiểu 12 ký tự.")


def resolve_seed_password(env_value: str) -> str:
    if env_value:
        if len(env_value) < 12:
            raise RuntimeError("Mật khẩu seed tối thiểu 12 ký tự để tránh brute-force.")
        return env_value
    return ADMIN_DEFAULT_PASSWORD
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./db.sqlite")
engine = None
SQL_INITIALIZED = False

def initialize_database():
    """Initialize database connection with fallback to in-memory mode"""
    global engine, DATABASE_URL, SQL_INITIALIZED

    if SQL_INITIALIZED:
        return

    try:
        connect_args = {}
        pool_config = {}

        if DATABASE_URL.startswith("postgres"):
            print(f"[DB] Đang kết nối PostgreSQL: {DATABASE_URL.split('@')[1].split('/')[0] if '@' in DATABASE_URL else 'unknown'}")
            # Tối ưu connection pooling cho Supabase
            connect_args["connect_timeout"] = int(os.getenv("PG_CONNECT_TIMEOUT", "10"))
            connect_args["keepalives"] = 1
            connect_args["keepalives_idle"] = 30
            connect_args["keepalives_interval"] = 10
            connect_args["keepalives_count"] = 5

            # Pool configuration
            pool_config = {
                "pool_size": 10,  # Số connection giữ trong pool
                "max_overflow": 20,  # Số connection tạm thời thêm khi cần
                "pool_timeout": 30,  # Timeout khi đợi connection từ pool
                "pool_recycle": 3600,  # Recycle connection sau 1 giờ
                "pool_pre_ping": True,  # Test connection trước khi dùng
            }
        else:
            pool_config["pool_pre_ping"] = True

        engine = create_engine(
            DATABASE_URL,
            echo=False,
            connect_args=connect_args if connect_args else {},
            **pool_config
        )

        # Test connection
        with engine.connect() as conn:
            conn.execute(sa_text("SELECT 1"))

        # Ensure all models are defined before creating tables
        SQLModel.metadata.create_all(engine)
        SQL_INITIALIZED = True
        print(f"[DB] Kết nối thành công: {DATABASE_URL.split('://')[0]}")

    except (OperationalError, Exception) as e:
        print(f"[DB] Không thể kết nối PostgreSQL: {e}")
        print(f"[DB] Fallback sang chế độ in-memory")
        # Fallback to in-memory SQLite with same thread disabled for FastAPI
        DATABASE_URL = "sqlite:///:memory:"
        engine = create_engine(
            DATABASE_URL,
            echo=False,
            connect_args={"check_same_thread": False},
            poolclass=StaticPool  # Important for in-memory SQLite
        )
        SQLModel.metadata.create_all(engine)
        SQL_INITIALIZED = True
        print(f"[DB] In-memory SQLite khởi tạo thành công")


# --- Default seed data ------------------------------------------------------
DEFAULT_SETTINGS = Settings()

DEFAULT_USERS: List[User] = [
    User(
        id=1,
        name="Owner A",
        email="owner_a@example.com",
        password_hash=pwd_context.hash(resolve_seed_password(OWNER_A_PASSWORD)),
        role="ADMIN",
        is_owner=True,
        created_at=datetime.utcnow(),
    ),
    User(
        id=2,
        name="Owner B",
        email="owner_b@example.com",
        password_hash=pwd_context.hash(resolve_seed_password(OWNER_B_PASSWORD)),
        role="ADMIN",
        is_owner=True,
        created_at=datetime.utcnow(),
    ),
    User(
        id=3,
        name="Thợ Lan",
        email="maker_lan@example.com",
        password_hash=pwd_context.hash("maker123"),
        role="maker",
        is_owner=False,
        created_at=datetime.utcnow(),
    ),
    User(
        id=4,
        name="Thợ Hương",
        email="maker_huong@example.com",
        password_hash=pwd_context.hash("maker123"),
        role="maker",
        is_owner=False,
        created_at=datetime.utcnow(),
    ),
]

DEFAULT_MATERIALS: List[Material] = [
    Material(
        id=1,
        code="Susan5-06",
        name="Len Susan 5 - 06 đỏ gạch",
        type="len",
        unit="gram",
        unit_price=1_200,
        stock_quantity=350,
        low_threshold=1.0,
        note="Hay dùng cho bé ma Noel",
        created_by=1,
    ),
    Material(
        id=2,
        code="Susan5-02",
        name="Len Susan 5 - 02 trắng",
        type="len",
        unit="gram",
        unit_price=1_100,
        stock_quantity=280,
        low_threshold=1.0,
        created_by=1,
    ),
    Material(
        id=3,
        code="Eye-8mm",
        name="Mắt thú 8mm",
        type="phụ kiện",
        unit="cặp",
        unit_price=1500,
        stock_quantity=25,
        low_threshold=2,
        created_by=1,
    ),
    Material(
        id=4,
        code="Keyring",
        name="Móc khóa bạc",
        type="phụ kiện",
        unit="cái",
        unit_price=800,
        stock_quantity=40,
        low_threshold=5,
        created_by=1,
    ),
]

DEFAULT_PRODUCTS: List[Product] = [
    Product(
        id=1,
        name="Bé ma Noel",
        difficulty=2,
        time_minutes=90,
        materials=[
            MaterialUsage(material_id=1, quantity=60),
            MaterialUsage(material_id=2, quantity=30),
            MaterialUsage(material_id=3, quantity=1),
            MaterialUsage(material_id=4, quantity=1),
        ],
        base_price=159000,
        packaging_cost=8000,
        marketing_cost=5000,
        platform_fee_percent=5,
        priority=5,
        notes="Bán mạnh từ Halloween đến Noel",
        tags=["noel", "halloween"],
        seasons=[1, 2],
        categories=[1, 3],
        role="seasonal",
        lifecycle_status="live",
        created_by=1,
    ),
    Product(
        id=2,
        name="Chú ếch may mắn",
        difficulty=3,
        time_minutes=150,
        materials=[
            MaterialUsage(material_id=2, quantity=80),
            MaterialUsage(material_id=3, quantity=1),
            MaterialUsage(material_id=4, quantity=1),
        ],
        base_price=189000,
        packaging_cost=10000,
        marketing_cost=6000,
        platform_fee_percent=5,
        priority=3,
        notes="Quà tặng sinh nhật",
        tags=["quà sinh nhật"],
        seasons=[],
        categories=[2],
        role="core",
        lifecycle_status="live",
        created_by=1,
    ),
    Product(
        id=3,
        name="Cây thông mini",
        difficulty=2,
        time_minutes=110,
        materials=[
            MaterialUsage(material_id=1, quantity=90),
            MaterialUsage(material_id=4, quantity=1),
        ],
        base_price=149000,
        packaging_cost=7000,
        marketing_cost=4000,
        platform_fee_percent=5,
        priority=4,
        notes="Trang trí bàn làm việc dịp Noel",
        tags=["trang trí", "noel"],
        seasons=[2],
        categories=[1],
        role="seasonal",
        lifecycle_status="prototype",
        created_by=1,
    ),
]

DEFAULT_ORDERS: List[Order] = [
    Order(
        id=1,
        date=date.today().replace(day=5),
        channel="Shopee",
        order_lines=[
            OrderLine(product_id=1, quantity=2, unit_price=120000),
            OrderLine(product_id=3, quantity=1, unit_price=155000),
        ],
        shipping_fee=25000,
        discount=15000,
        maker_user_id=1,  # Owner A (admin cũng là thợ)
        created_by=1,
    ),
    Order(
        id=2,
        date=date.today().replace(day=12),
        channel="TikTok",
        order_lines=[OrderLine(product_id=2, quantity=1, unit_price=185000)],
        shipping_fee=20000,
        discount=0,
        maker_user_id=2,  # Owner B (admin cũng là thợ)
        created_by=2,
    ),
]

DEFAULT_SEASONS: List[Season] = [
    Season(id=1, name="Halloween", from_date=date(date.today().year, 10, 1), to_date=date(date.today().year, 10, 31)),
    Season(id=2, name="Noel", from_date=date(date.today().year, 11, 15), to_date=date(date.today().year, 12, 26)),
]

DEFAULT_CATEGORIES: List[Category] = [
    Category(id=1, name="Trang trí", parent_id=None),
    Category(id=2, name="Quà tặng", parent_id=None),
    Category(id=3, name="Seasonal Collections", parent_id=1),
]

DEFAULT_SUPPLIERS: List[Supplier] = [
    Supplier(id=1, name="Nhà cung cấp len A", contact_name="Chị Hoa", phone="0901234567", note="Chuyên len Susan", rating=5),
    Supplier(id=2, name="Bao bì B", contact_name="Anh Nam", phone="0909988776", note="Túi hộp, ribbon", rating=4),
]

DEFAULT_PURCHASE_ORDERS: List[PurchaseOrder] = [
    PurchaseOrder(
        id=1,
        supplier_id=1,
        status="received",
        expected_date=date.today(),
        note="Đơn nhập mẫu",
        lines=[PurchaseOrderLine(material_id=1, quantity=50, unit_price=1200)],
        total_amount=50 * 1200,
        created_by=1,
        created_at=datetime.utcnow(),
        received_at=datetime.utcnow(),
    )
]

DEFAULT_PROMO_CODES: List[PromoCode] = [
    PromoCode(id=1, code="WELCOME10", type="percent", value=10, min_order_amount=100000),
    PromoCode(id=2, code="FREESHIP", type="fixed", value=20000, min_order_amount=0),
]
DEFAULT_ORDER_RETURNS: List[OrderReturn] = []
RETURN_STATUS_ALLOWED = {"pending", "approved", "rejected", "processed"}

DEFAULT_IDEAS: List[Idea] = [
    Idea(
        id=1,
        name="Móc khóa củ cà rốt",
        description="Nhỏ gọn, dễ upsell",
        estimated_time=60,
        estimated_price=75000,
        status="Đang thử",
        created_by=1,
    ),
    Idea(
        id=2,
        name="Bó hoa len mini",
        description="Gợi ý cho 8/3",
        estimated_time=180,
        estimated_price=250000,
        status="Chưa thử",
        created_by=2,
    ),
]

DEFAULT_CONTENT_PLANS: List[ContentPlan] = [
    ContentPlan(
        id=1,
        date=date.today(),
        platform="TikTok",
        title="Quá trình móc Bé ma Noel",
        related_product_id=1,
        status="Đã quay",
        estimate_views=5000,
        estimate_inquiries=20,
        estimate_saves=80,
        created_by=1,
    ),
    ContentPlan(
        id=2,
        date=date.fromordinal(date.today().toordinal() + 2),
        platform="Reels",
        title="Set up bàn làm việc chuẩn Noel",
        related_product_id=3,
        status="Ý tưởng",
        estimate_views=2000,
        estimate_inquiries=10,
        estimate_saves=30,
        created_by=2,
    ),
]

DEFAULT_EXPERIMENTS: List[Experiment] = [
    Experiment(
        id=1,
        name="Test thumbnail CTA",
        hypothesis="CTA rõ ràng tăng inbox",
        metric="inquiries",
        target_value=0.05,
        start_date=date.today(),
        status="running",
        variant_a="CTA mờ",
        variant_b="CTA rõ + giá",
        notes="Đo inbox/1000 views trong 7 ngày",
        created_by=1,
    ),
    Experiment(
        id=2,
        name="Giảm giá 10% bó hoa",
        hypothesis="Giảm giá tăng đơn +20%",
        metric="orders",
        target_value=20,
        start_date=date.today(),
        status="paused",
        variant_a="Giá cũ",
        variant_b="Giá -10%",
        notes="Dừng tạm do thiếu nguyên liệu",
        created_by=2,
    ),
]

DEFAULT_PRODUCT_BUNDLES: List[ProductBundle] = [
    ProductBundle(id=1, parent_product_id=1, child_product_id=3, quantity=1),
]

DEFAULT_PRODUCT_IMAGES: List[ProductImage] = [
    ProductImage(id=1, product_id=1, url="https://placehold.co/400x400?text=Be+ma+Noel", is_primary=True, display_order=1),
    ProductImage(id=2, product_id=1, url="https://placehold.co/400x400?text=Be+ma+Noel+2", is_primary=False, display_order=2),
    ProductImage(id=3, product_id=2, url="https://placehold.co/400x400?text=Ech+may+man", is_primary=True, display_order=1),
]

DEFAULT_PRODUCT_REVIEWS: List[ProductReview] = [
    ProductReview(id=1, product_id=1, customer_name="Linh", rating=5, comment="Đẹp và chắc tay", created_at=datetime.utcnow()),
    ProductReview(id=2, product_id=1, customer_name="Huy", rating=4, comment="Giao nhanh, giá ổn", created_at=datetime.utcnow()),
    ProductReview(id=3, product_id=2, customer_name="My", rating=5, comment="Bạn bè thích lắm", created_at=datetime.utcnow()),
]

# Demand & issues sample
DEFAULT_DEMAND: List[DemandSignal] = [
    DemandSignal(id=1, product_id=1, week_of=date(date.today().year, 11, 10), views=1200, inquiries=45, saves=30, created_by=1),
    DemandSignal(id=2, product_id=1, week_of=date(date.today().year, 11, 17), views=1500, inquiries=60, saves=42, created_by=1),
    DemandSignal(id=3, product_id=1, week_of=date(date.today().year, 11, 24), views=2100, inquiries=55, saves=50, created_by=1),
    DemandSignal(id=4, product_id=2, week_of=date(date.today().year, 11, 24), views=800, inquiries=25, saves=18, created_by=2),
]

DEFAULT_ISSUES: List[Issue] = [
    Issue(
        id=1,
        product_id=1,
        type="PRICE",
        description="Khách kêu giá hơi cao",
        evidence="5/10 inbox không chốt vì giá",
        hypothesis="Giá cao hơn shop khác ~10%",
        next_action="Test giảm 10% trong 1 tuần",
        priority=3,
        status="open",
        created_by=1,
        created_at=datetime.utcnow(),
        impact_revenue=500000,
        is_template=False,
        assigned_to=1,
    ),
    Issue(
        id=2,
        product_id=1,
        type="CONTENT",
        description="CTR thấp",
        evidence="Views cao nhưng inbox thấp",
        hypothesis="Caption chưa rõ CTA",
        next_action="Viết lại caption, thêm giá",
        priority=2,
        status="in_progress",
        created_by=1,
        created_at=datetime.utcnow(),
        impact_revenue=0,
        is_template=True,
        assigned_to=None,
    ),
    Issue(
        id=3,
        product_id=2,
        type="DEMAND",
        description="Nhu cầu chậm",
        evidence="Views chỉ 800/tuần",
        hypothesis="Chưa đẩy đúng tệp",
        next_action="Test nội dung tặng quà sinh nhật",
        priority=1,
        status="open",
        created_by=2,
        created_at=datetime.utcnow(),
    ),
]

DEFAULT_PRICE_CHANGES: List[PriceChange] = [
    PriceChange(
        id=1,
        product_id=1,
        old_price=110000,
        new_price=120000,
        changed_by=1,
        changed_at=datetime.utcnow(),
    ),
    PriceChange(
        id=2,
        product_id=3,
        old_price=140000,
        new_price=150000,
        changed_by=1,
        changed_at=datetime.utcnow(),
    ),
]

DEFAULT_LIFECYCLE_EVENTS: List[LifecycleEvent] = [
    LifecycleEvent(
        id=1, product_id=1, status="idea", note="Nghĩ mẫu bé ma", changed_by=1, changed_at=datetime.utcnow()
    ),
    LifecycleEvent(
        id=2, product_id=1, status="prototype", note="Làm mẫu đầu tiên", changed_by=1, changed_at=datetime.utcnow()
    ),
    LifecycleEvent(
        id=3, product_id=1, status="experiment", note="Test giá và content", changed_by=1, changed_at=datetime.utcnow()
    ),
    LifecycleEvent(
        id=4, product_id=2, status="prototype", note="Ảnh chụp lần 1", changed_by=2, changed_at=datetime.utcnow()
    ),
    LifecycleEvent(
        id=5, product_id=2, status="live", note="Bán đều 2 đơn/tuần", changed_by=2, changed_at=datetime.utcnow()
    ),
    LifecycleEvent(
        id=6, product_id=3, status="idea", note="Thử mẫu cây thông", changed_by=1, changed_at=datetime.utcnow()
    ),
    LifecycleEvent(
        id=7, product_id=3, status="prototype", note="Ảnh chụp đang làm", changed_by=1, changed_at=datetime.utcnow()
    ),
]

# --- Mongo connection (optional, default off for speed) --------------------
mongo_client = None
mongo_db = None
USE_MONGO = os.getenv("USE_MONGO", "false").lower() == "true"
MONGO_URL = os.getenv("MONGO_URL")
# Flag to avoid double-writing to Mongo khi đã có Postgres/SQL làm nguồn chính
SQL_AVAILABLE = True
SQL_HAS_DATA = False
if USE_MONGO and MONGO_URL:
    try:
        mongo_client = MongoClient(MONGO_URL, serverSelectionTimeoutMS=2000)
        mongo_client.admin.command("ping")
        db_from_uri = mongo_client.get_default_database()
        mongo_db = db_from_uri if db_from_uri is not None else mongo_client["hala_handmade"]
        print("MongoDB connected:", mongo_db.name)
    except Exception as exc:  # pragma: no cover - only on connection issues
        print(f"MongoDB connection failed, fallback to in-memory. Detail: {exc}")
        mongo_client = None
        mongo_db = None
else:
    if not USE_MONGO:
        print("USE_MONGO=false → bỏ qua Mongo, dùng SQL/in-memory.")
    else:
        print("MONGO_URL not set, using in-memory data only")

# --- Helpers for SQL persistence -------------------------------------------
def product_to_table(product: Product) -> ProductTable:
    return ProductTable(
        id=product.id,
        name=product.name,
        difficulty=product.difficulty,
        time_minutes=product.time_minutes,
        materials_json=json.dumps([
            m if isinstance(m, dict) else m.model_dump()
            for m in (product.materials or [])
        ]),
        base_price=product.base_price,
        priority=product.priority,
        notes=product.notes,
        tags_json=json.dumps(product.tags or []),
        seasons_json=json.dumps(product.seasons or []),
        categories_json=json.dumps(product.categories or []),
        role=product.role,
        lifecycle_status=product.lifecycle_status,
        demand_score=product.demand_score or 0,
        feasibility_score=product.feasibility_score or 0,
        packaging_cost=getattr(product, "packaging_cost", 0) or 0,
        marketing_cost=getattr(product, "marketing_cost", 0) or 0,
        platform_fee_percent=getattr(product, "platform_fee_percent", 0) or 0,
        created_by=product.created_by,
        updated_by=product.updated_by,
    )


def product_from_table(row: ProductTable) -> Product:
    return Product(
        id=row.id,
        name=row.name,
        difficulty=row.difficulty,
        time_minutes=row.time_minutes,
        materials=[MaterialUsage(**m) for m in json.loads(row.materials_json or "[]")],
        base_price=row.base_price,
        priority=row.priority,
        notes=row.notes,
        tags=json.loads(row.tags_json or "[]"),
        seasons=json.loads(row.seasons_json or "[]"),
        categories=json.loads(row.categories_json or "[]"),
        role=row.role,
        lifecycle_status=row.lifecycle_status,
        demand_score=row.demand_score,
        feasibility_score=row.feasibility_score,
        packaging_cost=row.packaging_cost,
        marketing_cost=row.marketing_cost,
        platform_fee_percent=row.platform_fee_percent,
        created_by=row.created_by,
        updated_by=row.updated_by,
    )


def issue_to_table(issue: Issue) -> IssueTable:
    return IssueTable(
        id=issue.id,
        product_id=issue.product_id,
        type=issue.type,
        description=issue.description,
        evidence=issue.evidence,
        hypothesis=issue.hypothesis,
        next_action=issue.next_action,
        priority=issue.priority,
        status=issue.status,
        impact_revenue=issue.impact_revenue,
        is_template=issue.is_template,
        assigned_to=issue.assigned_to,
        created_by=issue.created_by,
        created_at=issue.created_at,
        resolved_at=issue.resolved_at,
        resolution_hours=issue.resolution_hours,
        history_json=None,
    )


def issue_from_table(row: IssueTable) -> Issue:
    return Issue(
        id=row.id,
        product_id=row.product_id,
        type=row.type,
        description=row.description,
        evidence=row.evidence,
        hypothesis=row.hypothesis,
        next_action=row.next_action,
        priority=row.priority,
        status=row.status,
        impact_revenue=row.impact_revenue,
        is_template=row.is_template,
        assigned_to=row.assigned_to,
        created_by=row.created_by,
        created_at=row.created_at,
        resolved_at=row.resolved_at,
        resolution_hours=row.resolution_hours,
        comments_count=0,
    )


def task_to_table(task: Task) -> TaskTable:
    return TaskTable(
        id=task.id,
        title=task.title,
        description=task.description,
        assignee_id=task.assignee_id,
        due_date=task.due_date,
        priority=task.priority,
        status=task.status,
        tags_json=json.dumps(task.tags or []),
        created_by=task.created_by,
        created_at=task.created_at,
        completed_at=task.completed_at,
    )


def task_from_table(row: TaskTable) -> Task:
    return Task(
        id=row.id,
        title=row.title,
        description=row.description,
        assignee_id=row.assignee_id,
        due_date=row.due_date,
        priority=row.priority,
        status=row.status,
        tags=json.loads(row.tags_json or "[]"),
        created_by=row.created_by,
        created_at=row.created_at,
        completed_at=row.completed_at,
    )


def demand_to_table(signal: DemandSignal) -> DemandSignalTable:
    return DemandSignalTable(
        id=signal.id,
        product_id=signal.product_id,
        views=signal.views,
        inquiries=signal.inquiries,
        saves=signal.saves,
        week_of=signal.week_of,
        created_by=signal.created_by,
    )


def demand_from_table(row: DemandSignalTable) -> DemandSignal:
    return DemandSignal(
        id=row.id,
        product_id=row.product_id,
        views=row.views,
        inquiries=row.inquiries,
        saves=row.saves,
        week_of=row.week_of,
        created_by=row.created_by,
    )


def material_to_table(m: Material) -> MaterialTable:
    return MaterialTable(
        id=m.id,
        code=m.code,
        name=m.name,
        type=m.type,
        unit=m.unit,
        unit_price=m.unit_price,
        stock_quantity=m.stock_quantity,
        low_threshold=m.low_threshold,
        note=m.note,
        created_by=m.created_by,
        updated_by=m.updated_by,
    )


def price_change_to_table(pc: PriceChange) -> PriceChangeTable:
    return PriceChangeTable(
        id=pc.id,
        product_id=pc.product_id,
        old_price=pc.old_price,
        new_price=pc.new_price,
        changed_by=pc.changed_by,
        changed_at=pc.changed_at,
    )


def supplier_to_table(s: Supplier) -> "SupplierTable":
    return SupplierTable(
        id=s.id,
        name=s.name,
        contact_name=s.contact_name,
        phone=s.phone,
        email=s.email,
        address=s.address,
        note=s.note,
        rating=s.rating,
        lead_time_days=s.lead_time_days,
        created_at=s.created_at,
    )


def supplier_from_table(row: "SupplierTable") -> Supplier:
    return Supplier(
        id=row.id,
        name=row.name,
        contact_name=row.contact_name,
        phone=row.phone,
        email=row.email,
        address=row.address,
        note=row.note,
        rating=row.rating,
        lead_time_days=row.lead_time_days,
        created_at=row.created_at,
    )


def po_to_table(po: PurchaseOrder) -> "PurchaseOrderTable":
    return PurchaseOrderTable(
        id=po.id,
        supplier_id=po.supplier_id,
        status=po.status,
        expected_date=po.expected_date,
        note=po.note,
        lines_json=json.dumps([l.model_dump(mode="json") for l in po.lines]),
        total_amount=po.total_amount,
        created_by=po.created_by,
        created_at=po.created_at,
        received_at=po.received_at,
    )


def po_from_table(row: "PurchaseOrderTable") -> PurchaseOrder:
    return PurchaseOrder(
        id=row.id,
        supplier_id=row.supplier_id,
        status=row.status,
        expected_date=row.expected_date,
        note=row.note,
        lines=[PurchaseOrderLine(**l) for l in json.loads(row.lines_json or "[]")],
        total_amount=row.total_amount,
        created_by=row.created_by,
        created_at=row.created_at,
        received_at=row.received_at,
    )


def price_change_from_table(row: PriceChangeTable) -> PriceChange:
    return PriceChange(
        id=row.id,
        product_id=row.product_id,
        old_price=row.old_price,
        new_price=row.new_price,
        changed_by=row.changed_by,
        changed_at=row.changed_at,
    )


def lifecycle_to_table(ev: LifecycleEvent) -> LifecycleEventTable:
    return LifecycleEventTable(
        id=ev.id,
        product_id=ev.product_id,
        status=ev.status,
        note=ev.note,
        changed_by=ev.changed_by,
        changed_at=ev.changed_at,
    )


def lifecycle_from_table(row: LifecycleEventTable) -> LifecycleEvent:
    return LifecycleEvent(
        id=row.id,
        product_id=row.product_id,
        status=row.status,
        note=row.note,
        changed_by=row.changed_by,
        changed_at=row.changed_at,
    )


def material_from_table(row: MaterialTable) -> Material:
    return Material(
        id=row.id,
        code=row.code,
        name=row.name,
        type=row.type,
        unit=row.unit,
        unit_price=row.unit_price,
        stock_quantity=row.stock_quantity,
        low_threshold=row.low_threshold,
        note=row.note,
        created_by=row.created_by,
        updated_by=row.updated_by,
    )


def stock_movement_to_table(movement: StockMovement) -> StockMovementTable:
    return StockMovementTable(
        id=movement.id,
        material_id=movement.material_id,
        quantity_change=movement.quantity_change,
        movement_type=movement.movement_type,
        reference_type=movement.reference_type,
        reference_id=movement.reference_id,
        batch_id=movement.batch_id,
        expiry_date=movement.expiry_date,
        user_id=movement.user_id,
        note=movement.note,
        created_at=movement.created_at,
    )


def stock_movement_from_table(row: StockMovementTable) -> StockMovement:
    return StockMovement(
        id=row.id,
        material_id=row.material_id,
        quantity_change=row.quantity_change,
        movement_type=row.movement_type,
        reference_type=row.reference_type,
        reference_id=row.reference_id,
        batch_id=row.batch_id,
        expiry_date=row.expiry_date,
        user_id=row.user_id,
        note=row.note,
        created_at=row.created_at,
    )


def order_return_to_table(ret: OrderReturn) -> "OrderReturnTable":
    return OrderReturnTable(
        id=ret.id,
        order_id=ret.order_id,
        reason=ret.reason,
        amount=ret.amount,
        status=ret.status,
        refund_method=ret.refund_method,
        refund_amount=ret.refund_amount,
        note=ret.note,
        created_by=ret.created_by,
        created_at=ret.created_at,
    )


def order_return_from_table(row: "OrderReturnTable") -> OrderReturn:
    return OrderReturn(
        id=row.id,
        order_id=row.order_id,
        reason=row.reason,
        amount=row.amount,
        status=row.status,
        refund_method=row.refund_method,
        refund_amount=row.refund_amount,
        note=row.note,
        created_by=row.created_by,
        created_at=row.created_at,
    )


def save_product_sql(product: Product):
    with Session(engine) as session:
        table_obj = product_to_table(product)
        session.merge(table_obj)
        session.commit()


def save_issue_sql(issue: Issue):
    with Session(engine) as session:
        table_obj = issue_to_table(issue)
        session.merge(table_obj)
        session.commit()


def save_demand_sql(signal: DemandSignal):
    with Session(engine) as session:
        table_obj = demand_to_table(signal)
        session.merge(table_obj)
        session.commit()


def save_task_sql(task: Task):
    with Session(engine) as session:
        table_obj = task_to_table(task)
        session.merge(table_obj)
        session.commit()


def save_material_sql(material: Material):
    with Session(engine) as session:
        table_obj = material_to_table(material)
        session.merge(table_obj)
        session.commit()


def save_order_sql(order: Order):
    with Session(engine) as session:
        session.merge(
            OrderTable(
                id=order.id,
                date=order.date,
                channel=order.channel,
                order_json=json.dumps(order.model_dump(mode="json")),
                created_by=order.created_by,
                updated_by=order.updated_by,
            )
        )
        session.commit()


def save_price_change_sql(pc: PriceChange):
    with Session(engine) as session:
        session.merge(price_change_to_table(pc))
        session.commit()


def save_lifecycle_sql(ev: LifecycleEvent):
    with Session(engine) as session:
        session.merge(lifecycle_to_table(ev))
        session.commit()


def save_variant_sql(variant: ProductVariant):
    with Session(engine) as session:
        session.merge(
            ProductVariantTable(
                id=variant.id,
                product_id=variant.product_id,
                name=variant.name,
                sku=variant.sku,
                price_modifier=variant.price_modifier,
                stock_quantity=variant.stock_quantity,
                is_active=variant.is_active,
                created_at=variant.created_at,
            )
        )
        session.commit()


def save_order_return_sql(ret: OrderReturn):
    with Session(engine) as session:
        session.merge(order_return_to_table(ret))
        session.commit()


# --- Data bootstrap ---------------------------------------------------------
settings = DEFAULT_SETTINGS
materials: List[Material] = []
products: List[Product] = []
orders: List[Order] = []
seasons: List[Season] = []
ideas: List[Idea] = []
content_plans: List[ContentPlan] = []
users: List[User] = []
activity_logs: List[ActivityLog] = []
demand_signals: List[DemandSignal] = []
issues: List[Issue] = []
price_changes: List[PriceChange] = []
lifecycle_events: List[LifecycleEvent] = []
customers: List[Customer] = []
stock_movements: List[StockMovement] = []
product_variants: List[ProductVariant] = []
payments: List[Payment] = []
categories: List[Category] = []
product_bundles: List[ProductBundle] = []
product_images: List[ProductImage] = []
product_reviews: List[ProductReview] = []
LOGIN_ATTEMPTS: Dict[str, List[datetime]] = {}


def clean_doc(doc: dict) -> dict:
    doc = dict(doc)
    doc.pop("_id", None)
    return doc


def load_collection(name: str, model_cls, fallback: List[BaseModel]) -> List[BaseModel]:
    # Nếu SQL đã có data → không đọc/ghi Mongo để tránh double-write
    if SQL_HAS_DATA:
        return copy.deepcopy(fallback)

    if USE_MONGO and mongo_db is not None:
        docs = list(mongo_db[name].find())
        if docs:
            return [model_cls.model_validate(clean_doc(doc)) for doc in docs]
        if fallback:
            mongo_db[name].insert_many([item.model_dump(mode="json") for item in fallback])
    return copy.deepcopy(fallback)


def load_settings() -> Settings:
    if USE_MONGO and mongo_db is not None:
        doc = mongo_db["settings"].find_one({"_id": "settings"})
        if doc:
            return Settings.model_validate(clean_doc(doc))
        mongo_db["settings"].replace_one({"_id": "settings"}, DEFAULT_SETTINGS.model_dump(mode="json"), upsert=True)
    return Settings.model_validate(DEFAULT_SETTINGS.model_dump())


settings = load_settings()


def ensure_sql_columns():
    if not engine or not SQL_INITIALIZED:
        return
    if os.getenv("SKIP_SCHEMA_PATCH", "false").lower() == "true":
        return
    inspector = sa_inspect(engine)
    backend = engine.url.get_backend_name()
    # SQLite: chỉ thêm cột đơn giản (ADD COLUMN) để tránh lỗi model mismatch
    if backend.startswith("sqlite"):
        statements: List[str] = []
        if inspector.has_table("issuetable"):
            cols = {c["name"] for c in inspector.get_columns("issuetable")}
            if "impact_revenue" not in cols:
                statements.append("ALTER TABLE issuetable ADD COLUMN impact_revenue REAL DEFAULT 0")
            if "is_template" not in cols:
                statements.append("ALTER TABLE issuetable ADD COLUMN is_template BOOLEAN DEFAULT 0")
            if "resolution_hours" not in cols:
                statements.append("ALTER TABLE issuetable ADD COLUMN resolution_hours REAL")
            if "assigned_to" not in cols:
                statements.append("ALTER TABLE issuetable ADD COLUMN assigned_to INTEGER")
        if inspector.has_table("orderreturntable"):
            rcols = {c["name"] for c in inspector.get_columns("orderreturntable")}
            if "refund_method" not in rcols:
                statements.append("ALTER TABLE orderreturntable ADD COLUMN refund_method TEXT")
            if "refund_amount" not in rcols:
                statements.append("ALTER TABLE orderreturntable ADD COLUMN refund_amount REAL")
        if inspector.has_table("stockmovementtable"):
            smcols = {c["name"] for c in inspector.get_columns("stockmovementtable")}
            if "batch_id" not in smcols:
                statements.append("ALTER TABLE stockmovementtable ADD COLUMN batch_id TEXT")
            if "expiry_date" not in smcols:
                statements.append("ALTER TABLE stockmovementtable ADD COLUMN expiry_date DATE")
        if inspector.has_table("tasktable"):
            tcols = {c["name"] for c in inspector.get_columns("tasktable")}
            if "assignee_id" not in tcols:
                statements.append("ALTER TABLE tasktable ADD COLUMN assignee_id INTEGER")
            if "due_date" not in tcols:
                statements.append("ALTER TABLE tasktable ADD COLUMN due_date DATE")
            if "priority" not in tcols:
                statements.append("ALTER TABLE tasktable ADD COLUMN priority INTEGER DEFAULT 2")
            if "status" not in tcols:
                statements.append("ALTER TABLE tasktable ADD COLUMN status TEXT DEFAULT 'open'")
            if "tags_json" not in tcols:
                statements.append("ALTER TABLE tasktable ADD COLUMN tags_json TEXT")
            if "completed_at" not in tcols:
                statements.append("ALTER TABLE tasktable ADD COLUMN completed_at TIMESTAMP")
        if statements:
            with engine.begin() as conn:
                for stmt in statements:
                    try:
                        conn.execute(sa_text(stmt))
                    except Exception:
                        pass
        return
    statements: List[str] = []
    # product columns
    if inspector.has_table("producttable"):
        cols = {c["name"] for c in inspector.get_columns("producttable")}
        if "categories_json" not in cols:
            statements.append("ALTER TABLE producttable ADD COLUMN categories_json JSONB DEFAULT '[]'::jsonb")
        if "packaging_cost" not in cols:
            statements.append("ALTER TABLE producttable ADD COLUMN packaging_cost DOUBLE PRECISION DEFAULT 0")
        if "marketing_cost" not in cols:
            statements.append("ALTER TABLE producttable ADD COLUMN marketing_cost DOUBLE PRECISION DEFAULT 0")
        if "platform_fee_percent" not in cols:
            statements.append("ALTER TABLE producttable ADD COLUMN platform_fee_percent DOUBLE PRECISION DEFAULT 0")
    if inspector.has_table("settingstable"):
        scols = {c["name"] for c in inspector.get_columns("settingstable")}
        for col, dtype in [
            ("business_name", "TEXT"),
            ("business_address", "TEXT"),
            ("business_logo", "TEXT"),
            ("capacity_hours_per_month", "DOUBLE PRECISION"),
            ("tax_rate", "DOUBLE PRECISION"),
            ("backup_email", "TEXT"),
            ("smtp_host", "TEXT"),
            ("smtp_port", "INTEGER"),
            ("smtp_user", "TEXT"),
            ("smtp_password", "TEXT"),
            ("smtp_use_tls", "BOOLEAN"),
        ]:
            if col not in scols:
                statements.append(f"ALTER TABLE settingstable ADD COLUMN {col} {dtype}")
    # order columns
    if inspector.has_table("ordertable"):
        ocols = {c["name"] for c in inspector.get_columns("ordertable")}
        if "status" not in ocols:
            statements.append("ALTER TABLE ordertable ADD COLUMN status VARCHAR(50) DEFAULT 'pending'")
        if "payment_status" not in ocols:
            statements.append("ALTER TABLE ordertable ADD COLUMN payment_status VARCHAR(50) DEFAULT 'unpaid'")
        if "customer_id" not in ocols:
            statements.append("ALTER TABLE ordertable ADD COLUMN customer_id INTEGER")
        if "source_content_id" not in ocols:
            statements.append("ALTER TABLE ordertable ADD COLUMN source_content_id INTEGER")
        if "shipping_carrier" not in ocols:
            statements.append("ALTER TABLE ordertable ADD COLUMN shipping_carrier VARCHAR(100)")
        if "tracking_number" not in ocols:
            statements.append("ALTER TABLE ordertable ADD COLUMN tracking_number VARCHAR(100)")
        if "estimated_delivery_date" not in ocols:
            statements.append("ALTER TABLE ordertable ADD COLUMN estimated_delivery_date DATE")
        if "created_by" not in ocols:
            statements.append("ALTER TABLE ordertable ADD COLUMN created_by INTEGER")
        if "updated_by" not in ocols:
            statements.append("ALTER TABLE ordertable ADD COLUMN updated_by INTEGER")
    if inspector.has_table("issuetable"):
        icol = {c["name"] for c in inspector.get_columns("issuetable")}
        if "impact_revenue" not in icol:
            statements.append("ALTER TABLE issuetable ADD COLUMN impact_revenue DOUBLE PRECISION DEFAULT 0")
        if "is_template" not in icol:
            statements.append("ALTER TABLE issuetable ADD COLUMN is_template BOOLEAN DEFAULT FALSE")
        if "assigned_to" not in icol:
            statements.append("ALTER TABLE issuetable ADD COLUMN assigned_to INTEGER")
        if "resolution_hours" not in icol:
            statements.append("ALTER TABLE issuetable ADD COLUMN resolution_hours DOUBLE PRECISION")
    if inspector.has_table("tasktable"):
        tcols = {c["name"] for c in inspector.get_columns("tasktable")}
        for col, dtype in [
            ("assignee_id", "INTEGER"),
            ("due_date", "DATE"),
            ("priority", "INTEGER"),
            ("status", "VARCHAR(50)"),
            ("tags_json", "JSONB"),
            ("completed_at", "TIMESTAMP"),
        ]:
            if col not in tcols:
                statements.append(f"ALTER TABLE tasktable ADD COLUMN {col} {dtype}")
    if inspector.has_table("settingstable"):
        scols = {c["name"] for c in inspector.get_columns("settingstable")}
        if "notification_emails" not in scols:
            statements.append("ALTER TABLE settingstable ADD COLUMN notification_emails JSONB DEFAULT '[]'::jsonb")
        if "notify_low_stock" not in scols:
            statements.append("ALTER TABLE settingstable ADD COLUMN notify_low_stock BOOLEAN DEFAULT TRUE")
        if "notify_forecast_low" not in scols:
            statements.append("ALTER TABLE settingstable ADD COLUMN notify_forecast_low BOOLEAN DEFAULT TRUE")
        for col, dtype in [
            ("backup_email", "TEXT"),
            ("smtp_host", "TEXT"),
            ("smtp_port", "INTEGER"),
            ("smtp_user", "TEXT"),
            ("smtp_password", "TEXT"),
            ("smtp_use_tls", "BOOLEAN"),
        ]:
            if col not in scols:
                statements.append(f"ALTER TABLE settingstable ADD COLUMN {col} {dtype}")
    if inspector.has_table("customertable"):
        ccols = {c["name"] for c in inspector.get_columns("customertable")}
        if "first_order_date" not in ccols:
            statements.append("ALTER TABLE customertable ADD COLUMN first_order_date DATE")
    if inspector.has_table("stockmovementtable"):
        smcols = {c["name"] for c in inspector.get_columns("stockmovementtable")}
        if "batch_id" not in smcols:
            statements.append("ALTER TABLE stockmovementtable ADD COLUMN batch_id VARCHAR(255)")
        if "expiry_date" not in smcols:
            statements.append("ALTER TABLE stockmovementtable ADD COLUMN expiry_date DATE")
    # order return columns
    if inspector.has_table("orderreturntable"):
        rcols = {c["name"] for c in inspector.get_columns("orderreturntable")}
        if "refund_method" not in rcols:
            statements.append("ALTER TABLE orderreturntable ADD COLUMN refund_method VARCHAR(50)")
        if "refund_amount" not in rcols:
            statements.append("ALTER TABLE orderreturntable ADD COLUMN refund_amount DOUBLE PRECISION")
    if statements:
        with engine.begin() as conn:
            for stmt in statements:
                try:
                    conn.execute(sa_text(stmt))
                except Exception as exc:  # pragma: no cover - best-effort bootstrap
                    # Tránh làm chết app khi thiếu cột/bảng cũ ở DB từ trước
                    print(f"Skip index creation '{stmt}' because: {exc}")
                print(f"Ensured SQL index: {stmt}")
                print(f"Applied SQL column patch: {stmt}")


def ensure_sql_indexes():
    if not engine or not SQL_INITIALIZED:
        return
    if os.getenv("SKIP_SCHEMA_PATCH", "false").lower() == "true":
        return
    inspector = sa_inspect(engine)
    backend = engine.url.get_backend_name()
    if backend.startswith("sqlite"):
        return

    def missing(table: str, name: str) -> bool:
        try:
            return not any(idx.get("name") == name for idx in inspector.get_indexes(table))
        except Exception:
            return True

    statements = []
    if inspector.has_table("producttable"):
        if missing("producttable", "ix_product_lifecycle"):
            statements.append("CREATE INDEX IF NOT EXISTS ix_product_lifecycle ON producttable (lifecycle_status)")
        if missing("producttable", "ix_product_role"):
            statements.append("CREATE INDEX IF NOT EXISTS ix_product_role ON producttable (role)")
    if inspector.has_table("issuetable"):
        if missing("issuetable", "ix_issue_product"):
            statements.append("CREATE INDEX IF NOT EXISTS ix_issue_product ON issuetable (product_id)")
        if missing("issuetable", "ix_issue_status"):
            statements.append("CREATE INDEX IF NOT EXISTS ix_issue_status ON issuetable (status)")
    if inspector.has_table("demandsignaltable"):
        dcols = {c["name"] for c in inspector.get_columns("demandsignaltable")}
        if {"product_id", "week_of"}.issubset(dcols) and missing("demandsignaltable", "ix_demand_product_week"):
            statements.append("CREATE INDEX IF NOT EXISTS ix_demand_product_week ON demandsignaltable (product_id, week_of)")
    if inspector.has_table("ordertable"):
        ocols = {c["name"] for c in inspector.get_columns("ordertable")}
        if "date" in ocols and missing("ordertable", "ix_order_date"):
            statements.append("CREATE INDEX IF NOT EXISTS ix_order_date ON ordertable (date)")
        if "status" in ocols and missing("ordertable", "ix_order_status"):
            statements.append("CREATE INDEX IF NOT EXISTS ix_order_status ON ordertable (status)")
        if "channel" in ocols and missing("ordertable", "ix_order_channel"):
            statements.append("CREATE INDEX IF NOT EXISTS ix_order_channel ON ordertable (channel)")
    if inspector.has_table("materialtable"):
        if missing("materialtable", "ux_material_code"):
            statements.append("CREATE UNIQUE INDEX IF NOT EXISTS ux_material_code ON materialtable (code)")
    if inspector.has_table("customertable"):
        if missing("customertable", "ix_customer_source"):
            statements.append("CREATE INDEX IF NOT EXISTS ix_customer_source ON customertable (source)")
        if missing("customertable", "ix_customer_spent"):
            statements.append("CREATE INDEX IF NOT EXISTS ix_customer_spent ON customertable (total_spent)")
    if inspector.has_table("purchaseordertable"):
        if missing("purchaseordertable", "ix_po_status"):
            statements.append("CREATE INDEX IF NOT EXISTS ix_po_status ON purchaseordertable (status)")
        if missing("purchaseordertable", "ix_po_supplier"):
            statements.append("CREATE INDEX IF NOT EXISTS ix_po_supplier ON purchaseordertable (supplier_id)")
    if inspector.has_table("stockmovementtable"):
        if missing("stockmovementtable", "ix_stock_movement_material"):
            statements.append("CREATE INDEX IF NOT EXISTS ix_stock_movement_material ON stockmovementtable (material_id)")
        if missing("stockmovementtable", "ix_stock_movement_type"):
            statements.append("CREATE INDEX IF NOT EXISTS ix_stock_movement_type ON stockmovementtable (movement_type)")
        if missing("stockmovementtable", "ix_stock_batch_expiry"):
            statements.append("CREATE INDEX IF NOT EXISTS ix_stock_batch_expiry ON stockmovementtable (batch_id, expiry_date)")
    if inspector.has_table("orderreturntable"):
        if missing("orderreturntable", "ix_return_order"):
            statements.append("CREATE INDEX IF NOT EXISTS ix_return_order ON orderreturntable (order_id)")
        if missing("orderreturntable", "ix_return_status"):
            statements.append("CREATE INDEX IF NOT EXISTS ix_return_status ON orderreturntable (status)")
    if inspector.has_table("activitylogtable"):
        if missing("activitylogtable", "ix_activity_entity"):
            statements.append("CREATE INDEX IF NOT EXISTS ix_activity_entity ON activitylogtable (entity_type)")
        if missing("activitylogtable", "ix_activity_user"):
            statements.append("CREATE INDEX IF NOT EXISTS ix_activity_user ON activitylogtable (user_id)")

    if statements:
        with engine.begin() as conn:
            for stmt in statements:
                try:
                    conn.execute(sa_text(stmt))
                    print(f"Ensured SQL index: {stmt}")
                except Exception as exc:  # pragma: no cover - best-effort bootstrap
                    print(f"Skip SQL index '{stmt}' because: {exc}")


def load_sql_or_seed(table_cls, seed_list, to_model):
    global SQL_HAS_DATA
    initialize_database()  # Ensure database is initialized
    ensure_sql_columns()
    ensure_sql_indexes()
    with Session(engine) as session:
        rows = session.exec(select(table_cls)).all()
        if rows:
            SQL_HAS_DATA = True
            return [to_model(r) for r in rows]
        if seed_list:
            for item in seed_list:
                if table_cls == ProductTable:
                    session.add(product_to_table(item))
                elif table_cls == MaterialTable:
                    session.add(material_to_table(item))
                elif table_cls == IssueTable:
                    session.add(issue_to_table(item))
                elif table_cls == DemandSignalTable:
                    session.add(demand_to_table(item))
                elif table_cls == OrderTable and isinstance(item, Order):
                    session.add(
                        OrderTable(
                            id=item.id,
                            date=item.date,
                            channel=item.channel,
                            status=item.status,
                            payment_status=item.payment_status,
                            customer_id=item.customer_id,
                            source_content_id=item.source_content_id,
                            shipping_carrier=item.shipping_carrier,
                            tracking_number=item.tracking_number,
                            estimated_delivery_date=item.estimated_delivery_date,
                            order_json=json.dumps(item.model_dump(mode="json")),
                        )
                    )
                elif table_cls == LifecycleEventTable:
                    session.add(lifecycle_to_table(item))
                elif table_cls == PurchaseOrderTable and isinstance(item, PurchaseOrder):
                    session.add(
                        PurchaseOrderTable(
                            id=item.id,
                            supplier_id=item.supplier_id,
                            status=item.status,
                            expected_date=item.expected_date,
                            note=item.note,
                            lines_json=json.dumps([l.model_dump(mode="json") for l in item.lines]),
                            total_amount=item.total_amount,
                            created_by=item.created_by,
                            created_at=item.created_at,
                            received_at=item.received_at,
                        )
                    )
                elif table_cls == PriceChangeTable:
                    session.add(price_change_to_table(item))
                elif table_cls == OrderReturnTable and isinstance(item, OrderReturn):
                    session.add(order_return_to_table(item))
            session.commit()
            SQL_HAS_DATA = True
            return seed_list
    return []


materials = load_sql_or_seed(MaterialTable, DEFAULT_MATERIALS, material_from_table)
if not materials:
    materials = load_collection("materials", Material, DEFAULT_MATERIALS)

products = load_sql_or_seed(ProductTable, DEFAULT_PRODUCTS, product_from_table)
if not products:
    products = load_collection("products", Product, DEFAULT_PRODUCTS)

orders = load_sql_or_seed(OrderTable, DEFAULT_ORDERS, lambda r: Order(**json.loads(r.order_json)))
if not orders:
    orders = load_collection("orders", Order, DEFAULT_ORDERS)

seasons = load_collection("seasons", Season, DEFAULT_SEASONS)
ideas = load_collection("ideas", Idea, DEFAULT_IDEAS)
content_plans = load_collection("content_plans", ContentPlan, DEFAULT_CONTENT_PLANS)
experiments = load_collection("experiments", Experiment, DEFAULT_EXPERIMENTS)
# Users đã được seed và cache sẵn ở trên
activity_logs = load_collection("activity_logs", ActivityLog, [])
demand_signals = load_sql_or_seed(DemandSignalTable, [], demand_from_table)
if not demand_signals:
    demand_signals = load_collection("demand_signals", DemandSignal, DEFAULT_DEMAND)
issues = load_sql_or_seed(IssueTable, [], issue_from_table)
if not issues:
    issues = load_collection("issues", Issue, DEFAULT_ISSUES)
price_changes = load_sql_or_seed(PriceChangeTable, [], price_change_from_table)
if not price_changes:
    price_changes = load_collection("price_changes", PriceChange, DEFAULT_PRICE_CHANGES)
lifecycle_events = load_sql_or_seed(LifecycleEventTable, [], lifecycle_from_table)
if not lifecycle_events:
    lifecycle_events = load_collection("lifecycle_events", LifecycleEvent, DEFAULT_LIFECYCLE_EVENTS)
issue_comments: List[IssueComment] = load_collection("issue_comments", IssueComment, [])
tasks: List[Task] = load_sql_or_seed(TaskTable, [], task_from_table)
if not tasks:
    tasks = load_collection("tasks", Task, [])

goals: List[Goal] = load_collection("goals", Goal, [])

DEFAULT_CUSTOMERS = [
    Customer(
        id=1,
        name="Nguyễn Văn A",
        phone="0901234567",
        email="nguyenvana@example.com",
        source="TikTok",
        tags=["VIP"],
        created_at=datetime(2024, 1, 15),
        total_orders=5,
        total_spent=2500000,
        last_order_date=date(2024, 11, 20),
        created_by=1
    ),
    Customer(
        id=2,
        name="Trần Thị B",
        phone="0912345678",
        email="tranthib@example.com",
        source="Facebook",
        tags=["repeater"],
        created_at=datetime(2024, 3, 10),
        total_orders=3,
        total_spent=1200000,
        last_order_date=date(2024, 10, 5),
        created_by=1
    ),
    Customer(
        id=3,
        name="Lê Văn C",
        phone="0923456789",
        email="levanc@example.com",
        source="Instagram",
        tags=[],
        created_at=datetime(2024, 6, 20),
        total_orders=1,
        total_spent=350000,
        last_order_date=date(2024, 6, 25),
        created_by=1
    ),
    Customer(
        id=4,
        name="Phạm Thị D",
        phone="0934567890",
        email="phamthid@example.com",
        source="TikTok",
        tags=["VIP"],
        created_at=datetime(2024, 2, 1),
        total_orders=8,
        total_spent=4500000,
        last_order_date=date(2024, 11, 28),
        created_by=1
    ),
    Customer(
        id=5,
        name="Hoàng Văn E",
        phone="0945678901",
        source="Zalo",
        tags=[],
        created_at=datetime(2024, 8, 10),
        total_orders=2,
        total_spent=800000,
        last_order_date=date(2024, 9, 15),
        created_by=1
    )
]

customers = load_collection("customers", Customer, DEFAULT_CUSTOMERS)
stock_movements = load_sql_or_seed(StockMovementTable, [], stock_movement_from_table)
if not stock_movements:
    stock_movements = load_collection("stock_movements", StockMovement, [])
product_variants = load_collection("product_variants", ProductVariant, [])
payments = load_collection("payments", Payment, [])
categories = load_collection("categories", Category, DEFAULT_CATEGORIES)
product_bundles = load_collection("product_bundles", ProductBundle, DEFAULT_PRODUCT_BUNDLES)
product_images = load_collection("product_images", ProductImage, DEFAULT_PRODUCT_IMAGES)
product_reviews = load_collection("product_reviews", ProductReview, DEFAULT_PRODUCT_REVIEWS)
suppliers = load_sql_or_seed(SupplierTable, DEFAULT_SUPPLIERS, supplier_from_table)
if not suppliers:
    suppliers = load_collection("suppliers", Supplier, DEFAULT_SUPPLIERS)
purchase_orders = load_sql_or_seed(PurchaseOrderTable, DEFAULT_PURCHASE_ORDERS, po_from_table)
if not purchase_orders:
    purchase_orders = load_collection("purchase_orders", PurchaseOrder, DEFAULT_PURCHASE_ORDERS)
promo_codes = load_collection("promo_codes", PromoCode, DEFAULT_PROMO_CODES)
order_returns: List[OrderReturn] = load_sql_or_seed(OrderReturnTable, DEFAULT_ORDER_RETURNS, order_return_from_table)
if not order_returns:
    order_returns = load_collection("order_returns", OrderReturn, DEFAULT_ORDER_RETURNS)


def seed_sql_defaults():
    # Làm sạch toàn bộ user cũ và tạo lại 2 tài khoản mặc định (bcrypt hash)
    with Session(engine) as session:
        session.exec(delete(UserTable))
        session.commit()
        for u in DEFAULT_USERS:
            session.add(
                UserTable(
                    name=u.name,
                    email=u.email,
                    password_hash=u.password_hash,
                    role=u.role,
                    is_owner=u.is_owner,
                    created_at=u.created_at,
                )
            )
        session.commit()

    # Đồng bộ sang Mongo (nếu có và chưa ưu tiên SQL)
    if not SQL_HAS_DATA and mongo_db is not None:
        mongo_db["users"].delete_many({})
        mongo_db["users"].insert_many([u.model_dump() for u in DEFAULT_USERS])
        mongo_db["suppliers"].delete_many({})
        mongo_db["suppliers"].insert_many([s.model_dump(mode="json") for s in suppliers])
        mongo_db["purchase_orders"].delete_many({})
        mongo_db["purchase_orders"].insert_many([po.model_dump(mode="json") for po in purchase_orders])


seed_sql_defaults()

# In-memory cache cho users sau khi seed
users = [User(**u.model_dump()) for u in DEFAULT_USERS]
if generated_admin_password:
    print(
        "[WARN] Seed users owner_a@example.com / owner_b@example.com đang dùng mật khẩu tạm. "
        f"Mật khẩu tạm thời: {generated_admin_password}. Hãy đặt ADMIN_DEFAULT_PASSWORD hoặc OWNER_*_PASSWORD cho production."
    )


# --- Helpers ----------------------------------------------------------------
def next_id(items: List[BaseModel]) -> int:
    return max((item.id for item in items), default=0) + 1


ORDER_STATUS_ALLOWED = {
    "pending",
    "confirmed",
    "processing",
    "completed",
    "shipped",
    "delivered",
    "cancelled",
}

PAYMENT_STATUS_ALLOWED = {"unpaid", "partial", "paid", "refunded"}
PAYMENT_RECORD_STATUS_ALLOWED = {"pending", "paid", "failed", "refunded"}
PAYMENT_METHOD_ALLOWED = {"cash", "bank_transfer", "momo", "zalopay", "cod", "credit_card", "other"}
PURCHASE_ORDER_STATUS_ALLOWED = {"draft", "ordered", "received", "cancelled"}
RETURN_STATUS_ALLOWED = {"pending", "approved", "rejected", "processed"}


def upsert_document(collection: str, obj: BaseModel, identifier: Optional[int] = None):
    # Nếu SQL đã có data thì coi SQL là nguồn chính, bỏ qua Mongo
    if SQL_HAS_DATA or not USE_MONGO or mongo_db is None:
        return
    doc = obj.model_dump(mode="json")
    if collection == "settings":
        key = {"_id": "settings"}
    else:
        obj_id = identifier if identifier is not None else getattr(obj, "id", None)
        key = {"id": obj_id}
    mongo_db[collection].replace_one(key, doc, upsert=True)


def delete_document(collection: str, identifier: int):
    if SQL_HAS_DATA or not USE_MONGO or mongo_db is None:
        return
    mongo_db[collection].delete_one({"id": identifier})


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    return pwd_context.verify(password, hashed)


def validate_product_exists(product_id: int):
    if not any(p.id == product_id for p in products):
        raise HTTPException(status_code=404, detail=f"Sản phẩm ID {product_id} không tồn tại")


def validate_order_payload(payload: OrderCreate):
    if payload.status not in ORDER_STATUS_ALLOWED:
        raise HTTPException(status_code=400, detail="Trạng thái đơn không hợp lệ")
    if payload.payment_status not in PAYMENT_STATUS_ALLOWED:
        raise HTTPException(status_code=400, detail="Trạng thái thanh toán không hợp lệ")
    if payload.customer_id:
        if not any(c.id == payload.customer_id for c in customers):
            raise HTTPException(status_code=404, detail="Khách hàng không tồn tại")
    if payload.maker_user_id:
        if not any(u.id == payload.maker_user_id for u in users):
            raise HTTPException(status_code=404, detail="Maker không tồn tại")
    if payload.source_content_id:
        if not any(cp.id == payload.source_content_id for cp in content_plans):
            raise HTTPException(status_code=404, detail="Content nguồn không tồn tại")
    if not payload.order_lines:
        raise HTTPException(status_code=400, detail="Đơn hàng phải có ít nhất 1 sản phẩm")
    for line in payload.order_lines:
        validate_product_exists(line.product_id)
        if line.quantity <= 0:
            raise HTTPException(status_code=400, detail="Số lượng phải lớn hơn 0")
        if line.unit_price < 0:
            raise HTTPException(status_code=400, detail="Đơn giá không được âm")
    # promo code validation
    if payload.promo_code:
        promo = next((p for p in promo_codes if p.code.lower() == payload.promo_code.lower() and p.is_active), None)
        if not promo:
            raise HTTPException(status_code=400, detail="Mã khuyến mãi không hợp lệ")
        if promo.expires_at and promo.expires_at < datetime.utcnow():
            raise HTTPException(status_code=400, detail="Mã khuyến mãi đã hết hạn")


def validate_payment_payload(payload: PaymentCreate):
    if payload.amount <= 0:
        raise HTTPException(status_code=400, detail="Số tiền phải lớn hơn 0")
    status = payload.status
    if status == "completed":
        status = "paid"
    if status not in PAYMENT_RECORD_STATUS_ALLOWED:
        raise HTTPException(status_code=400, detail="Trạng thái thanh toán không hợp lệ")
    if payload.method not in PAYMENT_METHOD_ALLOWED:
        raise HTTPException(status_code=400, detail="Phương thức thanh toán không hợp lệ")
    find_order(payload.order_id)
    return status


def compute_promo_discount(promo: PromoCode, order_lines: List[OrderLine]) -> float:
    gross = sum(line.unit_price * line.quantity for line in order_lines)
    if gross < promo.min_order_amount:
        return 0.0
    if promo.type == "percent":
        discount = gross * promo.value / 100
        if promo.max_discount:
            discount = min(discount, promo.max_discount)
        return discount
    return min(promo.value, gross)


def apply_promo(order_obj):
    if not getattr(order_obj, "promo_code", None):
        return
    promo = next((p for p in promo_codes if p.code.lower() == order_obj.promo_code.lower() and p.is_active), None)
    if not promo:
        return
    if promo.expires_at and promo.expires_at < datetime.utcnow():
        return
    promo_discount = compute_promo_discount(promo, order_obj.order_lines)
    if promo_discount > 0:
        order_obj.discount = max(order_obj.discount, promo_discount)


def validate_purchase_order_payload(payload: PurchaseOrderCreate):
    if payload.status not in PURCHASE_ORDER_STATUS_ALLOWED:
        raise HTTPException(status_code=400, detail="Trạng thái PO không hợp lệ")
    if not payload.lines:
        raise HTTPException(status_code=400, detail="Đơn mua phải có ít nhất 1 dòng")
    find_supplier(payload.supplier_id)
    for line in payload.lines:
        if line.quantity <= 0:
            raise HTTPException(status_code=400, detail="Số lượng phải > 0")
        if line.unit_price < 0:
            raise HTTPException(status_code=400, detail="Đơn giá phải >= 0")
        find_material(line.material_id)


def create_access_token(data: dict, expires_minutes: int = 60 * 24 * 7) -> str:
    to_encode = data.copy()
    if "sub" in to_encode:
        to_encode["sub"] = str(to_encode["sub"])
    expire = datetime.utcnow() + timedelta(minutes=expires_minutes)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, JWT_SECRET, algorithm=JWT_ALGO)


def find_user_by_email(email: str) -> Optional[User]:
    # Try SQL DB first
    with Session(engine) as session:
        stmt = select(UserTable).where(UserTable.email == email)
        row = session.exec(stmt).first()
        if row:
            return User(
                id=row.id,
                name=row.name,
                email=row.email,
                password_hash=row.password_hash,
                role=row.role,
                is_owner=row.is_owner,
                created_at=row.created_at,
                last_login_at=row.last_login_at,
            )
    for user in users:
        if user.email.lower() == email.lower():
            return user
    return None


def log_activity(user_id: int, entity_type: str, entity_id: Optional[int], action: str, changes: Optional[dict] = None):
    log = ActivityLog(
        id=next_id(activity_logs),
        user_id=user_id,
        entity_type=entity_type,
        entity_id=entity_id,
        action=action,
        changes=changes,
        created_at=datetime.utcnow(),
    )
    activity_logs.insert(0, log)
    # Chỉ ghi Mongo khi được bật và chưa ưu tiên SQL, tránh chậm API
    if USE_MONGO and not SQL_HAS_DATA and mongo_db is not None:
        mongo_db["activity_logs"].insert_one(log.model_dump(mode="json"))
    with Session(engine) as session:
        try:
            session.add(
                ActivityLogTable(
                    user_id=user_id,
                    entity_type=entity_type,
                    entity_id=entity_id,
                    action=action,
                    changes=log.changes if log.changes is None else str(log.changes),
                    created_at=log.created_at,
                )
            )
            session.commit()
        except Exception:
            session.rollback()


def record_login_attempt(client_ip: str):
    now = datetime.utcnow()
    window_seconds = 60
    max_attempts = 5
    attempts = LOGIN_ATTEMPTS.get(client_ip, [])
    attempts = [t for t in attempts if (now - t).total_seconds() <= window_seconds]
    if len(attempts) >= max_attempts:
        raise HTTPException(status_code=429, detail="Thử đăng nhập quá nhiều, thử lại sau 1 phút")
    attempts.append(now)
    LOGIN_ATTEMPTS[client_ip] = attempts


def stock_movements_for_order(order_id: int) -> List[StockMovement]:
    return [mv for mv in stock_movements if mv.reference_type == "order" and mv.reference_id == order_id]


def deduct_stock_for_order(order: Order, current_user: User):
    existing = stock_movements_for_order(order.id)
    if existing:
        return  # đã trừ rồi
    for line in order.order_lines:
        product = find_product(line.product_id)
        for usage in product.materials:
            material = find_material(usage.material_id)
            quantity_used = usage.quantity * line.quantity
            material.stock_quantity -= quantity_used
            save_material_sql(material)
            upsert_document("materials", material, material.id)

            movement = StockMovement(
                id=next_id(stock_movements),
                material_id=material.id,
                quantity_change=-quantity_used,
                movement_type="production",
                reference_type="order",
                reference_id=order.id,
                batch_id=getattr(material, "batch_id", None),
                expiry_date=getattr(material, "expiry_date", None),
                user_id=current_user.id,
                note=f"Làm {product.name} cho order #{order.id}",
                created_at=datetime.utcnow(),
            )
            stock_movements.append(movement)
            upsert_document("stock_movements", movement)
            with Session(engine) as session:
                session.add(stock_movement_to_table(movement))
                session.commit()


def restock_for_order(order: Order, current_user: User):
    productions = stock_movements_for_order(order.id)
    if not productions:
        return
    for mv in productions:
        material = find_material(mv.material_id)
        material.stock_quantity += -mv.quantity_change  # reverse deduction
        save_material_sql(material)
        upsert_document("materials", material, material.id)

        reversal = StockMovement(
            id=next_id(stock_movements),
            material_id=material.id,
            quantity_change=-mv.quantity_change,
            movement_type="adjustment",
            reference_type="order",
            reference_id=order.id,
            user_id=current_user.id,
            note=f"Hoàn kho do huỷ order #{order.id}",
            created_at=datetime.utcnow(),
        )
        stock_movements.append(reversal)
        upsert_document("stock_movements", reversal)
        with Session(engine) as session:
            session.add(stock_movement_to_table(reversal))
            session.commit()


# --- Marketplace Integration Helpers ----------------------------------------
async def sync_shopee_orders(settings: Settings, date_from: date, date_to: date) -> Dict:
    """
    Sync orders from Shopee API
    Note: This is a placeholder. Real implementation needs:
    1. Install shopee-open-api-v2 or requests
    2. Generate auth signature with HMAC-SHA256
    3. Handle pagination for large result sets
    """
    if not all([settings.shopee_partner_id, settings.shopee_partner_key, settings.shopee_shop_id]):
        raise HTTPException(status_code=400, detail="Shopee credentials not configured")

    # Placeholder response structure
    return {
        "orders": [],
        "total": 0,
        "message": "Shopee API integration placeholder. Need to implement with real API calls."
    }


async def sync_lazada_orders(settings: Settings, date_from: date, date_to: date) -> Dict:
    """
    Sync orders from Lazada API
    Note: This is a placeholder. Real implementation needs:
    1. Install lazop-sdk or requests
    2. Generate auth signature
    3. Handle order status mapping
    """
    if not all([settings.lazada_app_key, settings.lazada_app_secret, settings.lazada_access_token]):
        raise HTTPException(status_code=400, detail="Lazada credentials not configured")

    # Placeholder response structure
    return {
        "orders": [],
        "total": 0,
        "message": "Lazada API integration placeholder. Need to implement with real API calls."
    }


def marketplace_order_to_internal(mp_order: MarketplaceOrder, current_user: User) -> OrderCreate:
    """Convert marketplace order to internal order format"""
    # Map marketplace status to internal status
    status_map = {
        "UNPAID": "pending",
        "READY_TO_SHIP": "confirmed",
        "PROCESSED": "processing",
        "SHIPPED": "shipped",
        "COMPLETED": "completed",
        "CANCELLED": "cancelled"
    }

    # Extract order lines from marketplace items
    order_lines = []
    for item in mp_order.items:
        # Try to match by SKU or product name
        product = None
        if "sku" in item and item["sku"]:
            # Search products by name/code (simplified)
            pass  # TODO: Implement SKU matching

        # For now, create order line with placeholder product_id = 1
        order_lines.append(OrderLine(
            product_id=item.get("product_id", 1),
            quantity=item.get("quantity", 1),
            unit_price=item.get("price", 0)
        ))

    return OrderCreate(
        date=datetime.fromtimestamp(mp_order.create_time).date(),
        channel=mp_order.marketplace.capitalize(),
        order_lines=order_lines,
        shipping_fee=0,  # Extract from marketplace data if available
        discount=0,
        status=status_map.get(mp_order.order_status, "pending"),
        payment_status="paid" if mp_order.order_status in ["READY_TO_SHIP", "PROCESSED", "SHIPPED", "COMPLETED"] else "unpaid",
        shipping_carrier=mp_order.shipping_carrier,
        tracking_number=mp_order.tracking_number,
        note=f"Synced from {mp_order.marketplace} - Order SN: {mp_order.order_sn}"
    )


async def get_current_user(token: str = Depends(oauth2_scheme)) -> User:
    from fastapi import HTTPException
    from jwt import PyJWTError, decode
    if not token:
        raise HTTPException(status_code=401, detail="Missing token")
    try:
        payload = decode(token, JWT_SECRET, algorithms=[JWT_ALGO])
        user_id = payload.get("sub")
        if not user_id:
            raise HTTPException(status_code=401, detail="Invalid token")
        # Find user by id
        with Session(engine) as session:
            stmt = select(UserTable).where(UserTable.id == int(user_id))
            row = session.exec(stmt).first()
            if row:
                return User(
                    id=row.id,
                    name=row.name,
                    email=row.email,
                    password_hash=row.password_hash,
                    role=row.role,
                    is_owner=row.is_owner,
                    created_at=row.created_at,
                    last_login_at=row.last_login_at,
                )
        raise HTTPException(status_code=401, detail="User not found")
    except PyJWTError:
        raise HTTPException(status_code=401, detail="Invalid token")

# --- AuditLogTable model (define above API usage) ---

class AuditLogTable(SQLModel, table=True):
    __tablename__ = "auditlogtable"
    id: Optional[int] = SQLField(default=None, primary_key=True)
    user_id: int
    user_name: Optional[str] = None
    action: str
    table_name: Optional[str] = None
    record_id: Optional[int] = None
    before_data: Optional[str] = None
    after_data: Optional[str] = None
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    timestamp: datetime = SQLField(default_factory=datetime.utcnow)

# --- Audit Log API ----------------------------------------------------------

@app.get("/audit-logs")
async def get_audit_logs(
    page: int = 1,
    page_size: int = 50,
    current_user: User = Depends(get_current_user)
):
    """Get audit logs with pagination"""
    try:
        with Session(engine) as session:
            query = select(AuditLogTable).order_by(AuditLogTable.timestamp.desc())
            result = session.exec(select(AuditLogTable)).all()
            total = len(result)
            query = query.offset((page - 1) * page_size).limit(page_size)
            logs = session.exec(query).all()
            items = [
                {
                    "id": log.id,
                    "user_id": log.user_id,
                    "user_name": log.user_name,
                    "action": log.action,
                    "table_name": log.table_name,
                    "record_id": log.record_id,
                    "before_data": log.before_data,
                    "after_data": log.after_data,
                    "ip_address": log.ip_address,
                    "user_agent": log.user_agent,
                    "timestamp": log.timestamp.isoformat() if log.timestamp else None
                }
                for log in logs
            ]
            total_pages = (total + page_size - 1) // page_size
            return JSONResponse({
                "items": items,
                "total": total,
                "page": page,
                "page_size": page_size,
                "total_pages": total_pages
            })
            with Session(engine) as session:
                query = select(AuditLogTable).order_by(AuditLogTable.timestamp.desc())
                total = session.exec(select(AuditLogTable)).count()
                query = query.offset((page - 1) * page_size).limit(page_size)
                logs = session.exec(query).all()
                items = [
                    {
                        "id": log.id,
                        "user_id": log.user_id,
                        "user_name": log.user_name,
                        "action": log.action,
                        "table_name": log.table_name,
                        "record_id": log.record_id,
                        "before_data": log.before_data,
                        "after_data": log.after_data,
                        "ip_address": log.ip_address,
                        "user_agent": log.user_agent,
                        "timestamp": log.timestamp.isoformat() if log.timestamp else None
                    }
                    for log in logs
                ]
                total_pages = (total + page_size - 1) // page_size
                return JSONResponse({
                    "items": items,
                    "total": total,
                    "page": page,
                    "page_size": page_size,
                    "total_pages": total_pages
                })
    except jwt.PyJWTError:
        raise credentials_exception
    # Check SQL DB first
    with Session(engine) as session:
        row = session.get(UserTable, user_id)
        if row:
            return User(
                id=row.id,
                name=row.name,
                email=row.email,
                password_hash=row.password_hash,
                role=row.role,
                is_owner=row.is_owner,
                created_at=row.created_at,
                last_login_at=row.last_login_at,
            )
    for user in users:
        if user.id == user_id:
            return user
    raise credentials_exception


async def get_current_user_optional(
    authorization: Optional[str] = Header(None), token: Optional[str] = Depends(oauth2_scheme)
) -> Optional[User]:
    raw_token = token
    if not raw_token and not authorization:
        return None
    if not raw_token:
        scheme, raw_token = get_authorization_scheme_param(authorization)
        if scheme.lower() != "bearer" or not raw_token:
            return None
    try:
        return await get_current_user(raw_token)
    except HTTPException:
        return None


def require_admin(user: User):
    if user.role != "ADMIN":
        raise HTTPException(status_code=403, detail="Chỉ ADMIN mới được thao tác này")


def find_material(material_id: int) -> Material:
    for material in materials:
        if material.id == material_id:
            return material
    raise HTTPException(status_code=404, detail=f"Material {material_id} không tồn tại")


def find_product(product_id: int) -> Product:
    for product in products:
        if product.id == product_id:
            return product
    raise HTTPException(status_code=404, detail=f"Product {product_id} không tồn tại")


def find_issue(issue_id: int) -> Issue:
    for issue in issues:
        if issue.id == issue_id:
            return issue
    raise HTTPException(status_code=404, detail=f"Issue {issue_id} không tồn tại")


def find_supplier(supplier_id: int) -> Supplier:
    for supplier in suppliers:
        if supplier.id == supplier_id:
            return supplier
    raise HTTPException(status_code=404, detail=f"Supplier {supplier_id} không tồn tại")


async def create_audit_log(
    user: User,
    action: str,
    table_name: str,
    record_id: int,
    before_data: Optional[dict],
    after_data: Optional[dict],
    request: Request
):
    """Create audit log entry for tracking changes"""
    try:
        audit_entry = AuditLogTable(
            id=next_id([]),  # Generate new ID
            user_id=user.id,
            user_name=user.name or user.email,
            action=action,
            table_name=table_name,
            record_id=record_id,
            before_data=json.dumps(before_data) if before_data else None,
            after_data=json.dumps(after_data) if after_data else None,
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent", None),
            timestamp=datetime.utcnow()
        )

        # Save to database
        with Session(engine) as session:
            session.add(audit_entry)
            session.commit()

        # Log to console
        print(f"[AUDIT] {action} {table_name} #{record_id} by {user.name} ({user.id})")
    except Exception as e:
        # Don't fail the main operation if audit logging fails
        print(f"[AUDIT ERROR] Failed to create audit log: {e}")


def compute_po_total(lines: List[PurchaseOrderLine]) -> float:
    return sum(line.unit_price * line.quantity for line in lines)


def receive_purchase_order(po: PurchaseOrder, current_user: User):
    if po.received_at:
        return
    po.status = "received"
    po.received_at = datetime.utcnow()
    for line in po.lines:
        material = find_material(line.material_id)
        material.stock_quantity += line.quantity
        save_material_sql(material)
        upsert_document("materials", material, material.id)

        movement = StockMovement(
            id=next_id(stock_movements),
            material_id=material.id,
            quantity_change=line.quantity,
            movement_type="purchase",
            reference_type="purchase_order",
            reference_id=po.id,
            batch_id=getattr(line, "batch_id", None),
            expiry_date=getattr(line, "expiry_date", None),
            user_id=current_user.id,
            note=f"Nhập kho từ PO #{po.id}",
            created_at=datetime.utcnow(),
        )
        stock_movements.append(movement)
        upsert_document("stock_movements", movement)
        with Session(engine) as session:
            session.add(stock_movement_to_table(movement))
            session.commit()


def find_order(order_id: int) -> Order:
    for order in orders:
        if order.id == order_id:
            return order
    raise HTTPException(status_code=404, detail=f"Order {order_id} không tồn tại")


def find_customer(customer_id: int) -> Customer:
    for cust in customers:
        if cust.id == customer_id:
            return cust
    raise HTTPException(status_code=404, detail=f"Customer {customer_id} không tồn tại")


def compute_customer_metrics():
    for cust in customers:
        cust.total_orders = 0
        cust.total_spent = 0
        cust.last_order_date = None
        cust.first_order_date = None
    for order in orders:
        if not order.customer_id:
            continue
        totals = compute_order_totals(order)
        cust = next((c for c in customers if c.id == order.customer_id), None)
        if not cust:
            continue
        cust.total_orders += 1
        cust.total_spent += totals["revenue"]
        if cust.last_order_date is None or order.date > cust.last_order_date:
            cust.last_order_date = order.date
        if cust.first_order_date is None or order.date < cust.first_order_date:
            cust.first_order_date = order.date
    with Session(engine) as session:
        for cust in customers:
            row = session.get(CustomerTable, cust.id)
            if row:
                row.total_orders = cust.total_orders
                row.total_spent = cust.total_spent
                row.last_order_date = cust.last_order_date
                row.first_order_date = cust.first_order_date
                session.add(row)
        session.commit()


def compute_product_cost(product: Product) -> Dict[str, float]:
    material_cost = 0.0
    for usage in product.materials:
        material = find_material(usage.material_id)
        material_cost += material.unit_price * usage.quantity

    labor_cost = (product.time_minutes / 60) * settings.hourly_rate
    packaging_cost = getattr(product, "packaging_cost", 0) or 0
    marketing_cost = getattr(product, "marketing_cost", 0) or 0
    platform_fee_percent = getattr(product, "platform_fee_percent", 0) or 0
    platform_fee_amount = product.base_price * platform_fee_percent / 100
    cost_breakdown = getattr(product, "cost_breakdown", None) or {}
    packaging_cost += cost_breakdown.get("packaging", 0) if isinstance(cost_breakdown, dict) else 0
    marketing_cost += cost_breakdown.get("marketing", 0) if isinstance(cost_breakdown, dict) else 0
    other_cost = cost_breakdown.get("other", 0) if isinstance(cost_breakdown, dict) else 0
    platform_fee_amount = product.base_price * platform_fee_percent / 100
    profit_per_unit = product.base_price - material_cost - labor_cost - packaging_cost - marketing_cost - platform_fee_amount - other_cost
    profit_margin = profit_per_unit / product.base_price if product.base_price else 0

    # Feasibility breakdown 0-100
    time_score = max(0, 1 - (product.time_minutes / 240)) * 100  # prefer <4h
    difficulty_score = max(0, (5 - product.difficulty) / 5) * 100
    priority_score = (getattr(product, "priority", 1) or 1) / 5 * 100
    demand_score = (getattr(product, "demand_score", 0) or 0)

    # Trend score from demand signals (simple delta views)
    trend_score = 50
    signals = sorted([d for d in demand_signals if d.product_id == product.id], key=lambda x: x.week_of)
    if len(signals) >= 2:
        latest, prev = signals[-1], signals[-2]
        delta = latest.views - prev.views
        base = prev.views or 1
        trend_score = max(0, min(100, 50 + (delta / base) * 50))

    open_issues = [i for i in issues if i.product_id == product.id and i.status != "resolved"]
    issue_health = max(0, 100 - len(open_issues) * 20)

    profit_per_hour = 0
    if product.time_minutes > 0:
        profit_per_hour = (profit_per_unit / product.time_minutes) * 60
    profit_score = max(0, min(100, profit_per_hour / 100000 * 100))

    feasibility_score = (
        demand_score * 0.4
        + profit_score * 0.3
        + trend_score * 0.2
        + issue_health * 0.1
    )
    feasibility_score = max(0, min(100, feasibility_score))

    # Capacity: min stock / required qty, ignoring non-material items
    capacities = []
    for usage in product.materials:
        material = find_material(usage.material_id)
        if usage.quantity > 0:
            capacities.append(material.stock_quantity // usage.quantity)
    max_units = int(min(capacities)) if capacities else None
    shortage_materials = []
    for usage in product.materials:
        material = find_material(usage.material_id)
        if material and material.stock_quantity < usage.quantity:
            shortage_materials.append(
                {
                    "material_id": usage.material_id,
                    "need": usage.quantity,
                    "have": material.stock_quantity,
                    "code": material.code,
                }
            )

    return {
        "material_cost": round(material_cost, 2),
        "labor_cost": round(labor_cost, 2),
        "packaging_cost": round(packaging_cost, 2),
        "marketing_cost": round(marketing_cost, 2),
        "other_cost": round(other_cost, 2),
        "platform_fee_amount": round(platform_fee_amount, 2),
        "profit_per_unit": round(profit_per_unit, 2),
        "profit_margin": round(profit_margin, 4),
        "profit_per_hour": round(profit_per_hour, 2),
        "feasibility_score": round(feasibility_score, 4),
        "feasibility_breakdown": {
          "demand": round(demand_score, 2),
          "profit_hour": round(profit_score, 2),
          "trend": round(trend_score, 2),
          "issue_health": round(issue_health, 2),
        },
        "max_units_from_stock": max_units,
        "shortage_materials": shortage_materials,
    }


# Cache để tránh tính lại nhiều lần cho cùng product
_product_cost_cache: Dict[int, Dict[str, float]] = {}

def get_product_cost_cached(product: Product) -> Dict[str, float]:
    """Cached version of compute_product_cost for better performance"""
    if product.id not in _product_cost_cache:
        _product_cost_cache[product.id] = compute_product_cost(product)
    return _product_cost_cache[product.id]

def clear_product_cost_cache(product_id: Optional[int] = None):
    """Clear cache khi có thay đổi product/material/settings"""
    global _product_cost_cache
    if product_id is not None:
        _product_cost_cache.pop(product_id, None)
    else:
        _product_cost_cache.clear()


def compute_order_totals(order: Order) -> Dict[str, float]:
    gross = sum(line.unit_price * line.quantity for line in order.order_lines)
    discount = order.discount
    # re-apply promo if còn active
    if getattr(order, "promo_code", None):
        promo = next((p for p in promo_codes if p.code.lower() == order.promo_code.lower() and p.is_active), None)
        if promo:
            promo_discount = compute_promo_discount(promo, order.order_lines)
            discount = max(discount, promo_discount)
    returns_amount = sum(
        r.refund_amount or r.amount
        for r in order_returns
        if r.order_id == order.id and r.status in {"approved", "processed"}
    )
    revenue = max(0, gross - discount - returns_amount)
    cost = order.shipping_fee
    for line in order.order_lines:
        product = find_product(line.product_id)
        product_cost = compute_product_cost(product)
        cost += (
            product_cost["material_cost"]
            + product_cost["labor_cost"]
            + product_cost.get("packaging_cost", 0)
            + product_cost.get("marketing_cost", 0)
            + product_cost.get("platform_fee_amount", 0)
        ) * line.quantity
    profit = revenue - cost
    return {
        "revenue": round(revenue, 2),
        "cost": round(cost, 2),
        "profit": round(profit, 2),
        "computed_discount": round(discount, 2),
    }


def adjust_payment_status_for_refund(order: Order):
    returns_amount = sum(r.refund_amount or r.amount for r in order_returns if r.order_id == order.id and r.status in {"approved", "processed"})
    totals = compute_order_totals(order)
    if returns_amount >= totals["revenue"]:
        order.payment_status = "refunded"
    elif returns_amount > 0:
        order.payment_status = "partial"


def get_low_stock_alerts() -> List[dict]:
    threshold = settings.low_stock_threshold if settings else 1.0
    alerts = []
    for m in materials:
        if m.stock_quantity <= (m.low_threshold or threshold):
            alerts.append(
                {
                    "material_id": m.id,
                    "code": m.code,
                    "name": m.name,
                    "stock_quantity": m.stock_quantity,
                    "unit": m.unit,
                    "low_threshold": m.low_threshold,
                }
            )
    return alerts


def send_notifications(payload: dict):
    recipients = list(settings.notification_emails or [])
    if settings.backup_email:
        recipients.append(settings.backup_email)
    if not recipients or not settings.smtp_host:
        print("NOTIFY (log only):", json.dumps(payload, default=str))
        return
    try:
        msg = EmailMessage()
        msg["Subject"] = "Handmade OS - Alert"
        msg["From"] = settings.smtp_user or "noreply@example.com"
        msg["To"] = ", ".join(recipients)
        msg.set_content(json.dumps(payload, default=str, indent=2, ensure_ascii=False))
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port or 25, timeout=5) as server:
            if settings.smtp_use_tls:
                server.starttls()
            if settings.smtp_user and settings.smtp_password:
                server.login(settings.smtp_user, settings.smtp_password)
            server.send_message(msg)
    except Exception as exc:  # pragma: no cover
        print("NOTIFY send failed, fallback log:", exc, payload)


def get_overdue_orders(days: int = 7) -> List[dict]:
    today = date.today()
    overdue = []
    for o in orders:
        if o.status in {"pending", "confirmed", "processing"} and (today - o.date).days >= days:
            overdue.append({"order_id": o.id, "date": o.date, "status": o.status, "customer_id": o.customer_id})
    return overdue


# --- Settings endpoints -----------------------------------------------------
@app.get("/settings", response_model=Settings)
async def get_settings(current_user: Optional[User] = Depends(get_current_user_optional)):
    # Cho phép xem public; nếu cần có thể dùng current_user để tùy chỉnh sau này
    return settings


@app.patch("/settings", response_model=Settings)
async def update_settings(updated: Settings, current_user: User = Depends(get_current_user)):
    require_admin(current_user)
    global settings
    # merge để giữ nguyên nếu client gửi thiếu field
    merged = Settings.model_validate({**settings.model_dump(), **updated.model_dump()})
    settings = merged
    upsert_document("settings", merged)
    with Session(engine) as session:
        session.merge(
            SettingsTable(
                id=1,
                hourly_rate=settings.hourly_rate,
                default_profit_margin=settings.default_profit_margin,
                low_stock_threshold=settings.low_stock_threshold,
                profit_share_mode=settings.profit_share_mode,
                share_user_a=settings.share_user_a,
                share_user_b=settings.share_user_b,
                business_name=settings.business_name,
                business_address=settings.business_address,
                business_logo=settings.business_logo,
                capacity_hours_per_month=settings.capacity_hours_per_month,
                tax_rate=settings.tax_rate,
                notification_emails=json.dumps(settings.notification_emails or []),
                notify_low_stock=settings.notify_low_stock,
                notify_forecast_low=settings.notify_forecast_low,
                backup_email=settings.backup_email,
                smtp_host=settings.smtp_host,
                smtp_port=settings.smtp_port,
                smtp_user=settings.smtp_user,
                smtp_password=settings.smtp_password,
                smtp_use_tls=settings.smtp_use_tls,
            )
        )
        session.commit()
    log_activity(current_user.id, "settings", None, "update", changes=merged.model_dump())
    return settings


# --- Product endpoints ------------------------------------------------------
@app.get("/products")
async def list_products(
    page: int = 1,
    page_size: int = 50,
    search: Optional[str] = None,
    category_id: Optional[int] = None,
    lifecycle_status: Optional[str] = None,
    current_user: User = Depends(get_current_user)
):
    # Filter products
    filtered = products
    if search:
        search_lower = search.lower()
        filtered = [p for p in filtered if search_lower in p.name.lower() or search_lower in (p.notes or "").lower()]
    if category_id:
        filtered = [p for p in filtered if category_id in p.categories]
    if lifecycle_status:
        filtered = [p for p in filtered if p.lifecycle_status == lifecycle_status]

    # Calculate pagination
    total = len(filtered)
    total_pages = (total + page_size - 1) // page_size
    start = (page - 1) * page_size
    end = start + page_size
    page_items = filtered[start:end]

    # Compute metrics for page items only
    computed = []
    for product in page_items:
        metrics = get_product_cost_cached(product)
        product.demand_score = metrics.get("demand_score", product.demand_score)
        metrics_feas = metrics.pop("feasibility_score", None)
        product.feasibility_score = metrics_feas or product.feasibility_score
        base_dump = product.model_dump(exclude={"feasibility_score", "demand_score"})
        for k in ["packaging_cost", "marketing_cost", "platform_fee_percent"]:
            metrics.pop(k, None)
        computed.append(
            ProductComputed(
                **base_dump,
                **metrics,
                demand_score=product.demand_score,
                feasibility_score=product.feasibility_score,
            )
        )

    return {
        "items": computed,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages
    }


@app.get("/products/summary")
async def products_summary(
    lifecycle_status: Optional[str] = None,
    category_id: Optional[int] = None,
    current_user: User = Depends(get_current_user)
):
    """
    Optimized endpoint for Products page - returns all necessary data in 1 call
    Replaces multiple API calls: /products, /materials, /seasons, /categories, /users
    """
    # Filter products
    filtered = products
    if lifecycle_status:
        filtered = [p for p in filtered if p.lifecycle_status == lifecycle_status]
    if category_id:
        filtered = [p for p in filtered if category_id in p.categories]

    # Compute metrics for all products
    computed = []
    for product in filtered:
        metrics = get_product_cost_cached(product)
        product.demand_score = metrics.get("demand_score", product.demand_score)
        metrics_feas = metrics.pop("feasibility_score", None)
        product.feasibility_score = metrics_feas or product.feasibility_score
        base_dump = product.model_dump(exclude={"feasibility_score", "demand_score"})
        for k in ["packaging_cost", "marketing_cost", "platform_fee_percent"]:
            metrics.pop(k, None)
        computed.append(
            ProductComputed(
                **base_dump,
                **metrics,
                demand_score=product.demand_score,
                feasibility_score=product.feasibility_score,
            )
        )

    # Statistics by lifecycle
    by_lifecycle = {}
    for p in products:
        status = p.lifecycle_status
        by_lifecycle[status] = by_lifecycle.get(status, 0) + 1

    # Calculate average feasibility
    feasibility_scores = [p.feasibility_score for p in computed if p.feasibility_score]
    avg_feasibility = sum(feasibility_scores) / len(feasibility_scores) if feasibility_scores else 0

    # Count low stock products (products that can't be made due to material shortage)
    low_stock_products = []
    for p in computed:
        if p.max_units_from_stock is not None and p.max_units_from_stock <= 0:
            low_stock_products.append(p.id)

    # Get unique users for assignment
    user_ids = set()
    for p in products:
        if p.created_by:
            user_ids.add(p.created_by)
        if p.updated_by:
            user_ids.add(p.updated_by)
    users_list = [u for u in users if u.id in user_ids] if user_ids else users[:10]

    return {
        "products": computed,
        "materials": materials,
        "seasons": seasons,
        "categories": categories,
        "users": users_list,
        "statistics": {
            "total": len(products),
            "by_lifecycle": by_lifecycle,
            "avg_feasibility": round(avg_feasibility, 1),
            "low_stock_count": len(low_stock_products),
            "low_stock_product_ids": low_stock_products
        }
    }


@app.post("/products", response_model=ProductComputed)
@limiter.limit("30/minute")  # Giới hạn tạo sản phẩm
async def create_product(request: Request, payload: ProductBase, current_user: User = Depends(get_current_user)):
    require_admin(current_user)
    new_product = Product(id=next_id(products), **payload.model_dump(), created_by=current_user.id)
    products.append(new_product)
    upsert_document("products", new_product)
    save_product_sql(new_product)
    lifecycle_event = LifecycleEvent(
        id=next_id(lifecycle_events),
        product_id=new_product.id,
        status=new_product.lifecycle_status,
        changed_by=current_user.id,
        changed_at=datetime.utcnow(),
    )
    lifecycle_events.append(lifecycle_event)
    save_lifecycle_sql(lifecycle_event)
    clear_product_cost_cache()  # Clear cache after creating product
    metrics = compute_product_cost(new_product)
    new_product.demand_score = metrics.get("demand_score", new_product.demand_score)
    new_product.feasibility_score = metrics.get("feasibility_score", new_product.feasibility_score)
    log_activity(current_user.id, "product", new_product.id, "create", changes=payload.model_dump())
    # Remove fields that are already in new_product to avoid duplicate keyword arguments
    for k in ["packaging_cost", "marketing_cost", "platform_fee_percent", "demand_score", "feasibility_score"]:
        metrics.pop(k, None)
    return ProductComputed(**new_product.model_dump(), **metrics)


@app.put("/products/{product_id}", response_model=ProductComputed)
async def update_product(product_id: int, payload: ProductBase, current_user: User = Depends(get_current_user)):
    require_admin(current_user)
    product = find_product(product_id)
    if payload.base_price != product.base_price:
        price_change = PriceChange(
            id=next_id(price_changes),
            product_id=product_id,
            old_price=product.base_price,
            new_price=payload.base_price,
            changed_by=current_user.id,
            changed_at=datetime.utcnow(),
        )
        price_changes.append(price_change)
        save_price_change_sql(price_change)
    if payload.lifecycle_status != product.lifecycle_status:
        lifecycle_event = LifecycleEvent(
            id=next_id(lifecycle_events),
            product_id=product_id,
            status=payload.lifecycle_status,
            note=None,
            changed_by=current_user.id,
            changed_at=datetime.utcnow(),
        )
        lifecycle_events.append(lifecycle_event)
        save_lifecycle_sql(lifecycle_event)
    payload_data = payload.model_dump(exclude={"created_by", "updated_by"})
    for field in payload_data.keys():
        setattr(product, field, getattr(payload, field))
    product.updated_by = current_user.id
    upsert_document("products", product, product_id)
    save_product_sql(product)
    clear_product_cost_cache(product_id)  # Clear cache for updated product
    metrics = compute_product_cost(product)
    product.demand_score = metrics.get("demand_score", product.demand_score)
    product.feasibility_score = metrics.get("feasibility_score", product.feasibility_score)
    log_activity(current_user.id, "product", product_id, "update", changes=payload.model_dump())
    for k in ["packaging_cost", "marketing_cost", "platform_fee_percent"]:
        metrics.pop(k, None)
    return ProductComputed(**product.model_dump(), **metrics)


# --- Bulk Import Endpoints --------------------------------------------------
class BulkImportRequest(BaseModel):
    items: List[dict]


class BulkImportResponse(BaseModel):
    imported: int
    failed: int
    errors: List[str] = []


@app.post("/products/import", response_model=BulkImportResponse)
@limiter.limit("10/minute")  # Limit bulk imports
async def import_products(request: Request, payload: BulkImportRequest, current_user: User = Depends(get_current_user)):
    """Bulk import products from Excel/CSV"""
    require_admin(current_user)
    imported = 0
    failed = 0
    errors = []

    for idx, item in enumerate(payload.items):
        try:
            # Validate required fields
            if not item.get("name"):
                errors.append(f"Row {idx + 1}: Missing name")
                failed += 1
                continue

            # Create product with defaults
            product_data = {
                "name": item["name"],
                "base_price": float(item.get("base_price", 0)),
                "difficulty": int(item.get("difficulty", 3)),
                "time_minutes": int(item.get("time_minutes", 60)),
                "notes": item.get("notes"),
                "tags": item.get("tags", "").split(",") if isinstance(item.get("tags"), str) else item.get("tags", []),
                "materials": [],
                "priority": 1,
                "role": "core",
                "lifecycle_status": "idea",
                "packaging_cost": 0,
                "marketing_cost": 0,
                "platform_fee_percent": 0,
            }

            new_product = Product(id=next_id(products), **product_data, created_by=current_user.id)
            products.append(new_product)
            upsert_document("products", new_product)
            save_product_sql(new_product)
            imported += 1
        except Exception as e:
            errors.append(f"Row {idx + 1}: {str(e)}")
            failed += 1

    log_activity(current_user.id, "product", None, "bulk_import", changes={"imported": imported, "failed": failed})
    return BulkImportResponse(imported=imported, failed=failed, errors=errors[:10])


@app.post("/materials/import", response_model=BulkImportResponse)
@limiter.limit("10/minute")
async def import_materials(request: Request, payload: BulkImportRequest, current_user: User = Depends(get_current_user)):
    """Bulk import materials from Excel/CSV"""
    require_admin(current_user)
    imported = 0
    failed = 0
    errors = []

    for idx, item in enumerate(payload.items):
        try:
            required = ["code", "name", "type", "unit", "unit_price", "stock_quantity"]
            missing = [f for f in required if not item.get(f)]
            if missing:
                errors.append(f"Row {idx + 1}: Missing {', '.join(missing)}")
                failed += 1
                continue

            # Check for duplicate code
            if any(m.code == item["code"] for m in materials):
                errors.append(f"Row {idx + 1}: Code {item['code']} already exists")
                failed += 1
                continue

            material_data = {
                "code": item["code"],
                "name": item["name"],
                "type": item["type"],
                "unit": item["unit"],
                "unit_price": float(item["unit_price"]),
                "stock_quantity": float(item["stock_quantity"]),
                "low_threshold": float(item.get("low_threshold", 1.0)),
                "note": item.get("note"),
            }

            new_material = Material(id=next_id(materials), **material_data, created_by=current_user.id)
            materials.append(new_material)
            upsert_document("materials", new_material)
            save_material_sql(new_material)
            imported += 1
        except Exception as e:
            errors.append(f"Row {idx + 1}: {str(e)}")
            failed += 1

    log_activity(current_user.id, "material", None, "bulk_import", changes={"imported": imported, "failed": failed})
    return BulkImportResponse(imported=imported, failed=failed, errors=errors[:10])


@app.post("/customers/import", response_model=BulkImportResponse)
@limiter.limit("10/minute")
async def import_customers(request: Request, payload: BulkImportRequest, current_user: User = Depends(get_current_user)):
    """Bulk import customers from Excel/CSV"""
    require_admin(current_user)
    imported = 0
    failed = 0
    errors = []

    for idx, item in enumerate(payload.items):
        try:
            if not item.get("name"):
                errors.append(f"Row {idx + 1}: Missing name")
                failed += 1
                continue

            customer_data = {
                "name": item["name"],
                "phone": item.get("phone"),
                "email": item.get("email"),
                "address": item.get("address"),
                "source": item.get("source"),
                "tags": item.get("tags", "").split(",") if isinstance(item.get("tags"), str) else item.get("tags", []),
                "notes": item.get("notes"),
            }

            new_customer = Customer(
                id=next_id(customers),
                **customer_data,
                total_orders=0,
                total_spent=0,
                created_by=current_user.id,
                created_at=datetime.utcnow()
            )
            customers.append(new_customer)
            upsert_document("customers", new_customer)
            with Session(engine) as session:
                session.add(CustomerTable(
                    id=new_customer.id,
                    name=new_customer.name,
                    phone=new_customer.phone,
                    email=new_customer.email,
                    address=new_customer.address,
                    source=new_customer.source,
                    tags=",".join(new_customer.tags) if new_customer.tags else "",
                    total_orders=0,
                    total_spent=0,
                    notes=new_customer.notes,
                    created_by=new_customer.created_by,
                    created_at=new_customer.created_at,
                ))
                session.commit()
            imported += 1
        except Exception as e:
            errors.append(f"Row {idx + 1}: {str(e)}")
            failed += 1

    log_activity(current_user.id, "customer", None, "bulk_import", changes={"imported": imported, "failed": failed})
    return BulkImportResponse(imported=imported, failed=failed, errors=errors[:10])


@app.delete("/products/{product_id}")
async def delete_product(product_id: int, current_user: User = Depends(get_current_user)):
    require_admin(current_user)
    product = find_product(product_id)
    products.remove(product)
    delete_document("products", product_id)
    with Session(engine) as session:
        session.exec(delete(ProductTable).where(ProductTable.id == product_id))
        session.commit()
    clear_product_cost_cache(product_id)  # Clear cache after deleting product
    log_activity(current_user.id, "product", product_id, "delete")
    return {"ok": True}


# --- Material endpoints -----------------------------------------------------
@app.get("/materials")
async def list_materials(
    page: int = 1,
    page_size: int = 100,
    search: Optional[str] = None,
    type: Optional[str] = None,
    low_stock_only: bool = False,
    current_user: User = Depends(get_current_user)
):
    # Filter
    filtered = materials
    if search:
        search_lower = search.lower()
        filtered = [m for m in filtered if search_lower in m.name.lower() or search_lower in m.code.lower()]
    if type:
        filtered = [m for m in filtered if m.type == type]
    if low_stock_only:
        filtered = [m for m in filtered if m.stock_quantity <= m.low_threshold]

    # Pagination
    total = len(filtered)
    total_pages = (total + page_size - 1) // page_size
    start = (page - 1) * page_size
    end = start + page_size

    return {
        "items": filtered[start:end],
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages
    }


@app.get("/inventory/summary")
async def inventory_summary(current_user: User = Depends(get_current_user)):
    """
    Optimized endpoint for Inventory page - returns all necessary data in 1 call
    Replaces: /materials, /products, /suppliers, /purchase-orders
    """
    # Material statistics
    low_stock_count = sum(1 for m in materials if m.stock_quantity <= m.low_threshold)
    total_value = sum(m.stock_quantity * m.unit_price for m in materials)

    # Material types breakdown
    types_breakdown = {}
    for m in materials:
        types_breakdown[m.type] = types_breakdown.get(m.type, 0) + 1

    # Products with max units calculation
    material_map = {m.id: m for m in materials}
    enhanced_products = []
    for p in products:
        if not p.materials:
            max_units = 0
        else:
            min_units = float('inf')
            for usage in p.materials:
                mat = material_map.get(usage.material_id)
                if mat:
                    max_for_mat = (mat.stock_quantity or 0) / (usage.quantity or 1)
                    min_units = min(min_units, max_for_mat)
            max_units = int(min_units) if min_units != float('inf') else 0

        product_dict = p.model_dump()
        product_dict['max_units_from_stock'] = max_units
        enhanced_products.append(product_dict)

    return {
        "materials": materials,
        "products": enhanced_products,
        "suppliers": suppliers,
        "purchase_orders": purchase_orders,
        "statistics": {
            "total_materials": len(materials),
            "low_stock_count": low_stock_count,
            "total_inventory_value": round(total_value, 2),
            "types_breakdown": types_breakdown
        }
    }


@app.post("/materials", response_model=Material)
async def create_material(payload: MaterialCreate, current_user: User = Depends(get_current_user)):
    require_admin(current_user)
    if any(m.code.lower() == payload.code.lower() for m in materials):
        raise HTTPException(status_code=400, detail="Mã nguyên liệu đã tồn tại")
    new_material = Material(id=next_id(materials), **payload.model_dump(), created_by=current_user.id)
    materials.append(new_material)
    upsert_document("materials", new_material)
    save_material_sql(new_material)
    clear_product_cost_cache()  # Material affects product costs
    log_activity(current_user.id, "material", new_material.id, "create", changes=payload.model_dump())
    return new_material


@app.put("/materials/{material_id}", response_model=Material)
async def update_material(material_id: int, payload: Material, request: Request, current_user: User = Depends(get_current_user)):
    require_admin(current_user)
    existing = find_material(material_id)
    old_data = existing.model_dump()
    if payload.id != material_id:
        raise HTTPException(status_code=400, detail="Không được đổi id")
    if any(m.code.lower() == payload.code.lower() and m.id != material_id for m in materials):
        raise HTTPException(status_code=400, detail="Mã nguyên liệu đã tồn tại")
    for field, value in payload.model_dump(exclude={"created_by", "updated_by"}).items():
        setattr(existing, field, value)
    existing.updated_by = current_user.id
    upsert_document("materials", existing, material_id)
    save_material_sql(existing)
    clear_product_cost_cache()  # Material changes affect all products
    log_activity(current_user.id, "material", material_id, "update", changes=payload.model_dump())
    await create_audit_log(current_user, "UPDATE", "materials", material_id, old_data, payload.model_dump(), request)
    return existing


@app.delete("/materials/{material_id}")
async def delete_material(material_id: int, request: Request, current_user: User = Depends(get_current_user)):
    require_admin(current_user)
    material = find_material(material_id)
    old_data = material.model_dump()
    materials.remove(material)
    delete_document("materials", material_id)
    with Session(engine) as session:
        session.exec(delete(MaterialTable).where(MaterialTable.id == material_id))
        session.commit()
    log_activity(current_user.id, "material", material_id, "delete")
    await create_audit_log(current_user, "DELETE", "materials", material_id, old_data, None, request)
    return {"ok": True}


# --- Orders endpoints -------------------------------------------------------
@app.get("/orders/summary")
async def orders_summary(current_user: User = Depends(get_current_user)):
    """Tổng hợp dữ liệu cho trang Orders trong 1 API call"""
    try:
        # Get paginated orders
        orders_with_totals = []
        for o in orders:
            try:
                totals = compute_order_totals(o)
                order_computed = OrderComputed(**o.model_dump(), **totals)
                orders_with_totals.append(order_computed)
            except Exception as e:
                print(f"Error computing order {o.id}: {e}")
                continue

        # Sort by date desc
        orders_with_totals.sort(key=lambda x: x.date, reverse=True)

        # Get products (with pagination data)
        products_data = []
        for p in products:
            try:
                cost_info = get_product_cost_cached(p)
                products_data.append({
                    "id": p.id,
                    "name": p.name,
                    "price": p.price,
                    "profit_per_unit": cost_info.get("profit_per_unit", 0),
                    "feasibility_score": cost_info.get("feasibility_score", 0)
                })
            except Exception as e:
                print(f"Error processing product {p.id}: {e}")
                continue

        # Get customers
        customers_data = []
        for c in customers:
            try:
                customers_data.append({
                    "id": c.id,
                    "name": c.name,
                    "source": getattr(c, 'source', '') or ""
                })
            except Exception as e:
                print(f"Error processing customer {c.id}: {e}")
                continue

        # Get content plans
        content_data = []
        for cp in content_plans:
            try:
                content_data.append({
                    "id": cp.id,
                    "title": cp.title,
                    "platform": getattr(cp, 'platform', '')
                })
            except Exception as e:
                print(f"Error processing content plan {cp.id}: {e}")
                continue

        # Get users
        users_data = []
        for u in users:
            try:
                users_data.append({
                    "id": u.id,
                    "username": u.name,
                    "role": u.role
                })
            except Exception as e:
                print(f"Error processing user {u.id}: {e}")
                continue

        # Get maker report - show all users who have orders with maker_user_id
        maker_report = []

        for user in users:
            try:
                # Find orders made by this user (admin can also be maker)
                user_orders = [o for o in orders_with_totals if getattr(o, 'maker_user_id', None) == user.id]
                if user_orders:
                    total_revenue = sum(getattr(o, 'revenue', 0) for o in user_orders)
                    total_profit = sum(getattr(o, 'profit', 0) for o in user_orders)
                    maker_report.append({
                        "maker_id": user.id,
                        "maker_name": user.name,
                        "orders": len(user_orders),
                        "revenue": total_revenue,
                        "profit": total_profit
                    })
            except Exception as e:
                print(f"Error processing maker report for user {user.id}: {e}")
                continue

        return {
            "orders": orders_with_totals[:100],  # Limit to 100 most recent
            "total_orders": len(orders),
            "products": products_data,
            "customers": customers_data,
            "contents": content_data,
            "users": users_data,
            "maker_report": maker_report
        }
    except Exception as e:
        print(f"Error in orders_summary: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Error generating summary: {str(e)}")


@app.get("/orders")
async def list_orders(
    page: int = 1,
    page_size: int = 50,
    status: Optional[str] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    customer_id: Optional[int] = None,
    current_user: User = Depends(get_current_user)
):
    # Filter orders
    filtered = orders
    if status:
        filtered = [o for o in filtered if o.status == status]
    if start_date:
        filtered = [o for o in filtered if o.date >= start_date]
    if end_date:
        filtered = [o for o in filtered if o.date <= end_date]
    if customer_id:
        filtered = [o for o in filtered if o.customer_id == customer_id]

    # Sort by date descending
    filtered = sorted(filtered, key=lambda x: x.date, reverse=True)

    # Pagination
    total = len(filtered)
    total_pages = (total + page_size - 1) // page_size
    start = (page - 1) * page_size
    end = start + page_size
    page_items = filtered[start:end]

    # Compute totals for page items only
    enriched = []
    for order in page_items:
        totals = compute_order_totals(order)
        enriched.append(OrderComputed(**order.model_dump(), **totals))

    return {
        "items": enriched,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages
    }


@app.post("/orders", response_model=OrderComputed)
@limiter.limit("30/minute")  # Giới hạn tạo đơn hàng
async def create_order(request: Request, payload: OrderCreate, current_user: User = Depends(get_current_user)):
    require_admin(current_user)
    validate_order_payload(payload)
    apply_promo(payload)

    # Validate stock availability if order is confirmed
    if payload.status in ["confirmed", "processing"]:
        stock_errors = []
        for line in payload.order_lines:
            product = find_product(line.product_id)
            for usage in product.materials:
                material = find_material(usage.material_id)
                needed = usage.quantity * line.quantity
                if material.stock_quantity < needed:
                    stock_errors.append(
                        f"Thiếu {material.code}: cần {needed} {material.unit}, chỉ còn {material.stock_quantity}"
                    )

        if stock_errors:
            raise HTTPException(
                status_code=400,
                detail=f"Không đủ nguyên liệu: {'; '.join(stock_errors)}"
            )

    # Create order
    new_order = Order(id=next_id(orders), **payload.model_dump(), created_by=current_user.id)
    orders.append(new_order)

    # Auto-deduct stock if order is confirmed
    if new_order.status in ["confirmed", "processing"]:
        deduct_stock_for_order(new_order, current_user)

    # Update customer stats if customer_id provided
    if new_order.customer_id:
        for customer in customers:
            if customer.id == new_order.customer_id:
                customer.total_orders += 1
                totals = compute_order_totals(new_order)
                customer.total_spent += totals["revenue"]
                customer.last_order_date = new_order.date
                upsert_document("customers", customer, customer.id)
                with Session(engine) as session:
                    row = session.get(CustomerTable, customer.id)
                    if row:
                        row.total_orders = customer.total_orders
                        row.total_spent = customer.total_spent
                        row.last_order_date = customer.last_order_date
                        session.add(row)
                        session.commit()
                break

    upsert_document("orders", new_order)
    save_order_sql(new_order)
    totals = compute_order_totals(new_order)
    log_activity(current_user.id, "order", new_order.id, "create", changes=payload.model_dump())
    return OrderComputed(**new_order.model_dump(), **totals)


@app.put("/orders/{order_id}", response_model=OrderComputed)
async def update_order(order_id: int, payload: Order, current_user: User = Depends(get_current_user)):
    require_admin(current_user)
    validate_order_payload(payload)
    apply_promo(payload)
    if payload.id != order_id:
        raise HTTPException(status_code=400, detail="Không được đổi id")
    for idx, order in enumerate(orders):
        if order.id == order_id:
            previous_status = order.status
            payload.created_by = order.created_by or payload.created_by
            payload.updated_by = current_user.id
            orders[idx] = payload
            upsert_document("orders", payload, order_id)
            save_order_sql(payload)

            # Nếu chuyển từ trạng thái chưa trừ kho sang confirmed/processing thì trừ kho
            if payload.status in ["confirmed", "processing"] and previous_status not in ["confirmed", "processing"]:
                # kiểm tra tồn đủ
                stock_errors = []
                for line in payload.order_lines:
                    product = find_product(line.product_id)
                    for usage in product.materials:
                        material = find_material(usage.material_id)
                        needed = usage.quantity * line.quantity
                        if material.stock_quantity < needed:
                            stock_errors.append(
                                f"Thiếu {material.code}: cần {needed} {material.unit}, chỉ còn {material.stock_quantity}"
                            )
                if stock_errors:
                    raise HTTPException(status_code=400, detail=f"Không đủ nguyên liệu: {'; '.join(stock_errors)}")
                deduct_stock_for_order(payload, current_user)

            # Nếu huỷ đơn và đã trừ kho thì hoàn kho
            if payload.status == "cancelled" and previous_status in ["confirmed", "processing", "completed", "shipped", "delivered"]:
                restock_for_order(payload, current_user)

            totals = compute_order_totals(payload)
            log_activity(current_user.id, "order", order_id, "update", changes=payload.model_dump())
            return OrderComputed(**payload.model_dump(), **totals)
    raise HTTPException(status_code=404, detail="Order không tồn tại")


@app.post("/orders/{order_id}/tracking", response_model=OrderComputed)
async def add_tracking_update(order_id: int, payload: ShippingUpdatePayload, current_user: User = Depends(get_current_user)):
    require_admin(current_user)
    order = find_order(order_id)
    if payload.status and payload.status not in ORDER_STATUS_ALLOWED:
        raise HTTPException(status_code=400, detail="Trạng thái vận chuyển không hợp lệ")

    # append shipping update
    if payload.status or payload.note:
        order.shipping_updates = list(order.shipping_updates or [])
        order.shipping_updates.append(ShippingUpdate(status=payload.status, note=payload.note, timestamp=datetime.utcnow()))

    if payload.tracking_number:
        order.tracking_number = payload.tracking_number
    if payload.shipping_carrier:
        order.shipping_carrier = payload.shipping_carrier
    if payload.estimated_delivery_date:
        order.estimated_delivery_date = payload.estimated_delivery_date
    if payload.status:
        order.status = payload.status
    order.updated_by = current_user.id

    upsert_document("orders", order, order.id)
    save_order_sql(order)
    totals = compute_order_totals(order)
    log_activity(current_user.id, "order", order_id, "tracking_update", changes=payload.model_dump())
    return OrderComputed(**order.model_dump(), **totals)


@app.post("/orders/{order_id}/auto-assign-maker")
async def auto_assign_maker(order_id: int, current_user: User = Depends(get_current_user)):
    """
    Automatically assign maker based on workload
    """
    require_admin(current_user)

    order = None
    for o in orders:
        if o.id == order_id:
            order = o
            break

    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    # Get all makers (users with role admin or maker)
    makers = [u for u in users if u.role in ["admin", "maker"]]

    if not makers:
        raise HTTPException(status_code=400, detail="No makers available")

    # Calculate current workload for each maker
    maker_workload = {m.id: 0 for m in makers}
    for o in orders:
        if o.status in ["confirmed", "processing"] and o.maker_user_id:
            # Count time_minutes for all products in this order
            for line in o.order_lines:
                product = find_product(line.product_id)
                if product:
                    maker_workload[o.maker_user_id] = maker_workload.get(o.maker_user_id, 0) + (product.time_minutes * line.quantity)

    # Assign to maker with lowest workload
    selected_maker = min(makers, key=lambda m: maker_workload[m.id])

    order.maker_user_id = selected_maker.id
    upsert_document("orders", order, order.id)
    save_order_sql(order)

    return {
        "order_id": order_id,
        "assigned_maker_id": selected_maker.id,
        "assigned_maker_name": selected_maker.name,
        "current_workload_minutes": maker_workload[selected_maker.id]
    }


@app.get("/orders/workflow-automation")
async def order_workflow_automation(current_user: User = Depends(get_current_user)):
    """
    Analyze orders for workflow automation opportunities
    """
    automation_suggestions = []

    for order in orders:
        suggestions = []

        # Suggest auto-assign if no maker assigned
        if order.status in ["confirmed", "processing"] and not order.maker_user_id:
            suggestions.append({
                "type": "assign_maker",
                "action": "Auto-assign maker based on workload",
                "priority": "high"
            })

        # Suggest tracking update if processing but no tracking
        if order.status == "processing" and not order.tracking_number:
            suggestions.append({
                "type": "add_tracking",
                "action": "Add tracking number and carrier",
                "priority": "medium"
            })

        # Suggest delivery confirmation if shipped >3 days
        if order.status == "shipped" and order.estimated_delivery_date:
            days_since_shipped = (date.today() - order.date).days
            if days_since_shipped > 3:
                suggestions.append({
                    "type": "confirm_delivery",
                    "action": "Confirm delivery and request review",
                    "priority": "high"
                })

        # Suggest follow-up if delivered >3 days
        if order.status == "delivered":
            days_since_delivered = (date.today() - order.date).days
            if days_since_delivered >= 3:
                suggestions.append({
                    "type": "request_review",
                    "action": "Send review request to customer",
                    "priority": "medium"
                })

        if suggestions:
            automation_suggestions.append({
                "order_id": order.id,
                "customer_id": order.customer_id,
                "status": order.status,
                "date": order.date,
                "suggestions": suggestions
            })

    return {
        "total_suggestions": len(automation_suggestions),
        "orders_needing_action": automation_suggestions[:20]  # Top 20
    }


@app.delete("/orders/{order_id}")
async def delete_order(order_id: int, request: Request, current_user: User = Depends(get_current_user)):
    require_admin(current_user)
    for order in orders:
        if order.id == order_id:
            old_data = order.model_dump()
            orders.remove(order)
            delete_document("orders", order_id)
            with Session(engine) as session:
                session.exec(delete(OrderTable).where(OrderTable.id == order_id))
                session.commit()
            log_activity(current_user.id, "order", order_id, "delete")
            await create_audit_log(current_user, "DELETE", "orders", order_id, old_data, None, request)
            return {"ok": True}
    raise HTTPException(status_code=404, detail="Order không tồn tại")


# --- Seasons endpoints ------------------------------------------------------
@app.get("/seasons", response_model=List[Season])
async def list_seasons(current_user: User = Depends(get_current_user)):
    return seasons


@app.post("/seasons", response_model=Season)
async def create_season(payload: SeasonCreate, current_user: User = Depends(get_current_user)):
    require_admin(current_user)
    new_season = Season(id=next_id(seasons), **payload.model_dump(), created_by=current_user.id)
    seasons.append(new_season)
    upsert_document("seasons", new_season)
    log_activity(current_user.id, "season", new_season.id, "create", changes=payload.model_dump())
    return new_season


@app.put("/seasons/{season_id}", response_model=Season)
async def update_season(season_id: int, payload: Season, current_user: User = Depends(get_current_user)):
    require_admin(current_user)
    if payload.id != season_id:
        raise HTTPException(status_code=400, detail="Không được đổi id")
    for idx, season in enumerate(seasons):
        if season.id == season_id:
            payload.created_by = season.created_by or payload.created_by
            payload.updated_by = current_user.id
            seasons[idx] = payload
            upsert_document("seasons", payload, season_id)
            log_activity(current_user.id, "season", season_id, "update", changes=payload.model_dump())
            return payload
    raise HTTPException(status_code=404, detail="Season không tồn tại")


@app.delete("/seasons/{season_id}")
async def delete_season(season_id: int, current_user: User = Depends(get_current_user)):
    require_admin(current_user)
    for season in seasons:
        if season.id == season_id:
            seasons.remove(season)
            delete_document("seasons", season_id)
            log_activity(current_user.id, "season", season_id, "delete")
            return {"ok": True}
    raise HTTPException(status_code=404, detail="Season không tồn tại")


# --- Ideas endpoints --------------------------------------------------------
@app.get("/ideas", response_model=List[Idea])
async def list_ideas(current_user: User = Depends(get_current_user)):
    return ideas


@app.post("/ideas", response_model=Idea)
async def create_idea(payload: IdeaCreate, current_user: User = Depends(get_current_user)):
    require_admin(current_user)
    new_idea = Idea(id=next_id(ideas), **payload.model_dump(), created_by=current_user.id)
    ideas.append(new_idea)
    upsert_document("ideas", new_idea)
    log_activity(current_user.id, "idea", new_idea.id, "create", changes=payload.model_dump())
    return new_idea


@app.put("/ideas/{idea_id}", response_model=Idea)
async def update_idea(idea_id: int, payload: Idea, current_user: User = Depends(get_current_user)):
    require_admin(current_user)
    if payload.id != idea_id:
        raise HTTPException(status_code=400, detail="Không được đổi id")
    for idx, idea in enumerate(ideas):
        if idea.id == idea_id:
            payload.created_by = idea.created_by or payload.created_by
            payload.updated_by = current_user.id
            ideas[idx] = payload
            upsert_document("ideas", payload, idea_id)
            log_activity(current_user.id, "idea", idea_id, "update", changes=payload.model_dump())
            return payload
    raise HTTPException(status_code=404, detail="Idea không tồn tại")


@app.delete("/ideas/{idea_id}")
async def delete_idea(idea_id: int, current_user: User = Depends(get_current_user)):
    require_admin(current_user)
    for idea in ideas:
        if idea.id == idea_id:
            ideas.remove(idea)
            delete_document("ideas", idea_id)
            log_activity(current_user.id, "idea", idea_id, "delete")
            return {"ok": True}
    raise HTTPException(status_code=404, detail="Idea không tồn tại")


# --- Content plan endpoints -------------------------------------------------
@app.get("/content-plans", response_model=List[ContentPlan])
async def list_content_plans(current_user: User = Depends(get_current_user)):
    return content_plans


@app.post("/content-plans", response_model=ContentPlan)
async def create_content_plan(payload: ContentPlanCreate, current_user: User = Depends(get_current_user)):
    require_admin(current_user)
    if payload.related_product_id:
        find_product(payload.related_product_id)
    new_plan = ContentPlan(id=next_id(content_plans), **payload.model_dump(), created_by=current_user.id)
    content_plans.append(new_plan)
    upsert_document("content_plans", new_plan)
    log_activity(current_user.id, "content_plan", new_plan.id, "create", changes=payload.model_dump())
    return new_plan


@app.put("/content-plans/{plan_id}", response_model=ContentPlan)
async def update_content_plan(plan_id: int, payload: ContentPlan, current_user: User = Depends(get_current_user)):
    require_admin(current_user)
    if payload.id != plan_id:
        raise HTTPException(status_code=400, detail="Không được đổi id")
    if payload.related_product_id:
        find_product(payload.related_product_id)
    for idx, plan in enumerate(content_plans):
        if plan.id == plan_id:
            payload.created_by = plan.created_by or payload.created_by
            payload.updated_by = current_user.id
            content_plans[idx] = payload
            upsert_document("content_plans", payload, plan_id)
            log_activity(current_user.id, "content_plan", plan_id, "update", changes=payload.model_dump())
            return payload
    raise HTTPException(status_code=404, detail="Content plan không tồn tại")


class ContentPerformanceUpdate(BaseModel):
    actual_views: Optional[int] = None
    actual_inquiries: Optional[int] = None
    actual_saves: Optional[int] = None
    actual_orders: Optional[int] = None
    actual_revenue: Optional[float] = None


@app.post("/content-plans/{plan_id}/performance", response_model=ContentPlan)
async def update_content_performance(plan_id: int, payload: ContentPerformanceUpdate, current_user: User = Depends(get_current_user)):
    require_admin(current_user)
    for idx, plan in enumerate(content_plans):
        if plan.id == plan_id:
            data = plan.model_dump()
            for field, value in payload.model_dump(exclude_none=True).items():
                data[field] = value
            updated = ContentPlan(**data, updated_by=current_user.id)
            content_plans[idx] = updated
            upsert_document("content_plans", updated, plan_id)
            log_activity(current_user.id, "content_plan", plan_id, "update_performance", changes=payload.model_dump(exclude_none=True))
            return updated
    raise HTTPException(status_code=404, detail="Content plan không tồn tại")


@app.get("/content-plans/analytics")
async def content_performance_analytics(current_user: User = Depends(get_current_user)):
    """
    Analyze content performance: ROI, best formats, posting schedule
    """
    analytics = []

    for content in content_plans:
        if content.status != "published" or not content.actual_revenue:
            continue

        # Calculate ROI (assuming zero cost for now since cost_to_create field doesn't exist)
        cost_to_create = 0  # ContentPlan doesn't have cost_to_create field
        roi = 0  # Can't calculate without cost data

        # Calculate conversion rates
        views = content.actual_views or 0
        inquiries = content.actual_inquiries or 0
        orders = content.actual_orders or 0

        view_to_inquiry = (inquiries / views * 100) if views > 0 else 0
        inquiry_to_order = (orders / inquiries * 100) if inquiries > 0 else 0
        view_to_order = (orders / views * 100) if views > 0 else 0

        # Revenue per view
        revenue_per_view = content.actual_revenue / views if views > 0 else 0

        analytics.append({
            "content_id": content.id,
            "product_id": content.related_product_id,
            "format": content.format,
            "channel": content.channel,
            "published_date": content.published_date,
            "views": views,
            "inquiries": inquiries,
            "orders": orders,
            "revenue": content.actual_revenue,
            "cost": cost_to_create,
            "roi": round(roi, 2),
            "view_to_inquiry_rate": round(view_to_inquiry, 2),
            "inquiry_to_order_rate": round(inquiry_to_order, 2),
            "view_to_order_rate": round(view_to_order, 2),
            "revenue_per_view": round(revenue_per_view, 2)
        })

    # Best performing formats
    format_stats = {}
    for a in analytics:
        fmt = a["format"]
        if fmt not in format_stats:
            format_stats[fmt] = {"count": 0, "total_revenue": 0, "total_views": 0, "total_roi": 0}
        format_stats[fmt]["count"] += 1
        format_stats[fmt]["total_revenue"] += a["revenue"]
        format_stats[fmt]["total_views"] += a["views"]
        format_stats[fmt]["total_roi"] += a["roi"]

    best_formats = [
        {
            "format": fmt,
            "count": stats["count"],
            "avg_revenue": round(stats["total_revenue"] / stats["count"], 2),
            "avg_views": round(stats["total_views"] / stats["count"], 2),
            "avg_roi": round(stats["total_roi"] / stats["count"], 2)
        }
        for fmt, stats in format_stats.items()
    ]
    best_formats.sort(key=lambda x: x["avg_roi"], reverse=True)

    # Best posting times (by day of week)
    day_stats = {}
    for a in analytics:
        if a["published_date"]:
            day = a["published_date"].strftime("%A")
            if day not in day_stats:
                day_stats[day] = {"count": 0, "total_views": 0, "total_revenue": 0}
            day_stats[day]["count"] += 1
            day_stats[day]["total_views"] += a["views"]
            day_stats[day]["total_revenue"] += a["revenue"]

    best_days = [
        {
            "day": day,
            "count": stats["count"],
            "avg_views": round(stats["total_views"] / stats["count"], 2),
            "avg_revenue": round(stats["total_revenue"] / stats["count"], 2)
        }
        for day, stats in day_stats.items()
    ]
    best_days.sort(key=lambda x: x["avg_revenue"], reverse=True)

    # Content fatigue detection (same product posted too many times)
    product_frequency = {}
    for content in content_plans:
        if content.related_product_id:
            product_frequency[content.related_product_id] = product_frequency.get(content.related_product_id, 0) + 1

    fatigued_products = [
        {"product_id": pid, "post_count": count}
        for pid, count in product_frequency.items()
        if count > 10
    ]

    return {
        "contents": analytics,
        "best_formats": best_formats,
        "best_posting_days": best_days,
        "fatigued_products": fatigued_products,
        "summary": {
            "total_contents": len(analytics),
            "total_revenue": round(sum(a["revenue"] for a in analytics), 2),
            "total_cost": round(sum(a["cost"] for a in analytics), 2),
            "avg_roi": round(sum(a["roi"] for a in analytics) / len(analytics), 2) if analytics else 0,
            "avg_conversion": round(sum(a["view_to_order_rate"] for a in analytics) / len(analytics), 2) if analytics else 0
        }
    }


# --- Activity logs ---------------------------------------------------------
@app.get("/activity", response_model=List[ActivityLog])
async def list_activity(
    limit: int = 100,
    entity_type: Optional[str] = None,
    user_id: Optional[int] = None,
    action: Optional[str] = None,
    current_user: User = Depends(get_current_user)
):
    """Lấy danh sách activity logs với filter tùy chọn"""
    result = activity_logs
    if entity_type:
        result = [log for log in result if log.entity_type == entity_type]
    if user_id:
        result = [log for log in result if log.user_id == user_id]
    if action:
        result = [log for log in result if log.action == action]
    return result[:limit]


@app.get("/activity/summary")
async def activity_summary(
    days: int = 7,
    current_user: User = Depends(get_current_user)
):
    """Thống kê activity trong N ngày gần nhất"""
    cutoff = datetime.utcnow() - timedelta(days=days)
    recent = [log for log in activity_logs if log.created_at >= cutoff]

    by_entity = {}
    by_user = {}
    by_action = {}

    for log in recent:
        by_entity[log.entity_type] = by_entity.get(log.entity_type, 0) + 1
        by_user[log.user_id] = by_user.get(log.user_id, 0) + 1
        by_action[log.action] = by_action.get(log.action, 0) + 1

    return {
        "total": len(recent),
        "by_entity_type": by_entity,
        "by_user": by_user,
        "by_action": by_action,
        "period_days": days,
    }


# --- Experiments (A/B testing) ---------------------------------------------
@app.get("/experiments", response_model=List[Experiment])
async def list_experiments(current_user: User = Depends(get_current_user)):
    return experiments


@app.post("/experiments", response_model=Experiment)
async def create_experiment(payload: ExperimentCreate, current_user: User = Depends(get_current_user)):
    require_admin(current_user)
    new_exp = Experiment(
        id=next_id(experiments),
        **payload.model_dump(),
        created_by=current_user.id,
        created_at=datetime.utcnow(),
    )
    experiments.append(new_exp)
    upsert_document("experiments", new_exp)
    log_activity(current_user.id, "experiment", new_exp.id, "create", changes=payload.model_dump())
    return new_exp


@app.put("/experiments/{exp_id}", response_model=Experiment)
async def update_experiment(exp_id: int, payload: ExperimentUpdate, current_user: User = Depends(get_current_user)):
    require_admin(current_user)
    for idx, exp in enumerate(experiments):
        if exp.id == exp_id:
            data = exp.model_dump()
            for field, value in payload.model_dump(exclude_none=True).items():
                data[field] = value
            updated = Experiment(**data)
            experiments[idx] = updated
            upsert_document("experiments", updated, exp_id)
            log_activity(current_user.id, "experiment", exp_id, "update", changes=payload.model_dump(exclude_none=True))
            return updated
    raise HTTPException(status_code=404, detail="Experiment không tồn tại")


@app.delete("/experiments/{exp_id}")
async def delete_experiment(exp_id: int, current_user: User = Depends(get_current_user)):
    require_admin(current_user)
    for exp in experiments:
        if exp.id == exp_id:
            experiments.remove(exp)
            delete_document("experiments", exp_id)
            log_activity(current_user.id, "experiment", exp_id, "delete")
            return {"ok": True}
    raise HTTPException(status_code=404, detail="Experiment không tồn tại")


# --- Goals ------------------------------------------------------------------
@app.get("/goals", response_model=List[Goal])
async def list_goals(current_user: User = Depends(get_current_user)):
    return goals


@app.post("/goals", response_model=Goal)
async def create_goal(payload: GoalCreate, current_user: User = Depends(get_current_user)):
    require_admin(current_user)
    new_goal = Goal(
        id=next_id(goals),
        **payload.model_dump(),
        created_by=current_user.id,
        created_at=datetime.utcnow(),
    )
    goals.append(new_goal)
    upsert_document("goals", new_goal)
    log_activity(current_user.id, "goal", new_goal.id, "create", changes=payload.model_dump())
    return new_goal


@app.put("/goals/{goal_id}", response_model=Goal)
async def update_goal(goal_id: int, payload: GoalCreate, current_user: User = Depends(get_current_user)):
    require_admin(current_user)
    for idx, goal in enumerate(goals):
        if goal.id == goal_id:
            updated = Goal(
                id=goal_id,
                **payload.model_dump(),
                created_by=goal.created_by,
                created_at=goal.created_at,
                achieved_at=goal.achieved_at,
            )
            goals[idx] = updated
            upsert_document("goals", updated, goal_id)
            log_activity(current_user.id, "goal", goal_id, "update", changes=payload.model_dump())
            return updated
    raise HTTPException(status_code=404, detail="Mục tiêu không tồn tại")


@app.delete("/goals/{goal_id}")
async def delete_goal(goal_id: int, current_user: User = Depends(get_current_user)):
    require_admin(current_user)
    for goal in goals:
        if goal.id == goal_id:
            goals.remove(goal)
            delete_document("goals", goal_id)
            log_activity(current_user.id, "goal", goal_id, "delete")
            return {"ok": True}
    raise HTTPException(status_code=404, detail="Mục tiêu không tồn tại")


@app.delete("/content-plans/{plan_id}")
async def delete_content_plan(plan_id: int, current_user: User = Depends(get_current_user)):
    require_admin(current_user)
    for plan in content_plans:
        if plan.id == plan_id:
            content_plans.remove(plan)
            delete_document("content_plans", plan_id)
            log_activity(current_user.id, "content_plan", plan_id, "delete")
            return {"ok": True}
    raise HTTPException(status_code=404, detail="Content plan không tồn tại")


# --- Tasks / Collaboration --------------------------------------------------
@app.get("/tasks", response_model=List[Task])
async def list_tasks(assignee_id: Optional[int] = None, status: Optional[str] = None, current_user: User = Depends(get_current_user)):
    data = tasks
    if assignee_id is not None:
        data = [t for t in data if t.assignee_id == assignee_id]
    if status:
        data = [t for t in data if t.status == status]
    return data


@app.post("/tasks", response_model=Task)
async def create_task(payload: TaskCreate, current_user: User = Depends(get_current_user)):
    require_admin(current_user)
    if payload.assignee_id and not any(u.id == payload.assignee_id for u in users):
        raise HTTPException(status_code=404, detail="Assignee không tồn tại")
    new_task = Task(
        id=next_id(tasks),
        **payload.model_dump(),
        created_by=current_user.id,
        created_at=datetime.utcnow(),
    )
    tasks.append(new_task)
    upsert_document("tasks", new_task)
    with Session(engine) as session:
        session.add(task_to_table(new_task))
        session.commit()
    log_activity(current_user.id, "task", new_task.id, "create", changes=payload.model_dump())
    return new_task


class TaskUpdate(TaskCreate):
    status: Optional[str] = None
    assignee_id: Optional[int] = None


@app.put("/tasks/{task_id}", response_model=Task)
async def update_task(task_id: int, payload: TaskUpdate, current_user: User = Depends(get_current_user)):
    require_admin(current_user)
    for idx, task in enumerate(tasks):
        if task.id == task_id:
            data = task.model_dump()
            for k, v in payload.model_dump(exclude_none=True).items():
                data[k] = v
            if data.get("status") == "done" and not data.get("completed_at"):
                data["completed_at"] = datetime.utcnow()
            updated = Task(**data)
            tasks[idx] = updated
            upsert_document("tasks", updated, task_id)
            save_task_sql(updated)
            log_activity(current_user.id, "task", task_id, "update", changes=payload.model_dump(exclude_none=True))
            return updated
    raise HTTPException(status_code=404, detail="Task không tồn tại")


@app.delete("/tasks/{task_id}")
async def delete_task(task_id: int, current_user: User = Depends(get_current_user)):
    require_admin(current_user)
    for task in tasks:
        if task.id == task_id:
            tasks.remove(task)
            delete_document("tasks", task_id)
            with Session(engine) as session:
                row = session.get(TaskTable, task_id)
                if row:
                    session.delete(row)
                    session.commit()
            log_activity(current_user.id, "task", task_id, "delete")
            return {"ok": True}
    raise HTTPException(status_code=404, detail="Task không tồn tại")


# --- Issues endpoints -------------------------------------------------------
@app.get("/issues", response_model=List[Issue])
async def list_issues(
    product_id: Optional[int] = None,
    status: Optional[str] = None,
    priority: Optional[int] = None,
    assignee_id: Optional[int] = None,
    q: Optional[str] = None,
    limit: int = 200,
    offset: int = 0,
    response: Response = None,
    current_user: User = Depends(get_current_user),
):
    def with_counts(src: List[Issue]) -> List[Issue]:
        for i in src:
            i.comments_count = len([c for c in issue_comments if c.issue_id == i.id])
        return src

    filtered = issues
    if product_id:
        filtered = [i for i in filtered if i.product_id == product_id]
    if status:
        filtered = [i for i in filtered if i.status == status]
    if priority is not None:
        filtered = [i for i in filtered if i.priority == priority]
    if assignee_id is not None:
        filtered = [i for i in filtered if i.assigned_to == assignee_id]
    if q:
        q_lower = q.lower()
        filtered = [i for i in filtered if q_lower in (i.description or "").lower() or q_lower in (i.type or "").lower()]
    total = len(filtered)
    if response is not None:
        response.headers["X-Total-Count"] = str(total)
    return with_counts(list(filtered))[offset : offset + limit]


@app.get("/issue-templates", response_model=List[Issue])
async def list_issue_templates(current_user: User = Depends(get_current_user)):
    return [i for i in issues if i.is_template]


@app.get("/issues/{issue_id}/comments", response_model=List[IssueComment])
async def list_issue_comments(issue_id: int, current_user: User = Depends(get_current_user)):
    find_issue(issue_id)
    return [c for c in issue_comments if c.issue_id == issue_id]


class IssueCommentCreate(BaseModel):
    content: str


@app.post("/issues/{issue_id}/comments", response_model=IssueComment)
async def create_issue_comment(issue_id: int, payload: IssueCommentCreate, current_user: User = Depends(get_current_user)):
    find_issue(issue_id)
    new_comment = IssueComment(
        id=next_id(issue_comments),
        issue_id=issue_id,
        user_id=current_user.id,
        content=payload.content,
        created_at=datetime.utcnow(),
    )
    issue_comments.append(new_comment)
    upsert_document("issue_comments", new_comment)
    for i in issues:
        if i.id == issue_id:
            i.comments_count = len([c for c in issue_comments if c.issue_id == issue_id])
            save_issue_sql(i)
            break
    log_activity(current_user.id, "issue", issue_id, "comment", changes={"content": payload.content})
    return new_comment


@app.post("/issues", response_model=Issue)
async def create_issue(payload: IssueCreate, current_user: User = Depends(get_current_user)):
    require_admin(current_user)
    find_product(payload.product_id)
    if payload.assigned_to and not any(u.id == payload.assigned_to for u in users):
        raise HTTPException(status_code=404, detail="Người được giao không tồn tại")
    new_issue = Issue(
        **payload.model_dump(),
        id=next_id(issues),
        created_at=datetime.utcnow(),
        created_by=current_user.id,
    )
    issues.append(new_issue)
    upsert_document("issues", new_issue)
    save_issue_sql(new_issue)
    log_activity(current_user.id, "issue", new_issue.id, "create", changes=payload.model_dump())
    return new_issue


@app.put("/issues/{issue_id}", response_model=Issue)
async def update_issue(issue_id: int, payload: Issue, current_user: User = Depends(get_current_user)):
    require_admin(current_user)
    for idx, issue in enumerate(issues):
        if issue.id == issue_id:
            payload.id = issue_id
            payload.created_at = issue.created_at
            payload.created_by = issue.created_by
            if payload.assigned_to and not any(u.id == payload.assigned_to for u in users):
                raise HTTPException(status_code=404, detail="Người được giao không tồn tại")
            if payload.status == "resolved" and payload.resolved_at is None:
                payload.resolved_at = datetime.utcnow()
                payload.resolution_hours = (
                    (payload.resolved_at - payload.created_at).total_seconds() / 3600
                    if payload.created_at
                    else None
                )
            issues[idx] = payload
            upsert_document("issues", payload, issue_id)
            save_issue_sql(payload)
            log_activity(current_user.id, "issue", issue_id, "update", changes=payload.model_dump())
            return payload
    raise HTTPException(status_code=404, detail="Issue không tồn tại")


class IssueFromTemplateRequest(BaseModel):
    template_id: int
    product_id: int
    description: Optional[str] = None
    priority: Optional[int] = None


@app.post("/issues/from-template", response_model=Issue)
async def create_issue_from_template(payload: IssueFromTemplateRequest, current_user: User = Depends(get_current_user)):
    require_admin(current_user)
    template = find_issue(payload.template_id)
    if not template.is_template:
        raise HTTPException(status_code=400, detail="Issue này không phải template")
    find_product(payload.product_id)
    new_issue = Issue(
        id=next_id(issues),
        product_id=payload.product_id,
        type=template.type,
        description=payload.description or template.description,
        evidence=template.evidence,
        hypothesis=template.hypothesis,
        next_action=template.next_action,
        priority=payload.priority or template.priority,
        status="open",
        impact_revenue=template.impact_revenue,
        is_template=False,
        created_by=current_user.id,
        created_at=datetime.utcnow(),
    )
    issues.append(new_issue)
    upsert_document("issues", new_issue)
    save_issue_sql(new_issue)
    log_activity(current_user.id, "issue", new_issue.id, "create_from_template", changes=payload.model_dump())
    return new_issue


@app.delete("/issues/{issue_id}")
async def delete_issue(issue_id: int, current_user: User = Depends(get_current_user)):
    require_admin(current_user)
    for issue in issues:
        if issue.id == issue_id:
            issues.remove(issue)
            delete_document("issues", issue_id)
            with Session(engine) as session:
                session.exec(delete(IssueTable).where(IssueTable.id == issue_id))
                session.commit()
            log_activity(current_user.id, "issue", issue_id, "delete")
            return {"ok": True}
    raise HTTPException(status_code=404, detail="Issue không tồn tại")


# --- Demand signals --------------------------------------------------------
@app.get("/demand", response_model=List[DemandSignal])
async def list_demand(product_id: Optional[int] = None, current_user: User = Depends(get_current_user)):
    if product_id:
        return [d for d in demand_signals if d.product_id == product_id]
    return demand_signals


@app.post("/demand", response_model=DemandSignal)
async def add_demand(payload: DemandSignalCreate, current_user: User = Depends(get_current_user)):
    require_admin(current_user)
    find_product(payload.product_id)
    new_signal = DemandSignal(
        id=next_id(demand_signals),
        product_id=payload.product_id,
        views=payload.views,
        inquiries=payload.inquiries,
        saves=payload.saves,
        week_of=payload.week_of,
        created_by=current_user.id,
    )
    demand_signals.append(new_signal)
    upsert_document("demand_signals", new_signal)
    save_demand_sql(new_signal)
    log_activity(current_user.id, "demand", new_signal.id, "create", changes=new_signal.model_dump())

    # Update product demand_score simple calc
    product = find_product(new_signal.product_id)
    weekly = [d for d in demand_signals if d.product_id == product.id]
    avg_views = sum(d.views for d in weekly) / len(weekly)
    avg_inquiries = sum(d.inquiries for d in weekly) / len(weekly)
    avg_saves = sum(d.saves for d in weekly) / len(weekly)
    demand_score = min(100, avg_views * 0.01 + avg_inquiries * 2 + avg_saves * 1.5)
    product.demand_score = demand_score
    upsert_document("products", product, product.id)
    save_product_sql(product)
    return new_signal


# --- Dashboard & reports ----------------------------------------------------
@app.get("/dashboard")
async def dashboard(current_user: User = Depends(get_current_user)):
    orders_with_totals = [OrderComputed(**o.model_dump(), **compute_order_totals(o)) for o in orders]

    total_profit_month = sum(o.profit for o in orders_with_totals if o.date.month == date.today().month)
    total_orders_month = len([o for o in orders_with_totals if o.date.month == date.today().month])

    product_sales: Dict[int, Dict[str, float]] = {}
    for order in orders:
        for line in order.order_lines:
            product_sales.setdefault(line.product_id, {"units": 0, "revenue": 0})
            product_sales[line.product_id]["units"] += line.quantity
            product_sales[line.product_id]["revenue"] += line.quantity * line.unit_price

    top_products = sorted(
        [
            {
                "product": find_product(pid).name,
                "units": stats["units"],
                "revenue": stats["revenue"],
            }
            for pid, stats in product_sales.items()
        ],
        key=lambda x: x["units"],
        reverse=True,
    )[:3]

    feasible_without_orders = []
    for product in products:
        metrics = get_product_cost_cached(product)
        if product.id not in product_sales and metrics.get("feasibility_score", 0) >= 1:
            feasible_without_orders.append({"product": product.name, **metrics})

    top_feasibility = sorted(
        [get_product_cost_cached(p) | {"name": p.name} for p in products],
        key=lambda x: x.get("feasibility_score", 0),
        reverse=True,
    )[:3]

    upcoming = []
    today = date.today()
    for season in seasons:
        if today <= season.to_date and (season.from_date - today).days <= 60:
            related = [p.name for p in products if season.id in p.seasons]
            upcoming.append({
                "name": season.name,
                "from": season.from_date,
                "to": season.to_date,
                "products": related,
            })

    return {
        "profit_this_month": round(total_profit_month, 2),
        "orders_this_month": total_orders_month,
        "top_products": top_products,
        "top_feasibility": top_feasibility,
        "feasible_to_push": feasible_without_orders,
        "upcoming_seasons": upcoming,
    }


@app.get("/dashboard/summary")
async def dashboard_summary(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    current_user: User = Depends(get_current_user)
):
    """Tổng hợp toàn bộ dữ liệu dashboard trong 1 API call duy nhất"""
    # Parse dates
    if start_date and end_date:
        start = datetime.strptime(start_date, "%Y-%m-%d").date()
        end = datetime.strptime(end_date, "%Y-%m-%d").date()
    else:
        today = date.today()
        start = date(today.year, today.month, 1)
        end = today

    # Filter orders by date range
    filtered_orders = [o for o in orders if start <= o.date <= end]
    orders_with_totals = [OrderComputed(**o.model_dump(), **compute_order_totals(o)) for o in filtered_orders]

    # Basic metrics
    total_profit = sum(o.profit for o in orders_with_totals)
    total_revenue = sum(o.revenue for o in orders_with_totals)
    total_orders = len(orders_with_totals)

    # Product sales
    product_sales: Dict[int, Dict[str, float]] = {}
    for order in filtered_orders:
        for line in order.order_lines:
            if line.product_id not in product_sales:
                product_sales[line.product_id] = {"units": 0, "revenue": 0, "profit": 0}

            product_sales[line.product_id]["units"] += line.quantity
            product_sales[line.product_id]["revenue"] += line.quantity * line.unit_price

            # Calculate profit for this line
            product = find_product(line.product_id)
            if product:
                cost_info = get_product_cost_cached(product)
                line_profit = (line.unit_price - cost_info.get("cost_per_unit", 0)) * line.quantity
                product_sales[line.product_id]["profit"] += line_profit

    top_products = sorted(
        [{
            "product_id": pid,
            "product_name": find_product(pid).name,
            "units_sold": stats["units"],
            "revenue": stats["revenue"],
            "profit": stats.get("profit", 0)
        } for pid, stats in product_sales.items()],
        key=lambda x: x["units_sold"],
        reverse=True,
    )[:5]

    # Feasibility scores
    top_feasibility = sorted(
        [{
            "product_id": p.id,
            "product_name": p.name,
            "feasibility_score": get_product_cost_cached(p).get("feasibility_score", 0),
            "profit_per_unit": get_product_cost_cached(p).get("profit_per_unit", 0),
            "max_units": get_product_cost_cached(p).get("max_units_from_stock")
        } for p in products],
        key=lambda x: x["feasibility_score"],
        reverse=True,
    )[:5]

    # Alerts
    low_stock = [{"material": m.name, "code": m.code, "stock": m.stock_quantity, "unit": m.unit, "threshold": m.low_threshold}
                 for m in materials if m.stock_quantity <= m.low_threshold]
    overdue_orders = [{"id": o.id, "date": o.date.isoformat(), "customer_name": find_customer(o.customer_id).name if o.customer_id else "N/A", "expected_date": o.date.isoformat()}
                      for o in orders if o.status != "delivered" and (date.today() - o.date).days > 7]

    # Channel performance
    channel_revenue = {}
    for order in filtered_orders:
        ch = order.channel or "direct"
        channel_revenue[ch] = channel_revenue.get(ch, 0) + compute_order_totals(order)["revenue"]

    channels = [{"channel": ch, "revenue": rev} for ch, rev in channel_revenue.items()]
    channels.sort(key=lambda x: x["revenue"], reverse=True)

    # Daily revenue trend (last 30 days for chart)
    daily_revenue = {}
    for order in [o for o in orders if (date.today() - o.date).days <= 30]:
        day_key = order.date.isoformat()
        daily_revenue[day_key] = daily_revenue.get(day_key, 0) + compute_order_totals(order)["revenue"]

    revenue_trend = [{"date": day, "revenue": rev} for day, rev in sorted(daily_revenue.items())]

    # Order status breakdown
    status_counts = {}
    for order in filtered_orders:
        status_counts[order.status] = status_counts.get(order.status, 0) + 1

    order_status = [{"status": status, "count": count} for status, count in status_counts.items()]

    # Material usage forecast
    material_forecast = []
    for material in materials[:10]:  # Top 10 materials
        weekly_usage = sum(
            usage.quantity
            for product in products
            for usage in product.materials
            if usage.material_id == material.id
        )
        weeks_remaining = material.stock_quantity / weekly_usage if weekly_usage > 0 else 999
        material_forecast.append({
            "material": material.name,
            "code": material.code,
            "stock": material.stock_quantity,
            "weeks_remaining": round(weeks_remaining, 1)
        })

    # P&L Report
    gross_revenue = total_revenue
    discount = sum(o.discount or 0 for o in filtered_orders)
    returns = 0  # TODO: track returns
    net_revenue = gross_revenue - discount - returns
    cogs = sum(
        get_product_cost_cached(find_product(line.product_id)).get("cost_per_unit", 0) * line.quantity
        for order in filtered_orders
        for line in order.order_lines
        if find_product(line.product_id)
    )
    shipping_cost = sum(o.shipping_fee or 0 for o in filtered_orders)
    gross_profit = net_revenue - cogs - shipping_cost

    # Inventory valuation
    inventory_value = sum(m.stock_quantity * m.unit_price for m in materials)
    valuation_items = [{
        "material_id": m.id,
        "code": m.code,
        "name": m.name,
        "stock_quantity": m.stock_quantity,
        "unit_price": m.unit_price,
        "value": m.stock_quantity * m.unit_price
    } for m in materials[:20]]

    # Funnel metrics
    total_views = sum(d.views for d in demand_signals)
    total_inquiries = sum(d.inquiries for d in demand_signals)
    total_saves = sum(d.saves for d in demand_signals)
    conv_inquiry = round(total_inquiries / total_views * 100, 2) if total_views > 0 else 0
    conv_order_view = round(total_orders / total_views * 100, 2) if total_views > 0 else 0
    conv_order_inquiry = round(total_orders / total_inquiries * 100, 2) if total_inquiries > 0 else 0

    # Customer analytics (RFM)
    customer_stats = []
    for customer in customers[:10]:
        customer_orders = [o for o in filtered_orders if o.customer_id == customer.id]
        if not customer_orders:
            continue
        total_spent = sum(compute_order_totals(o)["revenue"] for o in customer_orders)
        last_order = max(customer_orders, key=lambda o: o.date)
        recency_days = (date.today() - last_order.date).days
        rfm_score = min(100, (10 - min(recency_days / 30, 10)) * 3 + len(customer_orders) * 2 + total_spent / 1000)
        customer_stats.append({
            "customer_id": customer.id,
            "name": customer.name,
            "source": customer.source or "N/A",
            "total_orders": len(customer_orders),
            "total_spent": round(total_spent, 2),
            "avg_order": round(total_spent / len(customer_orders), 2),
            "recency_days": recency_days,
            "rfm_score": round(rfm_score, 1)
        })

    # Cashflow
    cash_in = total_revenue
    cash_out = cogs + shipping_cost
    refunds = 0  # TODO
    purchase_spend = sum(
        line.quantity * line.unit_price
        for po in purchase_orders
        if po.created_at and start <= po.created_at.date() <= end
        for line in po.lines
    )
    net_cash = cash_in - cash_out - refunds - purchase_spend

    # Balance sheet (simplified)
    cash_balance = net_cash
    assets = {
        "cash": round(cash_balance, 2),
        "inventory": round(inventory_value, 2),
        "total": round(cash_balance + inventory_value, 2)
    }
    liabilities = 0  # TODO
    equity = assets["total"] - liabilities

    # Demand history for chart
    demand_history = []
    for signal in sorted(demand_signals, key=lambda d: d.week_of)[-12:]:
        demand_history.append({
            "week": signal.week_of.strftime("%d/%m") if hasattr(signal.week_of, 'strftime') else str(signal.week_of),
            "views": signal.views,
            "inquiries": signal.inquiries,
            "saves": signal.saves
        })

    # Upcoming seasons
    upcoming_seasons = []
    today = date.today()
    for season in seasons:
        if today <= season.to_date and (season.from_date - today).days <= 60:
            related = [p.name for p in products if season.id in p.seasons]
            upcoming_seasons.append({
                "name": season.name,
                "from": season.from_date.isoformat(),
                "to": season.to_date.isoformat(),
                "products": related
            })

    # Goals tracking
    active_goals = [g for g in goals if g.status == "active" and start <= g.end_date and g.start_date <= end]
    goals_data = []
    for goal in active_goals:
        # Calculate current value based on goal type
        if goal.target_type == "revenue":
            current = total_revenue
        elif goal.target_type == "profit":
            current = total_profit
        elif goal.target_type == "orders":
            current = total_orders
        elif goal.target_type == "customers":
            current = len(set(o.customer_id for o in filtered_orders if o.customer_id))
        else:
            current = goal.current_value

        progress = min(100, (current / goal.target_value * 100) if goal.target_value > 0 else 0)
        goals_data.append({
            "id": goal.id,
            "title": goal.title,
            "target_type": goal.target_type,
            "target_value": round(goal.target_value, 2),
            "current_value": round(current, 2),
            "progress": round(progress, 2),
            "status": "achieved" if current >= goal.target_value else "active",
            "end_date": goal.end_date.isoformat()
        })

    # P&L Waterfall data (for chart)
    pnl_waterfall = [
        {"label": "Gross Revenue", "value": gross_revenue, "type": "total"},
        {"label": "Discount", "value": -discount, "type": "decrease"},
        {"label": "Returns", "value": -returns, "type": "decrease"},
        {"label": "Net Revenue", "value": net_revenue, "type": "total"},
        {"label": "COGS", "value": -cogs, "type": "decrease"},
        {"label": "Shipping", "value": -shipping_cost, "type": "decrease"},
        {"label": "Gross Profit", "value": gross_profit, "type": "total"}
    ]

    # Customer RFM scatter data (for visualization)
    customer_rfm_scatter = [
        {
            "name": c["name"],
            "recency": c["recency_days"],
            "frequency": c["total_orders"],
            "monetary": c["total_spent"],
            "rfm_score": c["rfm_score"]
        }
        for c in customer_stats[:20]
    ]

    # Inventory treemap data
    inventory_treemap = [
        {
            "name": item["name"],
            "value": item["value"],
            "category": item["code"][:2] if len(item["code"]) > 2 else "Other"
        }
        for item in valuation_items[:15]
    ]

    return {
        "period": {"start_date": start.isoformat(), "end_date": end.isoformat()},
        "metrics": {
            "total_profit": round(total_profit, 2),
            "total_revenue": round(total_revenue, 2),
            "total_orders": total_orders,
            "avg_order_value": round(total_revenue / total_orders, 2) if total_orders > 0 else 0,
        },
        "top_products": top_products,
        "top_feasibility": top_feasibility,
        "alerts": {
            "low_stock": low_stock[:5],
            "overdue_orders": overdue_orders[:5],
        },
        "channel_performance": channels,
        "revenue_trend": revenue_trend,
        "order_status": order_status,
        "material_forecast": material_forecast,
        "pnl": {
            "gross_revenue": round(gross_revenue, 2),
            "discount": round(discount, 2),
            "returns": round(returns, 2),
            "net_revenue": round(net_revenue, 2),
            "cogs": round(cogs, 2),
            "shipping_cost": round(shipping_cost, 2),
            "gross_profit": round(gross_profit, 2),
        },
        "pnl_waterfall": pnl_waterfall,
        "inventory_valuation": {
            "total_value": round(inventory_value, 2),
            "items": valuation_items
        },
        "inventory_treemap": inventory_treemap,
        "funnel": {
            "views": total_views,
            "inquiries": total_inquiries,
            "orders": total_orders,
            "saves": total_saves,
            "conv_inquiry": conv_inquiry,
            "conv_order_view": conv_order_view,
            "conv_order_inquiry": conv_order_inquiry
        },
        "customer_analytics": customer_stats,
        "customer_rfm_scatter": customer_rfm_scatter,
        "cashflow": {
            "cash_in": round(cash_in, 2),
            "cash_out": round(cash_out, 2),
            "refunds": round(refunds, 2),
            "purchase_spend": round(purchase_spend, 2),
            "net_cash": round(net_cash, 2)
        },
        "balance_sheet": {
            "assets": assets,
            "liabilities": round(liabilities, 2),
            "equity": round(equity, 2)
        },
        "demand_history": demand_history,
        "upcoming_seasons": upcoming_seasons,
        "goals": goals_data
    }


# =============================================================================
# REVENUE FORECASTING - Simple Linear Regression
# =============================================================================

class ForecastRequest(BaseModel):
    periods: int = Field(default=6, ge=1, le=24, description="Number of periods to forecast")
    period_type: str = Field(default="month", pattern="^(day|week|month)$")

class ForecastResponse(BaseModel):
    historical: List[Dict]
    forecast: List[Dict]
    metrics: Dict
    trend: str
    confidence: float

@app.post("/dashboard/forecast", response_model=ForecastResponse)
async def revenue_forecast(
    request: ForecastRequest,
    current_user: User = Depends(get_current_user)
):
    """
    Dự báo doanh thu sử dụng Simple Linear Regression.
    - Tính toán trend từ dữ liệu lịch sử
    - Dự báo cho N kỳ tiếp theo
    - Trả về độ tin cậy và chỉ số thống kê
    """
    from datetime import timedelta

    now = datetime.now()

    # Xác định khoảng thời gian theo period_type
    if request.period_type == "day":
        delta = timedelta(days=1)
        history_periods = 90  # 90 ngày gần nhất
        date_format = "%Y-%m-%d"
    elif request.period_type == "week":
        delta = timedelta(weeks=1)
        history_periods = 52  # 52 tuần
        date_format = "%Y-W%W"
    else:  # month
        delta = timedelta(days=30)
        history_periods = 24  # 24 tháng
        date_format = "%Y-%m"

    # Thu thập dữ liệu lịch sử
    historical_data = []

    for i in range(history_periods, 0, -1):
        if request.period_type == "month":
            # Tính theo tháng thực
            year = now.year
            month = now.month - i
            while month <= 0:
                month += 12
                year -= 1
            start_date = datetime(year, month, 1)
            if month == 12:
                end_date = datetime(year + 1, 1, 1)
            else:
                end_date = datetime(year, month + 1, 1)
            period_label = start_date.strftime("%Y-%m")
        elif request.period_type == "week":
            start_date = now - timedelta(weeks=i)
            start_date = start_date - timedelta(days=start_date.weekday())  # Monday
            end_date = start_date + timedelta(weeks=1)
            period_label = start_date.strftime("%Y-W%W")
        else:  # day
            start_date = now - timedelta(days=i)
            start_date = start_date.replace(hour=0, minute=0, second=0, microsecond=0)
            end_date = start_date + timedelta(days=1)
            period_label = start_date.strftime("%Y-%m-%d")

        # Tính doanh thu trong kỳ
        period_revenue = 0
        period_orders = 0
        for order in orders:
            order_dt = (
                order.date
                if isinstance(order.date, datetime)
                else datetime.combine(order.date, datetime.min.time()) if hasattr(order.date, 'year') else datetime.fromisoformat(str(order.date))
            )
            if start_date <= order_dt < end_date:
                totals = compute_order_totals(order)
                period_revenue += totals["revenue"]
                period_orders += 1

        historical_data.append({
            "period": period_label,
            "revenue": round(period_revenue, 2),
            "orders": period_orders
        })

    # Lọc bỏ các kỳ không có dữ liệu ở đầu
    while historical_data and historical_data[0]["revenue"] == 0 and historical_data[0]["orders"] == 0:
        historical_data.pop(0)

    # Simple Linear Regression
    n = len(historical_data)
    if n < 3:
        # Không đủ dữ liệu
        return ForecastResponse(
            historical=historical_data,
            forecast=[],
            metrics={"error": "Not enough historical data"},
            trend="unknown",
            confidence=0.0
        )

    # Chuẩn bị dữ liệu cho regression
    x = list(range(n))  # [0, 1, 2, ..., n-1]
    y = [d["revenue"] for d in historical_data]

    # Tính mean
    x_mean = sum(x) / n
    y_mean = sum(y) / n

    # Tính slope (beta) và intercept (alpha)
    numerator = sum((x[i] - x_mean) * (y[i] - y_mean) for i in range(n))
    denominator = sum((x[i] - x_mean) ** 2 for i in range(n))

    if denominator == 0:
        slope = 0
        intercept = y_mean
    else:
        slope = numerator / denominator
        intercept = y_mean - slope * x_mean

    # Tính R-squared (coefficient of determination)
    ss_tot = sum((y[i] - y_mean) ** 2 for i in range(n))
    y_pred = [slope * x[i] + intercept for i in range(n)]
    ss_res = sum((y[i] - y_pred[i]) ** 2 for i in range(n))

    r_squared = 1 - (ss_res / ss_tot) if ss_tot > 0 else 0
    r_squared = max(0, min(1, r_squared))  # Clamp to [0, 1]

    # Dự báo cho các kỳ tiếp theo
    forecast_data = []
    for i in range(request.periods):
        future_x = n + i
        predicted_revenue = slope * future_x + intercept
        predicted_revenue = max(0, predicted_revenue)  # Không âm

        # Tính label cho kỳ dự báo
        if request.period_type == "month":
            year = now.year
            month = now.month + i + 1
            while month > 12:
                month -= 12
                year += 1
            period_label = f"{year}-{month:02d}"
        elif request.period_type == "week":
            future_date = now + timedelta(weeks=i+1)
            period_label = future_date.strftime("%Y-W%W")
        else:
            future_date = now + timedelta(days=i+1)
            period_label = future_date.strftime("%Y-%m-%d")

        # Tính khoảng tin cậy (±20% dựa trên variance)
        std_error = (ss_res / (n - 2)) ** 0.5 if n > 2 else 0
        margin = 1.96 * std_error * ((1 + 1/n + (future_x - x_mean)**2 / denominator) ** 0.5) if denominator > 0 else predicted_revenue * 0.2

        forecast_data.append({
            "period": period_label,
            "predicted_revenue": round(predicted_revenue, 2),
            "lower_bound": round(max(0, predicted_revenue - margin), 2),
            "upper_bound": round(predicted_revenue + margin, 2)
        })

    # Xác định trend
    if slope > 0.01 * y_mean:
        trend = "increasing"
    elif slope < -0.01 * y_mean:
        trend = "decreasing"
    else:
        trend = "stable"

    # Tính các metrics bổ sung
    avg_revenue = y_mean
    growth_rate = (slope / y_mean * 100) if y_mean > 0 else 0

    return ForecastResponse(
        historical=historical_data[-12:],  # Chỉ trả về 12 kỳ gần nhất
        forecast=forecast_data,
        metrics={
            "slope": round(slope, 2),
            "intercept": round(intercept, 2),
            "r_squared": round(r_squared, 4),
            "avg_revenue": round(avg_revenue, 2),
            "growth_rate_per_period": round(growth_rate, 2),
            "total_historical_periods": n
        },
        trend=trend,
        confidence=round(r_squared * 100, 1)  # Confidence as percentage
    )


@app.get("/reports/profit-by-maker")
async def profit_by_maker(current_user: User = Depends(get_current_user)):
    maker_stats: Dict[int, Dict[str, float]] = {}
    for order in orders:
        if not order.maker_user_id:
            continue
        totals = compute_order_totals(order)
        agg = maker_stats.setdefault(
            order.maker_user_id,
            {"maker_user_id": order.maker_user_id, "orders_count": 0, "revenue": 0.0, "profit": 0.0},
        )
        agg["orders_count"] += 1
        agg["revenue"] += totals["revenue"]
        agg["profit"] += totals["profit"]

    result = []
    for maker_id, agg in maker_stats.items():
        name = next((u.name for u in users if u.id == maker_id), f"Maker #{maker_id}")
        result.append({**agg, "maker_name": name})
    return result


@app.get("/reports/product-performance")
async def product_performance(current_user: User = Depends(get_current_user)):
    stats: Dict[int, Dict[str, float]] = {}
    for order in orders:
        if not order.order_lines:
            continue
        total_gross = sum(l.unit_price * l.quantity for l in order.order_lines)
        total_qty = sum(l.quantity for l in order.order_lines)
        returns_amount = sum(
            r.refund_amount or r.amount
            for r in order_returns
            if r.order_id == order.id and r.status in {"approved", "processed"}
        )
        for line in order.order_lines:
            product = find_product(line.product_id)
            gross_line = line.unit_price * line.quantity
            revenue_line = gross_line
            if total_gross > 0:
                revenue_line -= order.discount * (gross_line / total_gross)
                revenue_line -= returns_amount * (gross_line / total_gross)
            product_cost = compute_product_cost(product)
            unit_cost = (
                product_cost["material_cost"]
                + product_cost["labor_cost"]
                + product_cost.get("packaging_cost", 0)
                + product_cost.get("marketing_cost", 0)
                + product_cost.get("platform_fee_amount", 0)
            )
            shipping_alloc = (order.shipping_fee * line.quantity / total_qty) if total_qty else 0
            cost_line = unit_cost * line.quantity + shipping_alloc

            agg = stats.setdefault(
                line.product_id,
                {
                    "product_id": line.product_id,
                    "product_name": product.name,
                    "units": 0,
                    "revenue": 0.0,
                    "cost": 0.0,
                },
            )
            agg["units"] += line.quantity
            agg["revenue"] += revenue_line
            agg["cost"] += cost_line

    result = []
    for _, agg in stats.items():
        profit = agg["revenue"] - agg["cost"]
        margin = profit / agg["revenue"] if agg["revenue"] else 0
        result.append({**agg, "profit": round(profit, 2), "margin": round(margin * 100, 2)})

    return sorted(result, key=lambda x: x["revenue"], reverse=True)


@app.get("/alerts")
async def get_alerts(current_user: User = Depends(get_current_user)):
    low_stock = get_low_stock_alerts()
    overdue = get_overdue_orders()
    forecast = await material_forecast(current_user)
    forecast_low = [f for f in forecast if f.get("days_left") is not None and f["days_left"] <= 7]
    tasks_overdue = [t for t in tasks if t.due_date and t.status != "done" and t.due_date < date.today()]
    alerts = {"low_stock": low_stock, "overdue_orders": overdue, "forecast_low": forecast_low, "tasks_overdue": tasks_overdue}
    send_notifications(alerts)
    return alerts


@app.get("/reports/channel-performance")
async def channel_performance(current_user: User = Depends(get_current_user)):
    agg: Dict[str, Dict[str, float]] = {}
    for o in orders:
        totals = compute_order_totals(o)
        ch = o.channel or "other"
        bucket = agg.setdefault(ch, {"channel": ch, "orders": 0, "revenue": 0.0, "profit": 0.0})
        bucket["orders"] += 1
        bucket["revenue"] += totals["revenue"]
        bucket["profit"] += totals["profit"]
    return sorted(agg.values(), key=lambda x: x["revenue"], reverse=True)


@app.get("/reports/cashflow")
async def cashflow_report(current_user: User = Depends(get_current_user)):
    cash_in = sum(p.amount for p in payments if p.status == "paid")
    refunds = sum(r.refund_amount or r.amount for r in order_returns)
    po_spend = sum(po.total_amount for po in purchase_orders if po.status in {"approved", "received"})
    cash_out = refunds + po_spend
    return {
        "cash_in": round(cash_in, 2),
        "cash_out": round(cash_out, 2),
        "net_cash": round(cash_in - cash_out, 2),
        "purchase_spend": round(po_spend, 2),
        "refunds": round(refunds, 2),
    }


@app.get("/reports/balance-sheet")
async def balance_sheet(current_user: User = Depends(get_current_user)):
    valuation = await inventory_valuation(current_user)
    cashflow = await cashflow_report(current_user)
    assets_cash = cashflow["net_cash"]
    assets_inventory = valuation["total_value"]
    assets_total = assets_cash + assets_inventory
    liabilities = 0.0  # simple version, chưa tracking nợ
    equity = assets_total - liabilities
    return {
        "as_of": date.today(),
        "assets": {
            "cash": round(assets_cash, 2),
            "inventory": round(assets_inventory, 2),
            "total": round(assets_total, 2),
        },
        "liabilities": round(liabilities, 2),
        "equity": round(equity, 2),
    }


@app.get("/reports/cashflow-statement")
async def cashflow_statement(current_user: User = Depends(get_current_user)):
    cash_in = sum(p.amount for p in payments if p.status == "paid")
    refunds = sum(r.refund_amount or r.amount for r in order_returns)
    po_spend = sum(po.total_amount for po in purchase_orders if po.status in {"approved", "received"})
    operating = cash_in - refunds
    investing = -po_spend
    financing = 0.0
    net = operating + investing + financing
    return {
        "operating": round(operating, 2),
        "investing": round(investing, 2),
        "financing": round(financing, 2),
        "net": round(net, 2),
    }


@app.post("/notifications/test")
async def test_notification(current_user: User = Depends(get_current_user)):
    require_admin(current_user)
    payload = {"message": "Test notification", "timestamp": datetime.utcnow().isoformat()}
    send_notifications(payload)
    return {"ok": True, "sent": True}


@app.get("/reports/content-performance")
async def content_performance(current_user: User = Depends(get_current_user)):
    result = []
    for cp in content_plans:
        actual_views = cp.actual_views or 0
        actual_orders = cp.actual_orders or 0
        conv_order_view = (actual_orders / actual_views) * 100 if actual_views else 0
        result.append(
            {
                "id": cp.id,
                "title": cp.title,
                "platform": cp.platform,
                "status": cp.status,
                "actual_views": actual_views,
                "actual_inquiries": cp.actual_inquiries or 0,
                "actual_saves": cp.actual_saves or 0,
                "actual_orders": actual_orders,
                "actual_revenue": cp.actual_revenue or 0,
                "estimate_views": cp.estimate_views or 0,
                "estimate_inquiries": cp.estimate_inquiries or 0,
                "estimate_saves": cp.estimate_saves or 0,
                "conversion_order_view": round(conv_order_view, 2),
            }
        )
    return sorted(result, key=lambda x: x["actual_views"], reverse=True)


@app.get("/reports/order-attribution")
async def order_attribution(current_user: User = Depends(get_current_user)):
    agg: Dict[str, Dict[str, float]] = {}
    for o in orders:
        key = str(o.source_content_id) if o.source_content_id else "organic"
        totals = compute_order_totals(o)
        bucket = agg.setdefault(
            key,
            {
                "content_id": o.source_content_id,
                "content_title": None,
                "channel": o.channel or "unknown",
                "orders": 0,
                "revenue": 0.0,
                "profit": 0.0,
            },
        )
        bucket["orders"] += 1
        bucket["revenue"] += totals["revenue"]
        bucket["profit"] += totals["profit"]
    for bucket in agg.values():
        if bucket["content_id"]:
            plan = next((c for c in content_plans if c.id == bucket["content_id"]), None)
            if plan:
                bucket["content_title"] = plan.title
                bucket["channel"] = plan.platform or bucket["channel"]
        else:
            bucket["content_title"] = "Organic / Direct"
    return sorted(agg.values(), key=lambda x: x["revenue"], reverse=True)


@app.get("/reports/material-forecast")
async def material_forecast(current_user: User = Depends(get_current_user)):
    horizon_days = 30
    cutoff = date.today() - timedelta(days=horizon_days)
    usage: Dict[int, float] = {}
    for o in orders:
        if o.date < cutoff:
            continue
        for line in o.order_lines:
            product = find_product(line.product_id)
            for mu in product.materials:
                usage[mu.material_id] = usage.get(mu.material_id, 0) + mu.quantity * line.quantity
    forecasts = []
    for mat in materials:
        consumed = usage.get(mat.id, 0)
        avg_daily = consumed / horizon_days if horizon_days else 0
        days_left = (mat.stock_quantity / avg_daily) if avg_daily > 0 else None
        forecasts.append(
            {
                "material_id": mat.id,
                "code": mat.code,
                "name": mat.name,
                "stock": mat.stock_quantity,
                "unit": mat.unit,
                "avg_daily_usage": round(avg_daily, 2),
                "days_left": round(days_left, 1) if days_left is not None else None,
            }
        )
    forecasts = sorted(forecasts, key=lambda x: (x["days_left"] or 9999))
    return forecasts


@app.get("/reports/user-performance")
async def user_performance(current_user: User = Depends(get_current_user)):
    result = []
    for u in users:
        task_done = len([t for t in tasks if t.assignee_id == u.id and t.status == "done"])
        task_open = len([t for t in tasks if t.assignee_id == u.id and t.status != "done"])
        issues_open = len([i for i in issues if i.assigned_to == u.id and i.status != "resolved"])
        issues_resolved = len([i for i in issues if i.assigned_to == u.id and i.status == "resolved"])
        revenue = sum(compute_order_totals(o)["revenue"] for o in orders if o.maker_user_id == u.id)
        result.append(
            {
                "user_id": u.id,
                "name": u.name,
                "tasks_done": task_done,
                "tasks_open": task_open,
                "issues_open": issues_open,
                "issues_resolved": issues_resolved,
                "maker_revenue": round(revenue, 2),
            }
        )
    return sorted(result, key=lambda x: x["maker_revenue"], reverse=True)


@app.get("/reports/issue-sla")
async def issue_sla(current_user: User = Depends(get_current_user)):
    resolved = [i for i in issues if i.status == "resolved" and i.resolution_hours]
    avg_hours = sum(i.resolution_hours for i in resolved) / len(resolved) if resolved else None
    max_hours = max((i.resolution_hours for i in resolved), default=None)
    open_issues = [i for i in issues if i.status != "resolved"]
    high_open = len([i for i in open_issues if i.priority == 3])
    by_priority: List[Dict[str, float]] = []
    for p in [1, 2, 3]:
        resolved_p = [i for i in resolved if i.priority == p]
        open_p = len([i for i in open_issues if i.priority == p])
        avg_p = sum(i.resolution_hours for i in resolved_p) / len(resolved_p) if resolved_p else None
        by_priority.append(
            {
                "priority": p,
                "open": open_p,
                "resolved": len(resolved_p),
                "avg_hours": round(avg_p, 1) if avg_p is not None else None,
            }
        )
    return {
        "open": len(open_issues),
        "high_open": high_open,
        "resolved": len(resolved),
        "avg_hours": round(avg_hours, 1) if avg_hours is not None else None,
        "max_hours": round(max_hours, 1) if max_hours is not None else None,
        "by_priority": by_priority,
    }


@app.get("/reports/funnel")
async def funnel_report(current_user: User = Depends(get_current_user)):
    horizon_days = 30
    cutoff = date.today() - timedelta(days=horizon_days)
    ds_filtered = [d for d in demand_signals if d.week_of >= cutoff]
    total_views = sum(d.views for d in ds_filtered)
    total_inquiries = sum(d.inquiries for d in ds_filtered)
    total_orders = len([o for o in orders if o.date >= cutoff])
    conv_inquiry = (total_inquiries / total_views) * 100 if total_views else 0
    conv_order_view = (total_orders / total_views) * 100 if total_views else 0
    conv_order_inquiry = (total_orders / total_inquiries) * 100 if total_inquiries else 0
    return {
        "views": total_views,
        "inquiries": total_inquiries,
        "orders": total_orders,
        "conv_inquiry": round(conv_inquiry, 2),
        "conv_order_view": round(conv_order_view, 2),
        "conv_order_inquiry": round(conv_order_inquiry, 2),
    }


@app.get("/reports/customer-analytics")
async def customer_analytics(current_user: User = Depends(get_current_user)):
    compute_customer_metrics()
    today = date.today()
    result = []
    for cust in customers:
        if cust.total_orders == 0:
            continue
        recency_days = (today - cust.last_order_date).days if cust.last_order_date else 999
        frequency = cust.total_orders
        monetary = cust.total_spent / cust.total_orders if cust.total_orders else 0
        # simple RFM scoring 1-5
        r_score = 5 if recency_days <= 30 else 4 if recency_days <= 60 else 3 if recency_days <= 120 else 2 if recency_days <= 180 else 1
        f_score = 5 if frequency >= 10 else 4 if frequency >= 6 else 3 if frequency >= 3 else 2 if frequency >= 2 else 1
        m_score = 5 if monetary >= 1_000_000 else 4 if monetary >= 500_000 else 3 if monetary >= 200_000 else 2 if monetary >= 100_000 else 1
        rfm = r_score + f_score + m_score
        result.append(
            {
                "customer_id": cust.id,
                "name": cust.name,
                "source": cust.source,
                "total_orders": cust.total_orders,
                "total_spent": round(cust.total_spent, 2),
                "avg_order": round(monetary, 2),
                "recency_days": recency_days,
                "rfm_score": rfm,
            }
        )
    result = sorted(result, key=lambda x: x["total_spent"], reverse=True)
    return result


@app.get("/reports/inventory-valuation")
async def inventory_valuation(current_user: User = Depends(get_current_user)):
    items = []
    total_value = 0.0
    for m in materials:
        value = m.stock_quantity * m.unit_price
        total_value += value
        items.append(
            {
                "material_id": m.id,
                "code": m.code,
                "name": m.name,
                "stock_quantity": m.stock_quantity,
                "unit_price": m.unit_price,
                "value": value,
            }
        )
    items = sorted(items, key=lambda x: x["value"], reverse=True)
    return {"total_value": round(total_value, 2), "items": items}


@app.get("/export/orders")
async def export_orders(current_user: User = Depends(get_current_user)):
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(
        [
            "id",
            "date",
            "channel",
            "customer_id",
            "status",
            "payment_status",
            "revenue",
            "profit",
            "discount",
            "shipping_fee",
            "promo_code",
        ]
    )
    for o in orders:
        totals = compute_order_totals(o)
        writer.writerow(
            [
                o.id,
                o.date,
                o.channel,
                o.customer_id or "",
                o.status,
                o.payment_status,
                totals["revenue"],
                totals["profit"],
                totals["computed_discount"],
                o.shipping_fee,
                o.promo_code or "",
            ]
        )
    return Response(
        content=output.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="orders.csv"'},
    )


@app.get("/export/products")
async def export_products(current_user: User = Depends(get_current_user)):
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(
        [
            "id",
            "name",
            "category_ids",
            "base_price",
            "material_cost",
            "labor_cost",
            "packaging_cost",
            "marketing_cost",
            "platform_fee_percent",
            "profit_per_unit",
            "profit_margin",
        ]
    )
    for p in products:
        metrics = compute_product_cost(p)
        writer.writerow(
            [
                p.id,
                p.name,
                ",".join(map(str, p.categories)),
                p.base_price,
                metrics["material_cost"],
                metrics["labor_cost"],
                metrics["packaging_cost"],
                metrics["marketing_cost"],
                metrics["platform_fee_percent"],
                metrics["profit_per_unit"],
                metrics["profit_margin"],
            ]
        )
    return Response(
        content=output.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="products.csv"'},
    )


@app.post("/backup")
async def backup_data(current_user: User = Depends(get_current_user)):
    require_admin(current_user)
    os.makedirs("backups", exist_ok=True)
    snapshot = {
        "settings": settings.model_dump(),
        "products": [p.model_dump() for p in products],
        "materials": [m.model_dump() for m in materials],
        "orders": [o.model_dump() for o in orders],
        "customers": [c.model_dump() for c in customers],
        "issues": [i.model_dump() for i in issues],
        "tasks": [t.model_dump() for t in tasks],
        "payments": [p.model_dump() for p in payments],
        "stock_movements": [s.model_dump() for s in stock_movements],
    }
    filename = f"backups/backup-{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}.json"
    with open(filename, "w", encoding="utf-8") as f:
        f.write(json.dumps(snapshot, default=str, ensure_ascii=False, indent=2))
    return Response(
        content=json.dumps(snapshot, default=str, ensure_ascii=False, indent=2),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{os.path.basename(filename)}"'},
    )


@app.get("/export/tasks")
async def export_tasks(
    status: Optional[str] = None,
    assignee_id: Optional[int] = None,
    current_user: User = Depends(get_current_user),
):
    data = tasks
    if status:
        data = [t for t in data if t.status == status]
    if assignee_id is not None:
        data = [t for t in data if t.assignee_id == assignee_id]
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(
        ["id", "title", "description", "assignee_id", "due_date", "priority", "status", "tags", "created_at", "completed_at"]
    )
    for t in data:
        writer.writerow(
            [
                t.id,
                t.title,
                t.description or "",
                t.assignee_id or "",
                t.due_date or "",
                t.priority,
                t.status,
                ",".join(t.tags or []),
                t.created_at,
                t.completed_at or "",
            ]
        )
    return Response(
        content=output.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="tasks.csv"'},
    )


@app.get("/export/issues")
async def export_issues(
    product_id: Optional[int] = None,
    status: Optional[str] = None,
    priority: Optional[int] = None,
    assignee_id: Optional[int] = None,
    q: Optional[str] = None,
    current_user: User = Depends(get_current_user),
):
    data = issues
    if product_id:
        data = [i for i in data if i.product_id == product_id]
    if status:
        data = [i for i in data if i.status == status]
    if priority is not None:
        data = [i for i in data if i.priority == priority]
    if assignee_id is not None:
        data = [i for i in data if i.assigned_to == assignee_id]
    if q:
        q_lower = q.lower()
        data = [i for i in data if q_lower in (i.description or "").lower() or q_lower in (i.type or "").lower()]
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(
        ["id", "product_id", "type", "description", "priority", "status", "assignee_id", "impact_revenue", "created_at", "resolved_at", "resolution_hours"]
    )
    for i in data:
        writer.writerow(
            [
                i.id,
                i.product_id,
                i.type,
                i.description,
                i.priority,
                i.status,
                i.assigned_to or "",
                i.impact_revenue or 0,
                i.created_at,
                i.resolved_at or "",
                i.resolution_hours or "",
            ]
        )
    return Response(
        content=output.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="issues.csv"'},
    )


@app.get("/reports/pnl")
async def report_pnl(
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    current_user: User = Depends(get_current_user),
):
    # default: current month
    today = date.today()
    start = start_date or today.replace(day=1)
    end = end_date or date(today.year, today.month, 28)
    # naive end-of-month: push to next month start then -1 day
    if end_date is None:
        if today.month == 12:
            end = date(today.year + 1, 1, 1)
        else:
            end = date(today.year, today.month + 1, 1)
        end = end - timedelta(days=1)

    filtered = [o for o in orders if start <= o.date <= end]
    gross_revenue = sum(sum(l.unit_price * l.quantity for l in o.order_lines) for o in filtered)
    # discount trước khi trừ refund
    discount = 0.0
    for o in filtered:
        promo_discount = 0.0
        if getattr(o, "promo_code", None):
            promo = next((p for p in promo_codes if p.code.lower() == o.promo_code.lower() and p.is_active), None)
            if promo:
                promo_discount = compute_promo_discount(promo, o.order_lines)
        discount += max(o.discount, promo_discount)

    returns_amount = sum(
        r.refund_amount or r.amount for r in order_returns if r.order_id in {o.id for o in filtered} and r.status in {"approved", "processed"}
    )
    net_revenue = max(0, gross_revenue - discount - returns_amount)

    cogs = 0.0
    shipping_cost = sum(o.shipping_fee for o in filtered)
    for o in filtered:
        for line in o.order_lines:
            product = find_product(line.product_id)
            pcost = compute_product_cost(product)
            cogs += (pcost["material_cost"] + pcost["labor_cost"] + pcost.get("packaging_cost", 0) + pcost.get("marketing_cost", 0) + pcost.get("platform_fee_amount", 0)) * line.quantity
    gross_profit = net_revenue - cogs - shipping_cost
    return {
        "start_date": start,
        "end_date": end,
        "orders_count": len(filtered),
        "gross_revenue": round(gross_revenue, 2),
        "discount": round(discount, 2),
        "returns": round(returns_amount, 2),
        "net_revenue": round(net_revenue, 2),
        "cogs": round(cogs, 2),
        "shipping_cost": round(shipping_cost, 2),
        "gross_profit": round(gross_profit, 2),
    }


@app.get("/products/{product_id}/history")
async def product_history(product_id: int, current_user: User = Depends(get_current_user)):
    history_price = [pc for pc in price_changes if pc.product_id == product_id]
    history_lifecycle = [ev for ev in lifecycle_events if ev.product_id == product_id]
    return {
        "price_changes": history_price,
        "lifecycle": history_lifecycle,
    }


@app.get("/")
def root():
    return {"message": "Handmade Business OS API is running"}


# --- Auth ------------------------------------------------------------------


@app.post("/auth/login", response_model=TokenResponse)
@limiter.limit("5/minute")  # Chống brute force - chỉ cho 5 lần đăng nhập/phút
def login(payload: LoginRequest, request: Request):
    client_ip = request.client.host if request.client else "unknown"
    record_login_attempt(client_ip)
    user = find_user_by_email(payload.email)
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=400, detail="Email hoặc mật khẩu không đúng")
    user.last_login_at = datetime.utcnow()
    # persist to SQL
    with Session(engine) as session:
        row = session.get(UserTable, user.id)
        if row:
            row.last_login_at = user.last_login_at
            session.add(row)
            session.commit()
        else:
            session.add(
                UserTable(
                    id=user.id,
                    name=user.name,
                    email=user.email,
                    password_hash=user.password_hash,
                    role=user.role,
                    is_owner=user.is_owner,
                    created_at=user.created_at,
                    last_login_at=user.last_login_at,
                )
            )
            session.commit()
    upsert_document("users", user, user.id)
    token = create_access_token({"sub": user.id, "role": user.role})
    return TokenResponse(access_token=token)
    return TokenResponse(access_token=token)


@app.get("/me", response_model=UserPublic)
async def me(current_user: User = Depends(get_current_user)):
    if current_user is None:
        from fastapi import HTTPException
        raise HTTPException(status_code=401, detail="Not authenticated")
    return UserPublic.model_validate(current_user.model_dump())


@app.get("/users", response_model=List[UserPublic])
async def list_users(current_user: User = Depends(get_current_user)):
    require_admin(current_user)
    return [UserPublic.model_validate(u.model_dump()) for u in users]


# --- Customer endpoints -----------------------------------------------------
@app.get("/customers")
async def list_customers(
    page: int = 1,
    page_size: int = 50,
    search: Optional[str] = None,
    current_user: User = Depends(get_current_user)
):
    # Filter
    filtered = customers
    if search:
        search_lower = search.lower()
        filtered = [c for c in filtered if
                   search_lower in c.name.lower() or
                   search_lower in (c.phone or "").lower() or
                   search_lower in (c.email or "").lower()]

    # Sort by total_spent descending
    filtered = sorted(filtered, key=lambda x: x.total_spent, reverse=True)

    # Pagination
    total = len(filtered)
    total_pages = (total + page_size - 1) // page_size
    start = (page - 1) * page_size
    end = start + page_size

    return {
        "items": filtered[start:end],
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages
    }


@app.get("/customers/summary")
async def customers_summary(current_user: User = Depends(get_current_user)):
    """
    Optimized endpoint for Customers page - returns all necessary data in 1 call
    Replaces: /customers, /orders, /reports/customer-analytics
    """
    compute_customer_metrics()
    today = date.today()

    # Customer analytics with RFM
    analytics = []
    for cust in customers:
        if cust.total_orders == 0:
            continue
        recency_days = (today - cust.last_order_date).days if cust.last_order_date else 999
        frequency = cust.total_orders
        monetary = cust.total_spent / cust.total_orders if cust.total_orders else 0
        # RFM scoring 1-5
        r_score = 5 if recency_days <= 30 else 4 if recency_days <= 60 else 3 if recency_days <= 120 else 2 if recency_days <= 180 else 1
        f_score = 5 if frequency >= 10 else 4 if frequency >= 6 else 3 if frequency >= 3 else 2 if frequency >= 2 else 1
        m_score = 5 if monetary >= 1_000_000 else 4 if monetary >= 500_000 else 3 if monetary >= 200_000 else 2 if monetary >= 100_000 else 1
        rfm = r_score + f_score + m_score
        analytics.append({
            "customer_id": cust.id,
            "name": cust.name,
            "source": cust.source,
            "total_orders": cust.total_orders,
            "total_spent": round(cust.total_spent, 2),
            "avg_order": round(monetary, 2),
            "recency_days": recency_days,
            "rfm_score": rfm,
        })

    # Statistics
    total_customers = len(customers)
    vip_customers = sum(1 for c in customers if "VIP" in (c.tags or []))
    repeat_customers = sum(1 for c in customers if c.total_orders > 1)
    avg_ltv = sum(c.total_spent for c in customers) / total_customers if total_customers > 0 else 0

    return {
        "customers": customers,
        "orders": orders,
        "analytics": sorted(analytics, key=lambda x: x["total_spent"], reverse=True),
        "statistics": {
            "total": total_customers,
            "vip": vip_customers,
            "repeat": repeat_customers,
            "avg_ltv": round(avg_ltv, 2)
        }
    }


@app.post("/customers", response_model=Customer)
@limiter.limit("30/minute")  # Giới hạn tạo khách hàng
async def create_customer(request: Request, payload: CustomerCreate, current_user: User = Depends(get_current_user)):
    require_admin(current_user)
    new_customer = Customer(
        id=next_id(customers),
        **payload.model_dump(),
        created_by=current_user.id,
        created_at=datetime.utcnow()
    )
    customers.append(new_customer)
    upsert_document("customers", new_customer)
    with Session(engine) as session:
        session.add(CustomerTable(
            id=new_customer.id,
            name=new_customer.name,
            phone=new_customer.phone,
            email=new_customer.email,
            address=new_customer.address,
            source=new_customer.source,
            tags_json=json.dumps(new_customer.tags or []),
            total_orders=0,
            total_spent=0,
            last_order_date=new_customer.last_order_date,
            notes=new_customer.notes,
            created_by=new_customer.created_by,
            created_at=new_customer.created_at,
        ))
        session.commit()
    log_activity(current_user.id, "customer", new_customer.id, "create", changes=payload.model_dump())
    return new_customer


@app.put("/customers/{customer_id}", response_model=Customer)
async def update_customer(customer_id: int, payload: Customer, request: Request, current_user: User = Depends(get_current_user)):
    require_admin(current_user)
    for idx, customer in enumerate(customers):
        if customer.id == customer_id:
            old_data = customer.model_dump()
            payload.id = customer_id
            payload.created_by = customer.created_by
            payload.created_at = customer.created_at
            customers[idx] = payload
            upsert_document("customers", payload, customer_id)
            with Session(engine) as session:
                row = session.get(CustomerTable, customer_id)
                if row:
                    row.name = payload.name
                    row.phone = payload.phone
                    row.email = payload.email
                    row.address = payload.address
                    row.source = payload.source
                    row.tags_json = json.dumps(payload.tags or [])
                    row.notes = payload.notes
                    row.total_orders = payload.total_orders
                    row.total_spent = payload.total_spent
                    row.last_order_date = payload.last_order_date
                    session.add(row)
                    session.commit()
            log_activity(current_user.id, "customer", customer_id, "update", changes=payload.model_dump())
            await create_audit_log(current_user, "UPDATE", "customers", customer_id, old_data, payload.model_dump(), request)
            return payload
    raise HTTPException(status_code=404, detail="Customer không tồn tại")


@app.delete("/customers/{customer_id}")
async def delete_customer(customer_id: int, request: Request, current_user: User = Depends(get_current_user)):
    require_admin(current_user)
    for customer in customers:
        if customer.id == customer_id:
            old_data = customer.model_dump()
            customers.remove(customer)
            delete_document("customers", customer_id)
            with Session(engine) as session:
                row = session.get(CustomerTable, customer_id)
                if row:
                    session.delete(row)
                    session.commit()
            log_activity(current_user.id, "customer", customer_id, "delete")
            await create_audit_log(current_user, "DELETE", "customers", customer_id, old_data, None, request)
            return {"ok": True}
    raise HTTPException(status_code=404, detail="Customer không tồn tại")


@app.post("/customers/auto-tag")
async def auto_tag_customers(current_user: User = Depends(get_current_user)):
    """
    Automatically tag customers based on their behavior
    - VIP: RFM score >= 12
    - repeater: total_orders > 1
    - inactive: last_order > 90 days
    - new: first order < 30 days ago
    """
    require_admin(current_user)
    compute_customer_metrics()
    today = date.today()
    updated_count = 0

    for customer in customers:
        if customer.total_orders == 0:
            continue

        # Calculate RFM
        recency_days = (today - customer.last_order_date).days if customer.last_order_date else 999
        frequency = customer.total_orders
        monetary = customer.total_spent / customer.total_orders if customer.total_orders else 0

        r_score = 5 if recency_days <= 30 else 4 if recency_days <= 60 else 3 if recency_days <= 120 else 2 if recency_days <= 180 else 1
        f_score = 5 if frequency >= 10 else 4 if frequency >= 6 else 3 if frequency >= 3 else 2 if frequency >= 2 else 1
        m_score = 5 if monetary >= 1_000_000 else 4 if monetary >= 500_000 else 3 if monetary >= 200_000 else 2 if monetary >= 100_000 else 1
        rfm_score = r_score + f_score + m_score

        new_tags = set(customer.tags or [])
        changed = False

        # VIP tagging
        if rfm_score >= 12:
            if "VIP" not in new_tags:
                new_tags.add("VIP")
                changed = True
        else:
            if "VIP" in new_tags:
                new_tags.remove("VIP")
                changed = True

        # Repeater tagging
        if frequency > 1:
            if "repeater" not in new_tags:
                new_tags.add("repeater")
                changed = True

        # Inactive tagging
        if recency_days > 90:
            if "inactive" not in new_tags:
                new_tags.add("inactive")
                changed = True
        else:
            if "inactive" in new_tags:
                new_tags.remove("inactive")
                changed = True

        # New customer tagging
        if customer.created_at and (datetime.utcnow() - customer.created_at).days < 30:
            if "new" not in new_tags:
                new_tags.add("new")
                changed = True
        else:
            if "new" in new_tags:
                new_tags.remove("new")
                changed = True

        # Update if changed
        if changed:
            customer.tags = list(new_tags)
            upsert_document("customers", customer, customer.id)
            with Session(engine) as session:
                row = session.get(CustomerTable, customer.id)
                if row:
                    row.tags_json = json.dumps(customer.tags)
                    session.add(row)
                    session.commit()
            updated_count += 1

    return {
        "updated_count": updated_count,
        "message": f"Auto-tagged {updated_count} customers"
    }


@app.get("/customers/lifecycle-analysis")
async def customer_lifecycle_analysis(current_user: User = Depends(get_current_user)):
    """
    Analyze customer lifecycle and suggest actions
    """
    compute_customer_metrics()
    today = date.today()

    segments = {
        "champions": [],
        "loyal": [],
        "at_risk": [],
        "win_back": [],
        "new": [],
        "promising": []
    }

    for customer in customers:
        if customer.total_orders == 0:
            continue

        recency_days = (today - customer.last_order_date).days if customer.last_order_date else 999
        frequency = customer.total_orders
        monetary = customer.total_spent / customer.total_orders if customer.total_orders else 0

        r_score = 5 if recency_days <= 30 else 4 if recency_days <= 60 else 3 if recency_days <= 120 else 2 if recency_days <= 180 else 1
        f_score = 5 if frequency >= 10 else 4 if frequency >= 6 else 3 if frequency >= 3 else 2 if frequency >= 2 else 1
        m_score = 5 if monetary >= 1_000_000 else 4 if monetary >= 500_000 else 3 if monetary >= 200_000 else 2 if monetary >= 100_000 else 1
        rfm_score = r_score + f_score + m_score

        customer_data = {
            "customer_id": customer.id,
            "name": customer.name,
            "recency_days": recency_days,
            "frequency": frequency,
            "monetary": round(monetary, 2),
            "rfm_score": rfm_score,
            "suggested_action": ""
        }

        # Segment customers
        if r_score >= 4 and f_score >= 4 and m_score >= 4:
            customer_data["suggested_action"] = "VIP treatment: Exclusive offers, early access"
            segments["champions"].append(customer_data)
        elif f_score >= 3 and m_score >= 3:
            customer_data["suggested_action"] = "Loyalty rewards, thank you notes"
            segments["loyal"].append(customer_data)
        elif r_score <= 2 and f_score >= 2:
            customer_data["suggested_action"] = "Win-back campaign: Special discount"
            segments["win_back"].append(customer_data)
        elif r_score == 3 and f_score >= 2:
            customer_data["suggested_action"] = "Re-engagement: New collection"
            segments["at_risk"].append(customer_data)
        elif frequency == 1 and recency_days <= 30:
            customer_data["suggested_action"] = "Welcome series, second purchase"
            segments["new"].append(customer_data)
        elif frequency == 1 and recency_days <= 60:
            customer_data["suggested_action"] = "Follow-up, ask for feedback"
            segments["promising"].append(customer_data)

    return {
        "segments": segments,
        "summary": {
            "champions": len(segments["champions"]),
            "loyal": len(segments["loyal"]),
            "at_risk": len(segments["at_risk"]),
            "win_back": len(segments["win_back"]),
            "new": len(segments["new"]),
            "promising": len(segments["promising"])
        }
    }


# --- Stock Movement endpoints -----------------------------------------------
@app.get("/stock-movements", response_model=List[StockMovement])
async def list_stock_movements(material_id: Optional[int] = None):
    if material_id:
        return [sm for sm in stock_movements if sm.material_id == material_id]
    return stock_movements


@app.post("/stock-movements", response_model=StockMovement)
async def create_stock_movement(payload: StockMovementCreate, current_user: User = Depends(get_current_user)):
    require_admin(current_user)
    find_material(payload.material_id)
    new_movement = StockMovement(
        id=next_id(stock_movements),
        **payload.model_dump(),
        user_id=current_user.id,
        created_at=datetime.utcnow()
    )
    stock_movements.append(new_movement)
    upsert_document("stock_movements", new_movement)
    with Session(engine) as session:
        session.add(stock_movement_to_table(new_movement))
        session.commit()

    # Update material stock
    material = find_material(new_movement.material_id)
    material.stock_quantity += new_movement.quantity_change
    save_material_sql(material)
    upsert_document("materials", material, material.id)

    log_activity(current_user.id, "stock_movement", new_movement.id, "create", changes=payload.model_dump())
    return new_movement


# --- Payment endpoints ------------------------------------------------------
@app.get("/payments", response_model=List[Payment])
async def list_payments(order_id: Optional[int] = None, current_user: User = Depends(get_current_user)):
    if order_id:
        return [p for p in payments if p.order_id == order_id]
    return payments


@app.post("/payments", response_model=Payment)
async def create_payment(payload: PaymentCreate, current_user: User = Depends(get_current_user)):
    require_admin(current_user)
    normalized_status = validate_payment_payload(payload)
    order = find_order(payload.order_id)
    new_payment = Payment(
        id=next_id(payments),
        order_id=payload.order_id,
        amount=payload.amount,
        method=payload.method,
        status=normalized_status,
        transaction_id=payload.transaction_id,
        paid_date=datetime.utcnow() if normalized_status == "paid" else None,
        notes=payload.notes,
        created_at=datetime.utcnow()
    )
    payments.append(new_payment)
    upsert_document("payments", new_payment)
    with Session(engine) as session:
        session.add(PaymentTable(
            id=new_payment.id,
            order_id=new_payment.order_id,
            amount=new_payment.amount,
            method=new_payment.method,
            status=new_payment.status,
            transaction_id=new_payment.transaction_id,
            paid_date=new_payment.paid_date,
            notes=new_payment.notes,
            created_at=new_payment.created_at,
        ))
        session.commit()

    # Update order payment status
    total_paid = sum(p.amount for p in payments if p.order_id == payload.order_id and p.status == "paid")
    totals = compute_order_totals(order)
    if total_paid >= totals["revenue"]:
        order.payment_status = "paid"
    elif total_paid > 0:
        order.payment_status = "partial"
    else:
        order.payment_status = "unpaid"
    save_order_sql(order)
    upsert_document("orders", order, order.id)

    log_activity(current_user.id, "payment", new_payment.id, "create", changes=new_payment.model_dump())
    return new_payment


# --- Product Variants endpoints ---------------------------------------------
@app.get("/variants", response_model=List[ProductVariant])
async def list_variants(product_id: Optional[int] = None, current_user: User = Depends(get_current_user)):
    if product_id:
        return [v for v in product_variants if v.product_id == product_id]
    return product_variants


@app.post("/variants", response_model=ProductVariant)
async def create_variant(payload: ProductVariantCreate, current_user: User = Depends(get_current_user)):
    require_admin(current_user)
    validate_product_exists(payload.product_id)
    new_variant = ProductVariant(
        id=next_id(product_variants),
        **payload.model_dump(),
        created_at=datetime.utcnow()
    )
    product_variants.append(new_variant)
    upsert_document("product_variants", new_variant)
    with Session(engine) as session:
        session.add(ProductVariantTable(
            id=new_variant.id,
            product_id=new_variant.product_id,
            name=new_variant.name,
            sku=new_variant.sku,
            price_modifier=new_variant.price_modifier,
            stock_quantity=new_variant.stock_quantity,
            is_active=new_variant.is_active,
            created_at=new_variant.created_at,
        ))
        session.commit()
    log_activity(current_user.id, "variant", new_variant.id, "create", changes=payload.model_dump())
    return new_variant


@app.put("/variants/{variant_id}", response_model=ProductVariant)
async def update_variant(variant_id: int, payload: ProductVariantCreate, current_user: User = Depends(get_current_user)):
    require_admin(current_user)
    validate_product_exists(payload.product_id)
    for variant in product_variants:
        if variant.id == variant_id:
            old = variant.model_dump()
            for k, v in payload.model_dump().items():
                setattr(variant, k, v)
            upsert_document("product_variants", variant, variant_id)
            save_variant_sql(variant)
            log_activity(current_user.id, "variant", variant_id, "update", changes={"old": old, "new": variant.model_dump()})
            return variant
    raise HTTPException(status_code=404, detail="Variant không tồn tại")


@app.delete("/variants/{variant_id}")
async def delete_variant(variant_id: int, current_user: User = Depends(get_current_user)):
    require_admin(current_user)
    for variant in product_variants:
        if variant.id == variant_id:
            product_variants.remove(variant)
            delete_document("product_variants", variant_id)
            with Session(engine) as session:
                row = session.get(ProductVariantTable, variant_id)
                if row:
                    session.delete(row)
                    session.commit()
            log_activity(current_user.id, "variant", variant_id, "delete")
            return {"ok": True}
    raise HTTPException(status_code=404, detail="Variant không tồn tại")


# --- Product bundles --------------------------------------------------------
@app.get("/bundles", response_model=List[ProductBundle])
async def list_bundles(parent_product_id: Optional[int] = None, current_user: User = Depends(get_current_user)):
    if parent_product_id:
        return [b for b in product_bundles if b.parent_product_id == parent_product_id]
    return product_bundles


@app.post("/bundles", response_model=ProductBundle)
async def create_bundle(payload: ProductBundleCreate, current_user: User = Depends(get_current_user)):
    require_admin(current_user)
    validate_product_exists(payload.parent_product_id)
    validate_product_exists(payload.child_product_id)
    new_bundle = ProductBundle(id=next_id(product_bundles), **payload.model_dump(), created_at=datetime.utcnow())
    product_bundles.append(new_bundle)
    upsert_document("product_bundles", new_bundle)
    log_activity(current_user.id, "bundle", new_bundle.id, "create", changes=payload.model_dump())
    return new_bundle


@app.delete("/bundles/{bundle_id}")
async def delete_bundle(bundle_id: int, current_user: User = Depends(get_current_user)):
    require_admin(current_user)
    for b in product_bundles:
        if b.id == bundle_id:
            product_bundles.remove(b)
            delete_document("product_bundles", bundle_id)
            log_activity(current_user.id, "bundle", bundle_id, "delete")
            return {"detail": "Đã xóa"}
    raise HTTPException(status_code=404, detail="Bundle không tồn tại")


# --- Product images ---------------------------------------------------------
@app.get("/product-images", response_model=List[ProductImage])
async def list_product_images(product_id: Optional[int] = None, current_user: User = Depends(get_current_user)):
    if product_id:
        return sorted([img for img in product_images if img.product_id == product_id], key=lambda x: x.display_order)
    return sorted(product_images, key=lambda x: (x.product_id, x.display_order))


@app.post("/product-images", response_model=ProductImage)
async def create_product_image(payload: ProductImageCreate, current_user: User = Depends(get_current_user)):
    require_admin(current_user)
    validate_product_exists(payload.product_id)
    img = ProductImage(id=next_id(product_images), **payload.model_dump(), created_at=datetime.utcnow())
    product_images.append(img)
    upsert_document("product_images", img)
    log_activity(current_user.id, "product_image", img.id, "create", changes=payload.model_dump())
    return img


@app.delete("/product-images/{image_id}")
async def delete_product_image(image_id: int, current_user: User = Depends(get_current_user)):
    require_admin(current_user)
    for img in product_images:
        if img.id == image_id:
            product_images.remove(img)
            delete_document("product_images", image_id)
            log_activity(current_user.id, "product_image", image_id, "delete")
            return {"detail": "Đã xóa"}
    raise HTTPException(status_code=404, detail="Ảnh không tồn tại")


# --- Product reviews --------------------------------------------------------
@app.get("/reviews", response_model=List[ProductReview])
async def list_reviews(product_id: Optional[int] = None, current_user: User = Depends(get_current_user)):
    if product_id:
        return [r for r in product_reviews if r.product_id == product_id]
    return product_reviews


@app.post("/reviews", response_model=ProductReview)
async def create_review(payload: ProductReviewCreate):
    validate_product_exists(payload.product_id)
    review = ProductReview(id=next_id(product_reviews), **payload.model_dump(), created_at=datetime.utcnow())
    product_reviews.append(review)
    upsert_document("product_reviews", review)
    log_activity(0, "review", review.id, "create", changes=payload.model_dump())
    return review


@app.delete("/reviews/{review_id}")
async def delete_review(review_id: int, current_user: User = Depends(get_current_user)):
    require_admin(current_user)
    for r in product_reviews:
        if r.id == review_id:
            product_reviews.remove(r)
            delete_document("product_reviews", review_id)
            log_activity(current_user.id, "review", review_id, "delete")
            return {"detail": "Đã xóa"}
    raise HTTPException(status_code=404, detail="Review không tồn tại")


# --- Categories -------------------------------------------------------------
@app.get("/categories", response_model=List[Category])
async def list_categories():
    return categories


@app.post("/categories", response_model=Category)
async def create_category(payload: CategoryCreate, current_user: User = Depends(get_current_user)):
    require_admin(current_user)
    if payload.parent_id:
        if not any(c.id == payload.parent_id for c in categories):
            raise HTTPException(status_code=404, detail="Danh mục cha không tồn tại")
    cat = Category(id=next_id(categories), **payload.model_dump(), created_at=datetime.utcnow())
    categories.append(cat)
    upsert_document("categories", cat)
    log_activity(current_user.id, "category", cat.id, "create", changes=payload.model_dump())
    return cat


@app.delete("/categories/{category_id}")
async def delete_category(category_id: int, current_user: User = Depends(get_current_user)):
    require_admin(current_user)
    for c in categories:
        if c.id == category_id:
            categories.remove(c)
            delete_document("categories", category_id)
            log_activity(current_user.id, "category", category_id, "delete")
            return {"detail": "Đã xóa"}
    raise HTTPException(status_code=404, detail="Danh mục không tồn tại")


# --- Promo codes ------------------------------------------------------------
@app.get("/promo-codes", response_model=List[PromoCode])
async def list_promo_codes(current_user: User = Depends(get_current_user)):
    return promo_codes


# --- Order returns / refunds -----------------------------------------------
@app.get("/returns", response_model=List[OrderReturn])
async def list_returns(order_id: Optional[int] = None, current_user: User = Depends(get_current_user)):
    if order_id:
        return [r for r in order_returns if r.order_id == order_id]
    return order_returns


@app.post("/returns", response_model=OrderReturn)
async def create_return(payload: OrderReturnCreate, current_user: User = Depends(get_current_user)):
    require_admin(current_user)
    if payload.amount <= 0:
        raise HTTPException(status_code=400, detail="Số tiền hoàn phải > 0")
    order = find_order(payload.order_id)
    new_return = OrderReturn(
        id=next_id(order_returns),
        **payload.model_dump(),
        status="approved",
        refund_amount=payload.refund_amount or payload.amount,
        created_by=current_user.id,
        created_at=datetime.utcnow(),
    )
    order_returns.append(new_return)
    adjust_payment_status_for_refund(order)
    upsert_document("order_returns", new_return)
    save_order_return_sql(new_return)
    save_order_sql(order)
    log_activity(current_user.id, "return", new_return.id, "create", changes=payload.model_dump())
    return new_return


# --- Suppliers --------------------------------------------------------------
@app.get("/suppliers", response_model=List[Supplier])
async def list_suppliers(current_user: User = Depends(get_current_user)):
    return suppliers


@app.post("/suppliers", response_model=Supplier)
async def create_supplier(payload: SupplierCreate, current_user: User = Depends(get_current_user)):
    require_admin(current_user)
    new_supplier = Supplier(id=next_id(suppliers), **payload.model_dump(), created_at=datetime.utcnow())
    suppliers.append(new_supplier)
    upsert_document("suppliers", new_supplier)
    with Session(engine) as session:
        session.add(supplier_to_table(new_supplier))
        session.commit()
    log_activity(current_user.id, "supplier", new_supplier.id, "create", changes=payload.model_dump())
    return new_supplier


@app.put("/suppliers/{supplier_id}", response_model=Supplier)
async def update_supplier(supplier_id: int, payload: SupplierCreate, current_user: User = Depends(get_current_user)):
    require_admin(current_user)
    for idx, sup in enumerate(suppliers):
        if sup.id == supplier_id:
            updated = Supplier(id=supplier_id, **payload.model_dump(), created_at=sup.created_at)
            suppliers[idx] = updated
            upsert_document("suppliers", updated, supplier_id)
            with Session(engine) as session:
                session.merge(supplier_to_table(updated))
                session.commit()
            log_activity(current_user.id, "supplier", supplier_id, "update", changes=payload.model_dump())
            return updated
    raise HTTPException(status_code=404, detail="Supplier không tồn tại")


@app.delete("/suppliers/{supplier_id}")
async def delete_supplier(supplier_id: int, current_user: User = Depends(get_current_user)):
    require_admin(current_user)
    for sup in suppliers:
        if sup.id == supplier_id:
            suppliers.remove(sup)
            delete_document("suppliers", supplier_id)
            with Session(engine) as session:
                row = session.get(SupplierTable, supplier_id)
                if row:
                    session.delete(row)
                    session.commit()
            log_activity(current_user.id, "supplier", supplier_id, "delete")
            return {"detail": "Đã xóa"}
    raise HTTPException(status_code=404, detail="Supplier không tồn tại")


# --- Purchase Orders --------------------------------------------------------
@app.get("/purchase-orders", response_model=List[PurchaseOrder])
async def list_purchase_orders(current_user: User = Depends(get_current_user)):
    return purchase_orders


@app.post("/purchase-orders", response_model=PurchaseOrder)
async def create_purchase_order(payload: PurchaseOrderCreate, current_user: User = Depends(get_current_user)):
    require_admin(current_user)
    validate_purchase_order_payload(payload)
    total_amount = compute_po_total(payload.lines)
    po = PurchaseOrder(
        id=next_id(purchase_orders),
        supplier_id=payload.supplier_id,
        status=payload.status,
        expected_date=payload.expected_date,
        note=payload.note,
        lines=payload.lines,
        total_amount=total_amount,
        created_by=current_user.id,
        created_at=datetime.utcnow(),
    )
    if po.status == "received":
        receive_purchase_order(po, current_user)
    purchase_orders.append(po)
    upsert_document("purchase_orders", po)
    with Session(engine) as session:
        session.add(po_to_table(po))
        session.commit()
    log_activity(current_user.id, "purchase_order", po.id, "create", changes=payload.model_dump())
    return po


@app.put("/purchase-orders/{po_id}", response_model=PurchaseOrder)
async def update_purchase_order(po_id: int, payload: PurchaseOrderCreate, current_user: User = Depends(get_current_user)):
    require_admin(current_user)
    validate_purchase_order_payload(payload)
    for idx, po in enumerate(purchase_orders):
        if po.id == po_id:
            previous_status = po.status
            updated = PurchaseOrder(
                id=po_id,
                supplier_id=payload.supplier_id,
                status=payload.status,
                expected_date=payload.expected_date,
                note=payload.note,
                lines=payload.lines,
                total_amount=compute_po_total(payload.lines),
                created_by=po.created_by,
                created_at=po.created_at,
                received_at=po.received_at,
            )
            if previous_status != "received" and payload.status == "received":
                receive_purchase_order(updated, current_user)
            purchase_orders[idx] = updated
            upsert_document("purchase_orders", updated, po_id)
            with Session(engine) as session:
                session.merge(po_to_table(updated))
                session.commit()
            log_activity(current_user.id, "purchase_order", po_id, "update", changes=payload.model_dump())
            return updated
    raise HTTPException(status_code=404, detail="Purchase order không tồn tại")


@app.get("/purchase-orders/suggestions")
async def suggest_purchase_orders(current_user: User = Depends(get_current_user)):
    """
    Auto-suggest purchase orders for materials running low
    Based on: current stock, low threshold, weekly usage, lead time
    """
    suggestions = []

    for material in materials:
        # Check if below threshold
        if material.stock_quantity > material.low_threshold:
            continue

        # Calculate weekly usage from recent orders
        weekly_usage = 0
        for product in products:
            for usage in product.materials:
                if usage.material_id == material.id:
                    # Count units sold in last 30 days
                    recent_orders = [o for o in orders if (date.today() - o.date).days <= 30]
                    units_sold = sum(
                        line.quantity
                        for order in recent_orders
                        for line in order.order_lines
                        if line.product_id == product.id
                    )
                    weekly_usage += (units_sold * usage.quantity) / 4  # 4 weeks

        # Calculate weeks remaining
        weeks_remaining = material.stock_quantity / weekly_usage if weekly_usage > 0 else 999

        # Calculate suggested order quantity
        # Order enough for 4 weeks + safety stock (2 weeks)
        suggested_quantity = weekly_usage * 6 if weekly_usage > 0 else material.low_threshold * 3

        # Find preferred supplier (most recent purchase)
        recent_po = None
        for po in reversed(purchase_orders):
            for line in po.lines:
                if line.material_id == material.id:
                    recent_po = po
                    break
            if recent_po:
                break

        suggestions.append({
            "material_id": material.id,
            "material_code": material.code,
            "material_name": material.name,
            "current_stock": material.stock_quantity,
            "low_threshold": material.low_threshold,
            "weekly_usage": round(weekly_usage, 2),
            "weeks_remaining": round(weeks_remaining, 2),
            "suggested_quantity": round(suggested_quantity, 2),
            "unit_price": material.unit_price,
            "estimated_cost": round(suggested_quantity * material.unit_price, 2),
            "suggested_supplier_id": recent_po.supplier_id if recent_po else None,
            "urgency": "critical" if weeks_remaining < 1 else "high" if weeks_remaining < 2 else "medium"
        })

    # Sort by urgency
    urgency_order = {"critical": 0, "high": 1, "medium": 2}
    suggestions.sort(key=lambda x: (urgency_order[x["urgency"]], x["weeks_remaining"]))

    return suggestions


@app.post("/purchase-orders/auto-create")
async def auto_create_purchase_orders(
    material_ids: List[int],
    current_user: User = Depends(get_current_user)
):
    """
    Automatically create purchase orders for selected materials
    """
    require_admin(current_user)

    # Get suggestions
    suggestions_response = await suggest_purchase_orders(current_user)
    suggestions = {s["material_id"]: s for s in suggestions_response}

    # Group by supplier
    by_supplier = {}
    for material_id in material_ids:
        if material_id not in suggestions:
            continue

        suggestion = suggestions[material_id]
        supplier_id = suggestion["suggested_supplier_id"]

        # If no supplier, use first supplier or create generic
        if not supplier_id and suppliers:
            supplier_id = suppliers[0].id
        elif not supplier_id:
            continue

        if supplier_id not in by_supplier:
            by_supplier[supplier_id] = []

        by_supplier[supplier_id].append({
            "material_id": material_id,
            "quantity": suggestion["suggested_quantity"],
            "unit_price": suggestion["unit_price"],
            "batch_id": None,
            "expiry_date": None
        })

    # Create POs
    created_pos = []
    for supplier_id, lines in by_supplier.items():
        payload = PurchaseOrderCreate(
            supplier_id=supplier_id,
            status="draft",
            expected_date=date.today() + timedelta(days=7),  # 1 week lead time
            note="Auto-generated based on low stock alerts",
            lines=lines
        )

        po = await create_purchase_order(payload, current_user)
        created_pos.append(po)

    return {
        "created_count": len(created_pos),
        "purchase_orders": created_pos
    }


# ============================================================================
# BUSINESS INTELLIGENCE & STRATEGIC PLANNING APIs
# ============================================================================

@app.get("/business-health")
async def get_business_health(current_user: User = Depends(get_current_user)):
    """
    Calculate comprehensive business health metrics based on proven frameworks:
    - North Star Metric (primary growth indicator)
    - Unit Economics (CAC, LTV, payback period)
    - Health Score (0-100 composite score)
    """
    # Calculate key metrics
    total_customers = len(customers)
    total_orders = len(orders)
    total_revenue = sum(compute_order_totals(o)["revenue"] for o in orders)

    # Calculate date ranges
    now = datetime.utcnow()
    thirty_days_ago = now - timedelta(days=30)
    ninety_days_ago = now - timedelta(days=90)

    # Recent metrics (last 30 days)
    recent_orders = [o for o in orders if o.date >= thirty_days_ago.date()]
    recent_revenue = sum(compute_order_totals(o)["revenue"] for o in recent_orders)
    recent_customers = len(set(o.customer_id for o in recent_orders))

    # Previous 30 days for comparison
    sixty_days_ago = now - timedelta(days=60)
    previous_orders = [o for o in orders if sixty_days_ago.date() <= o.date < thirty_days_ago.date()]
    previous_revenue = sum(compute_order_totals(o)["revenue"] for o in previous_orders)

    # North Star Metric: Monthly Active Revenue (MAR)
    # For handmade business: Revenue per Active Customer
    mar = recent_revenue / recent_customers if recent_customers > 0 else 0

    # Unit Economics
    # CAC (Customer Acquisition Cost) - estimate from content & ads
    total_content = len(content_plans)
    estimated_content_cost = total_content * 50000  # 50k VND per content
    cac = estimated_content_cost / total_customers if total_customers > 0 else 0

    # LTV (Customer Lifetime Value)
    avg_order_value = total_revenue / total_orders if total_orders > 0 else 0
    # Calculate repeat purchase rate
    customer_order_counts = {}
    for order in orders:
        customer_order_counts[order.customer_id] = customer_order_counts.get(order.customer_id, 0) + 1

    repeat_customers = sum(1 for count in customer_order_counts.values() if count > 1)
    repeat_rate = repeat_customers / total_customers if total_customers > 0 else 0

    # LTV = AOV * Purchase Frequency * Customer Lifespan (estimate 2 years for handmade)
    avg_purchases_per_customer = total_orders / total_customers if total_customers > 0 else 1
    ltv = avg_order_value * avg_purchases_per_customer * 2  # 2 year lifespan

    # LTV/CAC Ratio (healthy is > 3)
    ltv_cac_ratio = ltv / cac if cac > 0 else 0

    # Payback Period (months to recover CAC)
    monthly_revenue_per_customer = mar
    payback_period = cac / monthly_revenue_per_customer if monthly_revenue_per_customer > 0 else 0

    # Burn Rate & Runway
    # Estimate monthly costs
    monthly_material_cost = sum(m.stock_quantity * m.unit_price for m in materials) / 12  # Assuming 1 year of inventory
    monthly_fixed_costs = 5000000  # 5M VND estimate for overhead
    monthly_burn = monthly_material_cost + monthly_fixed_costs + estimated_content_cost / 12

    # Gross Margin
    total_material_cost = sum(
        sum(usage.quantity * next((m.unit_price for m in materials if m.id == usage.material_id), 0)
            for usage in p.materials)
        for p in products
    )
    gross_margin = (total_revenue - total_material_cost) / total_revenue if total_revenue > 0 else 0

    # Health Score Calculation (0-100)
    # Based on 5 pillars
    health_components = {
        "revenue_growth": min(100, ((recent_revenue - previous_revenue) / previous_revenue * 100) if previous_revenue > 0 else 50),
        "ltv_cac_ratio": min(100, ltv_cac_ratio / 5 * 100),  # Normalize to 5 as excellent
        "gross_margin": gross_margin * 100,
        "repeat_rate": repeat_rate * 100,
        "inventory_efficiency": min(100, (1 - len([m for m in materials if m.stock_quantity < m.low_threshold]) / len(materials)) * 100 if materials else 0)
    }

    health_score = sum(health_components.values()) / len(health_components)

    # Growth Rate
    revenue_growth_rate = ((recent_revenue - previous_revenue) / previous_revenue * 100) if previous_revenue > 0 else 0

    return {
        "north_star_metric": {
            "name": "Monthly Active Revenue (MAR)",
            "value": round(mar, 0),
            "unit": "VND/customer",
            "description": "Revenue per active customer in last 30 days"
        },
        "unit_economics": {
            "cac": round(cac, 0),
            "ltv": round(ltv, 0),
            "ltv_cac_ratio": round(ltv_cac_ratio, 2),
            "payback_period": round(payback_period, 1),
            "avg_order_value": round(avg_order_value, 0),
            "repeat_rate": round(repeat_rate * 100, 1)
        },
        "financial_metrics": {
            "total_revenue": round(total_revenue, 0),
            "recent_revenue": round(recent_revenue, 0),
            "revenue_growth_rate": round(revenue_growth_rate, 1),
            "gross_margin": round(gross_margin * 100, 1),
            "monthly_burn": round(monthly_burn, 0)
        },
        "health_score": {
            "overall": round(health_score, 1),
            "components": {k: round(v, 1) for k, v in health_components.items()},
            "rating": "excellent" if health_score >= 80 else "good" if health_score >= 60 else "fair" if health_score >= 40 else "poor"
        },
        "summary": {
            "total_customers": total_customers,
            "total_orders": total_orders,
            "active_customers_30d": recent_customers,
            "avg_purchases_per_customer": round(avg_purchases_per_customer, 2)
        }
    }


@app.get("/growth/aarrr-metrics")
async def get_aarrr_metrics(current_user: User = Depends(get_current_user)):
    """
    AARRR Pirate Metrics Framework for Growth
    - Acquisition: How people find you
    - Activation: First experience
    - Retention: Coming back
    - Revenue: Monetization
    - Referral: Word of mouth
    """
    now = datetime.utcnow()
    thirty_days_ago = now - timedelta(days=30)
    ninety_days_ago = now - timedelta(days=90)

    # Acquisition Metrics
    new_customers_30d = [c for c in customers if c.created_at >= thirty_days_ago]
    new_customers_90d = [c for c in customers if c.created_at >= ninety_days_ago]

    # Traffic sources (from content)
    content_views = sum(cp.estimate_views or 0 for cp in content_plans)
    content_engagement = sum(cp.estimate_inquiries or 0 for cp in content_plans)

    # Activation Metrics (customers who made first purchase within 7 days of signup)
    activated_customers = 0
    for customer in new_customers_30d:
        first_order = next((o for o in orders if hasattr(o, 'customer_id') and o.customer_id == customer.id), None)
        if first_order and hasattr(first_order, 'date') and first_order.date:
            order_datetime = datetime.combine(first_order.date, datetime.min.time())
            days_diff = (order_datetime - customer.created_at).days
            if days_diff <= 7:
                activated_customers += 1

    activation_rate = activated_customers / len(new_customers_30d) if new_customers_30d else 0

    # Retention Metrics
    # Cohort: customers from 60-90 days ago who made purchase in last 30 days
    sixty_days_ago = now - timedelta(days=60)
    cohort_customers = [c for c in customers if c.created_at and ninety_days_ago <= c.created_at < sixty_days_ago]
    retained_customers = []
    for c in cohort_customers:
        has_recent_order = any(
            hasattr(o, 'customer_id') and hasattr(o, 'date') and
            o.customer_id == c.id and o.date and o.date >= thirty_days_ago.date()
            for o in orders
        )
        if has_recent_order:
            retained_customers.append(c)
    retention_rate = len(retained_customers) / len(cohort_customers) if cohort_customers else 0

    # Revenue Metrics
    total_revenue = 0
    revenue_30d = 0
    paying_customer_ids = set()

    for o in orders:
        try:
            totals = compute_order_totals(o)
            revenue = totals.get("revenue", 0)
            total_revenue += revenue

            if hasattr(o, 'date') and o.date and o.date >= thirty_days_ago.date():
                revenue_30d += revenue

            if hasattr(o, 'customer_id') and o.customer_id:
                paying_customer_ids.add(o.customer_id)
        except Exception as e:
            # Skip orders that cause errors
            continue

    arpu = total_revenue / len(customers) if customers else 0  # Average Revenue Per User
    paying_customers = len(paying_customer_ids)
    arppu = total_revenue / paying_customers if paying_customers > 0 else 0

    # Referral Metrics (customers with referral tag or word-of-mouth)
    referral_customers = []
    for c in customers:
        tags_list = c.tags if c.tags else []
        tags_str = ' '.join(tags_list).lower() if isinstance(tags_list, list) else str(tags_list).lower()
        if 'referral' in tags_str or 'word-of-mouth' in tags_str:
            referral_customers.append(c)
    referral_rate = len(referral_customers) / len(customers) if customers else 0

    # Calculate funnel conversion rates
    funnel_data = {
        "acquisition": {
            "visitors": content_views,  # Estimated from content views
            "leads": content_engagement,  # Engaged viewers
            "customers": len(new_customers_30d)
        },
        "activation": {
            "signups": len(new_customers_30d),
            "activated": activated_customers,
            "rate": round(activation_rate * 100, 1)
        },
        "retention": {
            "cohort_size": len(cohort_customers),
            "retained": len(retained_customers),
            "rate": round(retention_rate * 100, 1)
        },
        "revenue": {
            "total_customers": len(customers),
            "paying_customers": paying_customers,
            "arpu": round(arpu, 0),
            "arppu": round(arppu, 0),
            "mrr": round(revenue_30d, 0)
        },
        "referral": {
            "total_customers": len(customers),
            "referral_customers": len(referral_customers),
            "rate": round(referral_rate * 100, 1)
        }
    }

    # Growth insights
    insights = []
    if activation_rate < 0.3:
        insights.append({
            "type": "warning",
            "metric": "Activation",
            "message": f"Activation rate is low ({activation_rate*100:.1f}%). Focus on first-time buyer experience.",
            "action": "Create welcome discount or first-purchase bundle"
        })

    if retention_rate < 0.2:
        insights.append({
            "type": "warning",
            "metric": "Retention",
            "message": f"Retention rate is {retention_rate*100:.1f}%. Customers not coming back.",
            "action": "Implement loyalty program or email remarketing"
        })

    if referral_rate < 0.1:
        insights.append({
            "type": "opportunity",
            "metric": "Referral",
            "message": f"Only {referral_rate*100:.1f}% customers from referrals. Huge growth opportunity.",
            "action": "Create referral program with incentives"
        })

    if activation_rate > 0.5:
        insights.append({
            "type": "success",
            "metric": "Activation",
            "message": f"Strong activation rate ({activation_rate*100:.1f}%). Keep this momentum!",
            "action": "Document what works and scale acquisition"
        })

    # Calculate revenue growth safely
    revenue_prev_period = total_revenue - revenue_30d
    if revenue_prev_period > 0:
        revenue_growth = round((revenue_30d / revenue_prev_period * 100), 1)
    else:
        revenue_growth = 100.0 if revenue_30d > 0 else 0.0

    return {
        "funnel": funnel_data,
        "insights": insights,
        "summary": {
            "acquisition_velocity": len(new_customers_30d),
            "activation_rate": round(activation_rate * 100, 1),
            "retention_rate": round(retention_rate * 100, 1),
            "revenue_growth": revenue_growth,
            "referral_rate": round(referral_rate * 100, 1)
        },
        "period": "last_30_days"
    }


@app.get("/customers/cohort-analysis")
async def get_cohort_analysis(current_user: User = Depends(get_current_user)):
    """
    Cohort analysis: Track customer behavior grouped by signup month
    Shows retention and revenue patterns over time
    """
    from collections import defaultdict

    # Group customers by first purchase month
    cohorts = defaultdict(list)
    for customer in customers:
        cohort_month = customer.created_at.strftime("%Y-%m")
        cohorts[cohort_month].append(customer)

    # Calculate retention for each cohort
    cohort_data = []
    for cohort_month, cohort_customers in sorted(cohorts.items()):
        cohort_size = len(cohort_customers)
        cohort_start = datetime.strptime(cohort_month, "%Y-%m")

        # Calculate retention for each month after cohort start
        retention_by_month = {}
        revenue_by_month = {}

        for i in range(12):  # Track up to 12 months
            month_start = cohort_start + timedelta(days=30 * i)
            month_end = month_start + timedelta(days=30)

            # Count customers who made purchase in this month
            active_in_month = set()
            revenue_in_month = 0

            for order in orders:
                if order.customer_id in [c.id for c in cohort_customers]:
                    if month_start <= order.created_at < month_end:
                        active_in_month.add(order.customer_id)
                        revenue_in_month += order.total

            retention_rate = len(active_in_month) / cohort_size if cohort_size > 0 else 0
            avg_revenue = revenue_in_month / cohort_size if cohort_size > 0 else 0

            retention_by_month[f"month_{i}"] = round(retention_rate * 100, 1)
            revenue_by_month[f"month_{i}"] = round(avg_revenue, 0)

        # Calculate LTV for this cohort
        cohort_orders = [o for o in orders if o.customer_id in [c.id for c in cohort_customers]]
        cohort_revenue = sum(compute_order_totals(o)["revenue"] for o in cohort_orders)
        cohort_ltv = cohort_revenue / cohort_size if cohort_size > 0 else 0

        cohort_data.append({
            "cohort": cohort_month,
            "size": cohort_size,
            "retention": retention_by_month,
            "revenue": revenue_by_month,
            "ltv": round(cohort_ltv, 0),
            "total_orders": len(cohort_orders)
        })

    # Calculate overall metrics
    if cohort_data:
        avg_month_1_retention = sum(c["retention"]["month_1"] for c in cohort_data) / len(cohort_data)
        avg_month_3_retention = sum(c["retention"]["month_3"] for c in cohort_data if "month_3" in c["retention"]) / len([c for c in cohort_data if "month_3" in c["retention"]]) if any("month_3" in c["retention"] for c in cohort_data) else 0
        avg_month_6_retention = sum(c["retention"]["month_6"] for c in cohort_data if "month_6" in c["retention"]) / len([c for c in cohort_data if "month_6" in c["retention"]]) if any("month_6" in c["retention"] for c in cohort_data) else 0
    else:
        avg_month_1_retention = avg_month_3_retention = avg_month_6_retention = 0

    return {
        "cohorts": cohort_data,
        "summary": {
            "total_cohorts": len(cohort_data),
            "avg_cohort_size": round(sum(c["size"] for c in cohort_data) / len(cohort_data), 1) if cohort_data else 0,
            "avg_month_1_retention": round(avg_month_1_retention, 1),
            "avg_month_3_retention": round(avg_month_3_retention, 1),
            "avg_month_6_retention": round(avg_month_6_retention, 1),
            "avg_ltv": round(sum(c["ltv"] for c in cohort_data) / len(cohort_data), 0) if cohort_data else 0
        },
        "insights": [
            {
                "type": "info",
                "message": f"Month 1 retention: {avg_month_1_retention:.1f}%. Industry benchmark for handmade: 25-35%"
            },
            {
                "type": "warning" if avg_month_3_retention < 15 else "success",
                "message": f"Month 3 retention: {avg_month_3_retention:.1f}%. {'Need improvement' if avg_month_3_retention < 15 else 'Good performance'}"
            }
        ]
    }


# In-memory storage for strategic planning
okrs_db: List[OKR] = []
swot_db: List[SWOTAnalysis] = []
market_insights_db: List[MarketInsight] = []


@app.get("/strategy/okrs")
async def get_okrs(
    quarter: Optional[str] = None,
    status: Optional[str] = None,
    current_user: User = Depends(get_current_user)
):
    """
    Get OKRs (Objectives and Key Results) for strategic planning
    """
    filtered_okrs = okrs_db

    if quarter:
        filtered_okrs = [o for o in filtered_okrs if o.quarter == quarter]
    if status:
        filtered_okrs = [o for o in filtered_okrs if o.status == status]

    # Calculate progress for each OKR
    okrs_with_progress = []
    for okr in filtered_okrs:
        total_progress = 0
        for kr in okr.key_results:
            kr_progress = (kr.get("current", 0) / kr.get("target", 1)) * 100 if kr.get("target", 0) > 0 else 0
            kr["progress"] = min(100, kr_progress)
            total_progress += kr["progress"]

        okr_dict = okr.model_dump()
        okr_dict["overall_progress"] = round(total_progress / len(okr.key_results), 1) if okr.key_results else 0
        okrs_with_progress.append(okr_dict)

    return {
        "okrs": okrs_with_progress,
        "summary": {
            "total": len(okrs_with_progress),
            "active": len([o for o in filtered_okrs if o.status == "active"]),
            "achieved": len([o for o in filtered_okrs if o.status == "achieved"]),
            "at_risk": len([o for o in filtered_okrs if o.status == "at_risk"])
        }
    }


@app.post("/strategy/okrs")
async def create_okr(
    payload: OKRCreate,
    current_user: User = Depends(require_admin)
):
    """
    Create new OKR
    """
    new_okr = OKR(
        id=len(okrs_db) + 1,
        **payload.model_dump()
    )
    okrs_db.append(new_okr)
    return new_okr


@app.put("/strategy/okrs/{okr_id}")
async def update_okr(
    okr_id: int,
    payload: dict,
    current_user: User = Depends(require_admin)
):
    """
    Update OKR progress or status
    """
    okr = next((o for o in okrs_db if o.id == okr_id), None)
    if not okr:
        raise HTTPException(status_code=404, detail="OKR not found")

    for key, value in payload.items():
        if hasattr(okr, key):
            setattr(okr, key, value)

    okr.updated_at = datetime.utcnow()
    return okr


@app.get("/strategy/swot")
async def get_swot_analysis(
    category: Optional[str] = None,
    type: Optional[str] = None,
    current_user: User = Depends(get_current_user)
):
    """
    Get SWOT Analysis (Strengths, Weaknesses, Opportunities, Threats)
    """
    filtered_swot = swot_db

    if category:
        filtered_swot = [s for s in filtered_swot if s.category == category]
    if type:
        filtered_swot = [s for s in filtered_swot if s.type == type]

    # Group by type for matrix view
    swot_matrix = {
        "strengths": [s for s in filtered_swot if s.type == "strength"],
        "weaknesses": [s for s in filtered_swot if s.type == "weakness"],
        "opportunities": [s for s in filtered_swot if s.type == "opportunity"],
        "threats": [s for s in filtered_swot if s.type == "threat"]
    }

    return {
        "matrix": swot_matrix,
        "summary": {
            "total": len(filtered_swot),
            "strengths": len(swot_matrix["strengths"]),
            "weaknesses": len(swot_matrix["weaknesses"]),
            "opportunities": len(swot_matrix["opportunities"]),
            "threats": len(swot_matrix["threats"])
        }
    }


@app.post("/strategy/swot")
async def create_swot(
    payload: SWOTCreate,
    current_user: User = Depends(require_admin)
):
    """
    Create SWOT analysis entry
    """
    new_swot = SWOTAnalysis(
        id=len(swot_db) + 1,
        created_by=current_user.id,
        **payload.model_dump()
    )
    swot_db.append(new_swot)
    return new_swot


@app.get("/strategy/market-insights")
async def get_market_insights(
    type: Optional[str] = None,
    priority: Optional[str] = None,
    current_user: User = Depends(get_current_user)
):
    """
    Get market insights and competitive intelligence
    """
    filtered_insights = market_insights_db

    if type:
        filtered_insights = [i for i in filtered_insights if i.type == type]
    if priority:
        filtered_insights = [i for i in filtered_insights if i.priority == priority]

    return {
        "insights": filtered_insights,
        "summary": {
            "total": len(filtered_insights),
            "high_priority": len([i for i in filtered_insights if i.priority == "high"]),
            "competitors": len([i for i in filtered_insights if i.type == "competitor"]),
            "trends": len([i for i in filtered_insights if i.type == "trend"])
        }
    }


@app.post("/strategy/market-insights")
async def create_market_insight(
    payload: MarketInsightCreate,
    current_user: User = Depends(require_admin)
):
    """
    Create market insight entry
    """
    new_insight = MarketInsight(
        id=len(market_insights_db) + 1,
        **payload.model_dump()
    )
    market_insights_db.append(new_insight)
    return new_insight


# ============================================================================
# SIGNAL DETECTION & ISSUES DIAGNOSIS SYSTEM
# ============================================================================

@app.get("/analytics/signals")
async def detect_signals(current_user: User = Depends(get_current_user)):
    """
    Detect 7 key business signals that indicate problems:
    1. View drop, 2. CTR drop, 3. Conversion drop, 4. Add-to-cart drop,
    5. Message drop, 6. Cart abandon rate increase, 7. Rating drop

    Based on comprehensive business intelligence framework
    """
    from collections import defaultdict

    now = datetime.utcnow()
    thirty_days_ago = now - timedelta(days=30)
    sixty_days_ago = now - timedelta(days=60)

    # Current period (last 30 days) - convert to date for comparison with week_of
    current_period_start = thirty_days_ago.date()
    current_period_end = now.date()

    # Previous period (30-60 days ago)
    previous_period_start = sixty_days_ago.date()
    previous_period_end = thirty_days_ago.date()

    signals = []

    # Calculate metrics for each product
    for product in products:
        product_signals = []

        # Get demand signals
        current_demand = [d for d in demand_signals if d.product_id == product.id and current_period_start <= d.week_of <= current_period_end]
        previous_demand = [d for d in demand_signals if d.product_id == product.id and previous_period_start <= d.week_of <= previous_period_end]

        # 1. VIEW DROP
        current_views = sum(d.views for d in current_demand)
        previous_views = sum(d.views for d in previous_demand)

        if previous_views > 0:
            view_change = ((current_views - previous_views) / previous_views) * 100
            if view_change < -20:  # 20% drop threshold
                product_signals.append({
                    "type": "view_drop",
                    "severity": "critical" if view_change < -50 else "high" if view_change < -30 else "medium",
                    "change_percent": round(view_change, 1),
                    "message": f"Views dropped {abs(view_change):.1f}% (from {previous_views} to {current_views})",
                    "impact": "Losing visibility on platform/search",
                    "playbook": ["Optimize images with brighter colors", "Update product title with trending keywords", "Add video to listing", "Check if product is suppressed"]
                })

        # 2. CTR DROP (Click-through rate = inquiries/views)
        current_ctr = (sum(d.inquiries for d in current_demand) / current_views * 100) if current_views > 0 else 0
        previous_ctr = (sum(d.inquiries for d in previous_demand) / previous_views * 100) if previous_views > 0 else 0

        if previous_ctr > 0 and current_ctr > 0:
            ctr_change = ((current_ctr - previous_ctr) / previous_ctr) * 100
            if ctr_change < -15:  # 15% drop threshold
                product_signals.append({
                    "type": "ctr_drop",
                    "severity": "high" if ctr_change < -30 else "medium",
                    "change_percent": round(ctr_change, 1),
                    "message": f"CTR dropped {abs(ctr_change):.1f}% (from {previous_ctr:.1f}% to {current_ctr:.1f}%)",
                    "impact": "Thumbnail/title not compelling enough",
                    "playbook": ["A/B test new main image", "Add benefit text overlay to image", "Improve title copy (pain point + solution)", "Check competitors' thumbnails"]
                })

        # 3. CONVERSION DROP
        current_orders = [o for o in orders if any(line.product_id == product.id for line in o.order_lines) and current_period_start <= o.date <= current_period_end]
        previous_orders = [o for o in orders if any(line.product_id == product.id for line in o.order_lines) and previous_period_start <= o.date <= previous_period_end]

        current_inquiries = sum(d.inquiries for d in current_demand)
        previous_inquiries = sum(d.inquiries for d in previous_demand)

        current_conversion = (len(current_orders) / current_inquiries * 100) if current_inquiries > 0 else 0
        previous_conversion = (len(previous_orders) / previous_inquiries * 100) if previous_inquiries > 0 else 0

        if previous_conversion > 0 and current_conversion > 0:
            conversion_change = ((current_conversion - previous_conversion) / previous_conversion) * 100
            if conversion_change < -20:
                product_signals.append({
                    "type": "conversion_drop",
                    "severity": "critical" if conversion_change < -40 else "high",
                    "change_percent": round(conversion_change, 1),
                    "message": f"Conversion dropped {abs(conversion_change):.1f}% (from {previous_conversion:.1f}% to {current_conversion:.1f}%)",
                    "impact": "People interested but not buying",
                    "playbook": ["Add customer review videos", "Improve product description (benefits > features)", "Add trust badges/guarantees", "Check if price increased vs competitors"]
                })

        # 4. RATING DROP
        reviews_for_product = [r for r in product_reviews if r.product_id == product.id]
        if len(reviews_for_product) >= 5:
            recent_reviews = [r for r in reviews_for_product if r.created_at >= thirty_days_ago]
            older_reviews = [r for r in reviews_for_product if r.created_at < thirty_days_ago]

            if recent_reviews and older_reviews:
                recent_avg = sum(r.rating for r in recent_reviews) / len(recent_reviews)
                older_avg = sum(r.rating for r in older_reviews) / len(older_reviews)

                if recent_avg < older_avg - 0.5:  # Drop of 0.5 stars
                    product_signals.append({
                        "type": "rating_drop",
                        "severity": "critical" if recent_avg < 3.5 else "high",
                        "change_percent": round((recent_avg - older_avg) / older_avg * 100, 1),
                        "message": f"Rating dropped from {older_avg:.1f} to {recent_avg:.1f} stars",
                        "impact": "Trust declining, will hurt all metrics",
                        "playbook": ["Contact recent buyers immediately", "Offer voucher for improved experience", "Fix quality issues ASAP", "Improve packaging/shipping"]
                    })

        # Add product info to signals
        if product_signals:
            signals.append({
                "product_id": product.id,
                "product_code": product.id,  # Sử dụng id thay cho code
                "product_name": product.name,
                "lifecycle": getattr(product, "lifecycle", getattr(product, "lifecycle_status", None)),
                "signals": product_signals,
                "total_severity": sum(1 for s in product_signals if s["severity"] == "critical") * 3 + \
                                sum(1 for s in product_signals if s["severity"] == "high") * 2 + \
                                sum(1 for s in product_signals if s["severity"] == "medium")
            })

    # Sort by severity
    signals.sort(key=lambda x: x["total_severity"], reverse=True)

    # Overall summary
    total_critical = sum(len([s for s in p["signals"] if s["severity"] == "critical"]) for p in signals)
    total_high = sum(len([s for s in p["signals"] if s["severity"] == "high"]) for p in signals)
    total_medium = sum(len([s for s in p["signals"] if s["severity"] == "medium"]) for p in signals)

    return {
        "signals": signals,
        "summary": {
            "products_affected": len(signals),
            "total_signals": sum(len(p["signals"]) for p in signals),
            "critical_signals": total_critical,
            "high_signals": total_high,
            "medium_signals": total_medium,
            "health_status": "critical" if total_critical > 0 else "warning" if total_high > 2 else "good"
        },
        "period": {
            "current": f"{current_period_start.strftime('%Y-%m-%d')} to {current_period_end.strftime('%Y-%m-%d')}",
            "previous": f"{previous_period_start.strftime('%Y-%m-%d')} to {previous_period_end.strftime('%Y-%m-%d')}"
        }
    }


@app.get("/analytics/issues/{product_id}")
async def diagnose_issues(
    product_id: int,
    current_user: User = Depends(get_current_user)
):
    """
    Deep dive diagnosis for a specific product
    Analyzes 10 root cause categories:
    1. Product issues, 2. Price issues, 3. Creative issues, 4. Description issues,
    5. Trust issues, 6. Competition issues, 7. Algorithm issues, 8. Seasonality,
    9. Operations issues, 10. Customer service issues
    """
    product = next((p for p in products if p.id == product_id), None)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    issues = []

    # 1. PRODUCT ISSUES
    product_issues = []
    if product.lifecycle in ["failed", "archived"]:
        product_issues.append("Product lifecycle indicates failure")
    if product.feasibility_score < 50:
        product_issues.append(f"Low feasibility score ({product.feasibility_score}/100)")

    # Check if product is outdated (no updates in 90 days)
    if product.updated_at and (datetime.utcnow() - product.updated_at).days > 90:
        product_issues.append("Product not updated in 90+ days (may look outdated)")

    if product_issues:
        issues.append({
            "category": "product",
            "severity": "high" if product.lifecycle == "failed" else "medium",
            "problems": product_issues,
            "solutions": [
                "Refresh product design/materials",
                "Add new variants or colors",
                "Research current market trends",
                "Consider discontinuing if can't improve"
            ]
        })

    # 2. PRICE ISSUES
    price_issues = []
    # Calculate profit margin
    material_cost = sum(usage.quantity * next((m.unit_price for m in materials if m.id == usage.material_id), 0) for usage in product.materials)
    profit_margin = ((product.price - material_cost) / product.price * 100) if product.price > 0 else 0

    if profit_margin < 30:
        price_issues.append(f"Low profit margin ({profit_margin:.1f}% - target >50% for handmade)")

    # Check price changes
    recent_price_changes = [pc for pc in price_changes if pc.product_id == product.id and (datetime.utcnow() - pc.changed_at).days < 30]
    if recent_price_changes and recent_price_changes[-1].new_price > recent_price_changes[-1].old_price:
        increase_percent = ((recent_price_changes[-1].new_price - recent_price_changes[-1].old_price) / recent_price_changes[-1].old_price) * 100
        if increase_percent > 15:
            price_issues.append(f"Recent price increase of {increase_percent:.1f}% may hurt conversions")

    if price_issues:
        issues.append({
            "category": "price",
            "severity": "high",
            "problems": price_issues,
            "solutions": [
                "Run limited-time promotion to test price sensitivity",
                "Bundle with complementary products",
                "Highlight value proposition (why worth the price)",
                "Optimize material costs to improve margin"
            ]
        })

    # 3. CREATIVE ISSUES (Images/Video)
    creative_issues = []
    images_for_product = [img for img in product_images if img.product_id == product.id]
    if len(images_for_product) < 3:
        creative_issues.append(f"Only {len(images_for_product)} images (recommend 5-8)")
    if not any(img.type == "video" for img in images_for_product):
        creative_issues.append("No product video (videos increase conversion 80%)")

    if creative_issues:
        issues.append({
            "category": "creative",
            "severity": "high",
            "problems": creative_issues,
            "solutions": [
                "Add lifestyle images showing product in use",
                "Create 15-30s product video",
                "Add size comparison images",
                "Include close-up detail shots"
            ]
        })

    # 4. TRUST ISSUES
    trust_issues = []
    reviews = [r for r in product_reviews if r.product_id == product.id]
    avg_rating = sum(r.rating for r in reviews) / len(reviews) if reviews else 0

    if len(reviews) < 5:
        trust_issues.append(f"Only {len(reviews)} reviews (need 20+ for trust)")
    if avg_rating < 4.0:
        trust_issues.append(f"Low rating ({avg_rating:.1f}/5.0)")
    if reviews and not any(r.has_image for r in reviews):
        trust_issues.append("No customer photo reviews")

    if trust_issues:
        issues.append({
            "category": "trust",
            "severity": "critical" if avg_rating < 3.5 else "high",
            "problems": trust_issues,
            "solutions": [
                "Send follow-up emails requesting reviews",
                "Offer small discount for photo reviews",
                "Feature customer testimonials prominently",
                "Add money-back guarantee"
            ]
        })

    # 5. SEASONALITY
    seasonal_issues = []
    if product.seasons:
        current_month = datetime.utcnow().month
        in_season = any(s for s in seasons if s.id in product.seasons and s.start_month <= current_month <= s.end_month)
        if not in_season:
            seasonal_issues.append("Currently off-season for this product")

    if seasonal_issues:
        issues.append({
            "category": "seasonality",
            "severity": "low",
            "problems": seasonal_issues,
            "solutions": [
                "Reduce ad spend during off-season",
                "Create content for upcoming season prep",
                "Focus on evergreen complementary products",
                "Plan inventory for next season"
            ]
        })

    # 6. OPERATIONS
    operations_issues = []
    # Check inventory
    required_materials = product.materials
    for usage in required_materials:
        material = next((m for m in materials if m.id == usage.material_id), None)
        if material and material.stock_quantity < material.low_threshold:
            operations_issues.append(f"Low stock for {material.name}")

    if operations_issues:
        issues.append({
            "category": "operations",
            "severity": "high",
            "problems": operations_issues,
            "solutions": [
                "Order materials immediately",
                "Set auto-reorder points",
                "Buffer stock for popular items",
                "Update product availability status"
            ]
        })

    # Calculate overall health score
    severity_weights = {"critical": 10, "high": 5, "medium": 2, "low": 1}
    total_severity = sum(severity_weights.get(issue["severity"], 0) for issue in issues)
    health_score = max(0, 100 - total_severity * 5)

    return {
        "product": {
            "id": product.id,
            "code": product.code,
            "name": product.name,
            "price": product.price,
            "lifecycle": product.lifecycle
        },
        "issues": issues,
        "health_score": health_score,
        "health_status": "excellent" if health_score >= 80 else "good" if health_score >= 60 else "fair" if health_score >= 40 else "poor",
        "summary": {
            "total_issues": len(issues),
            "critical": len([i for i in issues if i["severity"] == "critical"]),
            "high": len([i for i in issues if i["severity"] == "high"]),
            "medium": len([i for i in issues if i["severity"] == "medium"]),
            "low": len([i for i in issues if i["severity"] == "low"])
        }
    }


@app.get("/analytics/funnel")
async def analyze_funnel(
    product_id: Optional[int] = None,
    current_user: User = Depends(get_current_user)
):
    """
    Funnel analysis: Impression → View → Click → Add to Cart → Purchase
    Identifies conversion bottlenecks
    """
    now = datetime.utcnow()
    thirty_days_ago = now - timedelta(days=30)
    thirty_days_ago_date = thirty_days_ago.date()  # Convert to date for week_of comparison

    if product_id:
        # Single product funnel
        product = next((p for p in products if p.id == product_id), None)
        if not product:
            raise HTTPException(status_code=404, detail="Product not found")

        product_demand = [d for d in demand_signals if d.product_id == product_id and d.week_of >= thirty_days_ago_date]
        product_orders = [o for o in orders if any(line.product_id == product_id for line in o.order_lines) and o.date >= thirty_days_ago.date()]

        views = sum(d.views for d in product_demand)
        clicks = sum(d.inquiries for d in product_demand)  # inquiries = clicked to see details
        saves = sum(d.saves for d in product_demand)  # saves = add to cart proxy
        purchases = len(product_orders)

        # Assume impressions = views * 3 (estimated)
        impressions = views * 3

        funnel = [
            {"stage": "impressions", "count": impressions, "rate": 100},
            {"stage": "views", "count": views, "rate": round(views / impressions * 100, 1) if impressions > 0 else 0},
            {"stage": "clicks", "count": clicks, "rate": round(clicks / views * 100, 1) if views > 0 else 0},
            {"stage": "saves", "count": saves, "rate": round(saves / clicks * 100, 1) if clicks > 0 else 0},
            {"stage": "purchases", "count": purchases, "rate": round(purchases / saves * 100, 1) if saves > 0 else 0}
        ]

        # Find biggest drop
        biggest_drop = {"stage": None, "drop": 0}
        for i in range(len(funnel) - 1):
            drop = funnel[i]["rate"] - funnel[i + 1]["rate"]
            if drop > biggest_drop["drop"]:
                biggest_drop = {"stage": funnel[i + 1]["stage"], "drop": drop}

        bottleneck_solutions = {
            "views": ["Improve search ranking", "Increase ad spend", "Optimize product title for SEO"],
            "clicks": ["A/B test main image", "Add benefit overlay to thumbnail", "Improve title copy"],
            "saves": ["Strengthen product description", "Add social proof", "Highlight unique value"],
            "purchases": ["Reduce friction in checkout", "Add trust badges", "Offer free shipping", "Create urgency with limited stock"]
        }

        return {
            "product": {"id": product.id, "name": product.name},
            "funnel": funnel,
            "bottleneck": {
                "stage": biggest_drop["stage"],
                "drop_rate": round(biggest_drop["drop"], 1),
                "solutions": bottleneck_solutions.get(biggest_drop["stage"], [])
            },
            "overall_conversion": round(purchases / impressions * 100, 2) if impressions > 0 else 0
        }
    else:
        # Overall business funnel
        all_demand = [d for d in demand_signals if d.week_of >= thirty_days_ago_date]
        all_orders = [o for o in orders if o.date >= thirty_days_ago.date()]

        total_views = sum(d.views for d in all_demand)
        total_clicks = sum(d.inquiries for d in all_demand)
        total_saves = sum(d.saves for d in all_demand)
        total_purchases = len(all_orders)
        total_impressions = total_views * 3

        funnel = [
            {"stage": "impressions", "count": total_impressions, "rate": 100},
            {"stage": "views", "count": total_views, "rate": round(total_views / total_impressions * 100, 1) if total_impressions > 0 else 0},
            {"stage": "clicks", "count": total_clicks, "rate": round(total_clicks / total_views * 100, 1) if total_views > 0 else 0},
            {"stage": "saves", "count": total_saves, "rate": round(total_saves / total_clicks * 100, 1) if total_clicks > 0 else 0},
            {"stage": "purchases", "count": total_purchases, "rate": round(total_purchases / total_saves * 100, 1) if total_saves > 0 else 0}
        ]

        return {
            "funnel": funnel,
            "overall_conversion": round(total_purchases / total_impressions * 100, 2) if total_impressions > 0 else 0,
            "period": "last_30_days"
        }


@app.get("/analytics/market-benchmark/{product_id}")
async def get_market_benchmark(
    product_id: int,
    current_user: User = Depends(get_current_user)
):
    """
    Compare product against market benchmarks and competitors
    Provides competitive intelligence and positioning insights
    """
    product = next((p for p in products if p.id == product_id), None)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    # Get similar products (same category or lifecycle)
    similar_products = [p for p in products if p.id != product_id and (
        p.lifecycle == product.lifecycle or
        any(s in product.seasons for s in p.seasons) if product.seasons and p.seasons else False
    )][:5]

    # Calculate market averages
    all_active_products = [p for p in products if p.lifecycle in ["live", "experiment"]]

    if not all_active_products:
        raise HTTPException(status_code=404, detail="No active products for comparison")

    market_avg_price = sum(p.price for p in all_active_products) / len(all_active_products)

    # Calculate average reviews
    product_reviews_count = len([r for r in product_reviews if r.product_id == product.id])
    market_avg_reviews = sum(len([r for r in product_reviews if r.product_id == p.id]) for p in all_active_products) / len(all_active_products)

    # Calculate average rating
    product_ratings = [r.rating for r in product_reviews if r.product_id == product.id]
    product_avg_rating = sum(product_ratings) / len(product_ratings) if product_ratings else 0

    market_ratings = []
    for p in all_active_products:
        p_ratings = [r.rating for r in product_reviews if r.product_id == p.id]
        if p_ratings:
            market_ratings.append(sum(p_ratings) / len(p_ratings))
    market_avg_rating = sum(market_ratings) / len(market_ratings) if market_ratings else 0

    # Image count comparison
    product_images_count = len([img for img in product_images if img.product_id == product.id])
    market_avg_images = sum(len([img for img in product_images if img.product_id == p.id]) for p in all_active_products) / len(all_active_products)

    # Calculate material cost and profit margin
    product_material_cost = sum(
        usage.quantity * next((m.unit_price for m in materials if m.id == usage.material_id), 0)
        for usage in product.materials
    )
    product_profit_margin = ((product.price - product_material_cost) / product.price * 100) if product.price > 0 else 0

    # Market profit margins
    market_margins = []
    for p in all_active_products:
        p_cost = sum(
            usage.quantity * next((m.unit_price for m in materials if m.id == usage.material_id), 0)
            for usage in p.materials
        )
        if p.price > 0:
            market_margins.append((p.price - p_cost) / p.price * 100)
    market_avg_margin = sum(market_margins) / len(market_margins) if market_margins else 0

    # Competitive positioning
    positioning = {
        "price": "premium" if product.price > market_avg_price * 1.2 else "competitive" if product.price > market_avg_price * 0.8 else "budget",
        "quality": "high" if product_avg_rating > market_avg_rating + 0.3 else "average" if product_avg_rating > market_avg_rating - 0.3 else "low",
        "trust": "high" if product_reviews_count > market_avg_reviews * 1.5 else "average" if product_reviews_count > market_avg_reviews * 0.5 else "low",
        "content_quality": "high" if product_images_count >= market_avg_images else "low"
    }

    # Generate insights
    insights = []

    # Price insights
    price_diff_percent = ((product.price - market_avg_price) / market_avg_price * 100) if market_avg_price > 0 else 0
    if abs(price_diff_percent) > 20:
        if price_diff_percent > 0:
            insights.append({
                "category": "pricing",
                "type": "warning",
                "message": f"Price {price_diff_percent:.1f}% higher than market average",
                "recommendation": "Justify premium pricing with superior quality/story, or consider lowering price to improve conversion"
            })
        else:
            insights.append({
                "category": "pricing",
                "type": "opportunity",
                "message": f"Price {abs(price_diff_percent):.1f}% lower than market average",
                "recommendation": "Opportunity to increase price gradually or position as budget-friendly option"
            })

    # Rating insights
    if product_avg_rating < market_avg_rating - 0.5:
        insights.append({
            "category": "quality",
            "type": "critical",
            "message": f"Rating {product_avg_rating:.1f} vs market {market_avg_rating:.1f}",
            "recommendation": "Critical: Fix quality issues immediately. Survey recent buyers to identify problems"
        })
    elif product_avg_rating > market_avg_rating + 0.5:
        insights.append({
            "category": "quality",
            "type": "success",
            "message": f"Rating {product_avg_rating:.1f} exceeds market {market_avg_rating:.1f}",
            "recommendation": "Leverage high rating in marketing. Feature customer testimonials prominently"
        })

    # Review count insights
    if product_reviews_count < market_avg_reviews * 0.5:
        insights.append({
            "category": "trust",
            "type": "high",
            "message": f"Only {product_reviews_count} reviews vs market avg {market_avg_reviews:.0f}",
            "recommendation": "Send follow-up emails to request reviews. Offer incentive for photo reviews"
        })

    # Image insights
    if product_images_count < market_avg_images:
        insights.append({
            "category": "content",
            "type": "medium",
            "message": f"{product_images_count} images vs market avg {market_avg_images:.1f}",
            "recommendation": "Add more lifestyle images and detail shots. Market leaders have 5-8 images"
        })

    # Profit margin insights
    margin_diff = product_profit_margin - market_avg_margin
    if margin_diff < -10:
        insights.append({
            "category": "profitability",
            "type": "warning",
            "message": f"Profit margin {product_profit_margin:.1f}% vs market {market_avg_margin:.1f}%",
            "recommendation": "Optimize material costs or increase price to improve profitability"
        })

    # Competitive advantages
    advantages = []
    if positioning["price"] == "budget" and positioning["quality"] != "low":
        advantages.append("Great value proposition: Good quality at low price")
    if positioning["quality"] == "high":
        advantages.append("Superior quality backed by ratings")
    if positioning["trust"] == "high":
        advantages.append("Strong social proof with many reviews")
    if product_profit_margin > 50:
        advantages.append("Healthy profit margins allow for marketing investment")

    # Competitive weaknesses
    weaknesses = []
    if positioning["price"] == "premium" and positioning["quality"] != "high":
        weaknesses.append("High price not justified by quality")
    if positioning["trust"] == "low":
        weaknesses.append("Lack of social proof hurts conversion")
    if positioning["content_quality"] == "low":
        weaknesses.append("Inferior presentation vs competitors")
    if product_profit_margin < 30:
        weaknesses.append("Low margins limit growth potential")

    return {
        "product": {
            "id": product.id,
            "name": product.name,
            "price": product.price,
            "rating": round(product_avg_rating, 2),
            "reviews": product_reviews_count,
            "images": product_images_count,
            "profit_margin": round(product_profit_margin, 1)
        },
        "market_benchmarks": {
            "avg_price": round(market_avg_price, 0),
            "avg_rating": round(market_avg_rating, 2),
            "avg_reviews": round(market_avg_reviews, 1),
            "avg_images": round(market_avg_images, 1),
            "avg_profit_margin": round(market_avg_margin, 1)
        },
        "positioning": positioning,
        "competitive_advantages": advantages,
        "competitive_weaknesses": weaknesses,
        "insights": insights,
        "similar_products": [
            {
                "id": p.id,
                "name": p.name,
                "price": p.price,
                "lifecycle": p.lifecycle
            }
            for p in similar_products
        ]
    }


# ============================================================================
# CUSTOMER PSYCHOLOGY & MARKETING FRAMEWORKS
# ============================================================================

@app.get("/content/marketing-frameworks")
async def get_marketing_frameworks(current_user: User = Depends(get_current_user)):
    """
    Get marketing psychology frameworks: AIDA, STP, Hook & Story
    Provides templates and best practices
    """
    return {
        "frameworks": {
            "aida": {
                "name": "AIDA (Attention, Interest, Desire, Action)",
                "description": "Classic 4-stage customer journey framework",
                "stages": [
                    {
                        "stage": "attention",
                        "goal": "Stop the scroll, grab eyeballs",
                        "tactics": [
                            "Bold visual: bright colors, contrasting elements",
                            "Pattern interrupt: unexpected image or text",
                            "Curiosity gap: tease without revealing all",
                            "Social proof: '10,000+ sold' badge"
                        ],
                        "examples": [
                            "🔥 Bán chạy nhất tuần!",
                            "Bạn có biết bí mật này?",
                            "Chỉ còn 3 cái cuối cùng!"
                        ]
                    },
                    {
                        "stage": "interest",
                        "goal": "Make them want to know more",
                        "tactics": [
                            "Relate to their pain point",
                            "Show unique solution",
                            "Demonstrate expertise/authority",
                            "Use storytelling"
                        ],
                        "examples": [
                            "Mệt mỏi với túi xách nặng nề?",
                            "Sản phẩm handmade từ chất liệu thiên nhiên...",
                            "Nghệ nhân 20 năm kinh nghiệm"
                        ]
                    },
                    {
                        "stage": "desire",
                        "goal": "Make them WANT it, not just interested",
                        "tactics": [
                            "Paint the transformation (before/after)",
                            "Emotional connection (how it feels to own)",
                            "Social proof (reviews, testimonials)",
                            "Scarcity/exclusivity"
                        ],
                        "examples": [
                            "Hình ảnh bạn tự tin đeo túi đẹp đi làm",
                            "'Tôi cảm thấy sang trọng hơn' - Chị Mai",
                            "Chỉ làm 10 cái mỗi tháng"
                        ]
                    },
                    {
                        "stage": "action",
                        "goal": "Get them to buy NOW",
                        "tactics": [
                            "Clear CTA (Call-to-Action)",
                            "Remove friction (easy checkout)",
                            "Urgency (limited time/stock)",
                            "Risk reversal (guarantee, return policy)"
                        ],
                        "examples": [
                            "Đặt ngay - Miễn phí ship",
                            "Sale kết thúc trong 24h",
                            "Hoàn tiền 100% nếu không hài lòng"
                        ]
                    }
                ],
                "common_mistakes": [
                    "Jump straight to Action without building Desire",
                    "Focus on features (Attention) instead of benefits (Interest)",
                    "Not creating urgency in Action stage"
                ]
            },
            "stp": {
                "name": "STP (Segmentation, Targeting, Positioning)",
                "description": "Strategic marketing framework for finding your niche",
                "stages": [
                    {
                        "stage": "segmentation",
                        "goal": "Divide market into groups",
                        "questions": [
                            "Who are different customer types?",
                            "What are their characteristics?",
                            "Demographics: age, gender, location, income",
                            "Psychographics: values, lifestyle, interests",
                            "Behavioral: usage, loyalty, benefits sought"
                        ],
                        "example": "Túi handmade: (1) Sinh viên trendy (18-25), (2) Công sở chuyên nghiệp (25-40), (3) Mẹ bỉm trẻ em nhỏ"
                    },
                    {
                        "stage": "targeting",
                        "goal": "Choose which segment(s) to focus on",
                        "criteria": [
                            "Size: Đủ lớn để có lợi nhuận?",
                            "Growth: Segment đang tăng hay giảm?",
                            "Competition: Ít cạnh tranh?",
                            "Fit: Phù hợp với năng lực của bạn?"
                        ],
                        "strategies": [
                            "Undifferentiated: Một sản phẩm cho tất cả",
                            "Differentiated: Nhiều sản phẩm cho nhiều segment",
                            "Concentrated: Focus vào 1 segment (niche)"
                        ],
                        "recommendation": "Handmade nên chọn Concentrated (niche) vì nguồn lực hạn chế"
                    },
                    {
                        "stage": "positioning",
                        "goal": "How you want to be perceived in customer's mind",
                        "dimensions": [
                            "Price vs Quality: Premium, Mid-range, Budget",
                            "Functional vs Emotional: Practical vs Lifestyle",
                            "Traditional vs Modern: Classic vs Trendy"
                        ],
                        "positioning_statement": "For [target segment], [brand] is the [category] that [unique benefit] because [reason to believe]",
                        "example": "For eco-conscious millennials, GreenBag is the handmade bag that helps save the planet because we use 100% recycled materials and plant a tree for each purchase"
                    }
                ]
            },
            "hook_story": {
                "name": "Hook & Story Framework",
                "description": "Content structure that captures attention and builds connection",
                "components": [
                    {
                        "element": "hook",
                        "goal": "Stop them in first 3 seconds",
                        "types": [
                            "Question: 'Bạn có biết...?'",
                            "Bold statement: 'Đây là lý do 90% túi handmade thất bại'",
                            "Curiosity: 'Bí mật này đã giúp tôi bán 1000 túi'",
                            "Shocking fact: '80% túi da giả trên thị trường'",
                            "Relatable pain: 'Mệt mỏi với túi rách sau 3 tháng?'"
                        ],
                        "formula": "[Pain/Desire] + [Promise] + [Proof]"
                    },
                    {
                        "element": "story",
                        "goal": "Build emotional connection and trust",
                        "structure": [
                            "Before: Vấn đề/khó khăn/nỗi đau",
                            "Journey: Quá trình tìm kiếm giải pháp",
                            "After: Cuộc sống thay đổi thế nào",
                            "Lesson: Bài học/insight"
                        ],
                        "story_types": [
                            "Founder story: Tại sao bạn bắt đầu",
                            "Customer story: Khách hàng thay đổi thế nào",
                            "Product story: Sản phẩm được tạo ra như thế nào",
                            "Behind-the-scenes: Quy trình sản xuất"
                        ]
                    },
                    {
                        "element": "value",
                        "goal": "Educate and position as expert",
                        "content_types": [
                            "How-to: Cách chọn túi phù hợp",
                            "Tips: 5 cách bảo quản túi da",
                            "Comparison: Da thật vs da PU",
                            "Trend: Xu hướng túi 2025"
                        ]
                    },
                    {
                        "element": "cta",
                        "goal": "Guide next step",
                        "types": [
                            "Soft CTA: 'Tag bạn bè cần biết điều này'",
                            "Engagement: 'Comment 'YES' để nhận catalog'",
                            "Direct: 'Inbox ngay để đặt hàng'",
                            "Link: 'Link in bio để xem thêm'"
                        ]
                    }
                ],
                "content_formula": "Hook (3s) → Story/Value (30-60s) → CTA (5s)"
            }
        },
        "customer_psychology": {
            "principles": [
                {
                    "name": "Fear of Missing Out (FOMO)",
                    "description": "Sợ bỏ lỡ cơ hội",
                    "triggers": ["Limited stock", "Time-limited offer", "Exclusive access"],
                    "examples": ["Chỉ còn 3 cái", "Sale kết thúc 23:59 hôm nay", "Chỉ dành cho 100 người đầu"]
                },
                {
                    "name": "Social Proof",
                    "description": "Làm theo đám đông",
                    "triggers": ["Reviews", "Testimonials", "User count", "Influencer endorsement"],
                    "examples": ["1000+ khách hàng hài lòng", "Sản phẩm bán chạy #1", "Được báo chí đưa tin"]
                },
                {
                    "name": "Reciprocity",
                    "description": "Đền đáp khi nhận được",
                    "triggers": ["Free value", "Gifts", "Discounts for loyal customers"],
                    "examples": ["Ebook miễn phí", "Quà tặng khi mua", "Giảm 10% cho lần mua tiếp"]
                },
                {
                    "name": "Authority",
                    "description": "Tin tưởng chuyên gia",
                    "triggers": ["Certifications", "Years of experience", "Press mentions"],
                    "examples": ["Nghệ nhân 20 năm", "Chứng nhận organic", "Feature trên VnExpress"]
                },
                {
                    "name": "Scarcity",
                    "description": "Giá trị tăng khi khan hiếm",
                    "triggers": ["Limited edition", "Low stock", "Exclusive"],
                    "examples": ["Bộ sưu tập giới hạn", "Chỉ làm 50 cái", "Không bán lại"]
                },
                {
                    "name": "Anchoring",
                    "description": "Quyết định dựa trên thông tin đầu tiên",
                    "triggers": ["Original price shown", "Most popular option highlighted"],
                    "examples": ["Giá gốc 500k, giảm còn 350k", "Best seller (định hướng lựa chọn)"]
                }
            ],
            "buying_psychology": {
                "what_customers_fear": [
                    "Mua sai → waste money",
                    "Chất lượng kém → disappointment",
                    "Không đẹp như ảnh → regret",
                    "Giao hàng lâu → frustration"
                ],
                "what_customers_want": [
                    "Feel good về purchase",
                    "Được công nhận/khen ngợi",
                    "Giải quyết vấn đề thực tế",
                    "Experience tốt (unboxing, service)"
                ],
                "decision_process": [
                    "Buy with emotion (cảm xúc: đẹp, sang, độc đáo)",
                    "Justify with logic (lý trí: giá hợp lý, chất lượng tốt, đánh giá cao)"
                ]
            }
        },
        "content_templates": [
            {
                "type": "product_launch",
                "template": "[Hook: New arrival 🔥] → [Story: Behind the design] → [Benefits: 3 lý do phải có] → [CTA: Pre-order now]"
            },
            {
                "type": "customer_testimonial",
                "template": "[Hook: Real customer story] → [Before: Problem they had] → [After: How product helped] → [CTA: Your turn]"
            },
            {
                "type": "educational",
                "template": "[Hook: Did you know?] → [Value: Teach something useful] → [Connect to product] → [Soft CTA]"
            },
            {
                "type": "urgency",
                "template": "[Hook: Time-sensitive] → [Scarcity: Limited stock/time] → [Social proof: Others buying] → [Direct CTA]"
            }
        ]
    }


# --- Push Notification Endpoints ---------------------------------------------
@app.post("/notifications/subscribe")
async def subscribe_push(subscription: PushSubscription, current_user: User = Depends(get_current_user)):
    """Register push notification subscription"""
    try:
        with Session(engine) as session:
            # Check if endpoint already exists
            existing = session.exec(
                select(PushSubscriptionTable).where(PushSubscriptionTable.endpoint == subscription.endpoint)
            ).first()

            if existing:
                # Update user_id if changed
                if existing.user_id != current_user.id:
                    existing.user_id = current_user.id
                    session.add(existing)
                    session.commit()
                return {"message": "Subscription updated"}

            # Create new subscription
            new_sub = PushSubscriptionTable(
                user_id=current_user.id,
                endpoint=subscription.endpoint,
                p256dh=subscription.keys.get("p256dh", ""),
                auth=subscription.keys.get("auth", "")
            )
            session.add(new_sub)
            session.commit()

            return {"message": "Subscription registered successfully"}
    except Exception as e:
        print(f"Error subscribing to push: {e}")
        raise HTTPException(status_code=500, detail="Failed to register subscription")


@app.post("/notifications/send")
async def send_push_notification(payload: NotificationPayload, current_user: User = Depends(get_current_user)):
    """Send push notification (admin only)"""
    require_admin(current_user)

    try:
        with Session(engine) as session:
            # Get target subscriptions
            query = select(PushSubscriptionTable)
            if payload.user_ids:
                query = query.where(PushSubscriptionTable.user_id.in_(payload.user_ids))

            subscriptions = session.exec(query).all()

            sent_count = 0

            # Send via WebSocket (real-time)
            notification_data = {
                "type": "notification",
                "title": payload.title,
                "body": payload.body,
                "icon": payload.icon,
                "data": payload.data,
                "timestamp": datetime.now().isoformat()
            }

            if payload.user_ids:
                for user_id in payload.user_ids:
                    try:
                        await ws_manager.send_personal_message(notification_data, user_id)
                        sent_count += 1
                    except:
                        pass
            else:
                await ws_manager.broadcast(notification_data)
                sent_count = len(ws_manager.active_connections)

            return {
                "message": "Notification sent",
                "sent_count": sent_count,
                "subscriptions_found": len(subscriptions)
            }
    except Exception as e:
        print(f"Error sending notification: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/notifications/unsubscribe")
async def unsubscribe_push(endpoint: str, current_user: User = Depends(get_current_user)):
    """Unsubscribe from push notifications"""
    try:
        with Session(engine) as session:
            sub = session.exec(
                select(PushSubscriptionTable).where(
                    PushSubscriptionTable.endpoint == endpoint,
                    PushSubscriptionTable.user_id == current_user.id
                )
            ).first()

            if sub:
                session.delete(sub)
                session.commit()
                return {"message": "Unsubscribed successfully"}

            return {"message": "Subscription not found"}
    except Exception as e:
        print(f"Error unsubscribing: {e}")
        raise HTTPException(status_code=500, detail="Failed to unsubscribe")


# --- Marketplace Integration Endpoints --------------------------------------
@app.post("/marketplace/sync")
@limiter.limit("10/hour")  # Limit sync to prevent abuse
async def sync_marketplace_orders(
    request: Request,
    sync_request: MarketplaceSyncRequest,
    current_user: User = Depends(require_admin)
):
    """
    Sync orders from marketplace (Shopee/Lazada)
    Admin only to prevent abuse
    """
    try:
        settings = get_settings()

        # Default date range: last 7 days
        date_to = sync_request.date_to or date.today()
        date_from = sync_request.date_from or (date_to - timedelta(days=7))

        orders_synced = 0
        orders_failed = 0
        error_msg = None

        try:
            if sync_request.marketplace == "shopee":
                result = await sync_shopee_orders(settings, date_from, date_to)
            elif sync_request.marketplace == "lazada":
                result = await sync_lazada_orders(settings, date_from, date_to)
            else:
                raise HTTPException(status_code=400, detail="Invalid marketplace")

            # Process orders (placeholder - would create actual orders)
            # mp_orders = result.get("orders", [])
            # for mp_order in mp_orders:
            #     try:
            #         internal_order = marketplace_order_to_internal(mp_order, current_user)
            #         # Create order via existing endpoint logic
            #         orders_synced += 1
            #     except Exception as e:
            #         orders_failed += 1
            #         print(f"Failed to sync order: {e}")

            status = "success"
        except Exception as e:
            status = "failed"
            error_msg = str(e)
            print(f"Marketplace sync error: {e}")

        # Log sync operation
        with Session(engine) as session:
            log = MarketplaceSyncLogTable(
                marketplace=sync_request.marketplace,
                sync_type=sync_request.sync_type,
                status=status,
                orders_synced=orders_synced,
                orders_failed=orders_failed,
                error_message=error_msg
            )
            session.add(log)
            session.commit()
            session.refresh(log)

            return {
                "log_id": log.id,
                "orders_synced": orders_synced,
                "orders_failed": orders_failed,
                "status": status,
                "message": error_msg or "Sync completed successfully"
            }

    except Exception as e:
        print(f"Marketplace sync endpoint error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/marketplace/logs")
async def get_marketplace_sync_logs(
    marketplace: Optional[str] = None,
    limit: int = 50,
    current_user: User = Depends(get_current_user)
):
    """Get marketplace sync history"""
    try:
        with Session(engine) as session:
            query = select(MarketplaceSyncLogTable).order_by(MarketplaceSyncLogTable.synced_at.desc())

            if marketplace:
                query = query.where(MarketplaceSyncLogTable.marketplace == marketplace)

            query = query.limit(limit)
            logs = session.exec(query).all()

            return {
                "logs": [
                    {
                        "id": log.id,
                        "marketplace": log.marketplace,
                        "sync_type": log.sync_type,
                        "status": log.status,
                        "orders_synced": log.orders_synced,
                        "orders_failed": log.orders_failed,
                        "error_message": log.error_message,
                        "synced_at": log.synced_at.isoformat()
                    }
                    for log in logs
                ],
                "total": len(logs)
            }
    except Exception as e:
        print(f"Error fetching sync logs: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# --- WebSocket Real-time Notifications --------------------------------------
class ConnectionManager:
    """Manage WebSocket connections for real-time notifications"""
    def __init__(self):
        self.active_connections: Dict[int, List[WebSocket]] = {}  # user_id -> list of connections

    async def connect(self, websocket: WebSocket, user_id: int):
        await websocket.accept()
        if user_id not in self.active_connections:
            self.active_connections[user_id] = []
        self.active_connections[user_id].append(websocket)

    def disconnect(self, websocket: WebSocket, user_id: int):
        if user_id in self.active_connections:
            if websocket in self.active_connections[user_id]:
                self.active_connections[user_id].remove(websocket)
            if not self.active_connections[user_id]:
                del self.active_connections[user_id]

    async def send_personal_message(self, message: dict, user_id: int):
        if user_id in self.active_connections:
            for connection in self.active_connections[user_id]:
                try:
                    await connection.send_json(message)
                except:
                    pass

    async def broadcast(self, message: dict):
        for user_id in self.active_connections:
            await self.send_personal_message(message, user_id)

ws_manager = ConnectionManager()

@app.websocket("/ws/{user_id}")
async def websocket_endpoint(websocket: WebSocket, user_id: int):
    """WebSocket endpoint for real-time notifications"""
    await ws_manager.connect(websocket, user_id)
    try:
        while True:
            # Keep connection alive, receive pings
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket, user_id)

# Helper function to send notifications
async def notify_new_order(order_data: dict, user_id: int = None):
    """Send notification when new order is created"""
    notification = {
        "type": "new_order",
        "title": "Đơn hàng mới",
        "message": f"Đơn hàng #{order_data.get('id')} - {order_data.get('product_name')}",
        "data": order_data,
        "timestamp": datetime.now().isoformat()
    }
    if user_id:
        await ws_manager.send_personal_message(notification, user_id)
    else:
        await ws_manager.broadcast(notification)

async def notify_low_stock(material_data: dict):
    """Send notification when stock is low"""
    notification = {
        "type": "low_stock",
        "title": "Cảnh báo tồn kho",
        "message": f"{material_data.get('name')} sắp hết ({material_data.get('stock_quantity')} {material_data.get('unit')})",
        "data": material_data,
        "timestamp": datetime.now().isoformat()
    }
    await ws_manager.broadcast(notification)

async def notify_order_status_change(order_id: int, new_status: str, user_id: int = None):
    """Send notification when order status changes"""
    notification = {
        "type": "order_status",
        "title": "Cập nhật đơn hàng",
        "message": f"Đơn hàng #{order_id} đã chuyển sang: {new_status}",
        "data": {"order_id": order_id, "status": new_status},
        "timestamp": datetime.now().isoformat()
    }
    if user_id:
        await ws_manager.send_personal_message(notification, user_id)
    else:
        await ws_manager.broadcast(notification)



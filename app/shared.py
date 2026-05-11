"""
Shared business logic, models, data stores, and helper functions.
Extracted from the original monolithic main.py.
All endpoint files import from this module.
"""

import copy
import os
import json
import re
import secrets
import jwt
import csv
import io
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional, Generic, TypeVar
from functools import lru_cache
from contextlib import asynccontextmanager
from dotenv import load_dotenv

from fastapi import Depends, FastAPI, HTTPException, Header, Request, Response, status, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordBearer
from fastapi.security.utils import get_authorization_scheme_param

from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

from sqlmodel import Field as SQLField, Session, SQLModel, create_engine, select, delete
from sqlalchemy.exc import OperationalError
from sqlalchemy import inspect as sa_inspect, text as sa_text
from sqlalchemy.pool import StaticPool
from passlib.context import CryptContext
from pydantic import BaseModel, Field, field_validator, EmailStr
from email.message import EmailMessage
import smtplib

# --- Configuration & Environment --------------------------------------------
load_dotenv()

# JWT Config
JWT_SECRET = os.getenv("JWT_SECRET", "").strip()
if not JWT_SECRET:
    # Fallback for development if not in production
    JWT_SECRET = "dev_secret_key_change_in_production_at_least_32_chars"
    print(f"[WARN] JWT_SECRET not found in .env, using default development key.")

JWT_ALGO = "HS256"
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")

pwd_context = CryptContext(
    schemes=["bcrypt", "pbkdf2_sha256"],
    deprecated="auto",
)

# Admin Config
ADMIN_DEFAULT_PASSWORD = os.getenv("ADMIN_DEFAULT_PASSWORD", "").strip()
OWNER_A_PASSWORD = os.getenv("OWNER_A_PASSWORD", "").strip()
OWNER_B_PASSWORD = os.getenv("OWNER_B_PASSWORD", "").strip()
generated_admin_password = None

if not ADMIN_DEFAULT_PASSWORD:
    generated_admin_password = secrets.token_urlsafe(16)
    ADMIN_DEFAULT_PASSWORD = generated_admin_password
    print(f"[WARN] ADMIN_DEFAULT_PASSWORD not set, using temporary suffix.")

def resolve_seed_password(env_value: str) -> str:
    if env_value:
        if len(env_value) < 12:
            print("[WARN] Seed password is too short, consider using at least 12 characters.")
        return env_value
    return ADMIN_DEFAULT_PASSWORD

if len(ADMIN_DEFAULT_PASSWORD) < 12:
    print("[WARN] ADMIN_DEFAULT_PASSWORD is too short, consider using at least 12 characters.")

# Database Config
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./db.sqlite")
engine = None
SQL_INITIALIZED = False

def initialize_database():
    """Initialize database connection with fallback to in-memory mode"""
    global engine, DATABASE_URL, SQL_INITIALIZED
    if SQL_INITIALIZED and engine is not None:
        return engine

    try:
        connect_args = {}
        pool_config = {}

        if DATABASE_URL.startswith("postgres"):
            print(f"[DB] Connecting to PostgreSQL...")
            connect_args["connect_timeout"] = int(os.getenv("PG_CONNECT_TIMEOUT", "10"))
            pool_config = {
                "pool_size": 10,
                "max_overflow": 20,
                "pool_timeout": 30,
                "pool_recycle": 3600,
                "pool_pre_ping": True,
            }

        engine = create_engine(
            DATABASE_URL,
            echo=False,
            connect_args=connect_args,
            **pool_config
        )

        # Test connection
        with engine.connect() as conn:
            conn.execute(sa_text("SELECT 1"))

        print(f"[DB] Connection successful: {DATABASE_URL.split('://')[0]}")
    except Exception as e:
        print(f"[DB] Connection failed: {e}. Falling back to SQLite.")
        DATABASE_URL = "sqlite:///./db.sqlite"
        engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})

    SQL_INITIALIZED = True
    return engine

# Initialize engine at module level if possible, or it will be done in lifespan
if os.getenv("INIT_DB_ON_IMPORT", "true").lower() == "true":
    initialize_database()

# Rate limiter setup
limiter = Limiter(
    key_func=get_remote_address,
    default_limits=["200/minute"],
)

# --- Common Dependencies ----------------------------------------------------
def get_db():
    with Session(engine) as session:
        yield session

# --- Input Validators -------------------------------------------------------

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
    unit_price: Optional[float] = None
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
    new_price: Optional[float] = None
    unit_price: Optional[float] = None
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
    is_public: bool = True
    display_order: int = 0
    created_at: datetime = Field(default_factory=datetime.utcnow)


class ProductImageCreate(BaseModel):
    product_id: int
    url: str
    is_primary: bool = False
    is_public: bool = True
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
    unit_price: Optional[float] = None
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

# --- Ensure all tables are created on startup ---
# Startup function (called from app/main.py)
def create_all_tables():
    if engine:
        SQLModel.metadata.create_all(engine)

# Configuration loaded at top of file


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
    import os, json
    local_file = f"local_{name}.json"

    # Nếu SQL đã có data → không đọc/ghi Mongo để tránh double-write
    if SQL_HAS_DATA or not USE_MONGO or mongo_db is None:
        if os.path.exists(local_file):
            try:
                with open(local_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    return [model_cls.model_validate(clean_doc(item)) for item in data]
            except Exception:
                pass

        # Tạo file với dữ liệu fallback nếu chưa có file
        try:
            with open(local_file, "w", encoding="utf-8") as f:
                json.dump([item.model_dump(mode="json") for item in fallback], f, ensure_ascii=False, indent=2)
        except Exception:
            pass

        return copy.deepcopy(fallback)

    if USE_MONGO and mongo_db is not None:
        docs = list(mongo_db[name].find())
        if docs:
            return [model_cls.model_validate(clean_doc(doc)) for doc in docs]
        if fallback:
            mongo_db[name].insert_many([item.model_dump(mode="json") for item in fallback])
    return copy.deepcopy(fallback)


import json

def load_settings() -> Settings:
    if USE_MONGO and mongo_db is not None:
        doc = mongo_db["settings"].find_one({"_id": "settings"})
        if doc:
            return Settings.model_validate(clean_doc(doc))
        mongo_db["settings"].replace_one({"_id": "settings"}, DEFAULT_SETTINGS.model_dump(mode="json"), upsert=True)
        return Settings.model_validate(DEFAULT_SETTINGS.model_dump())

    import os
    if os.path.exists("settings_local.json"):
        try:
            with open("settings_local.json", "r", encoding="utf-8") as f:
                return Settings.model_validate(json.load(f))
        except Exception:
            pass

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
    # Save settings physically even if SQL is active
    if collection == "settings" and (not USE_MONGO or mongo_db is None):
        import json
        with open("settings_local.json", "w", encoding="utf-8") as f:
            json.dump(obj.model_dump(mode="json"), f)
        return

    # Якщо SQL đã có data thì coi SQL là nguồn chính, bỏ qua Mongo
    if SQL_HAS_DATA or not USE_MONGO or mongo_db is None:
        import json, os
        local_file = f"local_{collection}.json"

        current_data = []
        if os.path.exists(local_file):
            try:
                with open(local_file, "r", encoding="utf-8") as f:
                    current_data = json.load(f)
            except Exception:
                pass

        doc = obj.model_dump(mode="json")
        obj_id = identifier if identifier is not None else getattr(obj, "id", None)
        found = False
        for i, item in enumerate(current_data):
            if item.get("id") == obj_id:
                current_data[i] = doc
                found = True
                break

        if not found:
            current_data.append(doc)

        with open(local_file, "w", encoding="utf-8") as f:
            json.dump(current_data, f, ensure_ascii=False, indent=2)

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
        import json, os
        local_file = f"local_{collection}.json"
        if os.path.exists(local_file):
            try:
                with open(local_file, "r", encoding="utf-8") as f:
                    current_data = json.load(f)
                new_data = [item for item in current_data if item.get("id") != identifier]
                with open(local_file, "w", encoding="utf-8") as f:
                    json.dump(new_data, f, ensure_ascii=False, indent=2)
            except Exception:
                pass
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

        # Cập nhật giá vốn nguyên liệu bằng đúng mức giá của lô mới nhập nhất (LIFO / Latest Price)
        # Theo yêu cầu của user, mỗi lô nhập thì dùng luôn giá nhập mới
        if line.unit_price and line.unit_price > 0:
            material.unit_price = line.unit_price

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
            unit_price=line.unit_price,
            user_id=current_user.id,
            note=f"Nhập kho từ PO #{po.id}",
            created_at=datetime.utcnow(),
        )
        stock_movements.append(movement)
        upsert_document("stock_movements", movement)
        with Session(engine) as session:
            session.add(stock_movement_to_table(movement))
            session.commit()

    clear_product_cost_cache()


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




# --- Product endpoints ------------------------------------------------------








# --- Bulk Import Endpoints --------------------------------------------------
class BulkImportRequest(BaseModel):
    items: List[dict]


class BulkImportResponse(BaseModel):
    imported: int
    failed: int
    errors: List[str] = []










# --- Material endpoints -----------------------------------------------------










# --- Orders endpoints -------------------------------------------------------
















# --- Seasons endpoints ------------------------------------------------------








# --- Ideas endpoints --------------------------------------------------------








# --- Content plan endpoints -------------------------------------------------






class ContentPerformanceUpdate(BaseModel):
    actual_views: Optional[int] = None
    actual_inquiries: Optional[int] = None
    actual_saves: Optional[int] = None
    actual_orders: Optional[int] = None
    actual_revenue: Optional[float] = None






# --- Activity logs ---------------------------------------------------------




# --- Experiments (A/B testing) ---------------------------------------------








# --- Goals ------------------------------------------------------------------










# --- Tasks / Collaboration --------------------------------------------------




class TaskUpdate(TaskCreate):
    status: Optional[str] = None
    assignee_id: Optional[int] = None






# --- Issues endpoints -------------------------------------------------------






class IssueCommentCreate(BaseModel):
    content: str








class IssueFromTemplateRequest(BaseModel):
    template_id: int
    product_id: int
    description: Optional[str] = None
    priority: Optional[int] = None






# --- Demand signals --------------------------------------------------------




# --- Dashboard & reports ----------------------------------------------------




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



















































# --- Auth ------------------------------------------------------------------








# --- Customer endpoints -----------------------------------------------------














# --- Stock Movement endpoints -----------------------------------------------




# --- Payment endpoints ------------------------------------------------------




# --- Product Variants endpoints ---------------------------------------------








# --- Product bundles --------------------------------------------------------






# --- Product images ---------------------------------------------------------






# --- Product reviews --------------------------------------------------------






# --- Categories -------------------------------------------------------------






# --- Promo codes ------------------------------------------------------------


# --- Order returns / refunds -----------------------------------------------




# --- Suppliers --------------------------------------------------------------








# --- Purchase Orders --------------------------------------------------------










# ============================================================================
# BUSINESS INTELLIGENCE & STRATEGIC PLANNING APIs
# ============================================================================







# In-memory storage for strategic planning
okrs_db: List[OKR] = []
swot_db: List[SWOTAnalysis] = []
market_insights_db: List[MarketInsight] = []
















# ============================================================================
# SIGNAL DETECTION & ISSUES DIAGNOSIS SYSTEM
# ============================================================================









# ============================================================================
# CUSTOMER PSYCHOLOGY & MARKETING FRAMEWORKS
# ============================================================================



# --- Push Notification Endpoints ---------------------------------------------






# --- Marketplace Integration Endpoints --------------------------------------




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


# --- DB Session Dependency for FastAPI routes ---
def get_db():
    with Session(engine) as session:
        yield session

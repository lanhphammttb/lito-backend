from pydantic import BaseModel, Field, field_validator
from typing import Optional, List
from datetime import date, datetime

def validate_positive_number(value: float, field_name: str) -> float:
    if value < 0: raise ValueError(f'{field_name} phải >= 0')
    return value

ORDER_STATUS_ALLOWED = {"pending", "confirmed", "processing", "completed", "shipped", "delivered", "cancelled"}
PAYMENT_STATUS_ALLOWED = {"unpaid", "partial", "paid", "refunded"}

class OrderLine(BaseModel):
    product_id: int = Field(..., gt=0)
    quantity: int = Field(..., gt=0, le=10000)
    unit_price: float = Field(..., ge=0)

class ShippingUpdate(BaseModel):
    status: Optional[str] = Field(None, max_length=50)
    note: Optional[str] = Field(None, max_length=500)
    timestamp: datetime = Field(default_factory=datetime.utcnow)

class OrderCreate(BaseModel):
    date: date
    channel: str = Field(..., min_length=1, max_length=50)
    order_lines: List[OrderLine] = Field(..., min_length=1)
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
    source_content_id: Optional[int] = None

    @field_validator('status')
    @classmethod
    def check_status(cls, v):
        if v not in ORDER_STATUS_ALLOWED: raise ValueError('Invalid status')
        return v

    @field_validator('payment_status')
    @classmethod
    def check_payment_status(cls, v):
        if v not in PAYMENT_STATUS_ALLOWED: raise ValueError('Invalid payment_status')
        return v

class Order(OrderCreate):
    id: int
    created_by: Optional[int] = None
    updated_by: Optional[int] = None

class OrderComputed(Order):
    revenue: float
    cost: float
    profit: float
    computed_discount: Optional[float] = 0.0

class CustomerCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    phone: Optional[str] = Field(None, max_length=20)
    email: Optional[str] = None
    address: Optional[str] = Field(None, max_length=500)
    source: Optional[str] = Field(None, max_length=50)
    tags: List[str] = Field(default_factory=list)
    notes: Optional[str] = Field(None, max_length=1000)

class Customer(CustomerCreate):
    id: int
    total_orders: int = 0
    total_spent: float = 0
    last_order_date: Optional[date] = None
    first_order_date: Optional[date] = None
    created_by: Optional[int] = None
    created_at: datetime

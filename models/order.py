"""Order models."""
from typing import Optional, List
from datetime import datetime, date as date_type
from pydantic import BaseModel, Field
from sqlmodel import SQLModel, Field as SQLField, Relationship
from utils.datetime import utcnow


class OrderLine(BaseModel):
    """Order line item."""
    product_id: int
    quantity: int = 1
    unit_price: float = 0
    variant_id: Optional[int] = None


class ShippingUpdate(BaseModel):
    """Shipping status update."""
    order_id: Optional[int] = None
    status: Optional[str] = None
    note: Optional[str] = None
    shipping_carrier: Optional[str] = None
    tracking_number: Optional[str] = None
    estimated_delivery_date: Optional[date_type] = None
    timestamp: datetime = Field(default_factory=utcnow)


class Order(BaseModel):
    """Order domain model."""
    id: int
    date: date_type
    channel: Optional[str] = None
    customer_id: Optional[int] = None
    order_lines: List[OrderLine] = []
    shipping_fee: float = 0
    discount: float = 0
    promo_code: Optional[str] = None
    status: str = "pending"
    payment_status: str = "unpaid"
    shipping_carrier: Optional[str] = None
    tracking_number: Optional[str] = None
    estimated_delivery_date: Optional[date_type] = None
    shipping_updates: List[ShippingUpdate] = []
    note: Optional[str] = None
    maker_user_id: Optional[int] = None
    source_content_id: Optional[int] = None
    created_by: Optional[int] = None
    updated_by: Optional[int] = None
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: Optional[datetime] = None


class OrderLineTable(SQLModel, table=True):
    """Order line database table."""
    __tablename__ = "order_lines"

    id: Optional[int] = SQLField(default=None, primary_key=True)
    order_id: int = SQLField(foreign_key="orders.id", index=True)
    product_id: int = SQLField(index=True)
    variant_id: Optional[int] = None
    quantity: int = 1
    unit_price: float = 0

    order: "OrderTable" = Relationship(back_populates="lines")


class OrderTable(SQLModel, table=True):
    """Order database table."""
    __tablename__ = "orders"

    id: Optional[int] = SQLField(default=None, primary_key=True)
    order_date: date_type = SQLField(index=True)
    channel: Optional[str] = None
    customer_id: Optional[int] = SQLField(default=None, index=True)
    order_lines_json: str = "[]"
    lines: List[OrderLineTable] = Relationship(back_populates="order")
    shipping_fee: float = 0
    discount: float = 0
    promo_code: Optional[str] = None
    status: str = "pending"
    payment_status: str = "unpaid"
    shipping_carrier: Optional[str] = None
    tracking_number: Optional[str] = None
    estimated_delivery_date: Optional[date_type] = None
    shipping_updates_json: str = "[]"
    note: Optional[str] = None
    maker_user_id: Optional[int] = None
    source_content_id: Optional[int] = None
    created_by: Optional[int] = None
    updated_by: Optional[int] = None
    created_at: datetime = SQLField(default_factory=utcnow)
    updated_at: Optional[datetime] = None


class OrderComputed(Order):
    """Order with computed totals."""
    revenue: float = 0
    cost: float = 0
    profit: float = 0
    computed_discount: float = 0


class OrderReturn(BaseModel):
    """Order return/refund model."""
    id: int
    order_id: int
    reason: Optional[str] = None
    amount: float = 0
    refund_amount: Optional[float] = None
    status: str = "pending"  # pending, approved, rejected, processed
    created_by: Optional[int] = None
    created_at: datetime = Field(default_factory=utcnow)


class OrderReturnTable(SQLModel, table=True):
    """Order return database table."""
    __tablename__ = "order_returns"

    id: Optional[int] = SQLField(default=None, primary_key=True)
    order_id: int = SQLField(index=True)
    reason: Optional[str] = None
    amount: float = 0
    refund_amount: Optional[float] = None
    status: str = "pending"
    created_by: Optional[int] = None
    created_at: datetime = SQLField(default_factory=utcnow)


class Payment(BaseModel):
    """Payment model."""
    id: int
    order_id: int
    amount: float
    method: str = "cash"
    status: str = "pending"
    transaction_id: Optional[str] = None
    paid_date: Optional[datetime] = None
    notes: Optional[str] = None
    created_at: datetime = Field(default_factory=utcnow)


class PaymentTable(SQLModel, table=True):
    """Payment database table."""
    __tablename__ = "payments"

    id: Optional[int] = SQLField(default=None, primary_key=True)
    order_id: int = SQLField(index=True)
    amount: float
    method: str = "cash"
    status: str = "pending"
    transaction_id: Optional[str] = None
    paid_date: Optional[datetime] = None
    notes: Optional[str] = None
    created_at: datetime = SQLField(default_factory=utcnow)

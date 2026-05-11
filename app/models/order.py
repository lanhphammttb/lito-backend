from sqlmodel import SQLModel, Field
from typing import Optional
from datetime import date, datetime

class OrderTable(SQLModel, table=True):
    __tablename__ = "ordertable"
    id: Optional[int] = Field(default=None, primary_key=True)
    date: date
    channel: str
    shipping_fee: float = 0.0
    discount: float = 0.0
    promo_code: Optional[str] = None
    note: Optional[str] = None
    maker_user_id: Optional[int] = None
    status: str = Field(default="pending")
    payment_status: str = Field(default="unpaid")
    shipping_carrier: Optional[str] = None
    tracking_number: Optional[str] = None
    estimated_delivery_date: Optional[date] = None
    shipping_updates_str: str = "[]"
    lines_str: str = "[]"
    customer_id: Optional[int] = None
    created_by: Optional[int] = None
    updated_by: Optional[int] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    source_content_id: Optional[int] = None

class PaymentTable(SQLModel, table=True):
    __tablename__ = "paymenttable"
    id: Optional[int] = Field(default=None, primary_key=True)
    order_id: int = Field(index=True)
    amount: float
    method: str
    status: str = Field(default="pending")
    transaction_id: Optional[str] = None
    note: Optional[str] = None
    created_by: Optional[int] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)

class OrderReturnTable(SQLModel, table=True):
    __tablename__ = "orderreturntable"
    id: Optional[int] = Field(default=None, primary_key=True)
    order_id: int = Field(index=True)
    reason: str
    refund_amount: float = 0.0
    status: str = Field(default="pending")
    items_str: str = "[]"
    restock: bool = True
    created_by: Optional[int] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)

class CustomerTable(SQLModel, table=True):
    __tablename__ = "customertable"
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True)
    phone: Optional[str] = Field(default=None, index=True)
    email: Optional[str] = Field(default=None, index=True)
    address: Optional[str] = None
    source: Optional[str] = None
    tags_str: str = "[]"
    notes: Optional[str] = None
    created_by: Optional[int] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)

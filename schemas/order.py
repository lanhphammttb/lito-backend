"""Order schemas."""
import datetime
from typing import Optional, List
from pydantic import BaseModel, field_validator
from models.order import OrderLine


class OrderCreate(BaseModel):
    """Order create schema."""
    date: datetime.date
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
    estimated_delivery_date: Optional[datetime.date] = None
    note: Optional[str] = None
    maker_user_id: Optional[int] = None
    source_content_id: Optional[int] = None

    @field_validator('shipping_fee', 'discount')
    @classmethod
    def non_negative(cls, v: float) -> float:
        if v < 0:
            raise ValueError('Giá trị không được âm')
        return v

    @field_validator('order_lines')
    @classmethod
    def lines_quantity_positive(cls, v: List[OrderLine]) -> List[OrderLine]:
        for line in v:
            if line.quantity <= 0:
                raise ValueError(f'Số lượng sản phẩm phải lớn hơn 0')
            if line.unit_price < 0:
                raise ValueError(f'Đơn giá không được âm')
        return v

    @field_validator('estimated_delivery_date')
    @classmethod
    def delivery_after_order(cls, v: Optional[datetime.date], info) -> Optional[datetime.date]:
        if v is not None and 'date' in info.data and v < info.data['date']:
            raise ValueError('Ngày giao hàng dự kiến phải sau ngày đặt hàng')
        return v


class OrderReturnCreate(BaseModel):
    """Order return create schema."""
    order_id: int
    reason: Optional[str] = None
    amount: float
    refund_amount: Optional[float] = None

    @field_validator('amount')
    @classmethod
    def amount_positive(cls, v: float) -> float:
        if v <= 0:
            raise ValueError('Số tiền hoàn trả phải lớn hơn 0')
        return v


class PaymentCreate(BaseModel):
    """Payment create schema."""
    order_id: int
    amount: float
    method: str = "cash"
    status: str = "pending"
    transaction_id: Optional[str] = None
    notes: Optional[str] = None

    @field_validator('amount')
    @classmethod
    def amount_positive(cls, v: float) -> float:
        if v <= 0:
            raise ValueError('Số tiền thanh toán phải lớn hơn 0')
        return v


class ShippingUpdatePayload(BaseModel):
    """Shipping update payload."""
    status: Optional[str] = None
    note: Optional[str] = None
    tracking_number: Optional[str] = None
    shipping_carrier: Optional[str] = None
    estimated_delivery_date: Optional[datetime.date] = None

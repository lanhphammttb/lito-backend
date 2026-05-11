"""Customer schemas."""
import re
from typing import Optional, List
from pydantic import BaseModel, field_validator


class CustomerCreate(BaseModel):
    """Customer create schema."""
    name: str
    phone: Optional[str] = None
    email: Optional[str] = None
    address: Optional[str] = None
    source: Optional[str] = None
    tags: List[str] = []
    notes: Optional[str] = None

    @field_validator('name')
    @classmethod
    def name_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError('Tên khách hàng không được để trống')
        return v.strip()

    @field_validator('phone')
    @classmethod
    def phone_format(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        digits = re.sub(r'\s|-', '', v)
        if not re.match(r'^(0|\+84)[3-9]\d{8}$', digits):
            raise ValueError('Số điện thoại không hợp lệ (VD: 0912345678 hoặc +84912345678)')
        return digits

    @field_validator('email')
    @classmethod
    def email_format(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        if '@' not in v or '.' not in v.split('@')[-1]:
            raise ValueError('Email không hợp lệ')
        return v.strip().lower()

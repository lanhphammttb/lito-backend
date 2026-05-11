"""Expense models."""
from typing import Optional
from datetime import datetime, date as date_type
from pydantic import BaseModel
from sqlmodel import SQLModel, Field as SQLField


EXPENSE_CATEGORIES = [
    "rent", "utilities", "tools", "personnel", "marketing", "packaging", "other"
]

CATEGORY_LABELS = {
    "rent": "Thuê mặt bằng",
    "utilities": "Điện / nước / internet",
    "tools": "Dụng cụ sản xuất",
    "personnel": "Nhân công",
    "marketing": "Quảng cáo / marketing",
    "packaging": "Bao bì / đóng gói",
    "other": "Khác",
}


class Expense(BaseModel):
    id: int
    date: date_type
    category: str
    amount: float
    note: Optional[str] = None
    created_by: Optional[int] = None
    created_at: datetime


class ExpenseTable(SQLModel, table=True):
    __tablename__ = "expenses"
    id: Optional[int] = SQLField(default=None, primary_key=True)
    date: date_type = SQLField(index=True)
    category: str = "other"
    amount: float = 0
    note: Optional[str] = None
    created_by: Optional[int] = None
    created_at: datetime = SQLField(default_factory=datetime.utcnow)

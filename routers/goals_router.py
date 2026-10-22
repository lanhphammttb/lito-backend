"""Authenticated goals using the same order totals as business reports."""
from datetime import date
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlmodel import Session, select
from config.database import engine
from models.user import User
from models.goal import GoalTable
from models.order import OrderTable
from models.expense import ExpenseTable
from services.auth import get_current_user
from services.order import compute_order_totals, find_order
from utils.datetime import utcnow

router = APIRouter(dependencies=[Depends(get_current_user)])


def set_data_stores(*args):
    pass


class GoalCreate(BaseModel):
    title: str = Field(min_length=1, max_length=250)
    description: str | None = None
    target_type: Literal['revenue', 'profit', 'orders', 'products', 'customers'] = 'revenue'
    target_value: float = Field(default=0, ge=0, allow_inf_nan=False)
    start_date: date = Field(default_factory=date.today)
    end_date: date = Field(default_factory=date.today)
    status: Literal['active', 'achieved', 'failed', 'missed', 'cancelled'] = 'active'

    @field_validator('title')
    @classmethod
    def nonblank_title(cls, value):
        if not value.strip():
            raise ValueError('Nhập tên mục tiêu')
        return value.strip()

    @model_validator(mode='after')
    def valid_period(self):
        if self.end_date < self.start_date:
            raise ValueError('Ngày kết thúc phải từ ngày bắt đầu trở đi')
        return self


def _compute_current_value(goal) -> float:
    with Session(engine) as session:
        stmt = select(OrderTable).where(OrderTable.status.notin_(('cancelled', 'canceled', 'returned', 'void')))
        if goal.start_date:
            stmt = stmt.where(OrderTable.order_date >= goal.start_date)
        if goal.end_date:
            stmt = stmt.where(OrderTable.order_date <= goal.end_date)
        rows = session.exec(stmt).all()
        if goal.target_type == 'orders':
            return float(len(rows))
        if goal.target_type == 'customers':
            return float(len({row.customer_id for row in rows if row.customer_id}))
        orders = [find_order(row.id) for row in rows]
        if goal.target_type == 'products':
            return float(len({line.product_id for order in orders for line in order.order_lines}))
        totals = [compute_order_totals(order) for order in orders]
        if goal.target_type == 'revenue':
            return round(sum(total['revenue'] for total in totals), 2)
        expenses = select(ExpenseTable)
        if goal.start_date:
            expenses = expenses.where(ExpenseTable.date >= goal.start_date)
        if goal.end_date:
            expenses = expenses.where(ExpenseTable.date <= goal.end_date)
        return round(sum(total['profit'] for total in totals)
                     - sum(row.amount for row in session.exec(expenses)), 2)


def _serialize(goal):
    data = goal.model_dump()
    data['current_value'] = _compute_current_value(goal)
    # Derived status is a read projection; GET must not update database records.
    if goal.status == 'active' and goal.target_value > 0 and data['current_value'] >= goal.target_value:
        data['status'] = 'achieved'
    return data


@router.get('/goals')
async def list_goals():
    with Session(engine) as session:
        return [_serialize(row) for row in session.exec(select(GoalTable).order_by(GoalTable.id.desc()))]


@router.post('/goals')
async def create_goal(payload: GoalCreate, user: User = Depends(get_current_user)):
    with Session(engine) as session:
        row = GoalTable(**payload.model_dump(), created_by=user.id, created_at=utcnow(),
                        achieved_at=utcnow() if payload.status == 'achieved' else None)
        session.add(row)
        session.commit()
        session.refresh(row)
        return _serialize(row)


@router.put('/goals/{goal_id}')
async def update_goal(goal_id: int, payload: dict, user: User = Depends(get_current_user)):
    with Session(engine) as session:
        row = session.get(GoalTable, goal_id)
        if not row:
            raise HTTPException(404, 'Mục tiêu không tồn tại')
        from pydantic import ValidationError
        try:
            data = GoalCreate.model_validate({**row.model_dump(), **payload})
        except ValidationError:
            raise HTTPException(422, 'Thông tin mục tiêu không hợp lệ; kiểm tra tên, chỉ tiêu và khoảng thời gian') from None
        for field, value in data.model_dump().items():
            setattr(row, field, value)
        row.achieved_at = (row.achieved_at or utcnow()) if row.status == 'achieved' else None
        session.add(row)
        session.commit()
        session.refresh(row)
        return _serialize(row)


@router.delete('/goals/{goal_id}')
async def delete_goal(goal_id: int, user: User = Depends(get_current_user)):
    with Session(engine) as session:
        row = session.get(GoalTable, goal_id)
        if not row:
            raise HTTPException(404, 'Mục tiêu không tồn tại')
        session.delete(row)
        session.commit()
    return {'ok': True}

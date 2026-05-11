"""Operating expense routes."""
from typing import List, Optional
from datetime import datetime, date
from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from config.database import engine
from models.user import User
from models.expense import Expense, ExpenseTable, CATEGORY_LABELS
from services.auth import get_current_user

router = APIRouter()
expenses: List[Expense] = []


def load_expenses():
    with Session(engine) as session:
        rows = session.exec(select(ExpenseTable).order_by(ExpenseTable.date.desc())).all()
        expenses.clear()
        for row in rows:
            expenses.append(Expense(
                id=row.id,
                date=row.date,
                category=row.category,
                amount=row.amount,
                note=row.note,
                created_by=row.created_by,
                created_at=row.created_at,
            ))


@router.get("")
async def list_expenses(
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    category: Optional[str] = None,
    user: User = Depends(get_current_user),
):
    result = expenses[:]
    if start_date:
        result = [e for e in result if e.date >= start_date]
    if end_date:
        result = [e for e in result if e.date <= end_date]
    if category:
        result = [e for e in result if e.category == category]
    result.sort(key=lambda e: e.date, reverse=True)
    return result


@router.post("")
async def create_expense(payload: dict, user: User = Depends(get_current_user)):
    exp_date = payload.get("date")
    if isinstance(exp_date, str):
        exp_date = date.fromisoformat(exp_date.split("T")[0])
    elif not isinstance(exp_date, date):
        exp_date = date.today()

    amount = float(payload.get("amount", 0))
    if amount <= 0:
        raise HTTPException(status_code=400, detail="Số tiền phải > 0")

    row = ExpenseTable(
        date=exp_date,
        category=payload.get("category", "other"),
        amount=amount,
        note=payload.get("note"),
        created_by=user.id,
        created_at=datetime.utcnow(),
    )
    with Session(engine) as session:
        session.add(row)
        session.commit()
        session.refresh(row)

    exp = Expense(
        id=row.id,
        date=row.date,
        category=row.category,
        amount=row.amount,
        note=row.note,
        created_by=row.created_by,
        created_at=row.created_at,
    )
    expenses.insert(0, exp)
    return exp


@router.put("/{expense_id}")
async def update_expense(expense_id: int, payload: dict, user: User = Depends(get_current_user)):
    exp = next((e for e in expenses if e.id == expense_id), None)
    if not exp:
        raise HTTPException(status_code=404, detail="Không tìm thấy chi phí")

    exp_date = payload.get("date")
    if isinstance(exp_date, str):
        exp_date = date.fromisoformat(exp_date.split("T")[0])
    elif not isinstance(exp_date, date):
        exp_date = exp.date

    amount = float(payload.get("amount", exp.amount))
    if amount <= 0:
        raise HTTPException(status_code=400, detail="Số tiền phải > 0")

    exp.date = exp_date
    exp.category = payload.get("category", exp.category)
    exp.amount = amount
    exp.note = payload.get("note", exp.note)

    with Session(engine) as session:
        row = session.get(ExpenseTable, expense_id)
        if row:
            row.date = exp.date
            row.category = exp.category
            row.amount = exp.amount
            row.note = exp.note
            session.add(row)
            session.commit()
    return exp


@router.get("/summary")
async def expense_summary(
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    user: User = Depends(get_current_user),
):
    result = expenses[:]
    if start_date:
        result = [e for e in result if e.date >= start_date]
    if end_date:
        result = [e for e in result if e.date <= end_date]
    total = round(sum(e.amount for e in result), 2)
    by_cat = {}
    for e in result:
        by_cat[e.category] = round(by_cat.get(e.category, 0) + e.amount, 2)
    return {
        "total": total,
        "by_category": [
            {"category": k, "label": CATEGORY_LABELS.get(k, k), "amount": v}
            for k, v in sorted(by_cat.items(), key=lambda x: -x[1])
        ],
    }


@router.delete("/{expense_id}")
async def delete_expense(expense_id: int, user: User = Depends(get_current_user)):
    exp = next((e for e in expenses if e.id == expense_id), None)
    if not exp:
        raise HTTPException(status_code=404, detail="Không tìm thấy chi phí")
    expenses.remove(exp)
    with Session(engine) as session:
        row = session.get(ExpenseTable, expense_id)
        if row:
            session.delete(row)
            session.commit()
    return {"ok": True}

"""Legacy order-related root routes."""

from fastapi import APIRouter, Depends
from sqlmodel import Session, select

from config.database import engine
from models.order import OrderReturn, OrderReturnTable, Payment, PaymentTable
from models.user import User
from routers.orders import (
    PAID_PAYMENT_STATUSES,
    order_returns,
    payments,
    refresh_order_payment_status,
    save_payment_sql,
    save_return_sql,
)
from services.auth import get_current_user
from utils.datetime import utcnow

router = APIRouter()


@router.get("/returns")
async def list_returns(order_id: int = None, user: User = Depends(get_current_user)):
    """List order returns."""
    with Session(engine) as session:
        stmt = select(OrderReturnTable).order_by(OrderReturnTable.created_at.desc())
        if order_id:
            stmt = stmt.where(OrderReturnTable.order_id == order_id)
        rows = session.exec(stmt).all()
    return [
        {
            "id": row.id,
            "order_id": row.order_id,
            "reason": row.reason,
            "amount": row.amount,
            "status": row.status,
            "refund_amount": row.refund_amount,
            "created_at": row.created_at,
        }
        for row in rows
    ]


@router.post("/returns")
async def create_return(payload: dict, user: User = Depends(get_current_user)):
    """Create order return."""
    ret = OrderReturn(
        id=0, order_id=payload.get("order_id"), reason=payload.get("reason"),
        amount=payload.get("amount") or payload.get("refund_amount") or 0,
        status="pending", refund_amount=payload.get("refund_amount", 0), created_by=user.id, created_at=utcnow(),
    )
    persisted_return = save_return_sql(ret)
    order_returns.append(persisted_return)
    return {"id": persisted_return.id}


@router.get("/payments")
async def list_payments(order_id: int = None, user: User = Depends(get_current_user)):
    """List payments."""
    with Session(engine) as session:
        stmt = select(PaymentTable).order_by(PaymentTable.created_at.desc())
        if order_id:
            stmt = stmt.where(PaymentTable.order_id == order_id)
        rows = session.exec(stmt).all()
    return [
        {
            "id": row.id,
            "order_id": row.order_id,
            "amount": row.amount,
            "method": row.method,
            "status": row.status,
            "transaction_id": row.transaction_id,
            "paid_date": row.paid_date,
            "notes": row.notes,
            "created_at": row.created_at,
        }
        for row in rows
    ]


@router.post("/payments")
async def create_payment(payload: dict, user: User = Depends(get_current_user)):
    """Create payment."""
    status = payload.get("status", "paid")
    payment = Payment(
        id=0, order_id=payload.get("order_id"), amount=payload.get("amount"),
        method=payload.get("method", "cash"), status=status,
        paid_date=utcnow() if status in PAID_PAYMENT_STATUSES else None, created_at=utcnow(),
    )
    persisted_payment = save_payment_sql(payment)
    payments.append(persisted_payment)
    refresh_order_payment_status(persisted_payment.order_id)
    return {"id": persisted_payment.id}

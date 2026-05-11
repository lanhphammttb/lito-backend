"""Order routes."""
from typing import List, Optional
from datetime import datetime, date
from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request
from sqlmodel import Session

import json
from config.database import engine, upsert_mongo, delete_mongo
from config.settings import ORDER_STATUS_ALLOWED
from models.user import User
from models.order import (
    Order, OrderTable, OrderLine,
    OrderReturn, OrderReturnTable, Payment, PaymentTable,
    ShippingUpdate
)
from schemas.order import OrderCreate, OrderReturnCreate, PaymentCreate, ShippingUpdatePayload
from services.auth import get_current_user, require_admin
from services.order import (
    compute_order_totals, validate_order_payload, apply_promo,
    reserve_stock_for_order, restock_for_order, find_order
)
from services.activity import log_activity, create_audit_log
from services.notification import notify_new_order, notify_order_status_change
from services.product import find_product
from routers.products import save_product_sql
from utils.datetime import utcnow
from sqlmodel import select
from models.order import OrderLineTable


def save_order_sql(order):
    """Upsert an order to SQL."""
    lines_json = json.dumps([
        {"product_id": l.product_id, "quantity": l.quantity,
         "unit_price": l.unit_price, "variant_id": l.variant_id}
        for l in order.order_lines
    ])
    shipping_updates_json = json.dumps([
        {
            "order_id": getattr(u, "order_id", None),
            "status": getattr(u, "status", None),
            "note": getattr(u, "note", None),
            "shipping_carrier": getattr(u, "shipping_carrier", None),
            "tracking_number": getattr(u, "tracking_number", None),
            "estimated_delivery_date": (
                getattr(u, "estimated_delivery_date", None).isoformat()
                if getattr(u, "estimated_delivery_date", None)
                else None
            ),
            "timestamp": getattr(u, "timestamp", None).isoformat() if getattr(u, "timestamp", None) else None,
        }
        for u in getattr(order, "shipping_updates", [])
    ])
    with Session(engine) as session:
        row = session.get(OrderTable, order.id)
        if row:
            row.order_date = order.date
            row.channel = order.channel
            row.customer_id = order.customer_id
            row.order_lines_json = lines_json
            row.shipping_updates_json = shipping_updates_json
            row.shipping_fee = order.shipping_fee
            row.discount = order.discount
            row.promo_code = order.promo_code
            row.status = order.status
            row.payment_status = order.payment_status
            row.shipping_carrier = order.shipping_carrier
            row.tracking_number = order.tracking_number
            row.estimated_delivery_date = order.estimated_delivery_date
            row.note = order.note
            row.maker_user_id = order.maker_user_id
            row.source_content_id = order.source_content_id
            row.updated_by = getattr(order, "updated_by", None)
            row.updated_at = getattr(order, "updated_at", None)
        else:
            row = OrderTable(
                id=order.id,
                order_date=order.date,
                channel=order.channel,
                customer_id=order.customer_id,
                order_lines_json=lines_json,
                shipping_updates_json=shipping_updates_json,
                shipping_fee=order.shipping_fee,
                discount=order.discount,
                promo_code=order.promo_code,
                status=order.status,
                payment_status=order.payment_status,
                shipping_carrier=order.shipping_carrier,
                tracking_number=order.tracking_number,
                estimated_delivery_date=order.estimated_delivery_date,
                note=order.note,
                maker_user_id=order.maker_user_id,
                source_content_id=order.source_content_id,
                created_by=getattr(order, "created_by", None),
                created_at=order.created_at,
                updated_at=getattr(order, "updated_at", None),
            )
            session.add(row)
        
        # Handle relational OrderLineTable
        existing_lines = session.exec(select(OrderLineTable).where(OrderLineTable.order_id == order.id)).all()
        for line in existing_lines:
            session.delete(line)
        
        for l in order.order_lines:
            new_line = OrderLineTable(
                order_id=order.id,
                product_id=l.product_id,
                quantity=l.quantity,
                unit_price=l.unit_price,
                variant_id=l.variant_id
            )
            session.add(new_line)

        session.commit()


def save_return_sql(return_obj: OrderReturn) -> OrderReturn:
    """Persist an order return and return the normalized model."""
    with Session(engine) as session:
        row = session.get(OrderReturnTable, return_obj.id) if getattr(return_obj, "id", None) else None
        if row:
            row.order_id = return_obj.order_id
            row.reason = return_obj.reason
            row.amount = return_obj.amount
            row.refund_amount = return_obj.refund_amount
            row.status = return_obj.status
            row.created_by = return_obj.created_by
        else:
            row = OrderReturnTable(
                order_id=return_obj.order_id,
                reason=return_obj.reason,
                amount=return_obj.amount,
                refund_amount=return_obj.refund_amount,
                status=return_obj.status,
                created_by=return_obj.created_by,
            )
        session.add(row)
        session.commit()
        session.refresh(row)
        return OrderReturn(
            id=row.id,
            order_id=row.order_id,
            reason=row.reason,
            amount=row.amount,
            refund_amount=row.refund_amount,
            status=row.status,
            created_by=row.created_by,
            created_at=row.created_at,
        )


def save_payment_sql(payment: Payment) -> Payment:
    """Persist a payment and return the normalized model."""
    with Session(engine) as session:
        row = session.get(PaymentTable, payment.id) if getattr(payment, "id", None) else None
        if row:
            row.order_id = payment.order_id
            row.amount = payment.amount
            row.method = payment.method
            row.status = payment.status
            row.transaction_id = payment.transaction_id
            row.paid_date = payment.paid_date
            row.notes = payment.notes
        else:
            row = PaymentTable(
                order_id=payment.order_id,
                amount=payment.amount,
                method=payment.method,
                status=payment.status,
                transaction_id=payment.transaction_id,
                paid_date=payment.paid_date,
                notes=payment.notes,
            )
        session.add(row)
        session.commit()
        session.refresh(row)
        return Payment(
            id=row.id,
            order_id=row.order_id,
            amount=row.amount,
            method=row.method,
            status=row.status,
            transaction_id=row.transaction_id,
            paid_date=row.paid_date,
            notes=row.notes,
            created_at=row.created_at,
        )

router = APIRouter()
RESERVE_STATUSES = {"confirmed", "producing"}


SHIPPED_STATUSES = {"delivered", "completed"}

def _deduct_finished_qty(order):
    """Trừ thành phẩm khi hàng rời kho. Bỏ qua nếu sản phẩm không tìm thấy."""
    for line in order.order_lines:
        try:
            product = find_product(line.product_id)
            product.finished_qty = max(0, getattr(product, "finished_qty", 0) - line.quantity)
            save_product_sql(product)
        except Exception:
            pass

def _restore_finished_qty(order):
    """Hoàn lại thành phẩm khi đơn bị huỷ sau khi đã ship."""
    for line in order.order_lines:
        try:
            product = find_product(line.product_id)
            product.finished_qty = getattr(product, "finished_qty", 0) + line.quantity
            save_product_sql(product)
        except Exception:
            pass

def _apply_stock_transition(old_status: str, new_status: str, order, user):
    """
    Duy nhất một nơi quyết định thao tác kho khi đổi status đơn hàng.

    NVL (nguyên vật liệu):
    - confirmed / producing  → RESERVE  (giữ chỗ NVL)
    - cancelled              → RELEASE  (trả lại available)

    Thành phẩm (finished_qty):
    - → shipped/delivered/completed (lần đầu)  → DEDUCT
    - cancelled từ trạng thái đã ship          → RESTORE
    """
    was_reserved = old_status in RESERVE_STATUSES
    now_reserved  = new_status in RESERVE_STATUSES

    if not was_reserved and now_reserved:
        reserve_stock_for_order(order, user)
    elif was_reserved and new_status == "cancelled":
        restock_for_order(order, user)

    # Thành phẩm: trừ khi lần đầu chuyển sang trạng thái đã giao hàng
    was_shipped = old_status in SHIPPED_STATUSES
    now_shipped  = new_status in SHIPPED_STATUSES
    if not was_shipped and now_shipped:
        _deduct_finished_qty(order)
    elif was_shipped and new_status == "cancelled":
        _restore_finished_qty(order)


# In-memory data stores
orders: List[Order] = []
order_returns: List[OrderReturn] = []
payments: List[Payment] = []
shipping_updates: List[ShippingUpdate] = []


@router.get("")
async def list_orders(
    skip: int = 0,
    limit: int = 100,
    status: Optional[str] = None,
    customer_id: Optional[int] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    search: Optional[str] = None,
    user: User = Depends(get_current_user)
):
    """List all orders directly from Database using SQLModel."""
    with Session(engine) as session:
        statement = select(OrderTable)

        if status:
            statement = statement.where(OrderTable.status == status)
        if customer_id:
            statement = statement.where(OrderTable.customer_id == customer_id)
        if start_date:
            statement = statement.where(OrderTable.order_date >= start_date)
        if end_date:
            statement = statement.where(OrderTable.order_date <= end_date)

        # Handle Search (Simple ILIKE alternative for notes)
        if search:
            search_pattern = f"%{search}%"
            statement = statement.where(OrderTable.note.like(search_pattern))

        statement = statement.order_by(OrderTable.order_date.desc()).offset(skip).limit(limit)
        results = session.exec(statement).all()

        output = []
        for row in results:
            # Build relational lines if available, fallback to JSON
            lines = []
            if row.lines:
                lines = [OrderLine(product_id=l.product_id, quantity=l.quantity, unit_price=l.unit_price, variant_id=l.variant_id) for l in row.lines]
            elif row.order_lines_json:
                try:
                    lines = [OrderLine(**l) for l in json.loads(row.order_lines_json)]
                except Exception:
                    pass
            
            order_obj = Order(
                id=row.id,
                date=row.order_date,
                channel=row.channel,
                customer_id=row.customer_id,
                order_lines=lines,
                shipping_fee=row.shipping_fee,
                discount=row.discount,
                promo_code=row.promo_code,
                status=row.status,
                payment_status=row.payment_status,
                shipping_carrier=row.shipping_carrier,
                tracking_number=row.tracking_number,
                estimated_delivery_date=row.estimated_delivery_date,
                note=row.note,
                maker_user_id=row.maker_user_id,
                source_content_id=row.source_content_id,
                created_by=row.created_by,
                updated_by=row.updated_by,
                created_at=row.created_at,
                updated_at=row.updated_at
            )
            
            totals = compute_order_totals(order_obj)
            output.append({**order_obj.model_dump(), "computed": totals})

        return output


_products = []
_customers = []
_users = []
_content_plans = []


def set_related_stores(p, c, u, cp=None):
    """Inject products, customers, users, content_plans for summary endpoint."""
    global _products, _customers, _users, _content_plans
    _products = p
    _customers = c
    _users = u
    _content_plans = cp or []


@router.get("/summary")
async def get_orders_summary(user: User = Depends(get_current_user)):
    """Get order summary stats for orders page."""
    orders_out = []
    user_revenue: dict = {}
    user_profit: dict = {}
    user_count: dict = {}

    with Session(engine) as session:
        statement = select(OrderTable).order_by(OrderTable.order_date.desc())
        results = session.exec(statement).all()
        
        pending_count = 0
        completed_count = 0

        for row in results:
            if row.status == "pending":
                pending_count += 1
            elif row.status in ("done", "delivered", "completed"):
                completed_count += 1

            lines = []
            if getattr(row, "lines", None):
                lines = [OrderLine(product_id=l.product_id, quantity=l.quantity, unit_price=l.unit_price, variant_id=l.variant_id) for l in row.lines]
            elif row.order_lines_json:
                try:
                    lines = [OrderLine(**l) for l in json.loads(row.order_lines_json)]
                except Exception:
                    pass
                    
            from models.order import ShippingUpdate
            shipping_updates = []
            if getattr(row, "shipping_updates_json", None):
                try:
                    shipping_updates = [ShippingUpdate(**u) for u in json.loads(row.shipping_updates_json)]
                except Exception:
                    pass

            order_obj = Order(
                id=row.id,
                date=row.order_date,
                channel=row.channel,
                customer_id=row.customer_id,
                order_lines=lines,
                shipping_fee=row.shipping_fee,
                discount=row.discount,
                promo_code=row.promo_code,
                status=row.status,
                payment_status=row.payment_status,
                shipping_carrier=row.shipping_carrier,
                tracking_number=row.tracking_number,
                estimated_delivery_date=row.estimated_delivery_date,
                note=row.note,
                maker_user_id=row.maker_user_id,
                source_content_id=row.source_content_id,
                created_by=row.created_by,
                updated_by=row.updated_by,
                shipping_updates=shipping_updates,
                created_at=row.created_at,
                updated_at=row.updated_at
            )

            totals = compute_order_totals(order_obj)
            orders_out.append({**order_obj.model_dump(), **totals, "computed": totals})
            
            uid = getattr(order_obj, 'assigned_to', None) or getattr(order_obj, 'created_by', None)
            if uid:
                user_revenue[uid] = user_revenue.get(uid, 0) + totals["revenue"]
                user_profit[uid] = user_profit.get(uid, 0) + totals["profit"]
                user_count[uid] = user_count.get(uid, 0) + 1

    total_revenue = sum(o["computed"]["revenue"] for o in orders_out)

    products_out = [p.model_dump() if hasattr(p, 'model_dump') else dict(p) for p in _products]
    customers_out = [c.model_dump() if hasattr(c, 'model_dump') else dict(c) for c in _customers]
    users_out = [{"id": u.get("id"), "name": u.get("name"), "email": u.get("email"), "role": u.get("role")} for u in _users]

    maker_report = [
        {
            "maker_user_id": uid,
            "maker_name": next((u.get("name") for u in _users if u.get("id") == uid), f"User #{uid}"),
            "orders_count": user_count[uid],
            "revenue": round(user_revenue[uid], 2),
            "profit": round(user_profit[uid], 2),
        }
        for uid in user_revenue
    ]

    return {
        "total_orders": len(orders_out),
        "total_revenue": total_revenue,
        "pending": pending_count,
        "completed": completed_count,
        "orders": orders_out,
        "products": products_out,
        "customers": customers_out,
        "users": users_out,
        "contents": [cp.model_dump() if hasattr(cp, 'model_dump') else dict(cp) for cp in _content_plans],
        "maker_report": maker_report,
    }


@router.get("/{order_id}")
async def get_order(
    order_id: int,
    user: User = Depends(get_current_user)
):
    """Get single order with details directly from Database."""
    order = find_order(order_id)
    totals = compute_order_totals(order)

    with Session(engine) as session:
        returns_db = session.exec(select(OrderReturnTable).where(OrderReturnTable.order_id == order_id)).all()
        payments_db = session.exec(select(PaymentTable).where(PaymentTable.order_id == order_id)).all()
        
        return {
            **order.model_dump(),
            "computed": totals,
            "returns": [r.model_dump() for r in returns_db],
            "payments": [p.model_dump() for p in payments_db],
            "shipping_updates": [s.model_dump() for s in order.shipping_updates],
        }


@router.post("")
async def create_order(
    payload: OrderCreate,
    request: Request,
    user: User = Depends(get_current_user)
):
    """Create new order."""
    validate_order_payload(payload)
    apply_promo(payload)

    new_id = max((o.id for o in orders), default=0) + 1
    now = utcnow()

    order = Order(
        id=new_id,
        customer_id=payload.customer_id,
        date=payload.date or date.today(),
        status=payload.status,
        channel=payload.channel or "manual",
        shipping_fee=payload.shipping_fee or 0,
        discount=payload.discount or 0,
        promo_code=getattr(payload, "promo_code", None),
        note=payload.note,
        order_lines=[],
        created_at=now,
        updated_at=now,
    )

    # Add order lines
    for line_data in payload.order_lines:
        line = OrderLine(
            product_id=line_data.product_id,
            quantity=line_data.quantity,
            unit_price=line_data.unit_price,
            variant_id=line_data.variant_id,
        )
        order.order_lines.append(line)

    if order.status in RESERVE_STATUSES:
        reserve_stock_for_order(order, user)

    save_order_sql(order)
    upsert_mongo("orders", order.model_dump(mode="json") if hasattr(order, "model_dump") else order.__dict__)
    log_activity(user.id, "order", new_id, "create", {"status": order.status})
    await create_audit_log(user, "CREATE", "orders", new_id, None, order.__dict__, request)
    await notify_new_order({"id": new_id, "status": order.status}, user.id)

    totals = compute_order_totals(order)
    return {**order.__dict__, "computed": totals}


@router.put("/{order_id}")
async def update_order(
    order_id: int,
    request: Request,
    payload: dict = Body(...),
    user: User = Depends(get_current_user)
):
    """Update order."""
    order = find_order(order_id)
    before_data = order.__dict__.copy()
    old_status = order.status

    allowed = {
        "customer_id",
        "date",
        "status",
        "channel",
        "shipping_fee",
        "discount",
        "promo_code",
        "note",
        "payment_status",
        "shipping_carrier",
        "tracking_number",
        "estimated_delivery_date",
        "maker_user_id",
        "source_content_id",
        "order_lines",
    }
    data = {key: value for key, value in payload.items() if key in allowed}

    if "customer_id" in data:
        order.customer_id = data["customer_id"]
    if "date" in data and data["date"]:
        order.date = date.fromisoformat(data["date"]) if isinstance(data["date"], str) else data["date"]
    if "status" in data and data["status"]:
        order.status = data["status"]
    if "channel" in data and data["channel"]:
        order.channel = data["channel"]
    if "shipping_fee" in data:
        order.shipping_fee = float(data["shipping_fee"] or 0)
    if "discount" in data:
        order.discount = float(data["discount"] or 0)
    if "promo_code" in data:
        order.promo_code = data["promo_code"]
    if "note" in data:
        order.note = data["note"]
    if "payment_status" in data:
        order.payment_status = data["payment_status"]
    if "shipping_carrier" in data:
        order.shipping_carrier = data["shipping_carrier"]
    if "tracking_number" in data:
        order.tracking_number = data["tracking_number"]
    if "estimated_delivery_date" in data:
        value = data["estimated_delivery_date"]
        order.estimated_delivery_date = (
            date.fromisoformat(value) if isinstance(value, str) and value else value
        )
    if "maker_user_id" in data:
        order.maker_user_id = data["maker_user_id"]
    if "source_content_id" in data:
        order.source_content_id = data["source_content_id"]
    if "order_lines" in data:
        order.order_lines = []
        for line_data in data["order_lines"] or []:
            line = OrderLine(
                product_id=line_data["product_id"],
                quantity=line_data["quantity"],
                unit_price=line_data.get("unit_price", 0),
                variant_id=line_data.get("variant_id"),
            )
            order.order_lines.append(line)

        # Keep legacy validation only when the client actually sends order lines
        validate_order_payload(type("_Payload", (), {
            "status": order.status,
            "order_lines": order.order_lines,
        })())
        if order.promo_code:
            apply_promo(type("_Payload", (), {
                "promo_code": order.promo_code,
                "discount": order.discount,
                "order_lines": order.order_lines,
            })())

    order.updated_at = utcnow()

    _apply_stock_transition(old_status, order.status, order, user)

    save_order_sql(order)
    upsert_mongo("orders", order.model_dump(mode="json") if hasattr(order, "model_dump") else order.__dict__)
    log_activity(user.id, "order", order_id, "update", {"status": order.status})
    await create_audit_log(user, "UPDATE", "orders", order_id, before_data, order.__dict__, request)

    # Notify status change
    if old_status != order.status:
        await notify_order_status_change(order_id, order.status, user.id)

    totals = compute_order_totals(order)
    return {**order.__dict__, "computed": totals}


@router.patch("/{order_id}")
async def patch_order(
    order_id: int,
    payload: dict,
    request: Request,
    user: User = Depends(get_current_user)
):
    """Partial update — accepts any subset of order fields."""
    order = find_order(order_id)
    before_data = order.__dict__.copy()
    old_status = order.status

    allowed = {"status", "payment_status", "note", "channel", "shipping_fee",
               "discount", "shipping_carrier", "tracking_number", "maker_user_id"}
    for key, val in payload.items():
        if key in allowed:
            setattr(order, key, val)

    new_status = order.status
    _apply_stock_transition(old_status, new_status, order, user)

    save_order_sql(order)
    upsert_mongo("orders", order.model_dump(mode="json") if hasattr(order, "model_dump") else order.__dict__)
    log_activity(user.id, "order", order_id, "patch", payload)
    await create_audit_log(user, "UPDATE", "orders", order_id, before_data, order.__dict__, request)

    if old_status != new_status:
        await notify_order_status_change(order_id, new_status, user.id)

    return {**order.__dict__, "computed": compute_order_totals(order)}


@router.patch("/{order_id}/status")
async def update_order_status(
    order_id: int,
    payload: dict,
    request: Request,
    user: User = Depends(get_current_user)
):
    """Update order status only."""
    order = find_order(order_id)
    new_status = payload.get("status")

    if new_status not in ORDER_STATUS_ALLOWED:
        raise HTTPException(status_code=400, detail="Trạng thái không hợp lệ")

    old_status = order.status
    before_data = order.__dict__.copy()

    order.status = new_status
    order.updated_at = utcnow()

    _apply_stock_transition(old_status, new_status, order, user)

    save_order_sql(order)
    log_activity(user.id, "order", order_id, "status_change", {"from": old_status, "to": new_status})
    await create_audit_log(user, "UPDATE", "orders", order_id, before_data, order.__dict__, request)
    await notify_order_status_change(order_id, new_status, user.id)
    return {"message": "Đã cập nhật trạng thái", "status": new_status}


@router.delete("/{order_id}")
async def delete_order(
    order_id: int,
    request: Request,
    user: User = Depends(get_current_user)
):
    """Delete order."""
    require_admin(user)
    order = find_order(order_id)
    before_data = order.__dict__.copy()

    # Restock if needed
    if order.status in RESERVE_STATUSES:
        restock_for_order(order, user)

    with Session(engine) as session:
        row = session.get(OrderTable, order_id)
        if row:
            session.delete(row)
            session.commit()
    delete_mongo("orders", "id", order_id)
    log_activity(user.id, "order", order_id, "delete", {})
    await create_audit_log(user, "DELETE", "orders", order_id, before_data, None, request)
    return {"message": "Đã xóa đơn hàng"}


@router.post("/{order_id}/returns")
async def create_return(
    order_id: int,
    payload: OrderReturnCreate,
    request: Request,
    user: User = Depends(get_current_user)
):
    """Create order return."""
    find_order(order_id)

    return_obj = OrderReturn(
        id=0,
        order_id=order_id,
        reason=payload.reason,
        amount=payload.amount,
        refund_amount=payload.refund_amount,
        status="pending",
        created_by=user.id,
        created_at=utcnow(),
    )
    persisted_return = save_return_sql(return_obj)
    order_returns.append(persisted_return)

    log_activity(user.id, "order_return", persisted_return.id, "create", {"order_id": order_id})

    return persisted_return


@router.post("/{order_id}/payments")
async def create_payment(
    order_id: int,
    payload: PaymentCreate,
    request: Request,
    user: User = Depends(get_current_user)
):
    """Add payment to order."""
    find_order(order_id)

    payment = Payment(
        id=0,
        order_id=order_id,
        amount=payload.amount,
        method=payload.method,
        status=payload.status,
        transaction_id=payload.transaction_id,
        paid_date=utcnow() if payload.status == "paid" else None,
        notes=payload.notes,
        created_at=utcnow(),
    )
    persisted_payment = save_payment_sql(payment)
    payments.append(persisted_payment)

    log_activity(user.id, "payment", persisted_payment.id, "create", {"order_id": order_id, "amount": payload.amount})

    return persisted_payment


@router.post("/{order_id}/shipping")
async def add_shipping_update(
    order_id: int,
    payload: ShippingUpdatePayload,
    user: User = Depends(get_current_user)
):
    """Add shipping update to order."""
    find_order(order_id)

    update = ShippingUpdate(
        order_id=order_id,
        status=payload.status,
        note=payload.note,
        shipping_carrier=payload.shipping_carrier,
        tracking_number=payload.tracking_number,
        estimated_delivery_date=payload.estimated_delivery_date,
        timestamp=utcnow(),
    )
    shipping_updates.append(update)

    order = find_order(order_id)
    order.shipping_updates = list(order.shipping_updates or [])
    order.shipping_updates.append(update)
    save_order_sql(order)

    return update


@router.post("/{order_id}/tracking")
async def add_tracking_update(
    order_id: int,
    payload: ShippingUpdatePayload,
    user: User = Depends(get_current_user)
):
    """Alias endpoint for frontend compatibility."""
    return await add_shipping_update(order_id, payload, user)

"""Order services."""
from typing import Dict, List
from fastapi import HTTPException

from config.settings import ORDER_STATUS_ALLOWED
from models.order import OrderLine
from services.product import find_product, compute_product_cost
from services.stock_ledger import (
    calculate_material_requirements,
    validate_material_availability,
    reserve_materials_for_order,
    release_reserved_materials_for_order,
    consume_reserved_materials_for_order,
    has_consumed_materials_for_order,
)

# These will be injected from data store
orders = []
order_returns = []
promo_codes = []
stock_movements = []
materials = []


def set_data_stores(o, r, p, s, m):
    """Set data stores."""
    global orders, order_returns, promo_codes, stock_movements, materials
    orders = o
    order_returns = r
    promo_codes = p
    stock_movements = s
    materials = m


def find_order(order_id: int):
    """Find order by ID using Database."""
    from sqlmodel import Session
    from config.database import engine
    from models.order import OrderTable, Order, OrderLine, ShippingUpdate
    import json
    
    with Session(engine) as session:
        row = session.get(OrderTable, order_id)
        if not row:
            raise HTTPException(status_code=404, detail=f"Order {order_id} không tồn tại")
            
        lines = []
        if getattr(row, "lines", None):
            lines = [OrderLine(product_id=l.product_id, quantity=l.quantity, unit_price=l.unit_price, variant_id=l.variant_id) for l in row.lines]
        elif row.order_lines_json:
            try:
                lines = [OrderLine(**l) for l in json.loads(row.order_lines_json)]
            except Exception:
                pass
                
        shipping_updates = []
        if getattr(row, "shipping_updates_json", None):
            try:
                shipping_updates = [ShippingUpdate(**u) for u in json.loads(row.shipping_updates_json)]
            except Exception:
                pass
                
        return Order(
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


def validate_order_payload(payload):
    """Validate order payload."""
    if payload.status not in ORDER_STATUS_ALLOWED:
        raise HTTPException(status_code=400, detail="Trạng thái đơn hàng không hợp lệ")
    if not payload.order_lines:
        raise HTTPException(status_code=400, detail="Đơn hàng phải có ít nhất 1 sản phẩm")
    for line in payload.order_lines:
        find_product(line.product_id)
        if line.quantity <= 0:
            raise HTTPException(status_code=400, detail="Số lượng phải > 0")
        if line.unit_price < 0:
            raise HTTPException(status_code=400, detail="Đơn giá phải >= 0")


def compute_promo_discount(promo, order_lines: List[OrderLine]) -> float:
    """Compute discount amount from promo code."""
    if not promo.is_active:
        return 0

    applicable_total = 0
    for line in order_lines:
        if not promo.applicable_product_ids or line.product_id in promo.applicable_product_ids:
            applicable_total += line.unit_price * line.quantity

    if applicable_total < promo.min_order_value:
        return 0

    if promo.discount_type == "percent":
        discount = applicable_total * promo.discount_value / 100
    else:
        discount = promo.discount_value

    if promo.max_discount:
        discount = min(discount, promo.max_discount)

    return discount


def apply_promo(payload):
    """Apply promo code to order payload."""
    if not getattr(payload, "promo_code", None):
        return

    promo = next(
        (p for p in promo_codes if p.code.lower() == payload.promo_code.lower() and p.is_active),
        None
    )
    if promo:
        discount = compute_promo_discount(promo, payload.order_lines)
        if discount > payload.discount:
            payload.discount = discount


def compute_order_totals(order) -> Dict[str, float]:
    """Compute order totals including revenue, cost, profit."""
    gross = sum(line.unit_price * line.quantity for line in order.order_lines)
    discount = order.discount

    # Re-apply promo if active
    if getattr(order, "promo_code", None):
        promo = next((p for p in promo_codes if p.code.lower() == order.promo_code.lower() and p.is_active), None)
        if promo:
            promo_discount = compute_promo_discount(promo, order.order_lines)
            discount = max(discount, promo_discount)

    returns_amount = sum(
        r.refund_amount or r.amount
        for r in order_returns
        if r.order_id == order.id and r.status in {"approved", "processed"}
    )

    revenue = max(0, gross - discount - returns_amount)
    cost = order.shipping_fee

    for line in order.order_lines:
        try:
            product = find_product(line.product_id)
            product_cost = compute_product_cost(product)
            cost += (
                product_cost["material_cost"]
                + product_cost["labor_cost"]
                + product_cost.get("packaging_cost", 0)
                + product_cost.get("marketing_cost", 0)
                + product_cost.get("platform_fee_amount", 0)
            ) * line.quantity
        except Exception:
            pass

    profit = revenue - cost

    return {
        "revenue": round(revenue, 2),
        "cost": round(cost, 2),
        "profit": round(profit, 2),
        "computed_discount": round(discount, 2),
    }


def stock_movements_for_order(order_id: int):
    """Get stock movements for an order."""
    return [mv for mv in stock_movements if mv.reference_type == "order" and mv.reference_id == order_id]


def ensure_materials_available(order):
    """Fail fast if any material would go negative on reservation."""
    validate_material_availability(calculate_material_requirements(order))


def reserve_stock_for_order(order, current_user):
    """Reserve materials without consuming on-hand stock."""
    reserve_materials_for_order(order, current_user)


def release_reserved_stock_for_order(order, current_user):
    """Release reservation if production has not consumed it yet."""
    release_reserved_materials_for_order(order, current_user)


def deduct_stock_for_order(order, current_user):
    """Consume reserved stock when production actually starts."""
    consume_reserved_materials_for_order(order, current_user)


def restock_for_order(order, current_user):
    """Cancel only unconsumed reservations; production rollback must be manual."""
    if has_consumed_materials_for_order(order.id):
        raise HTTPException(
            status_code=409,
            detail="Đơn đã bắt đầu sản xuất, không thể hoàn kho tự động",
        )
    release_reserved_stock_for_order(order, current_user)

"""Order services."""
from typing import Dict, List, Any
from fastapi import HTTPException

from config.settings import ORDER_STATUS_ALLOWED
from models.order import OrderLine
from services.product import find_product, compute_product_cost
from services.stock_ledger import (
    calculate_material_requirements,
    validate_material_availability,
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


def order_lines_from_row(row):
    import json
    try:
        stored = json.loads(row.order_lines_json or '[]')
    except (ValueError, TypeError):
        stored = []
    if row.lines:
        result = []
        for index, line in enumerate(sorted(row.lines, key=lambda item: item.id)):
            values = {key: getattr(line, key) for key in ('product_id', 'variant_id', 'quantity', 'unit_price')}
            if index < len(stored) and all(stored[index].get(key) == value for key, value in values.items()):
                values['unit_cost_snapshot'] = stored[index].get('unit_cost_snapshot')
            result.append(OrderLine(**values))
        return result
    return [OrderLine(**values) for values in stored]


def snapshot_order_costs(order, previous_lines=()):
    previous = {(line.product_id, line.variant_id): line.unit_cost_snapshot for line in previous_lines
                if line.unit_cost_snapshot is not None}
    for line in order.order_lines:
        key = (line.product_id, line.variant_id)
        if key in previous:
            line.unit_cost_snapshot = previous[key]
        else:
            costs = compute_product_cost(find_product(line.product_id))
            line.unit_cost_snapshot = sum(costs.get(field, 0) for field in
                ('material_cost', 'labor_cost', 'packaging_cost', 'marketing_cost', 'platform_fee_amount', 'other_cost'))


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
            
        lines = order_lines_from_row(row)
                
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
        if line.variant_id is not None:
            from sqlmodel import Session
            from config.database import engine
            from models.product import ProductVariantTable
            with Session(engine) as session:
                variant = session.get(ProductVariantTable, line.variant_id)
                if not variant or variant.product_id != line.product_id:
                    raise HTTPException(422, 'Biến thể không thuộc sản phẩm đã chọn')
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


def compute_order_totals(order) -> Dict[str, Any]:
    """Compute order totals including revenue, cost, profit."""
    gross = sum(line.unit_price * line.quantity for line in order.order_lines)
    discount = order.discount

    returns_amount = sum(
        r.refund_amount or r.amount
        for r in order_returns
        if r.order_id == order.id and r.status in {"approved", "processed"}
    )

    revenue = max(0, gross - discount - returns_amount)
    cost = order.shipping_fee

    for line in order.order_lines:
        if getattr(line, 'unit_cost_snapshot', None) is not None:
            cost += line.unit_cost_snapshot * line.quantity
            continue
        try:
            product = find_product(line.product_id)
            product_cost = compute_product_cost(product)
            cost += (
                product_cost["material_cost"]
                + product_cost["labor_cost"]
                + product_cost.get("packaging_cost", 0)
                + product_cost.get("marketing_cost", 0)
                + product_cost.get("platform_fee_amount", 0)
                + product_cost.get("other_cost", 0)
            ) * line.quantity
        except Exception:
            pass

    profit = revenue - cost

    return {
        "revenue": round(revenue, 2),
        "cost": round(cost, 2),
        "profit": round(profit, 2),
        "computed_discount": round(discount, 2),
        "cost_is_estimated": True,
        "cost_basis": 'saved_estimate' if all(getattr(line, 'unit_cost_snapshot', None) is not None for line in order.order_lines)
                      else 'current_bom_estimate',
    }


def stock_movements_for_order(order_id: int):
    """Get stock movements for an order."""
    return [mv for mv in stock_movements if mv.reference_type == "order" and mv.reference_id == order_id]


def ensure_materials_available(order):
    """Fail fast if any material would go negative on reservation."""
    validate_material_availability(calculate_material_requirements(order))


def reserve_stock_for_order(order, current_user):
    """Material choice belongs to each job; confirming an order does not reserve BOM."""
    return


def release_reserved_stock_for_order(order, current_user):
    """Release reservation if production has not consumed it yet."""
    from services.stock_ledger import release_legacy_order_reservations
    if has_consumed_materials_for_order(order.id):
        raise HTTPException(409, "Đơn đã tiêu hao nguyên liệu, không thể hoàn giữ chỗ tự động")
    release_legacy_order_reservations(order.id, current_user.id)


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
    from services.stock_ledger import cancel_unstarted_order_jobs
    cancel_unstarted_order_jobs(order.id, current_user.id)
    release_reserved_stock_for_order(order, current_user)

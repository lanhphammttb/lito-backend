"""Inventory routes - Suppliers and Purchase Orders."""
import json
from typing import List, Optional
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlmodel import Session, select

from config.database import engine
from config.settings import PURCHASE_ORDER_STATUS_ALLOWED
from models.user import User
from models.inventory import Supplier, SupplierTable, PurchaseOrder, PurchaseOrderTable, PurchaseOrderLine
from models.material import MaterialPriceEntryTable
from schemas.inventory import SupplierCreate, PurchaseOrderCreate
from services.auth import get_current_user, require_admin
from services.inventory import find_supplier, compute_po_total, receive_purchase_order
from services.activity import log_activity, create_audit_log

router = APIRouter()

# In-memory data stores
suppliers: List[Supplier] = []
purchase_orders: List[PurchaseOrder] = []

# Additional data stores set via set_data_stores() at startup
_materials = []
_products = []


def set_data_stores(materials_list, products_list):
    """Inject shared materials and products lists for the summary endpoint."""
    global _materials, _products
    _materials = materials_list
    _products = products_list


def _resolve_latest_unit_prices(material_ids: List[int], supplier_by_material: Optional[dict] = None) -> dict:
    """Resolve latest known unit price per material from price history.

    Priority: latest price from preferred supplier -> latest price from any supplier.
    """
    ids = [int(mid) for mid in material_ids if mid]
    if not ids:
        return {}

    with Session(engine) as session:
        rows = session.exec(
            select(MaterialPriceEntryTable)
            .where(MaterialPriceEntryTable.material_id.in_(ids))
            .order_by(
                MaterialPriceEntryTable.purchase_date.desc(),
                MaterialPriceEntryTable.created_at.desc(),
            )
        ).all()

    latest_any = {}
    latest_by_supplier = {}
    for row in rows:
        mid = int(row.material_id)
        key = (mid, row.supplier_id)
        if mid not in latest_any:
            latest_any[mid] = float(row.unit_price or 0)
        if key not in latest_by_supplier:
            latest_by_supplier[key] = float(row.unit_price or 0)

    result = {}
    supplier_by_material = supplier_by_material or {}
    for mid in ids:
        preferred_supplier = supplier_by_material.get(mid)
        preferred_price = latest_by_supplier.get((mid, preferred_supplier))
        fallback_price = latest_any.get(mid)
        if preferred_price is not None:
            result[mid] = preferred_price
        elif fallback_price is not None:
            result[mid] = fallback_price
    return result


@router.get("/summary")
async def inventory_summary(user: User = Depends(get_current_user)):
    """
    Optimized endpoint for Inventory page - returns all necessary data in 1 call.
    Replaces: /materials, /products, /suppliers, /purchase-orders
    """
    # Material statistics
    low_stock_count = sum(1 for m in _materials if m.stock_quantity <= m.low_threshold)
    total_value = sum((m.stock_quantity or 0) * (getattr(m, "unit_price", 0) or 0) for m in _materials)

    # Material types breakdown
    types_breakdown = {}
    for m in _materials:
        types_breakdown[m.type] = types_breakdown.get(m.type, 0) + 1

    # Products with max units calculation
    material_map = {m.id: m for m in _materials}
    enhanced_products = []
    for p in _products:
        if not getattr(p, "materials", None):
            max_units = 0
        else:
            min_units = float("inf")
            for usage in p.materials:
                mat = material_map.get(usage.material_id)
                if mat:
                    max_for_mat = (mat.stock_quantity or 0) / (usage.quantity or 1)
                    min_units = min(min_units, max_for_mat)
            max_units = int(min_units) if min_units != float("inf") else 0

        product_dict = p.model_dump() if hasattr(p, "model_dump") else p.__dict__.copy()
        product_dict["max_units_from_stock"] = max_units
        enhanced_products.append(product_dict)

    with Session(engine) as session:
        all_suppliers = session.exec(select(SupplierTable)).all()
        all_pos = session.exec(select(PurchaseOrderTable)).all()

    from services.inventory import find_supplier, find_purchase_order

    return {
        "materials": [dict(m) for m in _materials],
        "products": enhanced_products,
        "suppliers": [find_supplier(s.id).model_dump() for s in all_suppliers],
        "purchase_orders": [find_purchase_order(p.id).model_dump() for p in all_pos],
        "statistics": {
            "total_materials": len(_materials),
            "low_stock_count": low_stock_count,
            "total_inventory_value": round(total_value, 2),
            "types_breakdown": types_breakdown,
        },
    }


@router.get("/suppliers")
async def list_suppliers(
    skip: int = 0,
    limit: int = 100,
    search: Optional[str] = None,
    user: User = Depends(get_current_user)
):
    """List all suppliers from Database."""
    from services.inventory import find_supplier
    with Session(engine) as session:
        statement = select(SupplierTable)
        if search:
            search_pattern = f"%{search}%"
            statement = statement.where(SupplierTable.name.like(search_pattern))
            
        results = session.exec(statement.offset(skip).limit(limit)).all()
        return [find_supplier(r.id) for r in results]


@router.get("/suppliers/{supplier_id}")
async def get_supplier(supplier_id: int, user: User = Depends(get_current_user)):
    """Get single supplier."""
    return find_supplier(supplier_id)


@router.post("/suppliers")
async def create_supplier(
    payload: SupplierCreate,
    request: Request,
    user: User = Depends(get_current_user)
):
    """Create new supplier."""
    require_admin(user)
    now = datetime.utcnow()
    supplier_row = SupplierTable(
        name=payload.name,
        contact_name=payload.contact_name,
        phone=payload.phone,
        email=payload.email,
        address=payload.address,
        note=payload.note,
        rating=payload.rating,
        lead_time_days=getattr(payload, "lead_time_days", None),
        created_at=now,
    )
    with Session(engine) as session:
        session.add(supplier_row)
        session.commit()
        session.refresh(supplier_row)

    supplier = Supplier(
        id=supplier_row.id,
        name=supplier_row.name,
        contact_name=supplier_row.contact_name,
        phone=supplier_row.phone,
        email=supplier_row.email,
        address=supplier_row.address,
        note=supplier_row.note,
        rating=supplier_row.rating,
        lead_time_days=getattr(supplier_row, "lead_time_days", None),
        created_at=supplier_row.created_at,
    )

    log_activity(user.id, "supplier", supplier.id, "create", {"name": supplier.name})
    return supplier


@router.put("/suppliers/{supplier_id}")
async def update_supplier(
    supplier_id: int,
    payload: SupplierCreate,
    user: User = Depends(get_current_user)
):
    """Update supplier."""
    require_admin(user)
    supplier = find_supplier(supplier_id)

    supplier.name = payload.name
    supplier.contact_name = payload.contact_name
    supplier.phone = payload.phone
    supplier.email = payload.email
    supplier.address = payload.address
    supplier.note = payload.note
    supplier.rating = payload.rating
    supplier.lead_time_days = getattr(payload, "lead_time_days", None)

    with Session(engine) as session:
        row = session.get(SupplierTable, supplier_id)
        if row:
            row.name = supplier.name
            row.contact_name = supplier.contact_name
            row.phone = supplier.phone
            row.email = supplier.email
            row.address = supplier.address
            row.note = supplier.note
            row.rating = supplier.rating
            row.lead_time_days = supplier.lead_time_days
            session.add(row)
            session.commit()

    log_activity(user.id, "supplier", supplier_id, "update", {"name": supplier.name})
    return supplier


@router.delete("/suppliers/{supplier_id}")
async def delete_supplier(
    supplier_id: int,
    user: User = Depends(get_current_user)
):
    """Delete supplier."""
    require_admin(user)
    supplier = find_supplier(supplier_id)

    with Session(engine) as session:
        row = session.get(SupplierTable, supplier_id)
        if row:
            session.delete(row)
            session.commit()

    log_activity(user.id, "supplier", supplier_id, "delete", {})
    return {"message": "Đã xóa nhà cung cấp"}


# Purchase Orders
@router.get("/purchase-orders/suggestions")
async def get_purchase_suggestions(user: User = Depends(get_current_user)):
    """Get purchase order suggestions based on low stock."""
    from services.material import get_low_stock_alerts

    alerts = get_low_stock_alerts()
    suggestions = []
    supplier_map = {a["material_id"]: a.get("supplier_id") for a in alerts}
    latest_prices = _resolve_latest_unit_prices([a["material_id"] for a in alerts], supplier_map)

    for alert in alerts:
        threshold = alert.get("low_threshold", 10)
        current = alert.get("stock_quantity", 0)
        unit_price = alert.get("unit_price", 0) or latest_prices.get(alert["material_id"], 0) or 0
        suggested_qty = max(threshold * 2 - current, threshold)
        weeks_of_stock = (current / threshold * 4) if threshold > 0 else 0

        if current <= 0:
            urgency = "critical"
        elif current < threshold:
            urgency = "high"
        else:
            urgency = "medium"

        suggestions.append({
            "material_id": alert["material_id"],
            "material_code": alert.get("code", ""),
            "material_name": alert["name"],
            "current_stock": current,
            "low_threshold": threshold,
            "suggested_quantity": suggested_qty,
            "unit": alert["unit"],
            "unit_price": unit_price,
            "estimated_cost": round(suggested_qty * unit_price, 0),
            "weeks_remaining": round(weeks_of_stock, 1),
            "urgency": urgency,
        })

    return suggestions


@router.post("/purchase-orders/auto-create")
async def auto_create_purchase_orders(
    material_ids: list,
    user: User = Depends(get_current_user)
):
    """Create draft POs for selected low-stock materials.

    Groups by supplier_id when possible (one PO per supplier),
    creates one PO per unassigned material otherwise.
    """
    from services.material import get_low_stock_alerts, find_material

    # Get current suggestions for all low-stock items
    alerts = get_low_stock_alerts()
    alert_map = {a["material_id"]: a for a in alerts}

    supplier_map = {a["material_id"]: a.get("supplier_id") for a in alerts}
    latest_prices = _resolve_latest_unit_prices(material_ids, supplier_map)

    # Build PO lines grouped by supplier
    by_supplier: dict = {}  # supplier_id (or None) → list of lines
    for mid in material_ids:
        mid = int(mid)
        if mid not in alert_map:
            # Not low stock, skip
            continue
        alert = alert_map[mid]
        threshold = alert.get("low_threshold", 10)
        current = alert.get("stock_quantity", 0)
        unit_price = alert.get("unit_price", 0) or latest_prices.get(mid, 0) or 0
        suggested_qty = max(threshold * 2 - current, threshold)

        try:
            mat = find_material(mid)
            supplier_id = getattr(mat, "supplier_id", None)
        except Exception:
            supplier_id = None

        key = supplier_id if supplier_id else f"no_supplier_{mid}"
        if key not in by_supplier:
            by_supplier[key] = {
                "supplier_id": supplier_id,
                "lines": [],
            }
        by_supplier[key]["lines"].append(PurchaseOrderLine(
            material_id=mid,
            quantity=suggested_qty,
            unit_price=unit_price,
        ))

    if not by_supplier:
        return {"created_count": 0, "po_ids": []}

    now = datetime.utcnow()
    created = []
    for grp in by_supplier.values():
        lines = grp["lines"]
        sup_id = grp["supplier_id"]
        lines_json = json.dumps([l.model_dump(mode="json") for l in lines])
        total = compute_po_total(lines)

        po_row = PurchaseOrderTable(
            supplier_id=sup_id,
            status="draft",
            lines_json=lines_json,
            total_amount=total,
            created_by=user.id,
            created_at=now,
        )
        with Session(engine) as session:
            session.add(po_row)
            session.commit()
            session.refresh(po_row)

        po = PurchaseOrder(
            id=po_row.id,
            supplier_id=po_row.supplier_id,
            status="draft",
            lines=lines,
            total_amount=total,
            created_by=po_row.created_by,
            created_at=po_row.created_at,
        )
        created.append(po_row.id)

    log_activity(user.id, "purchase_order", None, "auto_create", {"count": len(created)})
    return {"created_count": len(created), "po_ids": created}


@router.get("/purchase-orders")
async def list_purchase_orders(
    skip: int = 0,
    limit: int = 100,
    status: Optional[str] = None,
    supplier_id: Optional[int] = None,
    user: User = Depends(get_current_user)
):
    """List purchase orders from DB."""
    from services.inventory import find_purchase_order
    with Session(engine) as session:
        statement = select(PurchaseOrderTable)
        if status:
            statement = statement.where(PurchaseOrderTable.status == status)
        if supplier_id:
            statement = statement.where(PurchaseOrderTable.supplier_id == supplier_id)
            
        statement = statement.order_by(PurchaseOrderTable.created_at.desc()).offset(skip).limit(limit)
        results = session.exec(statement).all()
        
        output = []
        for row in results:
            po = find_purchase_order(row.id)
            output.append({
                **po.model_dump(),
                "computed_total": compute_po_total(po.lines),
            })
        return output


@router.get("/purchase-orders/{po_id}")
async def get_purchase_order(po_id: int, user: User = Depends(get_current_user)):
    """Get single purchase order."""
    from services.inventory import find_purchase_order
    po = find_purchase_order(po_id)
    return {
        **po.model_dump(),
        "computed_total": compute_po_total(po.lines),
    }


@router.post("/purchase-orders")
async def create_purchase_order(
    payload: PurchaseOrderCreate,
    request: Request,
    user: User = Depends(get_current_user)
):
    """Create purchase order."""
    if payload.status and payload.status not in PURCHASE_ORDER_STATUS_ALLOWED:
        raise HTTPException(status_code=400, detail="Trạng thái không hợp lệ")

    now = datetime.utcnow()
    lines = [
        PurchaseOrderLine(
            material_id=line_data.material_id,
            quantity=line_data.quantity,
            unit_price=line_data.unit_price,
            batch_id=getattr(line_data, "batch_id", None),
            expiry_date=getattr(line_data, "expiry_date", None),
        )
        for line_data in payload.lines
    ]
    lines_json = json.dumps([l.model_dump(mode="json") for l in lines])

    po_row = PurchaseOrderTable(
        supplier_id=payload.supplier_id,
        status=payload.status or "draft",
        expected_date=payload.expected_date,
        note=payload.note,
        lines_json=lines_json,
        total_amount=compute_po_total(lines),
        created_by=user.id,
        created_at=now,
    )
    with Session(engine) as session:
        session.add(po_row)
        session.commit()
        session.refresh(po_row)

    po = PurchaseOrder(
        id=po_row.id,
        supplier_id=po_row.supplier_id,
        status=po_row.status,
        expected_date=po_row.expected_date,
        note=po_row.note,
        lines=lines,
        total_amount=po_row.total_amount,
        created_by=po_row.created_by,
        created_at=po_row.created_at,
    )

    log_activity(user.id, "purchase_order", po.id, "create", {"supplier_id": po.supplier_id})
    return {**po.__dict__, "computed_total": compute_po_total(po.lines)}


@router.patch("/purchase-orders/{po_id}/status")
async def update_po_status(
    po_id: int,
    payload: dict,
    user: User = Depends(get_current_user)
):
    """Update purchase order status."""
    from services.inventory import find_purchase_order
    po = find_purchase_order(po_id)

    new_status = payload.get("status")
    if new_status not in PURCHASE_ORDER_STATUS_ALLOWED:
        raise HTTPException(status_code=400, detail="Trạng thái không hợp lệ")

    old_status = po.status
    po.status = new_status

    if new_status == "received" and old_status != "received":
        receive_purchase_order(po, user)

    with Session(engine) as session:
        row = session.get(PurchaseOrderTable, po_id)
        if row:
            row.status = po.status
            if po.received_at:
                row.received_at = po.received_at
            session.add(row)
            session.commit()

    log_activity(user.id, "purchase_order", po_id, "status_change", {"from": old_status, "to": new_status})
    return {"message": "Đã cập nhật trạng thái", "status": new_status}


@router.post("/purchase-orders/{po_id}/payment")
async def record_po_payment(
    po_id: int,
    payload: dict,
    user: User = Depends(get_current_user)
):
    """Record a payment against a purchase order.

    payload: { amount: float, method: str, note: str? }
    Cumulates paid_amount; sets payment_status = partial | paid automatically.
    """
    from services.inventory import find_purchase_order
    po = find_purchase_order(po_id)

    amount = float(payload.get("amount", 0))
    if amount <= 0:
        raise HTTPException(status_code=400, detail="Số tiền thanh toán phải > 0")

    po.paid_amount = round(getattr(po, "paid_amount", 0) + amount, 2)
    total = float(po.total_amount or 0)

    # If PO has not been priced yet (total_amount == 0), treat first payment as valuation.
    if total <= 0 and po.paid_amount > 0:
        po.total_amount = po.paid_amount
        total = po.total_amount

    if total > 0 and po.paid_amount >= total:
        po.payment_status = "paid"
    elif po.paid_amount > 0:
        po.payment_status = "partial"
    else:
        po.payment_status = "unpaid"

    with Session(engine) as session:
        row = session.get(PurchaseOrderTable, po_id)
        if row:
            row.total_amount = po.total_amount
            row.paid_amount = po.paid_amount
            row.payment_status = po.payment_status
            session.add(row)
            session.commit()

    log_activity(user.id, "purchase_order", po_id, "payment", {
        "amount": amount,
        "method": payload.get("method", "cash"),
        "paid_total": po.paid_amount,
    })
    return {"ok": True, "paid_amount": po.paid_amount, "payment_status": po.payment_status}


@router.delete("/purchase-orders/{po_id}")
async def delete_purchase_order(
    po_id: int,
    user: User = Depends(get_current_user)
):
    """Delete purchase order."""
    from services.inventory import find_purchase_order
    po = find_purchase_order(po_id)

    if po.status == "received":
        raise HTTPException(status_code=400, detail="Không thể xóa PO đã nhận hàng")

    with Session(engine) as session:
        row = session.get(PurchaseOrderTable, po_id)
        if row:
            session.delete(row)
            session.commit()

    log_activity(user.id, "purchase_order", po_id, "delete", {})
    return {"message": "Đã xóa purchase order"}



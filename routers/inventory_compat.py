"""Legacy inventory root routes."""

import json

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session

from config.database import engine
from models.inventory import PurchaseOrder, PurchaseOrderLine
from models import PurchaseOrderTable
from models.user import User
from routers.inventory import purchase_orders
from services.auth import get_current_user
from utils.datetime import utcnow

router = APIRouter()


@router.get("/stock-movements")
async def list_stock_movements(material_id: int = None, user: User = Depends(get_current_user)):
    """List stock movements — always read from DB so new movements appear immediately."""
    from models.material import StockMovementTable
    from sqlmodel import Session, select as sql_select
    with Session(engine) as session:
        stmt = sql_select(StockMovementTable).order_by(StockMovementTable.created_at.desc())
        if material_id:
            stmt = stmt.where(StockMovementTable.material_id == material_id)
        rows = session.exec(stmt).all()
    return [
        {
            "id": r.id, "material_id": r.material_id, "quantity_change": r.quantity_change,
            "movement_type": r.movement_type, "reference_type": r.reference_type,
            "reference_id": r.reference_id, "unit_price": r.unit_price,
            "note": r.note, "created_at": str(r.created_at) if r.created_at else None,
        }
        for r in rows
    ]


@router.post("/stock-movements")
async def create_stock_movement(payload: dict, user: User = Depends(get_current_user)):
    """Create stock movement via stock ledger (persists to SQL + updates balances)."""
    from services.stock_ledger import apply_adjustment, record_purchase
    from services.material import find_material, save_material_sql

    material_id = int(payload.get("material_id"))
    qty_change = float(payload.get("quantity_change", payload.get("quantity", 0)))
    movement_type = payload.get("movement_type", "adjustment")
    note = payload.get("note")
    new_price = payload.get("new_price")

    if movement_type == "purchase":
        movement = record_purchase(
            material_id=material_id,
            quantity=qty_change,
            user_id=user.id,
            reference_id=payload.get("reference_id"),
            note=note,
        )
    else:
        movement = apply_adjustment(
            material_id=material_id,
            quantity_change=qty_change,
            user_id=user.id,
            note=note,
        )

    if new_price is not None and float(new_price) > 0:
        mat = find_material(material_id)
        mat.unit_price = float(new_price)
        save_material_sql(mat)

    return movement


@router.post("/purchase-orders/generate")
async def generate_purchase_order(payload: dict, user: User = Depends(get_current_user)):
    """Generate a draft purchase order from suggested items."""
    items = payload.get("items") or payload.get("lines") or []
    if not items:
        raise HTTPException(status_code=400, detail="Danh sách vật tư không được trống")

    lines = []
    for item in items:
        material_id = item.get("material_id") or item.get("id")
        quantity = item.get("quantity") or item.get("suggested_quantity")
        if not material_id or quantity is None:
            raise HTTPException(status_code=400, detail="Mỗi dòng cần material_id và quantity")
        lines.append(PurchaseOrderLine(
            material_id=int(material_id),
            quantity=float(quantity),
            unit_price=float(item.get("unit_price", 0) or 0),
            batch_id=item.get("batch_id"),
            expiry_date=item.get("expiry_date"),
        ))

    now = utcnow()
    total = sum(line.quantity * line.unit_price for line in lines)
    po_row = PurchaseOrderTable(
        supplier_id=payload.get("supplier_id"),
        status="draft",
        note=payload.get("note") or "Tạo từ gợi ý mua hàng",
        lines_json=json.dumps([line.model_dump(mode="json") for line in lines]),
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
        status=po_row.status,
        note=po_row.note,
        lines=lines,
        total_amount=po_row.total_amount,
        created_by=po_row.created_by,
        created_at=po_row.created_at,
    )
    purchase_orders.append(po)
    return po

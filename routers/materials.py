"""Material routes."""
from typing import List, Optional
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlmodel import Session

from config.database import engine, upsert_mongo, delete_mongo
from models.user import User
from models.material import Material, MaterialTable, StockMovement, StockMovementTable, MaterialBatchTable, MaterialPriceEntry, MaterialPriceEntryTable
from schemas.material import MaterialCreate, StockMovementCreate
from services.auth import get_current_user
from services.material import find_material, get_low_stock_alerts, save_material_sql
from services.activity import log_activity, create_audit_log
from services.product import clear_product_cost_cache
from services.notification import ws_manager

router = APIRouter()

# In-memory data stores
materials: List[Material] = []
stock_movements: List[StockMovement] = []


@router.get("")
async def list_materials(
    skip: int = 0,
    limit: int = 100,
    type: Optional[str] = None,
    search: Optional[str] = None,
    low_stock: bool = False,
    user: User = Depends(get_current_user)
):
    """List all materials from Database."""
    from sqlmodel import select, or_
    with Session(engine) as session:
        statement = select(MaterialTable)
        if type:
            statement = statement.where(MaterialTable.type == type)
        if search:
            search_pattern = f"%{search}%"
            statement = statement.where(or_(MaterialTable.name.like(search_pattern), MaterialTable.code.like(search_pattern)))
            
        results = session.exec(statement).all()
        
        output = []
        for row in results:
            m = find_material(row.id)
            if low_stock:
                from config.settings import settings
                if m.stock_quantity > (m.low_threshold or settings.low_stock_threshold):
                    continue
            output.append(m)
            
        return output[skip:skip + limit]


@router.get("/alerts")
async def material_alerts(user: User = Depends(get_current_user)):
    """Get low stock alerts."""
    return get_low_stock_alerts()


@router.get("/{material_id}")
async def get_material(
    material_id: int,
    user: User = Depends(get_current_user)
):
    """Get single material."""
    return find_material(material_id)


@router.post("")
async def create_material(
    payload: MaterialCreate,
    request: Request,
    user: User = Depends(get_current_user)
):
    """Create new material."""
    now = datetime.utcnow()

    material = Material(
        id=0,
        code=payload.code,
        name=payload.name,
        type=payload.type,
        unit=payload.unit,
        unit_type=getattr(payload, "unit_type", "continuous") or "continuous",
        base_unit=getattr(payload, "base_unit", None) or payload.unit,
        unit_price=payload.unit_price if payload.unit_price is not None else 0,
        stock_quantity=(payload.on_hand_qty if payload.on_hand_qty is not None else payload.stock_quantity) or 0,
        on_hand_qty=payload.on_hand_qty if payload.on_hand_qty is not None else (payload.stock_quantity or 0),
        reserved_qty=getattr(payload, "reserved_qty", 0) or 0,
        available_qty=payload.available_qty if payload.available_qty is not None else ((payload.on_hand_qty if payload.on_hand_qty is not None else payload.stock_quantity) or 0),
        low_threshold=payload.low_threshold,
        supplier_id=payload.supplier_id,
        note=payload.note,
        created_at=now,
    )

    with Session(engine) as session:
        row = MaterialTable(
            code=material.code,
            name=material.name,
            type=material.type,
            unit=material.unit,
            unit_type=material.unit_type,
            base_unit=material.base_unit,
            unit_price=material.unit_price,
            stock_quantity=material.stock_quantity,
            on_hand_qty=material.on_hand_qty,
            reserved_qty=material.reserved_qty,
            available_qty=material.available_qty,
            low_threshold=material.low_threshold,
            supplier_id=material.supplier_id,
            note=material.note,
            created_at=material.created_at,
        )
        session.add(row)
        session.commit()
        session.refresh(row)

    material.id = row.id

    upsert_mongo("materials", material.model_dump(mode="json") if hasattr(material, "model_dump") else material.__dict__)
    log_activity(user.id, "material", material.id, "create", {"name": material.name})
    await create_audit_log(user, "CREATE", "materials", material.id, None, material.__dict__, request)
    clear_product_cost_cache()
    return material


@router.put("/{material_id}")
async def update_material(
    material_id: int,
    payload: MaterialCreate,
    request: Request,
    user: User = Depends(get_current_user)
):
    """Update material."""
    material = find_material(material_id)
    before_data = material.__dict__.copy()

    material.code = payload.code
    material.name = payload.name
    material.type = payload.type
    material.unit = payload.unit
    material.unit_type = getattr(payload, "unit_type", None) or getattr(material, "unit_type", "continuous")
    if payload.unit_price is not None:
        material.unit_price = payload.unit_price
    material.low_threshold = payload.low_threshold
    material.supplier_id = payload.supplier_id
    material.note = payload.note

    save_material_sql(material)

    log_activity(user.id, "material", material_id, "update", {"name": material.name})
    await create_audit_log(user, "UPDATE", "materials", material_id, before_data, material.__dict__, request)

    clear_product_cost_cache()

    return material


@router.delete("/{material_id}")
async def delete_material(
    material_id: int,
    request: Request,
    user: User = Depends(get_current_user)
):
    """Delete material."""
    material = find_material(material_id)
    before_data = material.__dict__.copy()

    # Delete from SQL
    with Session(engine) as session:
        row = session.get(MaterialTable, material_id)
        if row:
            session.delete(row)
            session.commit()

    delete_mongo("materials", "id", material_id)
    log_activity(user.id, "material", material_id, "delete", {"name": material.name})
    await create_audit_log(user, "DELETE", "materials", material_id, before_data, None, request)

    clear_product_cost_cache()

    return {"message": "Đã xóa nguyên vật liệu"}


@router.post("/{material_id}/movements")
async def add_stock_movement(
    material_id: int,
    payload: StockMovementCreate,
    request: Request,
    user: User = Depends(get_current_user)
):
    """Add stock movement (in/out/adjustment)."""
    material = find_material(material_id)

    from sqlmodel import Session, select
    with Session(engine) as session:
        max_id_val = session.exec(select(StockMovementTable.id).order_by(StockMovementTable.id.desc())).first()
        new_id = (max_id_val or 0) + 1
        
    movement = StockMovement(
        id=new_id,
        material_id=material_id,
        quantity_change=payload.quantity_change,
        movement_type=payload.movement_type,
        reference_type=payload.reference_type,
        reference_id=payload.reference_id,
        batch_id=payload.batch_id,
        expiry_date=payload.expiry_date,
        user_id=user.id,
        note=payload.note,
        created_at=datetime.utcnow(),
    )

    # Update material stock
    material.stock_quantity += payload.quantity_change
    save_material_sql(material)

    # Save movement to SQL
    with Session(engine) as session:
        session.add(StockMovementTable(
            material_id=material_id,
            quantity_change=movement.quantity_change,
            movement_type=movement.movement_type,
            reference_type=movement.reference_type,
            reference_id=movement.reference_id,
            batch_id=movement.batch_id,
            expiry_date=movement.expiry_date,
            user_id=movement.user_id,
            note=movement.note,
            created_at=movement.created_at,
        ))
        session.commit()

    log_activity(user.id, "material", material_id, "stock_movement", {
        "change": payload.quantity_change,
        "type": payload.movement_type,
    })

    clear_product_cost_cache()

    return movement


@router.get("/{material_id}/movements")
async def get_stock_movements(
    material_id: int,
    skip: int = 0,
    limit: int = 100,
    user: User = Depends(get_current_user)
):
    """Get stock movement history for material from Database."""
    find_material(material_id)
    with Session(engine) as session:
        from sqlmodel import select
        statement = select(StockMovementTable).where(StockMovementTable.material_id == material_id).order_by(StockMovementTable.created_at.desc()).offset(skip).limit(limit)
        rows = session.exec(statement).all()
        return [r.model_dump() for r in rows]


@router.get("/{material_id}/batches")
async def get_material_batches(
    material_id: int,
    user: User = Depends(get_current_user)
):
    """Get all batches/lots for a material, newest first."""
    find_material(material_id)
    with Session(engine) as session:
        from sqlmodel import select as sql_select
        batches = session.exec(
            sql_select(MaterialBatchTable)
            .where(MaterialBatchTable.material_id == material_id)
            .order_by(MaterialBatchTable.received_date.desc())
        ).all()
    return [b.model_dump() for b in batches]


ADJUSTMENT_REASONS = {"loss", "found", "damage", "sample", "correction", "return", "other"}


@router.post("/{material_id}/adjust")
async def adjust_stock(
    material_id: int,
    payload: dict,
    request: Request,
    user: User = Depends(get_current_user)
):
    """Manual stock adjustment with typed reason (loss/found/damage/sample/correction/return/other).

    payload: { quantity_change: float, reason: str, note: str? }
    Positive = nhập thêm, Negative = xuất/mất.
    """
    qty = float(payload.get("quantity_change", 0))
    if qty == 0:
        raise HTTPException(status_code=400, detail="Số lượng thay đổi không được bằng 0")
    reason = payload.get("reason", "other")
    if reason not in ADJUSTMENT_REASONS:
        raise HTTPException(status_code=400, detail=f"Lý do không hợp lệ. Chọn: {', '.join(ADJUSTMENT_REASONS)}")
    note = payload.get("note") or f"Điều chỉnh kho: {reason}"

    from services.stock_ledger import apply_adjustment
    apply_adjustment(material_id=material_id, quantity_change=qty, user_id=user.id, note=f"[{reason}] {note}")
    log_activity(user.id, "material", material_id, "adjust", {"change": qty, "reason": reason})

    # Broadcast low-stock alert if the material now falls below threshold
    mat = find_material(material_id)
    if mat.stock_quantity <= (mat.low_threshold or 1):
        await ws_manager.broadcast({
            "type": "low_stock_alert",
            "material_id": material_id,
            "name": mat.name,
            "stock": mat.stock_quantity,
            "threshold": mat.low_threshold,
            "unit": mat.unit,
        })

    return {"ok": True, "material_id": material_id, "quantity_change": qty, "reason": reason}


# ─── Material Price History ───────────────────────────────────────────────────

@router.post("/{material_id}/prices")
async def add_price_entry(
    material_id: int,
    payload: dict,
    user: User = Depends(get_current_user)
):
    """Record a new price entry for a material from a supplier."""
    find_material(material_id)
    from datetime import date as _date
    purchase_date = payload.get("purchase_date")
    if isinstance(purchase_date, str):
        purchase_date = _date.fromisoformat(purchase_date)
    elif not isinstance(purchase_date, _date):
        purchase_date = _date.today()

    unit_price = float(payload.get("unit_price", 0))
    total_quantity = payload.get("total_quantity")
    total_amount = payload.get("total_amount") or (
        round(unit_price * float(total_quantity), 2) if total_quantity else None
    )

    with Session(engine) as session:
        row = MaterialPriceEntryTable(
            material_id=material_id,
            supplier_id=payload.get("supplier_id"),
            supplier_name=payload.get("supplier_name"),
            unit_price=unit_price,
            total_quantity=float(total_quantity) if total_quantity is not None else None,
            total_amount=total_amount,
            purchase_date=purchase_date,
            quality_rating=payload.get("quality_rating"),
            note=payload.get("note"),
            created_by=user.id,
            created_at=datetime.utcnow(),
        )
        session.add(row)
        session.commit()
        session.refresh(row)
        return row.model_dump()


@router.get("/{material_id}/prices")
async def list_price_history(
    material_id: int,
    supplier_id: Optional[int] = None,
    user: User = Depends(get_current_user)
):
    """List price history for a material, newest first."""
    find_material(material_id)
    with Session(engine) as session:
        from sqlmodel import select as sql_select
        q = sql_select(MaterialPriceEntryTable).where(
            MaterialPriceEntryTable.material_id == material_id
        )
        if supplier_id:
            q = q.where(MaterialPriceEntryTable.supplier_id == supplier_id)
        rows = session.exec(q.order_by(MaterialPriceEntryTable.purchase_date.desc())).all()
    return [r.model_dump() for r in rows]


@router.get("/{material_id}/prices/summary")
async def price_summary(
    material_id: int,
    user: User = Depends(get_current_user)
):
    """Per-supplier price stats: avg, min, max, last price, entry count."""
    find_material(material_id)
    with Session(engine) as session:
        from sqlmodel import select as sql_select
        rows = session.exec(
            sql_select(MaterialPriceEntryTable)
            .where(MaterialPriceEntryTable.material_id == material_id)
            .order_by(MaterialPriceEntryTable.purchase_date.desc())
        ).all()

    # Group by supplier
    groups: dict = {}
    for r in rows:
        key = r.supplier_id or 0
        if key not in groups:
            groups[key] = {
                "supplier_id": r.supplier_id,
                "supplier_name": r.supplier_name or "Không rõ",
                "prices": [],
                "last_price": None,
                "last_date": None,
                "quality_ratings": [],
            }
        g = groups[key]
        g["prices"].append(r.unit_price)
        if g["last_price"] is None:
            g["last_price"] = r.unit_price
            g["last_date"] = str(r.purchase_date)
        if r.quality_rating:
            g["quality_ratings"].append(r.quality_rating)

    result = []
    for g in groups.values():
        prices = g["prices"]
        ratings = g["quality_ratings"]
        result.append({
            "supplier_id": g["supplier_id"],
            "supplier_name": g["supplier_name"],
            "count": len(prices),
            "avg_price": round(sum(prices) / len(prices), 2),
            "min_price": min(prices),
            "max_price": max(prices),
            "last_price": g["last_price"],
            "last_date": g["last_date"],
            "avg_rating": round(sum(ratings) / len(ratings), 1) if ratings else None,
        })

    result.sort(key=lambda x: x["avg_price"])
    return result


@router.delete("/{material_id}/prices/{price_id}")
async def delete_price_entry(
    material_id: int,
    price_id: int,
    user: User = Depends(get_current_user)
):
    """Delete a price history entry."""
    with Session(engine) as session:
        row = session.get(MaterialPriceEntryTable, price_id)
        if not row or row.material_id != material_id:
            raise HTTPException(status_code=404, detail="Không tìm thấy")
        session.delete(row)
        session.commit()
    return {"ok": True}

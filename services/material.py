"""Material services."""
from typing import List
from datetime import datetime
from fastapi import HTTPException
from sqlmodel import Session

from config.database import engine
from config.settings import settings

# In-memory data store
materials = []


def set_data_stores(m):
    """Set data stores."""
    global materials
    materials = m


def find_material(material_id: int):
    """Find material by ID from Database."""
    from sqlmodel import Session
    from config.database import engine
    from models.material import MaterialTable, Material
    with Session(engine) as session:
        row = session.get(MaterialTable, material_id)
        if not row:
            raise HTTPException(status_code=404, detail=f"Material {material_id} không tồn tại")
        
        stock_qty = row.stock_quantity or 0
        reserved_qty = getattr(row, "reserved_qty", None) or 0
        on_hand_qty = getattr(row, "on_hand_qty", None) or 0
        if on_hand_qty == 0 and stock_qty > 0:
            on_hand_qty = stock_qty
        available_qty = max(0.0, on_hand_qty - reserved_qty)
        
        return Material(
            id=row.id, code=row.code, name=row.name, type=row.type,
            unit=row.unit, unit_type=getattr(row, "unit_type", None) or "continuous",
            unit_price=row.unit_price, stock_quantity=row.stock_quantity,
            base_unit=getattr(row, "base_unit", None),
            on_hand_qty=on_hand_qty,
            reserved_qty=reserved_qty,
            available_qty=available_qty,
            low_threshold=row.low_threshold, supplier_id=getattr(row, "supplier_id", None),
            note=row.note, created_at=row.created_at,
        )


def get_reserved_quantity(material_id: int, reference_type=None, reference_id=None) -> float:
    """Compute outstanding reserved quantity from persisted stock movements."""
    from models.material import StockMovementTable

    material = find_material(material_id)
    if reference_type is None and reference_id is None:
        reserved_qty = getattr(material, "reserved_qty", None)
        if reserved_qty is not None:
            return round(max(0.0, float(reserved_qty)), 4)

    with Session(engine) as session:
        rows = session.query(StockMovementTable).filter(
            StockMovementTable.material_id == material_id
        ).all()

    reserved = 0.0
    for row in rows:
        if reference_type and row.reference_type != reference_type:
            continue
        if reference_id is not None and row.reference_id != reference_id:
            continue
        if row.movement_type == "reserve":
            reserved += row.quantity_change
        elif row.movement_type in {"release", "consume"}:
            reserved += row.quantity_change
    return round(max(0.0, reserved), 4)


def get_available_quantity(material_id: int) -> float:
    material = find_material(material_id)
    on_hand = getattr(material, "on_hand_qty", None)
    if on_hand is None:
        on_hand = material.stock_quantity or 0
    reserved_qty = getattr(material, "reserved_qty", None)
    if reserved_qty is None:
        reserved_qty = get_reserved_quantity(material_id)
    return round(max(0.0, float(on_hand) - float(reserved_qty)), 4)


def get_low_stock_alerts() -> List[dict]:
    """Get materials with low stock from Database."""
    from sqlmodel import Session, select
    from config.database import engine
    from models.material import MaterialTable
    
    threshold = settings.low_stock_threshold
    alerts = []
    with Session(engine) as session:
        rows = session.exec(select(MaterialTable)).all()
        for m in rows:
            m_threshold = m.low_threshold if m.low_threshold is not None else threshold
            if m.stock_quantity <= m_threshold:
                on_hand = getattr(m, "on_hand_qty", m.stock_quantity)
                if on_hand == 0 and m.stock_quantity > 0:
                    on_hand = m.stock_quantity
                
                alerts.append({
                    "material_id": m.id,
                    "code": m.code,
                    "name": m.name,
                    "stock_quantity": m.stock_quantity,
                    "on_hand_qty": on_hand,
                    "reserved_quantity": get_reserved_quantity(m.id),
                    "available_quantity": get_available_quantity(m.id),
                    "unit": m.unit,
                    "base_unit": getattr(m, "base_unit", None),
                    "low_threshold": m.low_threshold,
                    "unit_price": m.unit_price or 0,
                    "supplier_id": getattr(m, "supplier_id", None),
                })
    return alerts


def save_material_sql(material):
    """Save material to SQL + MongoDB (dual-write)."""
    from models.material import MaterialTable
    from config.database import upsert_mongo

    supplier_id = getattr(material, "supplier_id", None)
    on_hand_qty = getattr(material, "on_hand_qty", None)
    if on_hand_qty is None:
        on_hand_qty = material.stock_quantity
    reserved_qty = getattr(material, "reserved_qty", 0) or 0
    available_qty = getattr(material, "available_qty", None)
    if available_qty is None:
        available_qty = max(0.0, float(on_hand_qty) - float(reserved_qty))
    base_unit = getattr(material, "base_unit", None) or getattr(material, "unit", None)

    unit_type = getattr(material, "unit_type", None) or "continuous"

    with Session(engine) as session:
        row = session.get(MaterialTable, material.id)
        if row:
            row.code = material.code
            row.name = material.name
            row.type = material.type
            row.unit = material.unit
            row.unit_type = unit_type
            row.unit_price = material.unit_price
            row.stock_quantity = material.stock_quantity
            row.on_hand_qty = on_hand_qty
            row.reserved_qty = reserved_qty
            row.available_qty = available_qty
            row.base_unit = base_unit
            row.low_threshold = material.low_threshold
            row.supplier_id = supplier_id
            row.note = material.note
            session.add(row)
        else:
            session.add(MaterialTable(
                id=material.id, code=material.code, name=material.name,
                type=material.type, unit=material.unit, unit_type=unit_type,
                unit_price=material.unit_price,
                stock_quantity=material.stock_quantity, on_hand_qty=on_hand_qty,
                reserved_qty=reserved_qty, available_qty=available_qty, base_unit=base_unit,
                low_threshold=material.low_threshold,
                supplier_id=supplier_id, note=material.note,
            ))
        session.commit()

    # Mongo dual-write
    upsert_mongo("materials", {
        "id": material.id, "code": material.code, "name": material.name,
        "type": material.type, "unit": material.unit, "unit_price": material.unit_price,
        "stock_quantity": material.stock_quantity, "on_hand_qty": on_hand_qty,
        "reserved_qty": reserved_qty, "available_qty": available_qty,
        "base_unit": base_unit, "low_threshold": material.low_threshold,
        "supplier_id": supplier_id, "note": material.note,
    })


def persist_stock_movement(movement):
    """Save stock movement to SQL and Mongo."""
    from models.material import StockMovementTable
    from config.database import upsert_mongo

    with Session(engine) as session:
        row = StockMovementTable(
            material_id=movement.material_id,
            quantity_change=movement.quantity_change,
            movement_type=movement.movement_type,
            reference_type=movement.reference_type,
            reference_id=movement.reference_id,
            batch_id=movement.batch_id,
            expiry_date=movement.expiry_date,
            unit_price=getattr(movement, "unit_price", None),
            new_price=getattr(movement, "new_price", None),
            user_id=movement.user_id,
            note=movement.note,
            created_at=getattr(movement, "created_at", datetime.utcnow()),
        )
        session.add(row)
        session.commit()
        session.refresh(row)

    movement.id = row.id
    upsert_mongo("stock_movements", row.model_dump(mode="json") if hasattr(row, "model_dump") else row.__dict__)
    return movement

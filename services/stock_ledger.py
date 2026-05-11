"""Stock ledger helpers for Postgres-first inventory flow."""
import math
from collections import defaultdict
from datetime import datetime
from typing import Dict

from fastapi import HTTPException
from sqlmodel import Session, select

from config.database import engine
from models.material import StockMovement, StockMovementTable, MaterialBatchTable
from services.material import find_material, persist_stock_movement, save_material_sql
from services.product import find_product


def _material_state(material_id: int):
    material = find_material(material_id)
    on_hand = getattr(material, "on_hand_qty", None)
    reserved = getattr(material, "reserved_qty", None)

    if on_hand is None:
        on_hand = getattr(material, "stock_quantity", 0) or 0
    if reserved is None:
        reserved = 0

    # Always derive available from on_hand - reserved (available_qty is just a cache)
    available = max(0.0, float(on_hand) - float(reserved))

    return material, float(on_hand), float(reserved), float(available)


def get_material_balances(material_id: int) -> Dict[str, float]:
    """Return the current balance snapshot for one material."""
    _, on_hand, reserved, available = _material_state(material_id)
    return {
        "on_hand_qty": round(on_hand, 4),
        "reserved_qty": round(reserved, 4),
        "available_qty": round(available, 4),
    }


def _sync_material_snapshot(material_id: int, on_hand: float, reserved: float):
    material = find_material(material_id)
    material.stock_quantity = round(on_hand, 4)
    if hasattr(material, "on_hand_qty"):
        material.on_hand_qty = round(on_hand, 4)
    if hasattr(material, "reserved_qty"):
        material.reserved_qty = round(max(0.0, reserved), 4)
    if hasattr(material, "available_qty"):
        material.available_qty = round(max(0.0, on_hand - reserved), 4)
    if hasattr(material, "base_unit") and not getattr(material, "base_unit", None):
        material.base_unit = getattr(material, "unit", None)
    save_material_sql(material)
    return material


def calculate_material_requirements(order) -> Dict[int, float]:
    """Aggregate required material quantities from product BOM and wastage."""
    requirements: Dict[int, float] = defaultdict(float)
    for line in order.order_lines:
        product = find_product(line.product_id)
        for material_id, quantity in calculate_product_material_requirements(product, float(line.quantity)).items():
            requirements[material_id] += quantity
    return {material_id: round(quantity, 4) for material_id, quantity in requirements.items()}


def _consume_from_batches_fifo(material_id: int, quantity: float):
    """Deduct from oldest batches first (FIFO)."""
    with Session(engine) as session:
        batches = session.exec(
            select(MaterialBatchTable)
            .where(MaterialBatchTable.material_id == material_id)
            .where(MaterialBatchTable.quantity_remaining > 0)
            .order_by(MaterialBatchTable.received_date)
        ).all()
        remaining = round(quantity, 4)
        for batch in batches:
            if remaining <= 0:
                break
            deduct = min(batch.quantity_remaining, remaining)
            batch.quantity_remaining = round(batch.quantity_remaining - deduct, 4)
            remaining = round(remaining - deduct, 4)
            session.add(batch)
        session.commit()


def calculate_product_material_requirements(product, quantity: float) -> Dict[int, float]:
    """Calculate raw material requirements for a single product and quantity.

    For piece-type materials (mắt thú, nút...) the per-product amount is rounded up
    so you never end up ordering half an eyeball.
    """
    requirements: Dict[int, float] = defaultdict(float)
    product_wastage = getattr(product, "wastage_percent", 0) or 0
    for usage in product.materials:
        usage_wastage = getattr(usage, "wastage_percent", 0) or 0
        total_wastage = max(0.0, product_wastage + usage_wastage)
        qty_per_unit = float(usage.quantity) * (1 + total_wastage / 100)
        # Round up for piece-type materials so we never request 0.5 eyes
        material = find_material(usage.material_id)
        if getattr(material, "unit_type", "continuous") == "piece":
            qty_per_unit = math.ceil(qty_per_unit)
        requirements[usage.material_id] += qty_per_unit * float(quantity)
    return {material_id: round(total, 4) for material_id, total in requirements.items()}


def validate_material_availability(requirements: Dict[int, float]):
    """Raise if any material cannot cover the requested quantity."""
    shortages = []
    for material_id, required_qty in requirements.items():
        material = find_material(material_id)
        balances = get_material_balances(material_id)
        if balances["available_qty"] < required_qty:
            shortages.append({
                "material_id": material_id,
                "material_name": material.name,
                "required_quantity": round(required_qty, 4),
                "on_hand_quantity": balances["on_hand_qty"],
                "reserved_quantity": balances["reserved_qty"],
                "available_quantity": balances["available_qty"],
            })

    if shortages:
        raise HTTPException(
            status_code=400,
            detail={
                "message": "Không đủ nguyên liệu để xác nhận đơn",
                "shortages": shortages,
            },
        )


def _has_movement_for(reference_type: str, reference_id: int, movement_type: str) -> bool:
    with Session(engine) as session:
        stmt = select(StockMovementTable.id).where(
            StockMovementTable.reference_type == reference_type,
            StockMovementTable.reference_id == reference_id,
            StockMovementTable.movement_type == movement_type,
        )
        return session.exec(stmt).first() is not None


def _has_movement(order_id: int, movement_type: str) -> bool:
    return _has_movement_for("order", order_id, movement_type)


def _reserved_balance_for(reference_type: str, reference_id: int, material_id: int) -> float:
    with Session(engine) as session:
        movements = session.exec(
            select(StockMovementTable).where(
                StockMovementTable.reference_type == reference_type,
                StockMovementTable.reference_id == reference_id,
                StockMovementTable.material_id == material_id,
            )
        ).all()

    reserved = 0.0
    for movement in movements:
        if movement.movement_type == "reserve":
            reserved += movement.quantity_change
        elif movement.movement_type in {"release", "consume"}:
            reserved -= abs(movement.quantity_change)
    return round(max(0.0, reserved), 4)


def _current_reserved_balance(order_id: int, material_id: int) -> float:
    return _reserved_balance_for("order", order_id, material_id)


def has_reserved_materials_for_order(order_id: int) -> bool:
    return _has_movement(order_id, "reserve")


def has_consumed_materials_for_order(order_id: int) -> bool:
    return _has_movement(order_id, "consume")


def reserve_materials_for_order(order, current_user):
    """Reserve raw materials without reducing on-hand inventory."""
    if has_reserved_materials_for_order(order.id):
        return

    requirements = calculate_material_requirements(order)
    validate_material_availability(requirements)

    for material_id, required_qty in requirements.items():
        material, on_hand, reserved, _ = _material_state(material_id)
        movement = StockMovement(
            id=0,
            material_id=material_id,
            quantity_change=required_qty,
            movement_type="reserve",
            reference_type="order",
            reference_id=order.id,
            user_id=current_user.id,
            note=f"Reserve nguyên liệu cho order #{order.id}",
            created_at=datetime.utcnow(),
        )
        persist_stock_movement(movement)
        _sync_material_snapshot(material.id, on_hand, reserved + required_qty)


def release_reserved_materials_for_order(order, current_user):
    """Release unused reservations before production starts."""
    if has_consumed_materials_for_order(order.id):
        raise HTTPException(
            status_code=409,
            detail="Đơn đã tiêu hao nguyên liệu, không thể hoàn reserve tự động",
        )

    requirements = calculate_material_requirements(order)
    for material_id, _required_qty in requirements.items():
        reserved_balance = _current_reserved_balance(order.id, material_id)
        if reserved_balance <= 0:
            continue

        material, on_hand, reserved, _ = _material_state(material_id)
        release_qty = min(reserved_balance, reserved)
        movement = StockMovement(
            id=0,
            material_id=material_id,
            quantity_change=-release_qty,
            movement_type="release",
            reference_type="order",
            reference_id=order.id,
            user_id=current_user.id,
            note=f"Release reservation cho order #{order.id}",
            created_at=datetime.utcnow(),
        )
        persist_stock_movement(movement)
        _sync_material_snapshot(material.id, on_hand, reserved - release_qty)


def consume_reserved_materials_for_order(order, current_user, requirements: Dict[int, float] | None = None):
    """Convert reserved raw materials into consumed stock."""
    requirements = requirements or calculate_material_requirements(order)
    if not has_reserved_materials_for_order(order.id):
        reserve_materials_for_order(order, current_user)

    for material_id, required_qty in requirements.items():
        reserved_balance = _current_reserved_balance(order.id, material_id)
        if reserved_balance <= 0:
            continue

        consume_qty = min(required_qty, reserved_balance)
        material, on_hand, reserved, _ = _material_state(material_id)
        movement = StockMovement(
            id=0,
            material_id=material_id,
            quantity_change=-consume_qty,
            movement_type="consume",
            reference_type="order",
            reference_id=order.id,
            user_id=current_user.id,
            note=f"Consume nguyên liệu cho order #{order.id}",
            created_at=datetime.utcnow(),
        )
        persist_stock_movement(movement)
        _sync_material_snapshot(material.id, on_hand - consume_qty, reserved - consume_qty)
        _consume_from_batches_fifo(material_id, consume_qty)


def record_purchase(material_id: int, quantity: float, user_id: int, reference_id: int | None = None, note: str | None = None):
    """Record a purchase movement and refresh inventory snapshot."""
    material, on_hand, reserved, _ = _material_state(material_id)
    movement = StockMovement(
        id=0,
        material_id=material_id,
        quantity_change=quantity,
        movement_type="purchase",
        reference_type="purchase_order" if reference_id is not None else None,
        reference_id=reference_id,
        user_id=user_id,
        note=note,
        created_at=datetime.utcnow(),
    )
    persist_stock_movement(movement)
    _sync_material_snapshot(material.id, on_hand + quantity, reserved)


def apply_adjustment(material_id: int, quantity_change: float, user_id: int, note: str | None = None):
    """Apply a direct stock adjustment to on-hand inventory."""
    material, on_hand, reserved, _ = _material_state(material_id)
    movement = StockMovement(
        id=0,
        material_id=material_id,
        quantity_change=quantity_change,
        movement_type="adjustment",
        user_id=user_id,
        note=note,
        created_at=datetime.utcnow(),
    )
    persist_stock_movement(movement)
    _sync_material_snapshot(material.id, on_hand + quantity_change, reserved)


# ── Make-to-stock (MTS) job helpers ──────────────────────────────────────────

def reserve_materials_for_job(job, requirements: Dict[int, float], current_user):
    """Reserve materials for a standalone (no-order) production job."""
    if _has_movement_for("production_job", job.id, "reserve"):
        return
    validate_material_availability(requirements)
    for material_id, required_qty in requirements.items():
        material, on_hand, reserved, _ = _material_state(material_id)
        movement = StockMovement(
            id=0, material_id=material_id, quantity_change=required_qty,
            movement_type="reserve", reference_type="production_job",
            reference_id=job.id, user_id=current_user.id,
            note=f"Reserve NVL cho job #{job.id}",
            created_at=datetime.utcnow(),
        )
        persist_stock_movement(movement)
        _sync_material_snapshot(material.id, on_hand, reserved + required_qty)


def release_materials_for_job(job, requirements: Dict[int, float], current_user):
    """Release reserved materials from a cancelled MTS job."""
    if _has_movement_for("production_job", job.id, "consume"):
        raise HTTPException(
            status_code=409,
            detail="Job đã bắt đầu sản xuất, không thể hoàn nguyên liệu tự động",
        )
    for material_id in requirements:
        balance = _reserved_balance_for("production_job", job.id, material_id)
        if balance <= 0:
            continue
        material, on_hand, reserved, _ = _material_state(material_id)
        release_qty = min(balance, reserved)
        movement = StockMovement(
            id=0, material_id=material_id, quantity_change=-release_qty,
            movement_type="release", reference_type="production_job",
            reference_id=job.id, user_id=current_user.id,
            note=f"Release NVL cho job #{job.id}",
            created_at=datetime.utcnow(),
        )
        persist_stock_movement(movement)
        _sync_material_snapshot(material.id, on_hand, reserved - release_qty)


def consume_materials_for_job(job, requirements: Dict[int, float], current_user):
    """Consume reserved materials when a MTS job starts production."""
    if not _has_movement_for("production_job", job.id, "reserve"):
        reserve_materials_for_job(job, requirements, current_user)
    for material_id, required_qty in requirements.items():
        balance = _reserved_balance_for("production_job", job.id, material_id)
        if balance <= 0:
            continue
        consume_qty = min(required_qty, balance)
        material, on_hand, reserved, _ = _material_state(material_id)
        movement = StockMovement(
            id=0, material_id=material_id, quantity_change=-consume_qty,
            movement_type="consume", reference_type="production_job",
            reference_id=job.id, user_id=current_user.id,
            note=f"Consume NVL cho job #{job.id}",
            created_at=datetime.utcnow(),
        )
        persist_stock_movement(movement)
        _sync_material_snapshot(material.id, on_hand - consume_qty, reserved - consume_qty)
        _consume_from_batches_fifo(material_id, consume_qty)

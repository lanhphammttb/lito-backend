"""Production workflow routes for handmade orders."""
import json
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session

from config.database import engine
from models.user import User
from models.production import ProductionJob, ProductionJobTable, ProductionMaterial
from schemas.production import ProductionJobCreate, ProductionJobStatusUpdate, ProductionJobUpdate
from services.auth import get_current_user
from services.order import find_order
from services.product import find_product
from services.material import find_material
from services.notification import ws_manager
from utils.quantities import effective_quantity

from sqlmodel import select
router = APIRouter()

production_jobs: List[ProductionJob] = []


async def _broadcast_low_stock(material_ids):
    for mat_id in material_ids:
        try:
            mat = find_material(mat_id)
            if mat.stock_quantity <= (mat.low_threshold or 1):
                await ws_manager.broadcast({
                    "type": "low_stock_alert",
                    "material_id": mat_id,
                    "name": mat.name,
                    "stock": mat.stock_quantity,
                    "threshold": mat.low_threshold,
                    "unit": mat.unit,
                })
        except Exception:
            pass


def save_production_job_sql(job: ProductionJob):
    materials_json = json.dumps([m.model_dump(mode="json") for m in job.materials])
    with Session(engine) as session:
        if not job.id:
            if engine.dialect.name == "postgresql":
                from sqlalchemy import text
                session.exec(text("LOCK TABLE production_jobs IN SHARE ROW EXCLUSIVE MODE"))
            # Legacy rows used explicit IDs; their sequence may be behind MAX(id).
            highest = session.exec(select(ProductionJobTable.id).order_by(ProductionJobTable.id.desc())).first() or 0
            job.id = highest + 1
        row = session.get(ProductionJobTable, job.id)
        if row:
            row.quantity = job.quantity
            row.planned_minutes = job.planned_minutes
            row.status = job.status
            row.assigned_to = job.assigned_to
            row.notes = job.notes
            row.started_at = job.started_at
            row.due_at = job.due_at
            row.completed_at = job.completed_at
            row.materials_json = materials_json
            row.updated_at = job.updated_at
        else:
            row = ProductionJobTable(
                id=job.id or None,
                order_id=job.order_id,
                product_id=job.product_id,
                product_name=job.product_name,
                quantity=job.quantity,
                status=job.status,
                assigned_to=job.assigned_to,
                notes=job.notes,
                planned_minutes=job.planned_minutes,
                started_at=job.started_at,
                due_at=job.due_at,
                completed_at=job.completed_at,
                materials_json=materials_json,
                created_by=job.created_by,
                created_at=job.created_at,
                updated_at=job.updated_at,
            )
        session.add(row)
        session.commit()
        session.refresh(row)
        job.id = row.id



@router.get("")
async def list_production_jobs(
    status: Optional[str] = None,
    order_id: Optional[int] = None,
    user: User = Depends(get_current_user),
):
    with Session(engine) as session:
        statement = select(ProductionJobTable)
        if status:
            statement = statement.where(ProductionJobTable.status == status)
        if order_id:
            statement = statement.where(ProductionJobTable.order_id == order_id)
            
        statement = statement.order_by(ProductionJobTable.created_at.desc())
        results = session.exec(statement).all()
        
        output = []
        for r in results:
            d = r.model_dump()
            try:
                d['materials'] = json.loads(d.get('materials_json', '[]') or '[]')
            except:
                d['materials'] = []
            output.append(d)
        return output


@router.post("")
async def create_production_job(
    payload: ProductionJobCreate,
    user: User = Depends(get_current_user),
):
    """
    Tạo production job ở trạng thái 'planned'. Chưa đụng kho.

    MTO (có order_id): đơn phải confirmed/processing.
    MTS (không có order_id): làm trước để dự trữ.

    Kho chỉ bị trừ khi job chuyển sang in_progress.
    """
    product = find_product(payload.product_id)
    is_mts = payload.order_id is None

    if not is_mts:
        order = find_order(payload.order_id)
        if order.status not in {"confirmed", "processing", "producing"}:
            raise HTTPException(
                status_code=400,
                detail=f"Đơn #{payload.order_id} cần ở trạng thái confirmed hoặc processing (hiện tại: {order.status})"
            )
        if not any(line.product_id == payload.product_id for line in order.order_lines):
            raise HTTPException(400, "Sản phẩm không thuộc đơn hàng đã chọn")

    job = ProductionJob(
        id=0,
        order_id=payload.order_id,
        product_id=payload.product_id,
        product_name=product.name,
        quantity=payload.quantity,
        status="planned",
        assigned_to=payload.assigned_to,
        notes=payload.notes,
        planned_minutes=(product.time_minutes or 0) * payload.quantity,
        due_at=payload.due_at,
        materials=_plan_materials(product, payload.quantity, payload.materials),
        created_by=user.id,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    save_production_job_sql(job)
    if not is_mts:
        # Migrate only remaining legacy order reservations to job-level planning.
        from services.stock_ledger import release_legacy_order_reservations
        release_legacy_order_reservations(order.id, user.id)
    return job


def _load_job(row):
    return ProductionJob(**{**row.model_dump(), "materials": json.loads(row.materials_json or "[]")})


def _plan_materials(product, quantity, selected):
    usages = selected if selected is not None else product.materials
    materials = {}
    for source in usages:
        mid = source.material_id
        mat = find_material(mid)
        product_wastage = getattr(source, "product_wastage_percent", None)
        if product_wastage is None:
            product_wastage = product.wastage_percent
        per_product = effective_quantity(source.quantity, product_wastage, source.wastage_percent, mat.unit_type)
        needed = round(per_product * quantity, 4)
        if mid in materials:
            materials[mid].planned_quantity += needed
            materials[mid].quantity_per_product = None
            continue
        materials[mid] = ProductionMaterial(
            material_id=mid, planned_quantity=needed,
            quantity_per_product=source.quantity,
            wastage_percent=source.wastage_percent,
            product_wastage_percent=product_wastage,
            material_name=mat.name, unit=mat.unit, unit_type=mat.unit_type,
            unit_price=mat.unit_price,
        )
    return list(materials.values())


@router.put("/{job_id}")
async def update_production_job(job_id: int, payload: ProductionJobUpdate, user: User = Depends(get_current_user)):
    with Session(engine) as session:
        row = session.exec(select(ProductionJobTable).where(ProductionJobTable.id == job_id).with_for_update()).first()
        if not row:
            raise HTTPException(404, "Job không tồn tại")
        if row.status in {"completed", "cancelled"}:
            raise HTTPException(409, "Job đã kết thúc, không thể sửa")
        job = _load_job(row)
        fields = payload.model_fields_set
        if fields & {"quantity", "materials"}:
            if job.status != "planned":
                raise HTTPException(409, "Chỉ sửa số lượng/nguyên liệu khi job còn ở kế hoạch")
            new_quantity = payload.quantity or job.quantity
            if payload.materials is not None:
                job.materials = _plan_materials(find_product(job.product_id), new_quantity, payload.materials)
            else:
                for material in job.materials:
                    material.planned_quantity = round(material.planned_quantity * new_quantity / job.quantity, 4)
            job.planned_minutes = round(job.planned_minutes * new_quantity / job.quantity)
            job.quantity = new_quantity
        for key in ("assigned_to", "due_at", "notes"):
            if key in fields:
                setattr(job, key, getattr(payload, key))
        job.updated_at = datetime.utcnow()
        for key in ("quantity", "planned_minutes", "assigned_to", "due_at", "notes", "updated_at"):
            setattr(row, key, getattr(job, key))
        row.materials_json = json.dumps([m.model_dump() for m in job.materials])
        session.add(row)
        session.commit()
    return job


@router.patch("/{job_id}/status")
async def update_production_job_status(job_id: int, payload: ProductionJobStatusUpdate, user: User = Depends(get_current_user)):
    # Lock the job and material rows; stock, movements and status commit together.
    from models.material import MaterialTable, StockMovementTable, MaterialBatchTable
    from models.product import ProductTable
    allowed = {
        "planned": {"reserved", "in_progress", "completed", "cancelled"},
        "reserved": {"planned", "in_progress", "completed", "cancelled"},
        "in_progress": {"paused", "completed"},
        "paused": {"in_progress", "completed"},
        "completed": set(), "cancelled": set(),
    }
    with Session(engine) as session:
        row = session.exec(select(ProductionJobTable).where(ProductionJobTable.id == job_id).with_for_update()).first()
        if not row:
            raise HTTPException(404, "Job không tồn tại")
        job = _load_job(row)
        target = payload.status
        if target == job.status:
            return job
        if target not in allowed.get(job.status, set()):
            raise HTTPException(409, "Không thể chuyển trạng thái này; nguyên liệu đã dùng cần điều chỉnh kho riêng")
        if job.order_id:
            from services.stock_ledger import release_legacy_order_reservations
            release_legacy_order_reservations(job.order_id, user.id)
        # Older versions allowed planned -> paused without consuming anything.
        started = bool(job.started_at or any(m.actual_quantity > 0 for m in job.materials))
        if not started:
            shortages = []
            for usage in sorted(job.materials, key=lambda m: m.material_id):
                mat = session.exec(select(MaterialTable).where(MaterialTable.id == usage.material_id).with_for_update()).first()
                if not mat:
                    raise HTTPException(404, "Nguyên liệu của job không còn tồn tại")
                on_hand = mat.on_hand_qty if mat.on_hand_qty is not None else mat.stock_quantity
                if on_hand == 0 and mat.stock_quantity > 0:
                    on_hand = mat.stock_quantity
                own = usage.reserved_quantity
                needed = usage.planned_quantity
                available = on_hand - mat.reserved_qty + own
                if target in {"reserved", "in_progress", "completed"} and available + 1e-8 < needed:
                    shortages.append({"material_id": mat.id, "material_name": mat.name, "required_quantity": needed,
                        "available_quantity": max(0, available), "unit_price": mat.unit_price})
                    continue
                def movement(kind, delta):
                    session.add(StockMovementTable(material_id=mat.id, quantity_change=delta, movement_type=kind,
                        reference_type="production_job", reference_id=job.id, user_id=user.id, note=f"Job #{job.id}"))
                if target == "reserved":
                    mat.reserved_qty += needed - own
                    usage.reserved_quantity = needed
                    movement("reserve", needed - own)
                elif target in {"planned", "cancelled"}:
                    if own:
                        mat.reserved_qty -= own
                        usage.reserved_quantity = 0
                        movement("release", -own)
                elif target in {"in_progress", "completed"}:
                    mat.reserved_qty -= own
                    on_hand -= needed
                    usage.reserved_quantity = 0
                    usage.actual_quantity = needed
                    usage.unit_price = mat.unit_price
                    movement("consume", -needed)
                    remaining = needed
                    for batch in session.exec(select(MaterialBatchTable).where(MaterialBatchTable.material_id == mat.id,
                            MaterialBatchTable.quantity_remaining > 0).order_by(MaterialBatchTable.received_date).with_for_update()).all():
                        delta = min(remaining, batch.quantity_remaining)
                        batch.quantity_remaining -= delta
                        remaining -= delta
                        session.add(batch)
                mat.stock_quantity = mat.on_hand_qty = round(on_hand, 4)
                mat.available_qty = round(max(0, on_hand - mat.reserved_qty), 4)
                session.add(mat)
            if shortages:
                raise HTTPException(400, {"message": "Không đủ nguyên liệu đã chọn cho job", "shortages": shortages})
        if target in {"in_progress", "completed"}:
            job.started_at = job.started_at or datetime.utcnow()
        if target == "completed":
            product = session.exec(select(ProductTable).where(ProductTable.id == job.product_id).with_for_update()).first()
            if not product:
                raise HTTPException(404, "Sản phẩm không còn tồn tại")
            product.finished_qty += job.quantity
            session.add(product)
            job.completed_at = datetime.utcnow()
        job.status = target
        if payload.notes is not None:
            job.notes = payload.notes
        job.updated_at = datetime.utcnow()
        for key in ("status", "notes", "started_at", "completed_at", "updated_at"):
            setattr(row, key, getattr(job, key))
        row.materials_json = json.dumps([m.model_dump() for m in job.materials])
        session.add(row)
        session.commit()
    from services.product import clear_product_cost_cache
    clear_product_cost_cache()
    await _broadcast_low_stock([m.material_id for m in job.materials])
    return job

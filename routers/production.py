"""Production workflow routes for handmade orders."""
import json
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session

from config.database import engine
from models.user import User
from models.production import ProductionJob, ProductionJobTable, ProductionMaterial
from schemas.production import ProductionJobCreate, ProductionJobStatusUpdate
from services.auth import get_current_user
from services.order import find_order, reserve_stock_for_order, release_reserved_stock_for_order
from services.stock_ledger import (
    calculate_product_material_requirements,
    has_reserved_materials_for_order,
    consume_reserved_materials_for_order,
    release_materials_for_job,
    consume_materials_for_job,
    _material_state,
    _reserved_balance_for,
)
from services.product import find_product
from services.material import find_material
from services.notification import ws_manager
from routers.products import save_product_sql

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
        row = session.get(ProductionJobTable, job.id)
        if row:
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
                id=job.id,
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

    requirements = calculate_product_material_requirements(product, payload.quantity)
    with Session(engine) as session:
        new_id = session.exec(select(ProductionJobTable.id).order_by(ProductionJobTable.id.desc())).first() or 0
        new_id += 1

    job = ProductionJob(
        id=new_id,
        order_id=payload.order_id,
        product_id=payload.product_id,
        product_name=product.name,
        quantity=payload.quantity,
        status="planned",
        assigned_to=payload.assigned_to,
        notes=payload.notes,
        planned_minutes=(product.time_minutes or 0) * payload.quantity,
        due_at=payload.due_at,
        materials=[
            ProductionMaterial(material_id=mid, planned_quantity=qty, reserved_quantity=0)
            for mid, qty in requirements.items()
        ],
        created_by=user.id,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    save_production_job_sql(job)
    return job


@router.patch("/{job_id}/status")
async def update_production_job_status(
    job_id: int,
    payload: ProductionJobStatusUpdate,
    user: User = Depends(get_current_user),
):
    """
    Chỉ in_progress mới trừ kho (consume).
    completed chỉ đánh dấu hoàn thành — NVL đã trừ từ lúc in_progress.
    cancelled trước in_progress → release reserve.
    cancelled sau in_progress → 409, phải xử lý thủ công.
    """
    with Session(engine) as session:
        row = session.get(ProductionJobTable, job_id)
        if not row:
            raise HTTPException(status_code=404, detail="Production job không tồn tại")
        
        job = ProductionJob(**row.model_dump())
        try:
            materials_dicts = json.loads(row.materials_json or '[]')
            job.materials = [ProductionMaterial(**m) for m in materials_dicts]
        except:
            job.materials = []

    old_status = job.status
    new_status = payload.status
    if old_status == new_status:
        return job

    product = find_product(job.product_id)
    requirements = calculate_product_material_requirements(product, job.quantity)
    is_mts = job.order_id is None

    # ── in_progress: đây là điểm DUY NHẤT trừ kho ──────────────────────────
    if new_status == "in_progress" and old_status != "in_progress":
        if is_mts:
            # MTS: reserve + consume ngay (validate ở đây)
            consume_materials_for_job(job, requirements, user)
        else:
            order = find_order(job.order_id)
            # MTO: reserve toàn đơn nếu chưa, sau đó consume phần của job này
            if not has_reserved_materials_for_order(order.id):
                reserve_stock_for_order(order, user)
            # validate: phần còn lại trong reservation đủ cho job này không?
            shortages = []
            for mat_id, needed in requirements.items():
                remaining = _reserved_balance_for("order", order.id, mat_id)
                if remaining < needed:
                    _, on_hand, reserved, _ = _material_state(mat_id)
                    shortages.append({
                        "material_id": mat_id,
                        "needed": needed,
                        "reserved_remaining": remaining,
                    })
            if shortages:
                raise HTTPException(status_code=400, detail={
                    "message": "Không đủ NVL đã reserve cho job này (các job khác trong đơn đã dùng hết?)",
                    "shortages": shortages,
                })
            consume_reserved_materials_for_order(order, user, requirements)
        job.started_at = job.started_at or datetime.utcnow()
        await _broadcast_low_stock(requirements.keys())

    # ── completed: consume nếu chưa, rồi đánh dấu xong ────────────────────
    elif new_status == "completed":
        if old_status not in {"in_progress", "paused"}:
            # chưa qua in_progress → consume ngay bây giờ
            if is_mts:
                consume_materials_for_job(job, requirements, user)
            else:
                order = find_order(job.order_id)
                if not has_reserved_materials_for_order(order.id):
                    reserve_stock_for_order(order, user)
                shortages = []
                for mat_id, needed in requirements.items():
                    remaining = _reserved_balance_for("order", order.id, mat_id)
                    if remaining < needed:
                        shortages.append({"material_id": mat_id, "needed": needed, "reserved_remaining": remaining})
                if shortages:
                    raise HTTPException(status_code=400, detail={"message": "Không đủ NVL", "shortages": shortages})
                consume_reserved_materials_for_order(order, user, requirements)
            await _broadcast_low_stock(requirements.keys())
        job.completed_at = datetime.utcnow()
        # Thêm vào tồn kho thành phẩm (MTS: dự trữ bán sau; MTO: đã có đơn nhưng vẫn cộng để theo dõi)
        product.finished_qty = getattr(product, "finished_qty", 0) + job.quantity
        save_product_sql(product)

    # ── cancelled: release nếu chưa in_progress ─────────────────────────────
    elif new_status == "cancelled":
        if old_status == "in_progress":
            raise HTTPException(
                status_code=409,
                detail="Job đã bắt đầu sản xuất và NVL đã bị trừ. Cần điều chỉnh kho thủ công."
            )
        if is_mts:
            release_materials_for_job(job, requirements, user)
        else:
            order = find_order(job.order_id)
            release_reserved_stock_for_order(order, user)

    # ── paused: chỉ đổi status ──────────────────────────────────────────────
    # (đã in_progress, NVL đã consume, tạm dừng không ảnh hưởng kho)

    job.status = new_status
    if payload.notes:
        job.notes = payload.notes
    job.updated_at = datetime.utcnow()
    save_production_job_sql(job)
    return job

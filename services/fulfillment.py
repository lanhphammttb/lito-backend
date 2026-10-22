"""Outstanding production after finished stock and existing order jobs."""
from collections import defaultdict
from sqlmodel import select
from models.order import OrderTable
from models.product import ProductTable
from models.production import ProductionJobTable
from services.order import find_order
from fastapi import HTTPException


def production_requirements(session, order_id, exclude_job_id=None):
    order_row = session.exec(select(OrderTable).where(OrderTable.id == order_id).with_for_update()).first()
    if not order_row:
        raise HTTPException(404, 'Đơn hàng không tồn tại')
    demand = defaultdict(int)
    for line in find_order(order_id).order_lines:
        demand[line.product_id] += line.quantity
    planned, completed = defaultdict(int), defaultdict(int)
    jobs = session.exec(select(ProductionJobTable).where(ProductionJobTable.order_id == order_id)).all()
    for job in jobs:
        if job.id == exclude_job_id or job.status == 'cancelled':
            continue
        (completed if job.status == 'completed' else planned)[job.product_id] += job.quantity
    result = []
    for pid, quantity in demand.items():
        product = session.get(ProductTable, pid)
        finished = product.finished_qty if product else 0
        # Completed jobs have already entered finished stock, so do not count twice.
        covered = max(finished or 0, completed[pid])
        result.append({'product_id': pid, 'required_quantity': quantity,
                       'finished_quantity': finished or 0, 'planned_quantity': planned[pid],
                       'completed_quantity': completed[pid],
                       'remaining_quantity': max(0, quantity - covered - planned[pid])})
    return result


def validate_job_quantity(session, order_id, product_id, quantity, exclude_job_id=None):
    requirement = next((row for row in production_requirements(session, order_id, exclude_job_id)
                        if row['product_id'] == product_id), None)
    if requirement is None:
        raise HTTPException(400, 'Sản phẩm không thuộc đơn hàng')
    if quantity > requirement['remaining_quantity']:
        raise HTTPException(409, f"Chỉ còn cần lập lệnh cho {requirement['remaining_quantity']} sản phẩm; kiểm tra tồn thành phẩm và lệnh đã tạo")

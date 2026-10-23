"""Correct recorded consumption without rewriting production or deleting history."""
from collections import defaultdict
from datetime import datetime
import hashlib
import json
import uuid

from fastapi import HTTPException
from sqlmodel import select
from models.activity import AuditLogTable
from models.material import MaterialTable, MaterialBatchTable, StockMovementTable
from models.production import ProductionJob
from utils.datetime import utcnow


def consumption_revision(row):
    return hashlib.sha256((row.materials_json or '[]').encode()).hexdigest()


def consumption_response(row):
    return {**row.model_dump(), 'materials': json.loads(row.materials_json or '[]'),
            'consumption_revision': consumption_revision(row)}


def correct_consumption(session, row, payload, user):
    """Caller locks the job; stock, batches, job and audit use this same transaction."""
    job = ProductionJob(**{**row.model_dump(), 'materials': json.loads(row.materials_json or '[]')})
    if job.status not in {'in_progress', 'paused', 'completed'} or not (
            job.started_at or any(usage.actual_quantity > 0 for usage in job.materials)):
        raise HTTPException(409, 'Chỉ điều chỉnh tiêu hao của lệnh đã xuất nguyên liệu')
    changes = []
    deltas = defaultdict(float)
    for edit in payload.materials:
        if edit.material_index >= len(job.materials):
            raise HTTPException(422, 'Dòng nguyên liệu không tồn tại')
        usage = job.materials[edit.material_index]
        if usage.material_id != edit.material_id:
            raise HTTPException(409, 'Dòng nguyên liệu đã thay đổi; tải lại lệnh trước khi điều chỉnh')
        if usage.unit_type == 'piece' and not edit.actual_quantity.is_integer():
            raise HTTPException(422, 'Nguyên liệu dạng cái phải có lượng tiêu hao là số nguyên')
        delta = round(edit.actual_quantity - usage.actual_quantity, 4)
        if delta:
            changes.append({'material_index': edit.material_index, 'material_id': usage.material_id,
                'material_name': usage.material_name, 'unit': usage.unit,
                'previous_quantity': usage.actual_quantity, 'actual_quantity': edit.actual_quantity,
                'stock_change': -delta, 'unit_price': usage.unit_price})
            deltas[usage.material_id] += delta
    # Repeating an already applied target never changes stock or duplicates the audit.
    if not changes:
        return consumption_response(row)
    if payload.revision != consumption_revision(row):
        raise HTTPException(409, 'Tiêu hao của lệnh vừa thay đổi; tải lại lệnh và kiểm tra trước khi lưu')
    now = utcnow()
    adjustment_id = uuid.uuid4().hex
    for mid in sorted(deltas):
        delta = round(deltas[mid], 4)
        mat = session.exec(select(MaterialTable).where(MaterialTable.id == mid).with_for_update()).first()
        if not mat:
            raise HTTPException(409, 'Nguyên liệu của lệnh không còn tồn tại')
        on_hand = mat.on_hand_qty if mat.on_hand_qty is not None else mat.stock_quantity
        if on_hand == 0 and mat.stock_quantity > 0:
            on_hand = mat.stock_quantity
        if delta > 0 and on_hand - (mat.reserved_qty or 0) + 1e-8 < delta:
            raise HTTPException(409, f'Không đủ nguyên liệu khả dụng để xuất thêm: {mat.name}')
        mat.stock_quantity = mat.on_hand_qty = round(on_hand - delta, 4)
        mat.available_qty = round(max(0, mat.on_hand_qty - (mat.reserved_qty or 0)), 4)
        mat.updated_by = user.id
        session.add(mat)
        if delta > 0:
            remaining = delta
            batches = session.exec(select(MaterialBatchTable).where(MaterialBatchTable.material_id == mid,
                MaterialBatchTable.quantity_remaining > 0).order_by(MaterialBatchTable.received_date,
                MaterialBatchTable.id).with_for_update()).all()
            for batch in batches:
                amount = min(remaining, batch.quantity_remaining)
                batch.quantity_remaining = round(batch.quantity_remaining - amount, 4)
                remaining = round(remaining - amount, 4)
                session.add(batch)
                if remaining <= 0:
                    break
        elif delta < 0:
            # Legacy consumption has no original lot allocation. Preserve it and record a
            # separate return lot, rather than guessing which purchase lot to replenish.
            returns = [change for change in changes if change['material_id'] == mid and change['stock_change'] > 0]
            known_prices = [change['unit_price'] for change in returns if change['unit_price'] is not None]
            cost = sum(change['stock_change'] * (change['unit_price'] or 0) for change in returns) / sum(
                change['stock_change'] for change in returns) if len(known_prices) == len(returns) else mat.unit_price
            session.add(MaterialBatchTable(material_id=mid, batch_code=f'CORR-{job.id}-{adjustment_id[:12]}',
                quantity_received=-delta, quantity_remaining=-delta, unit_cost=cost,
                received_date=now.date(), note=f'Hoàn do sửa tiêu hao lệnh #{job.id}. '
                    + ('Giá tham khảo hiện tại. ' if len(known_prices) != len(returns) else '') + payload.reason))
    for change in changes:
        usage = job.materials[change['material_index']]
        usage.actual_quantity = change['actual_quantity']
        session.add(StockMovementTable(material_id=usage.material_id, quantity_change=change['stock_change'],
            movement_type='adjustment', reference_type='production_job', reference_id=job.id,
            unit_price=usage.unit_price, user_id=user.id, created_at=now,
            note=f"Điều chỉnh tiêu hao dòng {change['material_index'] + 1}: {change['previous_quantity']} → "
                 f"{change['actual_quantity']} {usage.unit or ''}. Lý do: {payload.reason}"))
    before = {'materials': json.loads(row.materials_json or '[]')}
    row.materials_json = json.dumps([usage.model_dump() for usage in job.materials])
    row.updated_at = datetime.utcnow()
    session.add(row)
    session.add(AuditLogTable(user_id=user.id, user_name=user.name, action='ADJUST_CONSUMPTION',
        table_name='production_jobs', record_id=job.id, before_data=json.dumps(before),
        after_data=json.dumps({'reason': payload.reason, 'changes': changes, 'adjustment_id': adjustment_id}), timestamp=now))
    return consumption_response(row)

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
            job.started_at or job.completed_at or any(usage.actual_quantity > 0 for usage in job.materials)):
        raise HTTPException(409, 'Chỉ điều chỉnh tiêu hao của lệnh đã xuất nguyên liệu')
    edits = []
    for edit in payload.materials:
        if edit.material_index >= len(job.materials):
            raise HTTPException(422, 'Dòng nguyên liệu không tồn tại')
        usage = job.materials[edit.material_index]
        target_id = edit.replacement_material_id or edit.material_id
        if usage.material_id == target_id and abs(usage.actual_quantity - edit.actual_quantity) < 1e-8:
            continue
        if usage.material_id != edit.material_id:
            raise HTTPException(409, 'Dòng nguyên liệu đã thay đổi; tải lại lệnh trước khi điều chỉnh')
        edits.append((edit, usage, target_id))
    # Repeating an already applied target never changes stock or duplicates the audit.
    if not edits:
        return consumption_response(row)
    if payload.revision != consumption_revision(row):
        raise HTTPException(409, 'Tiêu hao của lệnh vừa thay đổi; tải lại lệnh và kiểm tra trước khi lưu')
    now = utcnow()
    adjustment_id = uuid.uuid4().hex
    # Lock every old and replacement material in the same order, including swaps.
    locked = {}
    for mid in sorted({mid for _, usage, target in edits for mid in (usage.material_id, target)}):
        mat = session.exec(select(MaterialTable).where(MaterialTable.id == mid).with_for_update()).first()
        if not mat:
            raise HTTPException(409, 'Nguyên liệu của lệnh không còn tồn tại')
        locked[mid] = mat
    changes, replacements, deltas = [], [], defaultdict(float)

    def movement_change(index, usage, before, after):
        delta = round(after - before, 4)
        if delta:
            changes.append({'material_index': index, 'material_id': usage.material_id,
                'material_name': usage.material_name, 'unit': usage.unit,
                'previous_quantity': before, 'actual_quantity': after,
                'stock_change': -delta, 'unit_price': usage.unit_price,
                'unit_price_basis': usage.unit_price_basis})
            deltas[usage.material_id] += delta

    for edit, usage, target_id in edits:
        replacing = target_id != usage.material_id
        unit_type = locked[target_id].unit_type if replacing else (usage.unit_type or locked[target_id].unit_type)
        if unit_type == 'piece' and not edit.actual_quantity.is_integer():
            raise HTTPException(422, 'Nguyên liệu dạng cái phải có lượng tiêu hao là số nguyên')
        if replacing:
            replacements.append({'material_index': edit.material_index,
                'previous_material_id': usage.material_id, 'previous_material_name': usage.material_name,
                'material_id': target_id, 'material_name': locked[target_id].name})
            movement_change(edit.material_index, usage, usage.actual_quantity, 0)
            if usage.planned_material_id is None:
                usage.planned_material_id, usage.planned_material_name = usage.material_id, usage.material_name
                usage.planned_unit, usage.planned_unit_type = usage.unit, usage.unit_type
            target = locked[target_id]
            usage.material_id, usage.material_name = target.id, target.name
            usage.unit, usage.unit_type = target.unit, target.unit_type
            usage.unit_price = target.unit_price
            usage.unit_price_basis = 'correction_current_price'
            movement_change(edit.material_index, usage, 0, edit.actual_quantity)
        else:
            movement_change(edit.material_index, usage, usage.actual_quantity, edit.actual_quantity)
        usage.actual_quantity = edit.actual_quantity

    for mid in sorted(deltas):
        delta = round(deltas[mid], 4)
        mat = locked[mid]
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
        session.add(StockMovementTable(material_id=change['material_id'], quantity_change=change['stock_change'],
            movement_type='adjustment', reference_type='production_job', reference_id=job.id,
            unit_price=change['unit_price'], user_id=user.id, created_at=now,
            note=f"Điều chỉnh tiêu hao dòng {change['material_index'] + 1}: {change['previous_quantity']} → "
                 f"{change['actual_quantity']} {change['unit'] or ''}. Lý do: {payload.reason}"))
    before = {'materials': json.loads(row.materials_json or '[]')}
    row.materials_json = json.dumps([usage.model_dump() for usage in job.materials])
    row.updated_at = datetime.utcnow()
    session.add(row)
    session.add(AuditLogTable(user_id=user.id, user_name=user.name, action='ADJUST_CONSUMPTION',
        table_name='production_jobs', record_id=job.id, before_data=json.dumps(before),
        after_data=json.dumps({'reason': payload.reason, 'changes': changes, 'replacements': replacements,
            'materials': [usage.model_dump() for usage in job.materials], 'adjustment_id': adjustment_id}), timestamp=now))
    return consumption_response(row)

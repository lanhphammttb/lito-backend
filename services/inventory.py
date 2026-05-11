"""Inventory services - Suppliers and Purchase Orders."""
from typing import List
from datetime import datetime
from fastapi import HTTPException
from sqlmodel import Session

from config.database import engine
from models.inventory import PurchaseOrderLine
from models.material import MaterialBatchTable

# In-memory data stores
suppliers = []
purchase_orders = []
materials = []
stock_movements = []


def set_data_stores(s, p, m, sm):
    """Set data stores."""
    global suppliers, purchase_orders, materials, stock_movements
    suppliers = s
    purchase_orders = p
    materials = m
    stock_movements = sm


def find_supplier(supplier_id: int):
    """Find supplier by ID from Database."""
    from sqlmodel import Session
    from config.database import engine
    from models.inventory import SupplierTable, Supplier
    with Session(engine) as session:
        row = session.get(SupplierTable, supplier_id)
        if not row:
            raise HTTPException(status_code=404, detail=f"Supplier {supplier_id} không tồn tại")
        return Supplier(
            id=row.id, name=row.name, contact_name=row.contact_name,
            phone=row.phone, email=row.email, address=row.address,
            note=row.note, rating=row.rating,
            lead_time_days=getattr(row, "lead_time_days", None),
            created_at=row.created_at,
        )

def find_purchase_order(po_id: int):
    """Find purchase order by ID from Database."""
    from sqlmodel import Session
    from config.database import engine
    import json
    from models.inventory import PurchaseOrderTable, PurchaseOrder, PurchaseOrderLine
    with Session(engine) as session:
        row = session.get(PurchaseOrderTable, po_id)
        if not row:
            raise HTTPException(status_code=404, detail="Purchase order không tồn tại")
        lines = []
        if row.lines_json:
            try:
                lines = [PurchaseOrderLine(**l) for l in json.loads(row.lines_json)]
            except:
                pass
        return PurchaseOrder(
            id=row.id, supplier_id=row.supplier_id, status=row.status,
            expected_date=row.expected_date, note=row.note, lines=lines,
            total_amount=row.total_amount, paid_amount=row.paid_amount,
            payment_status=row.payment_status,
            created_by=row.created_by, received_at=row.received_at, created_at=row.created_at,
        )


def compute_po_total(lines: List[PurchaseOrderLine]) -> float:
    """Compute total amount of purchase order."""
    return sum(line.unit_price * line.quantity for line in lines)


def receive_purchase_order(po, current_user):
    """Process receiving a purchase order — also creates a MaterialBatch per line."""
    from services.stock_ledger import record_purchase

    if po.received_at:
        return

    po.status = "received"
    po.received_at = datetime.utcnow()
    today = datetime.utcnow().date()

    for line in po.lines:
        batch_code = (getattr(line, "batch_id", None) or
                      f"PO{po.id}-M{line.material_id}-{today.strftime('%Y%m%d')}")
        with Session(engine) as session:
            batch = MaterialBatchTable(
                material_id=line.material_id,
                batch_code=batch_code,
                purchase_order_id=po.id,
                supplier_id=po.supplier_id,
                quantity_received=line.quantity,
                quantity_remaining=line.quantity,
                unit_cost=line.unit_price or 0,
                received_date=today,
            )
            session.add(batch)
            session.commit()

        record_purchase(
            material_id=line.material_id,
            quantity=line.quantity,
            user_id=current_user.id,
            reference_id=po.id,
            note=f"Nhập kho từ PO #{po.id} | Lô: {batch_code}",
        )

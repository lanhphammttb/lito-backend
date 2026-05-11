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
    """Find supplier by ID."""
    for supplier in suppliers:
        if supplier.id == supplier_id:
            return supplier
    raise HTTPException(status_code=404, detail=f"Supplier {supplier_id} không tồn tại")


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

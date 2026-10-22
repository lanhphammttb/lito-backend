"""Permanent deletion with SQL reference checks in the caller's transaction."""
import json
import sys

from fastapi import HTTPException
from sqlalchemy import delete
from sqlmodel import Session, select

from models import (
    ContentPlanTable, CustomerTable, DemandSignalTable, IssueTable,
    LifecycleEventTable, OrderReturnTable, OrderTable, PaymentTable,
    PriceChangeTable, ProductBundleTable, ProductImageTable, ProductReviewTable,
    ProductTable, ProductVariantTable, ProductionJobTable, PurchaseOrderTable,
    StockMovementTable, SupplierTable,
)
from models.material import MaterialBatchTable, MaterialPriceEntryTable, MaterialTable
from models.order import OrderLineTable
from models.promo import PromoCodeTable


def _block(reason):
    raise HTTPException(409, reason)


def locked_row(session: Session, model, row_id: int, label: str):
    row = session.exec(select(model).where(model.id == row_id).with_for_update()).first()
    if row is None:
        raise HTTPException(404, f"{label} không tồn tại")
    return row


def _exists(session, model, *conditions):
    return session.exec(select(model.id).where(*conditions).limit(1)).first() is not None


def _json_list(value):
    try:
        result = json.loads(value or "[]")
    except (ValueError, TypeError):
        _block("Dữ liệu liên kết không hợp lệ; cần sửa trước khi xóa.")
    if not isinstance(result, list):
        _block("Dữ liệu liên kết không hợp lệ; cần sửa trước khi xóa.")
    return result


def _matches(value, row_id):
    return str(value) == str(row_id)


def _json_reference(session, model, column, row_id, *, field=None, alternatives=False):
    for value in session.exec(select(getattr(model, column))).all():
        for item in _json_list(value):
            if field:
                if not isinstance(item, dict):
                    _block("Dữ liệu liên kết không hợp lệ; cần sửa trước khi xóa.")
                if _matches(item.get(field), row_id):
                    return True
                if alternatives and any(_matches(v, row_id) for v in (item.get("alternative_material_ids") or [])):
                    return True
            elif _matches(item, row_id):
                return True
    return False


def _remove(session, model, *conditions):
    session.exec(delete(model).where(*conditions))


def forget_legacy(collection, row_id, field="id"):
    """Refresh existing list objects only after the SQL transaction commits."""
    for name, module in list(sys.modules.items()):
        if not name.startswith(("routers.", "services.")):
            continue
        items = getattr(module, collection, None)
        if isinstance(items, list):
            items[:] = [item for item in items if not _matches(
                item.get(field) if isinstance(item, dict) else getattr(item, field, None), row_id,
            )]


def delete_product(session, product_id):
    row = locked_row(session, ProductTable, product_id, "Sản phẩm")
    if row.finished_qty or _exists(session, ProductVariantTable,
                                   ProductVariantTable.product_id == product_id,
                                   ProductVariantTable.stock_quantity != 0):
        _block("Sản phẩm còn tồn thành phẩm hoặc tồn biến thể. Điều chỉnh tồn trước khi xóa.")
    if (_exists(session, OrderLineTable, OrderLineTable.product_id == product_id)
            or _json_reference(session, OrderTable, "order_lines_json", product_id, field="product_id")):
        _block("Sản phẩm đã có trong đơn hàng. Không thể xóa vì cần giữ lịch sử và thống kê.")
    if _exists(session, ProductionJobTable, ProductionJobTable.product_id == product_id):
        _block("Sản phẩm đang được job sản xuất sử dụng. Xóa job nháp chưa làm trước; giữ lịch sử job đã làm.")
    if _exists(session, ProductBundleTable, ProductBundleTable.child_product_id == product_id,
               ProductBundleTable.parent_product_id != product_id):
        _block("Sản phẩm đang nằm trong bộ sản phẩm khác. Bỏ liên kết bộ trước khi xóa.")
    if _exists(session, ContentPlanTable, ContentPlanTable.related_product_id == product_id):
        _block("Sản phẩm còn liên kết với kế hoạch nội dung. Xóa hoặc đổi liên kết nội dung trước.")
    if _exists(session, IssueTable, IssueTable.product_id == product_id):
        _block("Sản phẩm còn vấn đề được ghi nhận. Xóa hoặc xử lý liên kết vấn đề trước.")
    if _json_reference(session, PromoCodeTable, "applicable_product_ids_json", product_id):
        _block("Sản phẩm đang được mã khuyến mãi sử dụng. Bỏ liên kết khuyến mãi trước.")
    for model in (ProductVariantTable, ProductImageTable, ProductReviewTable,
                  PriceChangeTable, LifecycleEventTable, DemandSignalTable):
        _remove(session, model, model.product_id == product_id)
    _remove(session, ProductBundleTable, ProductBundleTable.parent_product_id == product_id)
    session.delete(row)


def delete_material(session, material_id):
    row = locked_row(session, MaterialTable, material_id, "Nguyên liệu")
    if any(abs(value or 0) > 1e-8 for value in (row.stock_quantity, row.on_hand_qty, row.reserved_qty)):
        _block("Nguyên liệu còn tồn kho hoặc đang giữ chỗ. Điều chỉnh tồn và giải phóng giữ chỗ trước khi xóa.")
    if _json_reference(session, ProductTable, "materials_json", material_id, field="material_id", alternatives=True):
        _block("Nguyên liệu đang được BOM hoặc danh sách nguyên liệu thay thế sử dụng. Bỏ liên kết trước khi xóa.")
    if _json_reference(session, ProductionJobTable, "materials_json", material_id, field="material_id"):
        _block("Nguyên liệu đã gắn với job sản xuất. Cần giữ để đọc định mức và lịch sử.")
    if _json_reference(session, PurchaseOrderTable, "lines_json", material_id, field="material_id"):
        _block("Nguyên liệu đã có trong đơn mua. Xử lý đơn mua trước khi xóa.")
    if (_exists(session, StockMovementTable, StockMovementTable.material_id == material_id)
            or _exists(session, MaterialBatchTable, MaterialBatchTable.material_id == material_id)):
        _block("Nguyên liệu đã phát sinh lịch sử xuất nhập hoặc lô hàng. Không thể xóa lịch sử kho.")
    _remove(session, MaterialPriceEntryTable, MaterialPriceEntryTable.material_id == material_id)
    session.delete(row)


def delete_supplier(session, supplier_id):
    row = locked_row(session, SupplierTable, supplier_id, "Nhà cung cấp")
    for model in (MaterialTable, PurchaseOrderTable, MaterialBatchTable, MaterialPriceEntryTable):
        if _exists(session, model, model.supplier_id == supplier_id):
            _block("Nhà cung cấp đang được nguyên liệu, đơn mua, lô hàng hoặc lịch sử giá sử dụng. Bỏ liên kết trước khi xóa.")
    session.delete(row)


def delete_customer(session, customer_id):
    row = locked_row(session, CustomerTable, customer_id, "Khách hàng")
    if (_exists(session, OrderTable, OrderTable.customer_id == customer_id)
            or _exists(session, ProductReviewTable, ProductReviewTable.customer_id == customer_id)):
        _block("Khách hàng đã có đơn hàng hoặc đánh giá. Cần giữ liên kết lịch sử.")
    session.delete(row)


def delete_order(session, order_id):
    row = locked_row(session, OrderTable, order_id, "Đơn hàng")
    if row.status not in {"pending", "draft", "cancelled"} or row.payment_status not in {"unpaid", None, ""}:
        _block("Chỉ xóa đơn nháp/chờ hoặc đã hủy và chưa thanh toán. Đơn đang xử lý cần hủy trước.")
    for model in (ProductionJobTable, PaymentTable, OrderReturnTable):
        if _exists(session, model, model.order_id == order_id):
            _block("Đơn hàng đã có job, thanh toán hoặc hoàn trả. Cần giữ lịch sử liên quan.")
    if _exists(session, StockMovementTable, StockMovementTable.reference_type == "order",
               StockMovementTable.reference_id == order_id):
        _block("Đơn hàng đã phát sinh lịch sử kho. Không thể xóa hoàn toàn.")
    _remove(session, OrderLineTable, OrderLineTable.order_id == order_id)
    session.delete(row)


def delete_purchase_order(session, po_id):
    row = locked_row(session, PurchaseOrderTable, po_id, "Đơn mua")
    if row.status == "received" or row.received_at or row.paid_amount or row.payment_status in {"paid", "partial"}:
        _block("Đơn mua đã nhận hàng hoặc thanh toán. Không thể xóa vì ảnh hưởng kho và dòng tiền.")
    if (_exists(session, MaterialBatchTable, MaterialBatchTable.purchase_order_id == po_id)
            or _exists(session, StockMovementTable, StockMovementTable.reference_type == "purchase_order",
                       StockMovementTable.reference_id == po_id)):
        _block("Đơn mua đã có lô hàng hoặc lịch sử nhập kho. Không thể xóa hoàn toàn.")
    session.delete(row)


def delete_content_plan(session, plan_id):
    row = locked_row(session, ContentPlanTable, plan_id, "Kế hoạch nội dung")
    if _exists(session, OrderTable, OrderTable.source_content_id == plan_id):
        _block("Nội dung đã là nguồn của đơn hàng. Cần giữ để thống kê doanh thu theo nội dung.")
    session.delete(row)


def delete_production_job(session, job_id):
    row = locked_row(session, ProductionJobTable, job_id, "Job")
    materials = _json_list(row.materials_json)
    if any(not isinstance(item, dict) for item in materials):
        _block("Dữ liệu nguyên liệu của job không hợp lệ; cần sửa trước khi xóa.")
    if (row.status not in {"planned", "cancelled"} or row.started_at or row.completed_at
            or any(item.get("actual_quantity", 0) or item.get("reserved_quantity", 0) for item in materials)):
        _block("Chỉ xóa job kế hoạch/đã hủy chưa bắt đầu và không còn giữ chỗ. Job đã làm cần giữ lịch sử.")
    movements = session.exec(select(StockMovementTable).where(
        StockMovementTable.reference_type == "production_job", StockMovementTable.reference_id == job_id,
    )).all()
    balances = {}
    for movement in movements:
        if movement.movement_type not in {"reserve", "release"}:
            _block("Job đã phát sinh xuất nhập nguyên liệu. Không thể xóa lịch sử sản xuất.")
        balances[movement.material_id] = balances.get(movement.material_id, 0) + (
            movement.quantity_change if movement.movement_type == "reserve" else -abs(movement.quantity_change)
        )
    if any(abs(balance) > 1e-8 for balance in balances.values()):
        _block("Job còn giữ chỗ nguyên liệu. Hủy job để giải phóng giữ chỗ trước khi xóa.")
    for movement in movements:
        session.delete(movement)
    session.delete(row)


def delete_variant(session, variant_id):
    row = locked_row(session, ProductVariantTable, variant_id, "Biến thể")
    if row.stock_quantity:
        _block("Biến thể còn tồn kho. Điều chỉnh tồn trước khi xóa.")
    if (_exists(session, OrderLineTable, OrderLineTable.variant_id == variant_id)
            or _json_reference(session, OrderTable, "order_lines_json", variant_id, field="variant_id")):
        _block("Biến thể đã được sử dụng trong đơn hàng. Cần giữ lịch sử.")
    session.delete(row)

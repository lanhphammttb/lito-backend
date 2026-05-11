"""Services package - Business logic."""
from .auth import (
    create_access_token,
    verify_password,
    hash_password,
    get_current_user,
    get_current_user_optional,
    require_admin,
    find_user_by_email,
)
from .product import (
    compute_product_cost,
    get_product_cost_cached,
    clear_product_cost_cache,
    find_product,
)
from .order import (
    compute_order_totals,
    compute_promo_discount,
    validate_order_payload,
    apply_promo,
    deduct_stock_for_order,
    restock_for_order,
    find_order,
)
from .material import find_material, get_low_stock_alerts
from .customer import find_customer, compute_customer_metrics
from .inventory import find_supplier, compute_po_total, receive_purchase_order
from .issue import find_issue
from .activity import log_activity, create_audit_log
from .notification import send_notifications, notify_new_order, notify_low_stock

__all__ = [
    # Auth
    "create_access_token", "verify_password", "hash_password",
    "get_current_user", "get_current_user_optional", "require_admin", "find_user_by_email",
    # Product
    "compute_product_cost", "get_product_cost_cached", "clear_product_cost_cache", "find_product",
    # Order
    "compute_order_totals", "compute_promo_discount", "validate_order_payload",
    "apply_promo", "deduct_stock_for_order", "restock_for_order", "find_order",
    # Material
    "find_material", "get_low_stock_alerts",
    # Customer
    "find_customer", "compute_customer_metrics",
    # Inventory
    "find_supplier", "compute_po_total", "receive_purchase_order",
    # Issue
    "find_issue",
    # Activity
    "log_activity", "create_audit_log",
    # Notification
    "send_notifications", "notify_new_order", "notify_low_stock",
]

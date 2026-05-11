"""Routers package - API route handlers."""
from .auth import router as auth_router
from .products import router as products_router
from .materials import router as materials_router
from .orders import router as orders_router
from .customers import router as customers_router
from .content import router as content_router
from .inventory import router as inventory_router
from .dashboard import router as dashboard_router
from .settings import router as settings_router
from .activity import router as activity_router
from .tasks import router as tasks_router
from .categories import router as categories_router

all_routers = [
    (auth_router, "/auth", ["Auth"]),
    (products_router, "/products", ["Products"]),
    (materials_router, "/materials", ["Materials"]),
    (orders_router, "/orders", ["Orders"]),
    (customers_router, "/customers", ["Customers"]),
    (content_router, "/content", ["Content"]),
    (inventory_router, "/inventory", ["Inventory"]),
    (dashboard_router, "/dashboard", ["Dashboard"]),
    (settings_router, "/settings", ["Settings"]),
    (activity_router, "/activity", ["Activity"]),
    (tasks_router, "/tasks", ["Tasks"]),
    (categories_router, "/categories", ["Categories"]),
]

__all__ = [
    "auth_router", "products_router", "materials_router", "orders_router",
    "customers_router", "content_router", "inventory_router", "dashboard_router",
    "settings_router", "activity_router", "tasks_router", "categories_router",
    "all_routers",
]

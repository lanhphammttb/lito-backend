"""FastAPI application construction helpers."""

import os
from contextlib import AbstractAsyncContextManager
from typing import Callable

import sentry_sdk
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sentry_sdk.integrations.fastapi import FastApiIntegration

from config.settings import CORS_ORIGINS
from routers.activity import router as activity_router
from routers.audit import router as audit_router
from routers.ai import router as ai_router
from routers.auth import router as auth_router
from routers.cashflow_router import router as cashflow_router
from routers.categories import router as categories_router
from routers.content import router as content_router
from routers.customers import router as customers_router
from routers.dashboard import router as dashboard_router
from routers.experiments_router import router as experiments_router
from routers.expenses import router as expenses_router
from routers.goals_router import router as goals_router
from routers.growth_analytics_router import router as growth_analytics_router
from routers.ideas import router as ideas_router
from routers.inventory import router as inventory_router
from routers.issues_router import router as issues_router
from routers.inventory_compat import router as inventory_compat_router
from routers.legacy_analytics import router as analytics_router
from routers.marketplace import router as marketplace_router
from routers.materials import router as materials_router
from routers.notifications import router as notifications_router
from routers.order_compat import router as order_compat_router
from routers.orders import router as orders_router
from routers.product_images import router as product_images_router
from routers.product_compat import router as product_compat_router
from routers.products import public_router as public_products_router
from routers.products import router as products_router
from routers.production import router as production_router
from routers.seasons import router as seasons_router
from routers.settings import router as settings_router
from routers.strategy_router import router as strategy_router
from routers.system import router as system_router, websocket_endpoint
from routers.tasks import router as tasks_router
from routers.upload import router as upload_router


APP_TITLE = "Hala Handmade Business OS"
APP_DESCRIPTION = "Complete business management system for handmade businesses"
APP_VERSION = "2.0.0"


def configure_sentry() -> None:
    """Enable Sentry when SENTRY_DSN is configured."""
    sentry_dsn = os.getenv("SENTRY_DSN")
    if not sentry_dsn:
        return

    sentry_sdk.init(
        dsn=sentry_dsn,
        integrations=[FastApiIntegration()],
        traces_sample_rate=float(os.getenv("SENTRY_TRACES_SAMPLE_RATE", "0.1")),
        send_default_pii=True,
    )


def include_routers(app: FastAPI) -> None:
    """Register all API routers."""
    app.include_router(ideas_router, tags=["Ideas"])
    app.include_router(goals_router, tags=["Goals"])
    app.include_router(experiments_router, tags=["Experiments"])
    app.include_router(issues_router, tags=["Issues"])
    app.include_router(strategy_router, tags=["Strategy"])
    app.include_router(growth_analytics_router, tags=["Growth Analytics"])
    app.include_router(analytics_router, tags=["Analytics Legacy"])
    app.include_router(auth_router, prefix="/auth", tags=["Auth"])
    app.include_router(public_products_router, tags=["Public Products"])
    app.include_router(product_compat_router, prefix="/products", tags=["Product Compatibility"])
    app.include_router(products_router, prefix="/products", tags=["Products"])
    app.include_router(materials_router, prefix="/materials", tags=["Materials"])
    app.include_router(order_compat_router, prefix="/orders", tags=["Order Compatibility"])
    app.include_router(orders_router, prefix="/orders", tags=["Orders"])
    app.include_router(customers_router, prefix="/customers", tags=["Customers"])
    app.include_router(content_router, prefix="/content", tags=["Content"])
    app.include_router(inventory_compat_router, prefix="/inventory", tags=["Inventory Compatibility"])
    app.include_router(inventory_router, prefix="/inventory", tags=["Inventory"])
    app.include_router(dashboard_router, prefix="/dashboard", tags=["Dashboard"])
    app.include_router(settings_router, prefix="/settings", tags=["Settings"])
    app.include_router(upload_router, prefix="/upload", tags=["Upload"])
    app.include_router(product_images_router, prefix="/product-images", tags=["Product Images"])
    app.include_router(activity_router, prefix="/activity", tags=["Activity"])
    app.include_router(tasks_router, prefix="/tasks", tags=["Tasks"])
    app.include_router(categories_router, prefix="/categories", tags=["Categories"])
    app.include_router(production_router, prefix="/production-jobs", tags=["Production"])
    app.include_router(expenses_router, prefix="/expenses", tags=["Expenses"])
    app.include_router(cashflow_router, prefix="/cashflow", tags=["CashFlow"])
    app.include_router(ai_router, prefix="/ai", tags=["AI"])
    app.include_router(seasons_router, prefix="/seasons", tags=["Seasons"])
    app.include_router(audit_router, prefix="/audit", tags=["Audit"])
    app.include_router(marketplace_router, prefix="/marketplace", tags=["Marketplace"])
    app.include_router(notifications_router, prefix="/notifications", tags=["Notifications"])
    app.include_router(system_router, prefix="/system", tags=["System"])
    app.add_api_websocket_route("/ws", websocket_endpoint)


def create_app(lifespan: Callable[[FastAPI], AbstractAsyncContextManager[None]]) -> FastAPI:
    """Create the FastAPI app with shared middleware and routers."""
    configure_sentry()

    app = FastAPI(
        title=APP_TITLE,
        description=APP_DESCRIPTION,
        version=APP_VERSION,
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    include_routers(app)

    @app.exception_handler(Exception)
    async def global_exception_handler(request, exc):
        print(f"[ERROR] {type(exc).__name__}: {exc}")
        return JSONResponse(status_code=500, content={"detail": "Internal server error"})

    return app

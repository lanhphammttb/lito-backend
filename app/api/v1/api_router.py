from fastapi import APIRouter
from app.api.v1.endpoints import (
    auth, users, products, orders, inventory, analytics, settings, dashboard, upload
)

api_router = APIRouter()

api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(users.router, tags=["users"])
api_router.include_router(products.router, tags=["products"])
api_router.include_router(orders.router, tags=["orders"])
api_router.include_router(inventory.router, tags=["inventory"])
api_router.include_router(analytics.router, tags=["analytics"])
api_router.include_router(settings.router, tags=["settings"])
api_router.include_router(dashboard.router, tags=["dashboard"])
api_router.include_router(upload.router, prefix="/upload", tags=["upload"])

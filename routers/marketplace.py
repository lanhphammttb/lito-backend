"""Marketplace compatibility routes."""

from fastapi import APIRouter, Depends
from sqlmodel import Session, select

from config.database import engine
from legacy_state import marketplace_logs
from models.notifications import MarketplaceSyncLogTable
from models.user import User
from services.auth import get_current_user
from utils.datetime import utcnow

router = APIRouter()


@router.get("/logs")
async def get_marketplace_logs(marketplace: str = None, platform: str = None, limit: int = 50, user: User = Depends(get_current_user)):
    """Get marketplace sync logs."""
    filter_val = marketplace or platform
    with Session(engine) as session:
        stmt = select(MarketplaceSyncLogTable).order_by(MarketplaceSyncLogTable.synced_at.desc()).limit(limit)
        if filter_val:
            stmt = stmt.where(MarketplaceSyncLogTable.marketplace == filter_val)
        rows = session.exec(stmt).all()
    logs = [
        {
            "id": row.id,
            "marketplace": row.marketplace,
            "platform": row.marketplace,
            "sync_type": row.sync_type,
            "status": row.status,
            "synced_at": row.synced_at.isoformat() if row.synced_at else None,
            "orders_synced": row.orders_synced,
            "orders_failed": row.orders_failed,
            "items_synced": row.orders_synced,
            "error_message": row.error_message,
        }
        for row in rows
    ]
    return {"logs": logs}


@router.post("/sync")
async def sync_marketplace(payload: dict, user: User = Depends(get_current_user)):
    """Record a marketplace sync attempt.

    Real marketplace API integration is not implemented here yet. The route now
    records an explicit skipped sync instead of returning a fake successful sync.
    """
    mkt = payload.get("marketplace") or payload.get("platform", "shopee")
    sync_type = payload.get("sync_type", "orders")
    synced_at = utcnow()
    row = MarketplaceSyncLogTable(
        marketplace=mkt,
        sync_type=sync_type,
        status="failed",
        orders_synced=0,
        orders_failed=0,
        error_message="Marketplace API integration is not configured",
        synced_at=synced_at,
    )
    with Session(engine) as session:
        session.add(row)
        session.commit()
        session.refresh(row)
    log = {
        "id": row.id,
        "marketplace": mkt,
        "platform": mkt,
        "sync_type": sync_type,
        "status": row.status,
        "message": row.error_message,
        "synced_at": synced_at.isoformat(),
        "orders_synced": 0,
        "items_synced": 0,
        "orders_failed": 0,
        "error_message": row.error_message,
    }
    marketplace_logs.append(log)
    return log

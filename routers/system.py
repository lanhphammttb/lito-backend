"""System and root compatibility routes."""

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool
from sqlmodel import Session, select

from config.database import engine
from legacy_state import users
from models import OrderTable
from models.user import User
from routers.tasks import tasks
from services.auth import get_current_user, get_current_user_ws, require_admin
from services.material import get_low_stock_alerts
from services.notification import ws_manager
from utils.datetime import utcnow

router = APIRouter()


@router.get("/me")
async def get_me(user: User = Depends(get_current_user)):
    """Get current user info."""
    return {"id": user.id, "name": user.name, "email": user.email, "role": user.role, "is_owner": user.is_owner}


@router.get("/users")
async def list_users(user: User = Depends(get_current_user)):
    """List all users."""
    return users


@router.get("/alerts")
async def get_alerts(user: User = Depends(get_current_user)):
    """Get system alerts."""
    low_stock = get_low_stock_alerts()
    pending_tasks = len([t for t in tasks if t.status != "done"])

    today = date.today()
    with Session(engine) as session:
        order_rows = session.exec(select(OrderTable)).all()
    overdue_orders = [
        {
            "id": o.id,
            "date": o.order_date.isoformat() if o.order_date else None,
            "status": o.status,
            "days_overdue": (today - o.order_date).days if o.order_date else 0
        }
        for o in order_rows
        if o.status not in ("delivered", "cancelled") and o.order_date and (today - o.order_date).days > 7
    ]

    return {
        "low_stock": low_stock[:10],
        "overdue_orders": overdue_orders[:10],
        "pending_tasks": pending_tasks,
        "notifications": []
    }


@router.get("/issue-templates")
async def list_issue_templates(user: User = Depends(get_current_user)):
    """List issue templates."""
    return [
        {"id": 1, "name": "Lỗi chất lượng", "description": "Template cho vấn đề chất lượng sản phẩm"},
        {"id": 2, "name": "Thiếu nguyên liệu", "description": "Template cho vấn đề thiếu nguyên liệu"},
    ]


@router.post("/backup")
async def create_backup(user: User = Depends(get_current_user)):
    """Download an actual consistent database snapshot for an administrator."""
    require_admin(user)
    from services.backup import export_snapshot
    snapshot = await run_in_threadpool(export_snapshot, engine)
    filename = f"lito-backup-{utcnow().strftime('%Y%m%d-%H%M%S')}.json"
    return JSONResponse(snapshot, headers={'Content-Disposition': f'attachment; filename="{filename}"',
                                          'Cache-Control': 'no-store'})


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket for real-time notifications."""
    try:
        user = await get_current_user_ws(websocket)
    except Exception as e:
        print(f"[WS] Auth error: {type(e).__name__}: {e}")
        await websocket.accept()
        await websocket.close(code=1008)
        return

    user_id = user.id
    await ws_manager.connect(websocket, user_id)
    try:
        while True:
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket, user_id)


@router.get("/health")
async def health_check():
    """Health check."""
    from sqlalchemy import text
    from starlette.concurrency import run_in_threadpool

    def check_database():
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))

    await run_in_threadpool(check_database)
    return {"status": "healthy", "database": engine.dialect.name, "timestamp": utcnow().isoformat(), "version": "2.0.0"}


@router.get("/")
async def root():
    """Root endpoint."""
    return {"name": "LITO Handmade Business OS", "version": "2.0.0", "docs": "/docs"}

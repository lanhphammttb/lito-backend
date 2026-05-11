"""Content routes - Content planning and demand signals."""
from typing import List, Optional
from datetime import datetime, date
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlmodel import Session

from config.database import engine
from models.user import User
from models.content import ContentPlan, ContentPlanTable, DemandSignal, DemandSignalTable
from schemas.content import ContentPlanCreate, ContentPerformanceUpdate, DemandSignalCreate
from services.auth import get_current_user
from services.activity import log_activity

router = APIRouter()

from sqlmodel import select

content_plans: List[ContentPlan] = []
demand_signals: List[DemandSignal] = []


def save_content_plan_sql(plan: ContentPlan) -> ContentPlan:
    """Persist a content plan and return the normalized model."""
    with Session(engine) as session:
        row = session.get(ContentPlanTable, plan.id) if getattr(plan, "id", None) else None
        if row:
            row.title = plan.title
            row.platform = plan.platform
            row.channel = plan.channel
            row.format = plan.format
            row.status = plan.status
            row.scheduled_date = plan.scheduled_date
            row.related_product_id = plan.related_product_id
            row.caption = plan.caption
            row.hashtags = plan.hashtags
            row.estimate_views = plan.estimate_views
            row.estimate_inquiries = plan.estimate_inquiries
            row.estimate_saves = plan.estimate_saves
            row.actual_views = plan.actual_views
            row.actual_inquiries = plan.actual_inquiries
            row.actual_saves = plan.actual_saves
            row.actual_orders = plan.actual_orders
            row.actual_revenue = plan.actual_revenue
            row.updated_by = plan.updated_by
        else:
            row = ContentPlanTable(
                title=plan.title,
                platform=plan.platform,
                channel=plan.channel,
                format=plan.format,
                status=plan.status,
                scheduled_date=plan.scheduled_date,
                related_product_id=plan.related_product_id,
                caption=plan.caption,
                hashtags=plan.hashtags,
                estimate_views=plan.estimate_views,
                estimate_inquiries=plan.estimate_inquiries,
                estimate_saves=plan.estimate_saves,
                actual_views=plan.actual_views,
                actual_inquiries=plan.actual_inquiries,
                actual_saves=plan.actual_saves,
                actual_orders=plan.actual_orders,
                actual_revenue=plan.actual_revenue,
                created_by=plan.created_by,
                updated_by=plan.updated_by,
                created_at=plan.created_at,
            )
        session.add(row)
        session.commit()
        session.refresh(row)
        return ContentPlan(
            id=row.id,
            title=row.title,
            platform=row.platform,
            channel=row.channel,
            format=row.format,
            status=row.status,
            scheduled_date=row.scheduled_date,
            published_date=row.published_date,
            related_product_id=row.related_product_id,
            caption=row.caption,
            hashtags=row.hashtags,
            estimate_views=row.estimate_views,
            estimate_inquiries=row.estimate_inquiries,
            estimate_saves=row.estimate_saves,
            actual_views=row.actual_views,
            actual_inquiries=row.actual_inquiries,
            actual_saves=row.actual_saves,
            actual_orders=row.actual_orders,
            actual_revenue=row.actual_revenue,
            created_by=row.created_by,
            updated_by=row.updated_by,
            created_at=row.created_at,
        )


def save_demand_signal_sql(signal: DemandSignal) -> DemandSignal:
    """Persist a demand signal and return the normalized model."""
    with Session(engine) as session:
        row = session.get(DemandSignalTable, signal.id) if getattr(signal, "id", None) else None
        if row:
            row.product_id = signal.product_id
            row.views = signal.views
            row.inquiries = signal.inquiries
            row.saves = signal.saves
            row.week_of = signal.week_of
            row.created_by = signal.created_by
        else:
            row = DemandSignalTable(
                product_id=signal.product_id,
                views=signal.views,
                inquiries=signal.inquiries,
                saves=signal.saves,
                week_of=signal.week_of,
                created_by=signal.created_by,
                created_at=signal.created_at,
            )
        session.add(row)
        session.commit()
        session.refresh(row)
        return DemandSignal(
            id=row.id,
            product_id=row.product_id,
            views=row.views,
            inquiries=row.inquiries,
            saves=row.saves,
            week_of=row.week_of,
            created_by=row.created_by,
            created_at=row.created_at,
        )


@router.get("/plans")
async def list_content_plans(
    skip: int = 0,
    limit: int = 100,
    status: Optional[str] = None,
    platform: Optional[str] = None,
    user: User = Depends(get_current_user)
):
    """List content plans from DB."""
    with Session(engine) as session:
        statement = select(ContentPlanTable)
        if status:
            statement = statement.where(ContentPlanTable.status == status)
        if platform:
            statement = statement.where(ContentPlanTable.platform == platform)
        
        statement = statement.order_by(ContentPlanTable.scheduled_date.desc()).offset(skip).limit(limit)
        results = session.exec(statement).all()
        return [r.model_dump() for r in results]


@router.post("/plans")
async def create_content_plan(
    payload: ContentPlanCreate,
    user: User = Depends(get_current_user)
):
    """Create content plan."""
    plan = ContentPlan(
        id=0,
        title=payload.title,
        platform=payload.platform,
        channel=payload.channel,
        format=payload.format,
        scheduled_date=payload.scheduled_date,
        status=payload.status or "draft",
        related_product_id=payload.related_product_id,
        caption=payload.caption,
        hashtags=payload.hashtags,
        estimate_views=payload.estimate_views,
        estimate_inquiries=payload.estimate_inquiries,
        estimate_saves=payload.estimate_saves,
        created_by=user.id,
        created_at=datetime.utcnow(),
    )
    persisted_plan = save_content_plan_sql(plan)
    
    log_activity(user.id, "content_plan", persisted_plan.id, "create", {"title": persisted_plan.title})
    
    return persisted_plan


@router.put("/plans/{plan_id}")
async def update_content_plan(
    plan_id: int,
    payload: ContentPlanCreate,
    user: User = Depends(get_current_user)
):
    """Update content plan."""
    with Session(engine) as session:
        row = session.get(ContentPlanTable, plan_id)
        if not row:
            raise HTTPException(status_code=404, detail="Content plan không tồn tại")
        
    plan = ContentPlan(**row.model_dump())
    
    plan.title = payload.title
    plan.platform = payload.platform
    plan.channel = payload.channel
    plan.format = payload.format
    plan.scheduled_date = payload.scheduled_date
    plan.status = payload.status or plan.status
    plan.related_product_id = payload.related_product_id
    plan.caption = payload.caption
    plan.hashtags = payload.hashtags
    plan.estimate_views = payload.estimate_views
    plan.estimate_inquiries = payload.estimate_inquiries
    plan.estimate_saves = payload.estimate_saves
    plan.updated_by = user.id
    
    persisted_plan = save_content_plan_sql(plan)
    
    log_activity(user.id, "content_plan", plan_id, "update", {"title": persisted_plan.title})
    
    return persisted_plan


@router.patch("/plans/{plan_id}/performance")
async def update_content_performance(
    plan_id: int,
    payload: ContentPerformanceUpdate,
    user: User = Depends(get_current_user)
):
    """Update content performance metrics."""
    with Session(engine) as session:
        row = session.get(ContentPlanTable, plan_id)
        if not row:
            raise HTTPException(status_code=404, detail="Content plan không tồn tại")
            
    plan = ContentPlan(**row.model_dump())
    
    plan.actual_views = payload.actual_views
    plan.actual_inquiries = payload.actual_inquiries
    plan.actual_saves = payload.actual_saves
    plan.actual_orders = payload.actual_orders
    plan.actual_revenue = payload.actual_revenue
    plan.updated_by = user.id
    
    persisted_plan = save_content_plan_sql(plan)
    
    return persisted_plan


@router.delete("/plans/{plan_id}")
async def delete_content_plan(
    plan_id: int,
    user: User = Depends(get_current_user)
):
    """Delete content plan."""
    with Session(engine) as session:
        row = session.get(ContentPlanTable, plan_id)
        if not row:
            raise HTTPException(status_code=404, detail="Content plan không tồn tại")
            
        session.delete(row)
        session.commit()
    log_activity(user.id, "content_plan", plan_id, "delete", {})
    
    return {"message": "Đã xóa content plan"}


# Demand Signals
@router.get("/signals")
async def list_demand_signals(
    skip: int = 0,
    limit: int = 100,
    product_id: Optional[int] = None,
    user: User = Depends(get_current_user)
):
    """List demand signals from DB."""
    with Session(engine) as session:
        statement = select(DemandSignalTable)
        if product_id:
            statement = statement.where(DemandSignalTable.product_id == product_id)
        
        statement = statement.order_by(DemandSignalTable.week_of.desc()).offset(skip).limit(limit)
        results = session.exec(statement).all()
        return [r.model_dump() for r in results]


@router.post("/signals")
async def create_demand_signal(
    payload: DemandSignalCreate,
    user: User = Depends(get_current_user)
):
    """Create demand signal."""
    signal = DemandSignal(
        id=0,
        product_id=payload.product_id,
        week_of=payload.week_of,
        views=payload.views or 0,
        inquiries=payload.inquiries or 0,
        saves=payload.saves or 0,
        created_by=user.id,
        created_at=datetime.utcnow(),
    )
    persisted_signal = save_demand_signal_sql(signal)
    
    return persisted_signal


@router.get("/analytics")
async def get_content_analytics(
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    user: User = Depends(get_current_user)
):
    """Get content analytics summary from DB."""
    with Session(engine) as session:
        statement = select(ContentPlanTable)
        if start_date:
            statement = statement.where(ContentPlanTable.scheduled_date >= start_date)
        if end_date:
            statement = statement.where(ContentPlanTable.scheduled_date <= end_date)
            
        result = session.exec(statement).all()
    
    total_views = sum(c.actual_views or 0 for c in result)
    total_inquiries = sum(c.actual_inquiries or 0 for c in result)
    total_saves = sum(c.actual_saves or 0 for c in result)
    total_conversions = sum(c.actual_orders or 0 for c in result)
    
    # By platform
    by_platform = {}
    for c in result:
        platform = c.platform or "unknown"
        if platform not in by_platform:
            by_platform[platform] = {"count": 0, "views": 0, "conversions": 0}
        by_platform[platform]["count"] += 1
        by_platform[platform]["views"] += c.actual_views or 0
        by_platform[platform]["conversions"] += c.actual_orders or 0
    
    return {
        "total_content": len(result),
        "total_views": total_views,
        "total_inquiries": total_inquiries,
        "total_saves": total_saves,
        "total_conversions": total_conversions,
        "engagement_rate": (total_inquiries + total_saves) / total_views if total_views else 0,
        "conversion_rate": total_conversions / total_views if total_views else 0,
        "by_platform": by_platform,
    }
